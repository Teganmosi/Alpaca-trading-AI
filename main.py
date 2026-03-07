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
TRADE_COOLDOWN_MINUTES = 120
API_KEY_ID = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY_ID or not SECRET_KEY:
    raise RuntimeError("Missing Alpaca API credentials.")

def get_next_boundary(minutes=60):
    now = datetime.now(timezone.utc)
    delta = minutes - (now.minute % minutes)
    boundary = now + timedelta(minutes=delta)
    return boundary.replace(second=0, microsecond=0)

def fetch_latest_data(client, symbol, days=5):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    req = CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Hour, start=start_date, end=end_date)
    bars = client.get_crypto_bars(req).df.droplevel(0)
    bars.index = pd.to_datetime(bars.index, utc=True).round('h')
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
    
    # 1h Specific Confirmation (Price vs EMA)
    df['above_ema'] = df['close'] > df['EMA50']
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

def reconstruct_position_if_needed(exec_engine, state_machine, current_snapshot):
    try:
        has_position = exec_engine.has_open_position(SYMBOL)
        print(f"[STARTUP] Position check: {has_position}")
        if has_position:
            ctx = exec_engine.get_position_details(SYMBOL)
            if ctx:
                side, qty, avg_price = ctx
                stop_loss = avg_price - side.value * current_snapshot.atr
                tp_target = avg_price + side.value * current_snapshot.atr * 2.2
                context = TradeContext(
                    direction=side,
                    entry_price=avg_price,
                    size=qty,
                    stop_loss=stop_loss,
                    tp_target=tp_target,
                    atr_at_entry=current_snapshot.atr,
                    entry_time=current_snapshot.timestamp,
                    runners_allowed=True,
                    state=TradeState.ENTERED
                )
                state_machine.enter(context)
                print(f"[RECON] Position reconstructed: {side.name} @ ${avg_price:.2f}")
    except Exception as e:
        print(f"[STARTUP] Position check failed: {e}")

def handle_active_trade(snapshot, state_machine, exec_engine, risk_mgr):
    ctx = state_machine.context
    direction = ctx.direction.value
    
    should_stop = (
        (direction == 1 and snapshot.low <= ctx.stop_loss) or
        (direction == -1 and snapshot.high >= ctx.stop_loss)
    )
    
    should_tp = (
        (direction == 1 and snapshot.high >= ctx.tp_target) or
        (direction == -1 and snapshot.low <= ctx.tp_target)
    )
    
    elapsed_candles = (snapshot.timestamp - ctx.entry_time).total_seconds() / 3600
    should_time_exit = elapsed_candles >= 20
    
    if should_stop or should_tp or should_time_exit:
        if should_stop:
            exit_reason = "SL"
            exit_price = ctx.stop_loss
        elif should_tp:
            exit_reason = "TP"
            exit_price = ctx.tp_target
        else:
            exit_reason = "TIME"
            exit_price = snapshot.close

        exec_engine.cancel_all_orders(SYMBOL)
        exec_engine.close_position(SYMBOL)
        
        pnl = direction * (exit_price - ctx.entry_price) * ctx.size
        r_pnl = pnl / (ctx.atr_at_entry * ctx.size)
        
        risk_mgr.record_trade(r_pnl, exit_reason, snapshot.timestamp)
        print(f"[EVENT] Trade Closed: {exit_reason} | Exit: ${exit_price:.2f} | R: {r_pnl:.2f}")
        
        state_machine._reset()
        return snapshot.timestamp
    
    print(f"[STATUS] In Trade | Entry: ${ctx.entry_price:.2f} | SL: ${ctx.stop_loss:.2f} | TP: ${ctx.tp_target:.2f} | Bars: {elapsed_candles:.0f}")
    return None

def check_for_signals(snapshot, equity, peak_equity, state_machine, risk_mgr, exec_engine, last_exit_time):
    if last_exit_time is not None:
        minutes_since_exit = (snapshot.timestamp - last_exit_time).total_seconds() / 60
        if minutes_since_exit < TRADE_COOLDOWN_MINUTES:
            print(f"[COOLDOWN] {minutes_since_exit:.1f}/{TRADE_COOLDOWN_MINUTES} min")
            return
    
    signal = StrategyEngine.get_signal(snapshot)
    if signal == Signal.NONE:
        print("[STATUS] No Signal")
        return

    allowed, _, runners_allowed = risk_mgr.check_gates(snapshot, equity, peak_equity, signal)
    if not allowed:
        print("[STATUS] Risk Gate blocked")
        return

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
        print(f"[EVENT] Entered {signal.name} at ${entry_price:.2f}")

def wait_for_next_bar():
    next_bar = get_next_boundary(60)
    wait_seconds = (next_bar - datetime.now(timezone.utc)).total_seconds()
    print(f"Sleeping until {next_bar} (Wait: {wait_seconds:.1f}s)...")
    if wait_seconds > 0:
        time.sleep(wait_seconds + 5)

def execute_cycle(data_client, exec_engine, state_machine, risk_mgr, last_exit_time, peak_equity):
    df_15m_raw = fetch_latest_data(data_client, SYMBOL)
    df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
    df_1h_raw = fetch_hourly_data(data_client, SYMBOL)
    regime, slope, _ = calculate_latest_regime(df_1h_raw)
    snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)
    
    equity = exec_engine.get_account_equity()
    new_peak_equity = max(peak_equity, equity)

    print(f"[{snapshot.timestamp}] Close: ${snapshot.close:.2f} | Regime: {regime}")

    new_last_exit_time = last_exit_time
    if not state_machine.is_flat():
        exit_time = handle_active_trade(snapshot, state_machine, exec_engine, risk_mgr)
        if exit_time:
            new_last_exit_time = exit_time

    if state_machine.is_flat():
        check_for_signals(snapshot, equity, new_peak_equity, state_machine, risk_mgr, exec_engine, new_last_exit_time)
        
    return equity, new_peak_equity, new_last_exit_time

def run_trading_loop():
    print("=== STARTING PRODUCTION LOOP (STATE MACHINE ONLY) ===")
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
    regime, slope, _ = calculate_latest_regime(df_1h_raw)
    df_15m_raw = fetch_latest_data(data_client, SYMBOL)
    df_15m = FeatureEngine.calculate_metrics(df_15m_raw)
    current_snapshot = FeatureEngine.get_snapshot(df_15m, -1, regime=regime, slope=slope)

    reconstruct_position_if_needed(exec_engine, state_machine, current_snapshot)

    peak_equity = equity
    last_heartbeat = datetime.now(timezone.utc)

    while True:
        try:
            healthy, mem, _ = check_health()
            if not healthy:
                print(f"[CRITICAL] Memory leak: {mem:.1f}MB")
                return

            if (datetime.now(timezone.utc) - last_heartbeat).total_seconds() > (HEARTBEAT_INTERVAL_HOURS * 3600):
                print(f"[HEARTBEAT] Equity: ${equity:.2f}")
                last_heartbeat = datetime.now(timezone.utc)

            wait_for_next_bar()

            equity, peak_equity, last_exit_time = execute_cycle(
                data_client, exec_engine, state_machine, risk_mgr, last_exit_time, peak_equity
            )

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
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
            import traceback
            traceback.print_exc()
            time.sleep(30)
