from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest, StopLimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from core.models import Signal
from core.telemetry import telemetry
import time

# Terminal states
TERMINAL_STATES = {"filled", "canceled", "rejected", "expired"}

class ExecutionEngine:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.client = TradingClient(api_key, secret_key, paper=paper)

    def execute_bracket_order(self, symbol: str, signal: Signal, size: float, stop_loss: float, tp_target: float):
        """
        Places an order for crypto with separate SL/TP.
        """
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        is_crypto = "/" in symbol
        
        if is_crypto:
            # For crypto: Submit simple market order first
            print(f"[EXECUTION] Submitting {side.name} market order for {symbol} | Qty: {size:.6f}")
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=size,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            
            order = self.client.submit_order(order_data)
            order_id_str = str(order.id)  # Convert UUID to string
            
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
            
            # Calculate remaining qty after fill (may have small difference due to fill)
            filled_qty = float(final_order.filled_qty) if final_order.filled_qty else size
            
            # SL/TP orders - use smaller qty to avoid insufficient balance
            # Leave some buffer for the SL/TP orders
            sl_tp_qty = filled_qty * 0.99  # 99% of filled qty
            
            # Submit stop loss
            try:
                sl_side = OrderSide.SELL if signal == Signal.LONG else OrderSide.BUY
                sl_order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=sl_tp_qty,
                    side=sl_side,
                    time_in_force=TimeInForce.GTC,
                    stop_loss=StopLossRequest(stop_price=stop_loss)
                )
                self.client.submit_order(sl_order_data)
                print(f"[EXECUTION] Stop loss submitted at ${stop_loss:.2f} | Qty: {sl_tp_qty:.6f}")
            except Exception as e:
                print(f"[WARNING] Could not submit stop loss: {e}")
            
            # Submit take profit
            try:
                tp_side = OrderSide.SELL if signal == Signal.LONG else OrderSide.BUY
                tp_order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=sl_tp_qty,
                    side=tp_side,
                    time_in_force=TimeInForce.GTC,
                    take_profit=TakeProfitRequest(limit_price=tp_target)
                )
                self.client.submit_order(tp_order_data)
                print(f"[EXECUTION] Take profit submitted at ${tp_target:.2f} | Qty: {sl_tp_qty:.6f}")
            except Exception as e:
                print(f"[WARNING] Could not submit take profit: {e}")
            
            return order_id_str, fill_price
        else:
            # For stocks: Use bracket order
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
            order_id_str = str(order.id)
            
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
            return order_id_str, fill_price

    def _handle_partial_fill_failure(self, symbol: str, reason: str, requested_qty: float):
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
        try:
            self.client.get_open_position(symbol)
            return True
        except Exception:
            return False

    def get_position_details(self, symbol: str):
        try:
            pos = self.client.get_open_position(symbol)
            side = Signal.LONG if pos.side == 'long' else Signal.SHORT
            return side, float(pos.qty), float(pos.avg_entry_price)
        except Exception:
            return None

    def get_symbol_bracket_orders(self, symbol: str):
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        orders = self.client.get_orders(req)
        sl, tp = None, None
        for o in orders:
            if o.type == 'stop': sl = float(o.stop_price)
            if o.type == 'limit': tp = float(o.limit_price)
        return sl, tp

    def close_position(self, symbol: str):
        print(f"[EXECUTION] Closing position for {symbol}")
        try:
            self.client.close_position(symbol)
        except Exception as e:
            print(f"[EXECUTION] Note (Close Position): {e}")

    def cancel_all_orders(self, symbol: str):
        print(f"[EXECUTION] Canceling all open orders for {symbol}")
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        open_orders = self.client.get_orders(req)
        for o in open_orders:
            self.client.cancel_order_by_id(o.id)

    def get_account_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)
