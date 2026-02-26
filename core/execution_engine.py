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
            print(f"[DEBUG] Position detected: {symbol} | Qty: {qty} | Side: {pos.side}")
            return qty > 0
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "no position" in err_str:
                print(f"[DEBUG] No open position for {symbol}")
                return False
            print(f"[DEBUG] Error checking position: {e}")
            return False

    def get_position_details(self, symbol: str):
        try:
            pos = self.client.get_open_position(symbol)
            qty = float(pos.qty)
            if qty <= 0:
                return None
            side = Signal.LONG if pos.side == 'long' else Signal.SHORT
            print(f"[DEBUG] Position details: {symbol} | Side: {side.name} | Qty: {qty}")
            return side, qty, float(pos.avg_entry_price)
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "no position" in err_str:
                print(f"[DEBUG] No position details for {symbol}")
            else:
                print(f"[DEBUG] Error getting position details: {e}")
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
        except Exception as e:
            print(f"[DEBUG] Error getting bracket orders: {e}")
            return None, None

    def execute_bracket_order(self, symbol: str, signal: Signal, size: float, stop_loss: float, tp_target: float):
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
            print(f"[EXECUTION] Order filled at ${fill_price:.2f}")
            
            # Wait for position to settle and retry getting it
            time.sleep(2)
            position_qty = None
            
            for retry in range(3):
                try:
                    pos = self.client.get_open_position(symbol)
                    position_qty = float(pos.qty)
                    print(f"[DEBUG] Position found after {retry+1} attempt(s): qty={position_qty}")
                    break
                except Exception as e:
                    if retry < 2:
                        print(f"[DEBUG] Position not found, retrying ({retry+1}/3)...")
                        time.sleep(1)
                    else:
                        print(f"[INFO] Could not get position after 3 attempts: {e}")
            
            if position_qty and position_qty > 0:
                sl_tp_qty = position_qty * 0.50
                if sl_tp_qty > 0.0001:
                    sl_side = OrderSide.SELL if signal == Signal.LONG else OrderSide.BUY
                    try:
                        sl_order_data = MarketOrderRequest(
                            symbol=symbol, qty=sl_tp_qty, side=sl_side,
                            time_in_force=TimeInForce.GTC,
                            stop_loss=StopLossRequest(stop_price=stop_loss)
                        )
                        self.client.submit_order(sl_order_data)
                        print(f"[EXECUTION] Stop loss submitted at ${stop_loss:.2f}")
                    except Exception as e:
                        print(f"[INFO] Stop loss not placed: {e}")
                    try:
                        tp_order_data = MarketOrderRequest(
                            symbol=symbol, qty=sl_tp_qty, side=sl_side,
                            time_in_force=TimeInForce.GTC,
                            take_profit=TakeProfitRequest(limit_price=tp_target)
                        )
                        self.client.submit_order(tp_order_data)
                        print(f"[EXECUTION] Take profit submitted at ${tp_target:.2f}")
                    except Exception as e:
                        print(f"[INFO] Take profit not placed: {e}")
            
            return order_id_str, fill_price
        else:
            # Stocks - bracket order
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
        print(f"[EXECUTION] Closing position for {symbol}")
        try:
            self.client.close_position(symbol)
        except Exception as e:
            print(f"[EXECUTION] Note (Close Position): {e}")

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
