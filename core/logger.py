import logging
import json
from datetime import datetime

class StructuredLogger:
    def __init__(self, name="trading_bot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # File handler
        fh = logging.FileHandler("trading_logs.json")
        self.logger.addHandler(fh)

    def log_event(self, event_type: str, data: dict):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data
        }
        self.logger.info(json.dumps(payload))

    def log_trade(self, context_data: dict, result_data: dict):
        self.log_event("TRADE_EXIT", {
            "entry": context_data,
            "exit": result_data
        })
        
bot_logger = StructuredLogger()
