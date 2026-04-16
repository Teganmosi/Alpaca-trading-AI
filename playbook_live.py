import os
from dotenv import load_dotenv

load_dotenv()
import time
import signal
import threading
import json
import pandas as pd
from datetime import datetime, timezone, timedelta
from flask import Flask

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from strategies.playbook_strategy import PlaybookStrategy
from core.models import Signal
from core.risk_manager import RiskManager
from core.execution_engine import ExecutionEngine
from core.logger import bot_logger
from core.telemetry import telemetry
from core.journal import journal
import logging_config
import logging

__version__ = "1.0.0"

config = {
    "SYMBOL": "BTC/USD",
    "API_KEY_ID": os.getenv("ALPACA_API_KEY"),
    "SECRET_KEY": os.getenv("ALPACA_SECRET_KEY"),
    "MEMORY_THRESHOLD_MB": 500,
    "TRADE_COOLDOWN_MINUTES": 60,
    "HEARTBEAT_INTERVAL_HOURS": 1,
}
logger = logging.getLogger(__name__)


class BotState:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_signal_time = None
        self.last_signal_type = "NONE"
        self.current_price = 0.0
        self.rsi_value = 0.0
        self.stoch_k = 0.0
        self.stoch_d = 0.0
        self.adx_value = 0.0
        self.open_position = None
        self.trade_history = []


bot_state = BotState()

app = Flask(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


def get_recent_logs(lines=50):
    log_file = "logs/trading.log"
    if not os.path.exists(log_file):
        return "Log file not found yet."
    with open(log_file, "r") as f:
        lines_list = f.readlines()[-lines:]
    return "".join(lines_list)


@app.route("/logs")
def logs():
    content = get_recent_logs()
    return f"<pre>{content}</pre>", 200, {"Content-Type": "text/html"}


@app.route("/dashboard")
def dashboard():
    with bot_state.lock:
        uptime = "N/A"  # Could calculate from start time
        html = f"""
        <html>
        <head>
            <title>Bot Dashboard</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ background: #121212; color: #fff; font-family: Arial, sans-serif; padding: 20px; }}
                h1, h2 {{ color: #00ff00; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #333; padding: 8px; text-align: left; }}
                th {{ background: #333; }}
            </style>
        </head>
        <body>
            <h1>Trading Bot Dashboard</h1>
            <h2>Bot Status: Running | Uptime: {uptime}</h2>
            <h3>Market Data</h3>
            <p>Current Price: ${bot_state.current_price:.2f}</p>
            <p>RSI: {bot_state.rsi_value:.2f}</p>
            <p>Stochastic K: {bot_state.stoch_k:.2f}</p>
            <p>Stochastic D: {bot_state.stoch_d:.2f}</p>
            <p>ADX: {bot_state.adx_value:.2f}</p>
            <h3>Last Signal</h3>
            <p>Type: {bot_state.last_signal_type} at {bot_state.last_signal_time}</p>
            <h3>Active Position</h3>
            {"<p>No active position</p>" if not bot_state.open_position else f"<p>Side: {bot_state.open_position['direction']}, Entry: ${bot_state.open_position['entry_price']:.2f}</p>"}
            <h3>Recent Trades</h3>
            <table>
                <tr><th>Date</th><th>Type</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Status</th></tr>
                {"".join(f"<tr><td>{t.get('date', 'N/A')}</td><td>{t.get('type', 'N/A')}</td><td>{t.get('entry', 'N/A')}</td><td>{t.get('exit', 'N/A')}</td><td>{t.get('pnl', 'N/A')}</td><td>{t.get('status', 'N/A')}</td></tr>" for t in bot_state.trade_history[-10:])}
            </table>
        </body>
        </html>
        """
        return html


# Optimized parameters
PLAYBOOK_PARAMS = {"trend_relax": True, "sl_buffer": 0.005, "breakeven_after_tp1": True}


def get_next_1h_boundary():
    now = datetime.now(timezone.utc)
    boundary = now.replace(minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=1)
    return boundary


def fetch_1h_data(client, symbol, days=30):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    req = CryptoBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(1, TimeFrameUnit.Hour),
        start=start_date,
        end=end_date,
    )
    bars = client.get_crypto_bars(req).df.droplevel(0)
    bars.index = pd.to_datetime(bars.index, utc=True)
    return bars


def resample_to_4h(df_1h):
    df_4h = (
        df_1h.resample("4H")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
    )
    return df_4h


def resample_to_daily(df_1h):
    df_daily = (
        df_1h.resample("D")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
    )
    return df_daily


def check_health():
    import psutil

    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_pct = process.cpu_percent(interval=None)
    return mem_mb < config["MEMORY_THRESHOLD_MB"], mem_mb, cpu_pct


def handle_partial_exits(exec_engine, position, strategy, idx):
    exits = strategy.get_exit_signals(position, idx)
    for exit_type, exit_price in exits:
        if exit_type == "TP1" and not position.get("tp1_hit", False):
            # Close 50%
            close_size = position["size"] * 0.5
            success, _ = exec_engine.close_partial_position(
                config["SYMBOL"], close_size
            )
            if success:
                position["tp1_hit"] = True
                position["size"] -= close_size
                logger.info(f"TP1 hit: Closed 50% at ${exit_price:.2f}")
        elif exit_type == "TP2":
            # Close remaining
            close_size = position["size"]
            success, _ = exec_engine.close_partial_position(
                config["SYMBOL"], close_size
            )
            if success:
                position["size"] = 0
                logger.info(f"TP2 hit: Closed remaining at ${exit_price:.2f}")
                return True  # Fully closed
        elif exit_type == "SL":
            # Close all
            success, _ = exec_engine.close_position(config["SYMBOL"])
            if success:
                position["size"] = 0
                logger.info(f"SL hit: Closed all at ${exit_price:.2f}")
                return True
    return False


def run_playbook_loop():
    logger.info("Starting Playbook Live Trading Loop")
    logger.info(f"Playbook Bot v{__version__}")
    logger.info(f"Parameters: {PLAYBOOK_PARAMS}")

    data_client = CryptoHistoricalDataClient(config["API_KEY_ID"], config["SECRET_KEY"])
    exec_engine = ExecutionEngine(
        config["API_KEY_ID"],
        config["SECRET_KEY"],
        paper=os.getenv("TRADING_MODE", "paper") == "paper",
    )
    risk_mgr = RiskManager()

    position = None  # {'direction': , 'entry_price': , 'size': , 'tp1_hit': False}

    try:
        equity = exec_engine.get_account_equity()
        logger.info(f"Initial equity: ${equity:.2f}")
    except Exception as e:
        logger.error(f"Alpaca connection failed: {e}")
        return

    last_exit_time = None

    while True:
        try:
            healthy, mem, _ = check_health()
            if not healthy:
                logger.critical(f"Memory leak: {mem:.1f}MB")
                return

            # Wait for next 1H bar
            next_bar = get_next_1h_boundary()
            wait_seconds = (next_bar - datetime.now(timezone.utc)).total_seconds()
            logger.info(
                f"Waiting for next 1H bar at {next_bar} (Wait: {wait_seconds:.1f}s)..."
            )
            if wait_seconds > 0:
                time.sleep(wait_seconds + 10)  # Extra 10s

            # Fetch data
            df_1h = fetch_1h_data(data_client, config["SYMBOL"])
            df_4h = resample_to_4h(df_1h)
            df_daily = resample_to_daily(df_1h)
            strategy = PlaybookStrategy(df_daily, df_4h, df_1h, **PLAYBOOK_PARAMS)

            # Get latest snapshot
            latest_idx = len(df_1h) - 1
            row = df_1h.iloc[latest_idx]
            current_time = row.name

            logger.info(f"[{current_time}] Close: ${row['close']:.2f}")

            with bot_state.lock:
                bot_state.last_signal_time = current_time
                bot_state.current_price = row["close"]

            # Handle active position
            if position:
                fully_closed = handle_partial_exits(
                    exec_engine, position, strategy, latest_idx
                )
                if fully_closed:
                    position = None
                    last_exit_time = current_time
                    with bot_state.lock:
                        bot_state.open_position = None

            # Check for new signal
            if not position:
                if last_exit_time:
                    minutes_since_exit = (
                        current_time - last_exit_time
                    ).total_seconds() / 60
                    if minutes_since_exit < config["TRADE_COOLDOWN_MINUTES"]:
                        logger.info(
                            f"Cooldown: {minutes_since_exit:.1f}/{config['TRADE_COOLDOWN_MINUTES']} min"
                        )
                    else:
                        signal = strategy.get_signal(latest_idx)
                        with bot_state.lock:
                            bot_state.last_signal_type = (
                                signal.name if signal != Signal.NONE else "NONE"
                            )
                        if signal != Signal.NONE:
                            equity = exec_engine.get_account_equity()
                            position_value = equity * 0.05
                            size_units = position_value / row["close"]

                            # Execute order
                            order_id, filled_price = exec_engine.execute_market_order(
                                config["SYMBOL"], signal, size_units
                            )
                            if order_id:
                                entry_price = (
                                    filled_price if filled_price else row["close"]
                                )
                                position = {
                                    "direction": signal.name,
                                    "entry_price": entry_price,
                                    "size": size_units,
                                    "tp1_hit": False,
                                    "entry_time": current_time,
                                }
                                with bot_state.lock:
                                    bot_state.open_position = position.copy()
                                logger.info(
                                    f"Entered {signal.name} at ${entry_price:.2f}, size: {size_units}"
                                )

        except Exception as e:
            logger.error(f"Error in loop: {e}")
            import traceback

            logger.error(traceback.format_exc())
            time.sleep(60)


def signal_handler(signum, frame):
    logger.info("Shutdown signal received")
    os._exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    trading_thread = threading.Thread(target=run_playbook_loop, daemon=True)
    trading_thread.start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
