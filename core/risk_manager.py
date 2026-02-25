from datetime import datetime, timedelta
from typing import Optional, Tuple
from core.models import FeatureSnapshot

class RiskManager:
    """
    Gatekeeper only.
    Does NOT own capital. Observes and Gates based on passed-in metrics.
    """

    BASE_RISK_PCT = 0.01  # 1% base (increased from 0.5%)
    DAILY_SL_LIMIT = 3   # Allow up to 3 losses per day (increased from 1)
    DAILY_PNL_LIMIT = -2.0 # Allow up to -2R daily loss before blocking
    VOL_CAP = 1.5         # Increased from 1.2 to allow more volatility
    DD_RISK_MULTIPLIER = 0.5 # Less aggressive: 50% reduction in DD (was 90%)

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

    def check_gates(
        self,
        snapshot: FeatureSnapshot,
        equity: float,
        peak_equity: float,
        signal=None
    ) -> Tuple[bool, float, bool]:
        """
        Returns: (Allowed, RiskPercent, RunnersAllowed)
        """
        self._reset_daily(snapshot.timestamp.date())

        # 1. Global Cooldown (reduced from 24h to 2h)
        if self.cooldown_until and snapshot.timestamp < self.cooldown_until:
            print(f"[RISK] Cooldown active until {self.cooldown_until}")
            return False, 0.0, False

        # 2. Daily Loss Streak Guard
        if self.daily_sl >= self.DAILY_SL_LIMIT:
            print(f"[RISK] Daily SL limit: {self.daily_sl}/{self.DAILY_SL_LIMIT}")
            return False, 0.0, False

        # 3. Daily PnL Circuit Breaker
        if self.daily_pnl_r <= self.DAILY_PNL_LIMIT:
            print(f"[RISK] Daily PnL limit: {self.daily_pnl_r:.2f}R")
            return False, 0.0, False

        # 4. Volatility Shutdown (ATR % Cap)
        if snapshot.atr_pct > self.VOL_CAP:
            print(f"[RISK] Volatility too high: {snapshot.atr_pct:.2f}%")
            return False, 0.0, False

        # Position sizing
        risk_pct = self.BASE_RISK_PCT

        # 5. Equity Curve Guard (less aggressive)
        if equity < peak_equity:
            risk_pct *= self.DD_RISK_MULTIPLIER

        # 6. Volatility-Adjusted Risk Sizing
        if snapshot.atr_pct > 1.2:
            risk_pct *= 0.7

        # 7. Runner Exposure Permission
        runners_allowed = snapshot.atr_pct < 1.5

        print(f"[RISK] Gate PASSED: risk_pct={risk_pct:.4f}")
        return True, risk_pct, runners_allowed

    def record_trade(self, r_multiple: float, tag: str, timestamp: datetime):
        """Standardizes profit/loss tracking in R-multiples."""
        self.daily_pnl_r += r_multiple

        if r_multiple < 0:
            self.daily_sl += 1
            self.consecutive_sl += 1

            # Reduced from 24h to 2h cooldown on consecutive losses
            if self.consecutive_sl >= 2:
                self.cooldown_until = timestamp + timedelta(hours=2)
                print(f"[RISK] Consecutive losses: {self.consecutive_sl}. Cooldown 2h.")
        else:
            if r_multiple > 0:
                self.consecutive_sl = 0
                print(f"[RISK] Win recorded. Consecutive SL reset.")
