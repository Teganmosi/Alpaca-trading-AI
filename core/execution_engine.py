from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from core.models import Signal
from core.telemetry import telemetry
import time

# Terminal states that end order lifecycle
TERMINAL_STATES = {"filled", "canceled", "rejected", "expired"}

class ExecutionEngine:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.client = TradingClient(api_key, secret_key, paper=paper)

    def execute_bracket_order(self, symbol: str, signal: Signal, size: float, stop_loss: float, tp_target: float):
        """
        Places a primary market order with attached SL and TP bracket orders.
        Returns: (order_id, actual_fill_price) or (None, None) on partial fill failure.
        
        HARDENING: Validates full quantity fill before returning success.
        """
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=size,
            side=side,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=tp_target),
            stop_loss=StopLossRequest(stop_price=stop_loss)
        )
        
        print(f"[EXECUTION] Submitting {side.name} bracket order for {symbol} | Qty: {size:.6f}")
        order = self.client.submit_order(order_data)
        
        # Poll until terminal state OR timeout
        # Terminal states: filled, canceled, rejected, expired
        final_order = None
        for _ in range(10):  # Max 10 attempts (approx 5-10s)
            time.sleep(1)
            updated_order = self.client.get_order_by_id(order.id)
            status = updated_order.status.lower() if hasattr(updated_order.status, 'lower') else str(updated_order.status).lower()
            
            if status in TERMINAL_STATES:
                final_order = updated_order
                break
        
        # HARDENING: Validate full quantity fill
        if final_order is None:
            # Timeout - order still pending
            self._handle_partial_fill_failure(symbol, "TIMEOUT", size)
            return None, None
        
        status = final_order.status.lower() if hasattr(final_order.status, 'lower') else str(final_order.status).lower()
        
        if status != "filled":
            # Order rejected/canceled/expired - not filled
            self._handle_partial_fill_failure(symbol, status, size)
            return None, None
        
        # Check filled quantity matches requested quantity
        filled_qty = float(getattr(final_order, 'filled_qty', 0) or 0)
        if filled_qty != size:
            # Partial fill detected
            self._handle_partial_fill_failure(symbol, f"PARTIAL_QTY:{filled_qty}/{size}", size)
            return None, None
        
        # Full fill confirmed
        fill_price = float(final_order.filled_avg_price)
        print(f"[EXECUTION] Order {order.id} fully filled at ${fill_price:.2f}")
        return order.id, fill_price

    def _handle_partial_fill_failure(self, symbol: str, reason: str, requested_qty: float):
        """
        Handles partial fill or non-fill scenarios with deterministic fail-closed behavior.
        Cancels open orders, closes any partial position, and emits CRITICAL telemetry.
        """
        print(f"[CRITICAL] Partial fill detected for {symbol} | Reason: {reason} | Requested: {requested_qty}")
        
        # Cancel all pending orders for symbol
        self.cancel_all_orders(symbol)
        
        # Close any partially filled position
        try:
            self.close_position(symbol)
        except Exception as e:
            print(f"[WARNING] Could not close partial position: {e}")
        
        # Emit CRITICAL telemetry
        telemetry.notify(
            "PARTIAL_FILL_ABORT",
            f"Symbol: {symbol} | Reason: {reason} | Requested Qty: {requested_qty}",
            severity="CRITICAL"
        )

    def has_open_position(self, symbol: str) -> bool:
        """Broker Truth Check: Check if Alpaca already has a position."""
        try:
            self.client.get_open_position(symbol)
            return True
        except Exception:
            return False

    def get_position_details(self, symbol: str):
        """Returns (side, qty, avg_entry_price) if position exists, else None."""
        try:
            pos = self.client.get_open_position(symbol)
            side = Signal.LONG if pos.side == 'long' else Signal.SHORT
            return side, float(pos.qty), float(pos.avg_entry_price)
        except Exception:
            return None

    def get_symbol_bracket_orders(self, symbol: str):
        """Returns (stop_loss, tp_target) if open orders exist for the symbol."""
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        orders = self.client.get_orders(req)
        
        sl, tp = None, None
        for o in orders:
            if o.type == 'stop': sl = float(o.stop_price)
            if o.type == 'limit': tp = float(o.limit_price)
        return sl, tp

    def close_position(self, symbol: str):
        """Emergency closure or specific close instruction."""
        print(f"[EXECUTION] Closing position for {symbol}")
        try:
            self.client.close_position(symbol)
        except Exception as e:
            print(f"[EXECUTION] Note (Close Position): {e}")

    def cancel_all_orders(self, symbol: str):
        """Cancels all open orders SPECIFICALLY for the symbol."""
        print(f"[EXECUTION] Canceling all open orders for {symbol}")
        # Fetching open orders for the symbol specifically
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        open_orders = self.client.get_orders(req)
        for o in open_orders:
            self.client.cancel_order_by_id(o.id)

    def get_account_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)
