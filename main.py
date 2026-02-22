import os
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from core.models import Signal, TradeContext, TradeState
from core.feature_engine import FeatureEngine
from core.strategy_engine import StrategyEngine
from core.risk_manager import RiskManager
from core.state_machine import TradeStateMachine
from core.execution_engine import ExecutionEngine
from core.logger import bot_logger
from core.telemetry import telemetry
from core.journal import journal
import psutil

# ---------------- CONFIGURATION ----------------
SYMBOL = "BTC/USD"
HEARTBEAT_INTERVAL_HOURS = 6
MEMORY_THRESHOLD_MB = 250 # Alert if bot exceeds 250MB
API_KEY_ID = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY_ID or not SECRET_KEY:
    raise RuntimeError("Missing Alpaca API credentials. Please set ALPACA_API_KEY and ALPACA_SECRET_KEY.")

def get_next_boundary(minutes=15):
    now = datetime.now(timezone.utc)
    delta = minutes - (now.minute % minutes)
    boundary = now + timedelta(minutes=delta)
    return boundary.replace(second=0, microsecond=0)

def fetch_latest_data(client, symbol, days=5):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    req = CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame(15, TimeFrameUnit.Minute), start=start_date, end=end_date)
    bars = client.get_crypto_bars(req).df.droplevel(0)
    bars.index = pd.to_datetime(bars.index, utc=True).floor('15min')
    return bars

def fetch_hourly_data(client, symbol, days=30):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    req = CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Hour, start=start_date, end=end_date)
    bars = client.get_crypto_bars(req).df.droplevel(0)
    bars.index = pd.to_datetime(bars.index, utc=True).round('h')
    return bars

def calculate_latest_regime(df_1h):
    df = df_1h.copy()
    EMA_FAST, ATR_PERIOD = 50, 14
    df['EMA50'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['TR'] = (df['high'] - df['low']).rolling(ATR_PERIOD).mean()
    df['ATR_pct'] = df['TR'] / df['close'] * 100
    df['EMA50_slope'] = df['EMA50'].pct_change() * 100
    
    row = df.iloc[-1]
    regime = 'Neutral'
    if row['EMA50_slope'] > 0.05: regime = 'Trend_Up'
    elif row['EMA50_slope'] < -0.05: regime = 'Trend_Down'
    elif row['ATR_pct'] > 1.3: regime = 'Expansion'
    
    return regime, row['EMA50_slope'], row['ATR_pct']

def check_health():
    """Monitors process resources and returns a health summary."""
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_pct = process.cpu_percent(interval=None)
    
    is_healthy = mem_mb < MEMORY_THRESHOLD_MB
    return is_healthy, mem_mb, cpu_pct

def reconstruct_context(exec_engine, symbol, current_atr, snapshot_timestamp):
    """Rebuilds a TradeContext from Alpaca's live position/orders."""
    details = exec_engine.get_position_details(symbol)
    if not details:
        return None
        
    side, qty, avg_price = details
    sl, tp = exec_engine.get_symbol_bracket_orders(symbol)
    
    # Heuristic: Reconstruct as ENTERED, FSM will promote to RUNNER if logic matches
    return TradeContext(
        direction=side,
        entry_price=avg_price,
        size=qty,
        stop_loss=sl if sl else (avg_price - side.value * current_atr),
        tp_target=tp if tp else (avg_price + side.value * current_atr * 2.2),
        atr_at_entry=current_atr, 
        entry_time=snapshot_timestamp, # Approximated as current if unknown
        runners_allowed=True,
        state=TradeState.ENTERED
    )

def run_trading_loop():
    """Main trading loop - extracted for supervisor wrapper."""
    print("=== STARTING DAY 17 PRODUCTION LOOP (RECONCILED) ===")
    
    # Initialize Core Components
    data_client = CryptoHistoricalDataClient(API_KEY_ID, SECRET_KEY)
    risk_mgr = RiskManager()
    state_machine = TradeStateMachine()
    exec_engine = ExecutionEngine(API_KEY_ID, SECRET_KEY, paper=True)
    
    # 1. Connectivity & Security Check (Telemetry Enabled)
    try:
        equity = exec_engine.get_account_equity()
        msg = f"Alpaca Connection Verified. Initial Equity: ${equity:.2f}"
        print(msg)
        telemetry.notify("BOOT", msg)
    except Exception as e:
        msg = f"Alpaca Connection Failed: {e}"
        print(msg)
        telemetry.notify("FATAL", msg, severity="CRITICAL")
        return

    # 2. Broker Truth & Early Data Fetch for Recon
    df_1h_raw = fetch_hourly_data(data_client, SYMBOL)
    regime, slope, h_atr_pct = calculate_latest_regime(df_1h_raw)
    df_15m_raw = fetch_latest_data(data_client, SYMBOL)
    df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
    current_snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)

    if exec_engine.has_open_position(SYMBOL):
        msg = f"Existing position detected for {SYMBOL}. Attempting reconstruction..."
        print(f"[RECON] {msg}")
        ctx = reconstruct_context(exec_engine, SYMBOL, current_snapshot.atr, current_snapshot.timestamp)
        if ctx:
            state_machine.enter(ctx)
            recon_msg = f"Recon Successful: State={ctx.state.name} | Direction={ctx.direction.name} | SL={ctx.stop_loss:.2f}"
            print(f"[RECON] {recon_msg}")
            telemetry.notify("RECON_SUCCESS", recon_msg)
        else:
            telemetry.notify("RECON_FAIL", "Failed to reconstruct context despite open position.", severity="WARNING")

    peak_equity = equity
    last_heartbeat = datetime.now(timezone.utc)

    while True:
        try:
            # Heartbeat & Health Check
            healthy, mem, cpu = check_health()
            if not healthy:
                telemetry.notify("HEALTH_CRITICAL", f"Memory leak detected: {mem:.1f}MB. Graceful shutdown initiated.", severity="CRITICAL")
                return

            if (datetime.now(timezone.utc) - last_heartbeat).total_seconds() > (HEARTBEAT_INTERVAL_HOURS * 3600):
                telemetry.notify("HEARTBEAT", f"System Live. Equity: ${equity:.2f} | Mem: {mem:.1f}MB | CPU: {cpu:.1f}%")
                last_heartbeat = datetime.now(timezone.utc)

            # 3. Wait for 15-minute Candle Close
            next_bar = get_next_boundary(15)
            wait_seconds = (next_bar - datetime.now(timezone.utc)).total_seconds()
            
            print(f"Sleeping until {next_bar} (Wait: {wait_seconds:.1f}s)...")
            if wait_seconds > 0:
                time.sleep(wait_seconds + 5) # Bar-close + padding

            # 4. Fetch & Process Data
            df_15m_raw = fetch_latest_data(data_client, SYMBOL)
            df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
            
            df_1h_raw = fetch_hourly_data(data_client, SYMBOL)
            regime, slope, h_atr_pct = calculate_latest_regime(df_1h_raw)
            
            snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)
            
            # Update Local Equity Check
            equity = exec_engine.get_account_equity()
            peak_equity = max(peak_equity, equity)

            print(f"[{snapshot.timestamp}] Close: {snapshot.close:.2f} | Regime: {regime} | Slope: {slope:.4f}")

            # 5. State Machine Update (Open Positions)
            if not state_machine.is_flat():
                r_pnl, tag = state_machine.update(snapshot)
                if r_pnl is not None:
                    # EXIT EVENT
                    exec_engine.cancel_all_orders(SYMBOL)
                    exec_engine.close_position(SYMBOL) # Ensure position is flat
                    risk_mgr.record_trade(r_pnl, tag, snapshot.timestamp)
                    
                    # Persistent Journaling
                    journal.log_trade(state_machine.context, snapshot, r_pnl, tag)
                    
                    bot_logger.log_event("STATE_TRANSITION", {"to": "FLAT", "reason": tag, "r_pnl": r_pnl})
                    telemetry.notify("TRADE_EXIT", f"Closed {SYMBOL} | Reason: {tag} | R-PnL: {r_pnl:.2f}")
                    print(f"[EVENT] Trade Closed: {tag} | R: {r_pnl:.2f}")
                else:
                    print(f"[STATUS] In Trade | State: {state_machine.context.state.name} | SL: {state_machine.context.stop_loss:.2f}")

            # 6. Strategy Engine (Entry Signals)
            if state_machine.is_flat():
                signal = StrategyEngine.get_signal(snapshot)
                
                if signal != Signal.NONE:
                    # 7. Risk Gate
                    allowed, risk_pct, runners_allowed = risk_mgr.check_gates(snapshot, equity, peak_equity)
                    
                    if allowed:
                        # 8. Precision Execution
                        size_dollars = equity * risk_pct
                        risk_per_unit = snapshot.atr
                        size_units = size_dollars / risk_per_unit
                        
                        # Explicit SL/TP logic (Direction-Safe)
                        if signal == Signal.LONG:
                            stop_loss = snapshot.close - snapshot.atr
                            tp_target = snapshot.close + (snapshot.atr * 2.2)
                        else: # Signal.SHORT
                            stop_loss = snapshot.close + snapshot.atr
                            tp_target = snapshot.close - (snapshot.atr * 2.2)
                        
                        order_id, filled_price = exec_engine.execute_bracket_order(
                            SYMBOL, signal, size_units, stop_loss, tp_target
                        )
                        
                        # Use actual fill price for context if available
                        entry_price = filled_price if filled_price else snapshot.close
                        
                        # 9. Update State
                        context = TradeContext(
                            direction=signal,
                            entry_price=entry_price,
                            size=size_units,
                            stop_loss=stop_loss,
                            tp_target=tp_target,
                            atr_at_entry=snapshot.atr,
                            entry_time=snapshot.timestamp,
                            runners_allowed=runners_allowed
                        )
                        state_machine.enter(context)
                        
                        bot_logger.log_event("STATE_TRANSITION", {
                            "to": "ENTERED", 
                            "order_id": order_id, 
                            "direction": signal.name,
                            "entry_price": entry_price
                        })
                        telemetry.notify("TRADE_ENTRY", f"Entered {signal.name} {SYMBOL} at {entry_price:.2f} | Size: {size_units:.4f}")
                        print(f"[EVENT] Entry Order Submitted: {order_id} | Filled: {entry_price:.2f}")
                    else:
                        print("[STATUS] Signal detected but Risk Gate blocked entry.")
                else:
                    print("[STATUS] No Signal.")

        except Exception as e:
            err_msg = f"Crash in loop: {e}"
            print(f"[ERROR] {err_msg}")
            telemetry.notify("CRASH", err_msg, severity="CRITICAL")
            time.sleep(30) # Backup wait

# ---------------- SUPERVISOR WRAPPER ----------------
def supervisor():
    """
    Supervisor wrapper for the trading loop.
    
    HARDENING: Provides auto-restart capability with:
    - Crash detection and logging
    - 30-second backoff before restart
    - Graceful shutdown handling for KeyboardInterrupt
    - Crash telemetry emission
    """
    crash_count = 0
    while True:
        try:
            run_trading_loop()
        except KeyboardInterrupt:
            # Graceful shutdown on Ctrl+C
            telemetry.notify("BOT_SHUTDOWN", "User initiated graceful shutdown", severity="INFO")
            print("\n[SUPERVISOR] Graceful shutdown received. Exiting.")
            break
        except Exception as e:
            crash_count += 1
            err_msg = f"Crash #{crash_count}: {type(e).__name__}: {e}"
            print(f"[CRITICAL] {err_msg}")
            telemetry.notify("BOT_CRASH", err_msg, severity="CRITICAL")
            
            # 30-second backoff before restart
            print("[SUPERVISOR] Waiting 30 seconds before restart...")
            time.sleep(30)
            
            # Continue to next iteration (reconciliation will rebuild state)
            continue
    
    print("[SUPERVISOR] Supervisor exited.")

if __name__ == "__main__":
    supervisor()
