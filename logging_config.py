import logging
import json
import os
from logging.handlers import RotatingFileHandler

# Create logs directory if not exists
os.makedirs("logs", exist_ok=True)

# Custom level for ALERT
ALERT_LEVEL = 25
logging.addLevelName(ALERT_LEVEL, "ALERT")


def alert(self, message, *args, **kwargs):
    if self.isEnabledFor(ALERT_LEVEL):
        self._log(ALERT_LEVEL, message, args, **kwargs)


logging.Logger.alert = alert

# Formatter for general logs
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# For errors
error_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# For trades JSON
class JSONFormatter(logging.Formatter):
    def format(self, record):
        if hasattr(record, "trade"):
            return json.dumps(record.trade)
        return super().format(record)


json_formatter = JSONFormatter()

# Handlers
trading_handler = RotatingFileHandler(
    "logs/trading.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
trading_handler.setLevel(logging.INFO)
trading_handler.setFormatter(formatter)

error_handler = RotatingFileHandler(
    "logs/errors.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(error_formatter)

trade_handler = RotatingFileHandler(
    "logs/trades.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5
)
trade_handler.setLevel(logging.INFO)
trade_handler.setFormatter(json_formatter)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(trading_handler)
root_logger.addHandler(error_handler)
root_logger.addHandler(trade_handler)


# Helper function for alerts
def send_alert(message):
    logger = logging.getLogger("alert")
    logger.alert(message)
