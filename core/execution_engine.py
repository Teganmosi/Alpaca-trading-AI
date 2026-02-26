from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from core.models import Signal
from core.telemetry import telemetry
import time

TERMINAL_STATES = {"filled", "canceled", "rejected", "expired"}

class ExecutionEngine:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.client = TradingClient(api_key, secret_key, paper=paper)

    def has_open_position(self, symbol: str) -> bool:
        try:
            pos = self.client.get_open_position(symbol)
            qty = float(pos.qty)
            return qty > 0
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "no position" in err_str:
                return False
            return False

    def get_position_details(self, symbol: str):
        try:
            pos = self.client.get_open_position(symbol)
            qty = float(pos.qty)
            if qty <= 0:
                return None
            side = Signal.LONG if pos.side == 'long' else Signal.SHORT
            return side, qty, float(pos.avg_entry_price)
        except Exception:
            return None

    def get_symbol_bracket_orders(self, symbol: str):
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            orders = self.client.get_orders(req)
            sl, tp = None, None
            for o in orders:
                if o.type == 'stop': 
                    sl = float(o.stop_price)
                if o.type == 'limit': 
                    tp = float(o.limit_price)
            return sl, tp
        except Exception:
            return None, None

    def execute_bracket_order(self, symbol: str, signal: Signal, size: float, stop_loss: float, tp_target: float):
        """
        Execute order - but DON'T submit separate SL/TP orders.
        Let the state machine handle exits via close_position() instead.
        This prevents duplicate fills.
        """
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        is_crypto = "/" in symbol
        
        if is_crypto:
            print(f"[EXECUTION] Submitting {side.name} market order for {symbol} | Qty: {size:.6f}")
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=size,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            
            order = self.client.submit_order(order_data)
            order_id_str = str(order.id)
            
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
            filled_qty = float(final_order.filled_qty) if final_order.filled_qty else size
            print(f"[EXECUTION] Order filled at ${fill_price:.2f} | Qty: {filled_qty}")
            
            # DON'T submit SL/TP orders here - let state machine handle exits
            # The state machine will call close_position() when SL/TP is hit
            print(f"[INFO] Position opened. SL: ${stop_loss:.2f}, TP: ${tp_target:.2f} (managed by state machine)")
            
            return order_id_str, fill_price
        else:
            # Stocks - use bracket order
            order_data = MarketOrderRequest(
                symbol=symbol, qty=size, side=side, time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=tp_target),
                stop_loss=StopLossRequest(stop_price=stop_loss)
            )
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
                return None, None
            fill_price = float(final_order.filled_avg_price)
            print(f"[EXECUTION] Order filled at ${fill_price:.2f}")
            return order_id_str, fill_price

    def close_position(self, symbol: str):
        """Close entire position at market"""
        print(f"[EXECUTION] Closing entire position for {symbol}")
        try:
            self.client.close_position(symbol)
            print(f"[EXECUTION] Position closed")
        except Exception as e:
            print(f"[WARNING] Close position error: {e}")

    def cancel_all_orders(self, symbol: str):
        print(f"[EXECUTION] Canceling all open orders for {symbol}")
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            open_orders = self.client.get_orders(req)
            for o in open_orders:
                self.client.cancel_order_by_id(o.id)
        except Exception as e:
            print(f"[WARNING] Error canceling orders: {e}")

    def get_account_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)
