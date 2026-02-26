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
MEMORY_THRESHOLD_MB = 250
TRADE_COOLDOWN_MINUTES = 15
API_KEY_ID = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY_ID or not SECRET_KEY:
    raise RuntimeError("Missing Alpaca API credentials.")

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
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_pct = process.cpu_percent(interval=None)
    return mem_mb < MEMORY_THRESHOLD_MB, mem_mb, cpu_pct

def reconstruct_context(exec_engine, symbol, current_atr, snapshot_timestamp):
    details = exec_engine.get_position_details(symbol)
    if not details:
        return None
    side, qty, avg_price = details
    sl, tp = exec_engine.get_symbol_bracket_orders(symbol)
    return TradeContext(
        direction=side,
        entry_price=avg_price,
        size=qty,
        stop_loss=sl if sl else (avg_price - side.value * current_atr),
        tp_target=tp if tp else (avg_price + side.value * current_atr * 2.2),
        atr_at_entry=current_atr, 
        entry_time=snapshot_timestamp,
        runners_allowed=True,
        state=TradeState.ENTERED
    )

def check_position_with_retry(exec_engine, symbol, retries=3):
    """Check position with retry - for when Alpaca has timing issues"""
    for i in range(retries):
        has_pos = exec_engine.has_open_position(symbol)
        if has_pos:
            return True
        if i < retries - 1:
            print(f"[DEBUG] Position check retry {i+1}/{retries}...")
            time.sleep(1)
    return False

def run_trading_loop():
    print("=== STARTING DAY 17 PRODUCTION LOOP (RECONCILED) ===")
    data_client = CryptoHistoricalDataClient(API_KEY_ID, SECRET_KEY)
    risk_mgr = RiskManager()
    state_machine = TradeStateMachine()
    exec_engine = ExecutionEngine(API_KEY_ID, SECRET_KEY, paper=True)
    last_exit_time = None
    
    try:
        equity = exec_engine.get_account_equity()
        print(f"Alpaca Connection Verified. Initial Equity: ${equity:.2f}")
    except Exception as e:
        print(f"Alpaca Connection Failed: {e}")
        return

    df_1h_raw = fetch_hourly_data(data_client, SYMBOL)
    regime, slope, h_atr_pct = calculate_latest_regime(df_1h_raw)
    df_15m_raw = fetch_latest_data(data_client, SYMBOL)
    df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
    current_snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)

    # Check for existing position on startup
    has_position = check_position_with_retry(exec_engine, SYMBOL)
    print(f"[STARTUP] Position check: {has_position}")
    
    if has_position:
        ctx = reconstruct_context(exec_engine, SYMBOL, current_snapshot.atr, current_snapshot.timestamp)
        if ctx:
            state_machine.enter(ctx)
            print(f"[RECON] Position reconstructed: {ctx.direction.name}")

    peak_equity = equity
    last_heartbeat = datetime.now(timezone.utc)

    while True:
        try:
            healthy, mem, cpu = check_health()
            if not healthy:
                print(f"[CRITICAL] Memory leak: {mem:.1f}MB")
                return

            if (datetime.now(timezone.utc) - last_heartbeat).total_seconds() > (HEARTBEAT_INTERVAL_HOURS * 3600):
                print(f"[HEARTBEAT] Equity: ${equity:.2f} | Mem: {mem:.1f}MB")
                last_heartbeat = datetime.now(timezone.utc)

            next_bar = get_next_boundary(15)
            wait_seconds = (next_bar - datetime.now(timezone.utc)).total_seconds()
            print(f"Sleeping until {next_bar} (Wait: {wait_seconds:.1f}s)...")
            if wait_seconds > 0:
                time.sleep(wait_seconds + 5)

            df_15m_raw = fetch_latest_data(data_client, SYMBOL)
            df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
            df_1h_raw = fetch_hourly_data(data_client, SYMBOL)
            regime, slope, h_atr_pct = calculate_latest_regime(df_1h_raw)
            snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)
            equity = exec_engine.get_account_equity()
            peak_equity = max(peak_equity, equity)

            print(f"[{snapshot.timestamp}] Close: {snapshot.close:.2f} | Regime: {regime}")

            if not state_machine.is_flat():
                # Use retry logic when checking position during trade
                actual_has_position = check_position_with_retry(exec_engine, SYMBOL)
                if not actual_has_position:
                    # Position might have closed - try to verify with a close attempt or wait
                    print(f"[DEBUG] Position check failed, attempting close...")
                    try:
                        exec_engine.close_position(SYMBOL)
                    except:
                        pass
                    time.sleep(2)
                    # Check again after close attempt
                    actual_has_position = check_position_with_retry(exec_engine, SYMBOL, retries=2)
                    
                    if not actual_has_position:
                        print(f"[WARNING] Position disappeared! Resetting state.")
                        state_machine._reset()
                    else:
                        # Position still exists, reconstruct
                        ctx = reconstruct_context(exec_engine, SYMBOL, snapshot.atr, snapshot.timestamp)
                        if ctx:
                            state_machine.enter(ctx)
                            print(f"[RECON] Position reconstructed after failed check")
                else:
                    r_pnl, tag = state_machine.update(snapshot)
                    if r_pnl is not None:
                        exec_engine.cancel_all_orders(SYMBOL)
                        exec_engine.close_position(SYMBOL)
                        risk_mgr.record_trade(r_pnl, tag, snapshot.timestamp)
                        last_exit_time = snapshot.timestamp
                        print(f"[EVENT] Trade Closed: {tag} | R: {r_pnl:.2f}")
                    else:
                        print(f"[STATUS] In Trade | SL: {state_machine.context.stop_loss:.2f}")

            if state_machine.is_flat():
                # Use retry logic for position check when flat too
                actual_has_position = check_position_with_retry(exec_engine, SYMBOL)
                if actual_has_position:
                    print(f"[WARNING] Hidden position detected! Reconstructing...")
                    ctx = reconstruct_context(exec_engine, SYMBOL, snapshot.atr, snapshot.timestamp)
                    if ctx:
                        state_machine.enter(ctx)
                
                # Check cooldown
                if last_exit_time is not None:
                    minutes_since_exit = (snapshot.timestamp - last_exit_time).total_seconds() / 60
                    if minutes_since_exit < TRADE_COOLDOWN_MINUTES:
                        print(f"[COOLDOWN] {minutes_since_exit:.1f}/{TRADE_COOLDOWN_MINUTES} min")
                        continue
                
                # Get signal and trade
                signal = StrategyEngine.get_signal(snapshot)
                if signal != Signal.NONE:
                    allowed, risk_pct, runners_allowed = risk_mgr.check_gates(snapshot, equity, peak_equity)
                    if allowed:
                        max_position_pct = 0.05
                        position_value = equity * max_position_pct
                        size_units = position_value / snapshot.close
                        
                        if signal == Signal.LONG:
                            stop_loss = snapshot.close - snapshot.atr
                            tp_target = snapshot.close + (snapshot.atr * 2.2)
                        else:
                            stop_loss = snapshot.close + snapshot.atr
                            tp_target = snapshot.close - (snapshot.atr * 2.2)
                        
                        order_id, filled_price = exec_engine.execute_bracket_order(
                            SYMBOL, signal, size_units, stop_loss, tp_target
                        )
                        
                        if order_id:
                            entry_price = filled_price if filled_price else snapshot.close
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
                            print(f"[EVENT] Entered {signal.name} at {entry_price:.2f}")
                    else:
                        print("[STATUS] Risk Gate blocked")
                else:
                    print("[STATUS] No Signal")

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(30)

if __name__ == "__main__":
    while True:
        try:
            run_trading_loop()
        except KeyboardInterrupt:
            print("Shutdown requested")
            break
        except Exception as e:
            print(f"[CRITICAL] {e}")
            time.sleep(30)
