from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Optional

class TradeState(Enum):
    FLAT = "FLAT"
    ENTERED = "ENTERED"
    RUNNER_ACTIVE = "RUNNER_ACTIVE"
    COOLDOWN = "COOLDOWN"

class Signal(Enum):
    LONG = 1
    SHORT = -1
    NONE = 0

@dataclass(frozen=True)
class FeatureSnapshot:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    ema_fast: float
    ema_slow: float
    atr: float
    atr_pct: float
    stoch: float
    adx: float
    regime: str
    slope: float
    setup_active: bool
    confirm_count: int

@dataclass
class TradeContext:
    direction: Signal
    entry_price: float
    size: float
    stop_loss: float
    tp_target: float
    atr_at_entry: float
    entry_time: datetime
    runners_allowed: bool
    state: TradeState = TradeState.FLAT
