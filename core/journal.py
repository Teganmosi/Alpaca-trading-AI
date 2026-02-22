import csv
import os
import math
from datetime import datetime
from pathlib import Path
from core.telemetry import telemetry

class TradeJournaler:
    """
    Persistent CSV-based journal for recording every trade exit and performance metric.
    This ensures that even if logs are rotated or lost, the trade history remains.
    
    HARDENING: Validates trade data BEFORE writing to prevent corruption.
    """
    def __init__(self, filename: str = "trade_journal.csv"):
        self.filepath = Path(filename)
        self.headers = [
            "exit_time", "symbol", "direction", "entry_price", "size", 
            "exit_price", "r_pnl", "tag", "regime", "slope", "atr_at_entry"
        ]
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not self.filepath.exists():
            with open(self.filepath, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)

    def _validate_trade_data(self, context, exit_snapshot, r_pnl: float) -> bool:
        """
        Validates trade data before writing to journal.
        Returns True if valid, raises exception if invalid.
        
        Validation rules:
        - r_pnl must be finite (not NaN, not inf)
        - entry_price must be > 0
        - stop_price must != entry_price (from context)
        - position_size must be > 0
        """
        # Check R is finite (not NaN, not inf)
        if not math.isfinite(r_pnl):
            raise ValueError(f"INVALID R-PNL: {r_pnl} (NaN or Inf detected)")
        
        # Check entry_price > 0
        if context.entry_price <= 0:
            raise ValueError(f"INVALID ENTRY_PRICE: {context.entry_price} (must be > 0)")
        
        # Check stop_price != entry_price
        if context.stop_loss == context.entry_price:
            raise ValueError(f"INVALID STOP_LOSS: equals entry price ({context.entry_price})")
        
        # Check position_size > 0
        if context.size <= 0:
            raise ValueError(f"INVALID POSITION_SIZE: {context.size} (must be > 0)")
        
        return True

    def log_trade(self, context, exit_snapshot, r_pnl: float, tag: str):
        """
        Records a completed trade into the CSV journal.
        
        HARDENING: Validates data BEFORE writing. If validation fails,
        emits CRITICAL telemetry and raises exception (halts trading).
        """
        # HARDENING: Validate BEFORE writing (correct order)
        try:
            self._validate_trade_data(context, exit_snapshot, r_pnl)
        except ValueError as e:
            # Emit CRITICAL telemetry and halt
            telemetry.notify(
                "JOURNAL_CORRUPTION",
                f"Trade validation failed: {e} | Context: entry={context.entry_price}, size={context.size}, stop={context.stop_loss}",
                severity="CRITICAL"
            )
            raise  # Re-raise to halt trading loop
        
        # Validation passed - write to journal
        row = {
            "exit_time": exit_snapshot.timestamp.isoformat(),
            "symbol": "BTC/USD", # Can be generalized from context if added
            "direction": context.direction.name,
            "entry_price": f"{context.entry_price:.2f}",
            "size": f"{context.size:.6f}",
            "exit_price": f"{exit_snapshot.close:.2f}",
            "r_pnl": f"{r_pnl:.4f}",
            "tag": tag,
            "regime": exit_snapshot.regime,
            "slope": f"{exit_snapshot.slope:.4f}",
            "atr_at_entry": f"{context.atr_at_entry:.2f}"
        }
        
        with open(self.filepath, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writerow(row)
        
        print(f"[JOURNAL] Trade recorded in {self.filepath}")

# Global instance
journal = TradeJournaler()
