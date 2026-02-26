from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest, StopLimitOrderRequest
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
        Places an order for crypto with separate SL/TP.
        Alpaca doesn't support bracket orders for crypto, so we use simple orders.
        
        Returns: (order_id, actual_fill_price) or (None, None) on failure.
        """
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        
        # Check if this is crypto
        is_crypto = "/" in symbol  # BTC/USD format
        
        if is_crypto:
            # For crypto: Submit simple market order, then submit separate SL/TP
            print(f"[EXECUTION] Submitting {side.name} market order for {symbol} | Qty: {size:.6f}")
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=size,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            
            order = self.client.submit_order(order_data)
            
            # Wait for fill
            final_order = None
            for _ in range(10):
                time.sleep(1)
                try:
                    updated_order = self.client.get_order_by_id(order.id)
                    status = updated_order.status.lower() if hasattr(updated_order.status, 'lower') else str(updated_order.status).lower()
                    
                    if status in TERMINAL_STATES:
                        final_order = updated_order
                        break
                except Exception as e:
                    print(f"[WARNING] Error checking order: {e}")
            
            if final_order is None or final_order.status.lower() != "filled":
                print(f"[CRITICAL] Order not filled: {final_order.status if final_order else 'timeout'}")
                return None, None
            
            fill_price = float(final_order.filled_avg_price)
            print(f"[EXECUTION] Order filled at ${fill_price:.2f}")
            
            # Now submit separate stop loss and take profit orders
            # Note: We submit them as bracket-style but Alpaca will handle them as separate orders
            try:
                # Stop loss order
                sl_side = OrderSide.SELL if signal == Signal.LONG else OrderSide.BUY
                sl_order = StopLimitOrderRequest(
                    symbol=symbol,
                    qty=size,
                    side=sl_side,
                    time_in_force=TimeInForce.GTC,
                    limit_price=stop_loss,  # Use limit for more control
                    stop_price=stop_loss
                )
                self.client.submit_order(sl_order)
                print(f"[EXECUTION] Stop loss submitted at ${stop_loss:.2f}")
            except Exception as e:
                print(f"[WARNING] Could not submit stop loss: {e}")
            
            try:
                # Take profit order  
                tp_side = OrderSide.SELL if signal == Signal.LONG else OrderSide.BUY
                tp_order = TakeProfitRequest(
                    limit_price=tp_target
                )
                # Submit as market with TP
                tp_order_req = MarketOrderRequest(
                    symbol=symbol,
                    qty=size,
                    side=tp_side,
                    time_in_force=TimeInForce.GTC,
                    take_profit=tp_order
                )
                self.client.submit_order(tp_order_req)
                print(f"[EXECUTION] Take profit submitted at ${tp_target:.2f}")
            except Exception as e:
                print(f"[WARNING] Could not submit take profit: {e}")
            
            return order.id, fill_price
        else:
            # For stocks: Use bracket order (original logic)
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
            
            final_order = None
            for _ in range(10):
                time.sleep(1)
                updated_order = self.client.get_order_by_id(order.id)
                status = updated_order.status.lower() if hasattr(updated_order.status, 'lower') else str(updated_order.status).lower()
                
                if status in TERMINAL_STATES:
                    final_order = updated_order
                    break
            
            if final_order is None or final_order.status.lower() != "filled":
                self._handle_partial_fill_failure(symbol, final_order.status if final_order else "timeout", size)
                return None, None
            
            fill_price = float(final_order.filled_avg_price)
            print(f"[EXECUTION] Order filled at ${fill_price:.2f}")
            return order.id, fill_price

    def _handle_partial_fill_failure(self, symbol: str, reason: str, requested_qty: float):
        """Handles partial fill or non-fill scenarios."""
        print(f"[CRITICAL] Partial fill detected for {symbol} | Reason: {reason} | Requested: {requested_qty}")
        
        self.cancel_all_orders(symbol)
        
        try:
            self.close_position(symbol)
        except Exception as e:
            print(f"[WARNING] Could not close partial position: {e}")
        
        telemetry.notify(
            "PARTIAL_FILL_ABORT",
            f"Symbol: {symbol} | Reason: {reason} | Requested Qty: {requested_qty}",
            severity="CRITICAL"
        )

    def has_open_position(self, symbol: str) -> bool:
        """Check if Alpaca already has a position."""
        try:
            self.client.get_open_position(symbol)
            return True
        except Exception:
            return False

    def get_position_details(self, symbol: str):
        """Returns (side, qty, avg_entry_price) if position exists."""
        try:
            pos = self.client.get_open_position(symbol)
            side = Signal.LONG if pos.side == 'long' else Signal.SHORT
            return side, float(pos.qty), float(pos.avg_entry_price)
        except Exception:
            return None

    def get_symbol_bracket_orders(self, symbol: str):
        """Returns (stop_loss, tp_target) if open orders exist."""
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        orders = self.client.get_orders(req)
        
        sl, tp = None, None
        for o in orders:
            if o.type == 'stop': sl = float(o.stop_price)
            if o.type == 'limit': tp = float(o.limit_price)
        return sl, tp

    def close_position(self, symbol: str):
        """Emergency closure."""
        print(f"[EXECUTION] Closing position for {symbol}")
        try:
            self.client.close_position(symbol)
        except Exception as e:
            print(f"[EXECUTION] Note (Close Position): {e}")

    def cancel_all_orders(self, symbol: str):
        """Cancels all open orders for the symbol."""
        print(f"[EXECUTION] Canceling all open orders for {symbol}")
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        open_orders = self.client.get_orders(req)
        for o in open_orders:
            self.client.cancel_order_by_id(o.id)

    def get_account_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)
