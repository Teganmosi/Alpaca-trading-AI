from typing import Optional, Tuple
from core.models import TradeState, FeatureSnapshot, TradeContext, Signal

class TradeStateMachine:
    """
    Owns exactly ONE trade lifecycle.
    Ensures idempotency and direction-safe execution (LONG/SHORT).
    """

    def __init__(self):
        self.context: Optional[TradeContext] = None

    def is_flat(self) -> bool:
        return self.context is None

    def enter(self, context: TradeContext):
        """Idempotency guard: Prevent entering a new trade if one is already open."""
        if self.context is not None:
            raise RuntimeError("FSM Violation: Double entry attempted. Already in a trade.")
        
        context.state = TradeState.ENTERED
        self.context = context

    def update(self, snapshot: FeatureSnapshot) -> Tuple[Optional[float], Optional[str]]:
        """
        Processes the current bar for an open trade.
        Returns: (R-Multiple if exited, ExitTag)
        """
        if self.context is None:
            return None, None

        ctx = self.context
        # Directional multiplier: 1 for Long, -1 for Short
        direction = ctx.direction.value

        # 1. STOP LOSS (Highest Priority)
        # Long: low <= stop
        # Short: high >= stop
        is_stopped = (
            (direction == 1 and snapshot.low <= ctx.stop_loss) or
            (direction == -1 and snapshot.high >= ctx.stop_loss)
        )
        
        if is_stopped:
            # PnL in dollars: direction * (exit - entry) * size
            pnl = direction * (ctx.stop_loss - ctx.entry_price) * ctx.size
            # R-Multiple: pnl / (initial_risk_in_dollars)
            r_multiple = pnl / (ctx.atr_at_entry * ctx.size)
            
            # Tag differentiation
            tag = "SL" if ctx.state == TradeState.ENTERED else "Runner"
            
            self._reset()
            return r_multiple, tag

        # 2. RUNNER ACTIVATION
        if ctx.state == TradeState.ENTERED and ctx.runners_allowed:
            hit_tp = (
                (direction == 1 and snapshot.high >= ctx.tp_target) or
                (direction == -1 and snapshot.low <= ctx.tp_target)
            )
            if hit_tp:
                ctx.state = TradeState.RUNNER_ACTIVE
                # Lock in 2.0R (Final system logic)
                ctx.stop_loss = ctx.entry_price + direction * (ctx.atr_at_entry * 2.0)
                
        # 3. TRAILING STOP (Only in Runner State)
        if ctx.state == TradeState.RUNNER_ACTIVE:
            # high_water is the 'best' price seen so far in the trade direction
            high_water = snapshot.high if direction == 1 else snapshot.low
            
            # Current profit in R
            r_now = direction * (high_water - ctx.entry_price) / ctx.atr_at_entry
            
            # Tighter trail for bigger wins (Day 13 logic)
            offset = 0.75 if r_now > 3.0 else 1.0
            new_stop = high_water - direction * (snapshot.atr * offset)

            # Only move stop in the direction of profit
            if (
                (direction == 1 and new_stop > ctx.stop_loss) or
                (direction == -1 and new_stop < ctx.stop_loss)
            ):
                ctx.stop_loss = new_stop
                
        # 4. TIME EXIT (40 candles as per final Day 13 logic)
        elapsed_candles = (snapshot.timestamp - ctx.entry_time).total_seconds() / 900
        if elapsed_candles >= 40:
            pnl = direction * (snapshot.close - ctx.entry_price) * ctx.size
            r_multiple = pnl / (ctx.atr_at_entry * ctx.size)
            self._reset()
            return r_multiple, "Time"

        return None, None

    def _reset(self):
        self.context = None
