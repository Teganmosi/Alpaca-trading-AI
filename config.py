from dotenv import load_dotenv
import os

load_dotenv()


def get_config():
    config = {
        "API_KEY_ID": os.getenv("ALPACA_API_KEY"),
        "SECRET_KEY": os.getenv("ALPACA_SECRET_KEY"),
        "TRADING_MODE": os.getenv("TRADING_MODE", "paper"),
        "SYMBOL": os.getenv("SYMBOL", "BTC/USD"),
        "HEARTBEAT_INTERVAL_HOURS": int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "6")),
        "MEMORY_THRESHOLD_MB": int(os.getenv("MEMORY_THRESHOLD_MB", "250")),
        "TRADE_COOLDOWN_MINUTES": int(os.getenv("TRADE_COOLDOWN_MINUTES", "120")),
        "LOOKBACK_PERIOD": int(os.getenv("LOOKBACK_PERIOD", "10")),
        "ATR_MULTIPLIER": float(os.getenv("ATR_MULTIPLIER", "1.5")),
    }

    # Validation
    if not config["API_KEY_ID"] or not config["SECRET_KEY"]:
        raise RuntimeError("Missing Alpaca API credentials.")

    if config["TRADING_MODE"] not in ["paper", "live"]:
        raise ValueError("TRADING_MODE must be 'paper' or 'live'")

    return config
