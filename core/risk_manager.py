from datetime import datetime, timedelta
from typing import Optional, Tuple
from core.models import FeatureSnapshot

class RiskManager:
    """
    Gatekeeper only.
    Does NOT own capital. Observes and Gates based on passed-in metrics.
    """

    BASE_RISK_PCT = 0.005 # 0.5% base
    DAILY_SL_LIMIT = 1
    DAILY_PNL_LIMIT = -1.0 # in R (not equity dollars)
    VOL_CAP = 1.2
    DD_RISK_MULTIPLIER = 0.1 # Aggressive 90% reduction in DD

    def __init__(self):
        self.current_date = None
        self.daily_pnl_r = 0.0
        self.daily_sl = 0
        self.consecutive_sl = 0
        self.cooldown_until: Optional[datetime] = None

    def _reset_daily(self, date):
        if self.current_date != date:
            self.current_date = date
            self.daily_pnl_r = 0.0
            self.daily_sl = 0
            # Note: consecutive_sl and cooldown_until persist across days

    def check_gates(
        self,
        snapshot: FeatureSnapshot,
        equity: float,
        peak_equity: float,
        signal=None  # Optional: for future signal-specific logic
    ) -> Tuple[bool, float, bool]:
        """
        Returns: (Allowed, RiskPercent, RunnersAllowed)
        Evaluates all core protection layers from Day 13.
        """
        self._reset_daily(snapshot.timestamp.date())

        # 1. Global Cooldown (Streak Guard)
        if self.cooldown_until and snapshot.timestamp < self.cooldown_until:
            return False, 0.0, False

        # 2. Daily Loss Streak Guard
        if self.daily_sl >= self.DAILY_SL_LIMIT:
            return False, 0.0, False

        # 3. Daily PnL Circuit Breaker
        if self.daily_pnl_r <= self.DAILY_PNL_LIMIT:
            return False, 0.0, False

        # 4. Volatility Shutdown (ATR % Cap)
        if snapshot.atr_pct > self.VOL_CAP:
            return False, 0.0, False

        # --- POSITION SIZING LOGIC ---
        risk_pct = self.BASE_RISK_PCT

        # 5. Equity Curve Guard (Observer model)
        if equity < peak_equity:
            risk_pct *= self.DD_RISK_MULTIPLIER

        # 6. Volatility-Adjusted Risk Sizing
        if snapshot.atr_pct > 1.0:
            risk_pct *= 0.5 # Vol stability mode

        # 7. Runner Exposure Permission
        runners_allowed = snapshot.atr_pct < 1.3

        return True, risk_pct, runners_allowed

    def record_trade(self, r_multiple: float, tag: str, timestamp: datetime):
        """Standardizes profit/loss tracking in R-multiples."""
        self.daily_pnl_r += r_multiple

        if r_multiple < 0:
            self.daily_sl += 1
            self.consecutive_sl += 1

            if self.consecutive_sl >= 1:
                # Surgical 24h Shutdown on SL hunt
                self.cooldown_until = timestamp + timedelta(hours=24)
        else:
            # Full reset on any win or breakeven/time/runner exit that results in profit
            if r_multiple > 0:
                self.consecutive_sl = 0
