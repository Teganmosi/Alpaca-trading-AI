from typing import Optional, Tuple
from core.models import TradeState, FeatureSnapshot, TradeContext, Signal

class TradeStateMachine:
    """
    Owns exactly ONE trade lifecycle.
    Ensures idempotency and direction-safe execution (LONG/SHORT).
    """

    # Configuration
    MIN_HOLD_CANDLES = 5  # Minimum candles to hold before time exit (5 * 15min = 75 min)
    MAX_HOLD_CANDLES = 20  # Maximum candles before time exit (reduced from 40)

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
        direction = ctx.direction.value
        
        # Calculate elapsed candles since entry
        elapsed_candles = (snapshot.timestamp - ctx.entry_time).total_seconds() / 900

        # 1. STOP LOSS (Highest Priority - always exits regardless of hold time)
        is_stopped = (
            (direction == 1 and snapshot.low <= ctx.stop_loss) or
            (direction == -1 and snapshot.high >= ctx.stop_loss)
        )
        
        if is_stopped:
            pnl = direction * (ctx.stop_loss - ctx.entry_price) * ctx.size
            r_multiple = pnl / (ctx.atr_at_entry * ctx.size)
            
            tag = "SL" if ctx.state == TradeState.ENTERED else "Runner"
            
            self._reset()
            return r_multiple, tag

        # 2. RUNNER ACTIVATION (only after minimum hold time)
        if elapsed_candles >= self.MIN_HOLD_CANDLES:
            if ctx.state == TradeState.ENTERED and ctx.runners_allowed:
                hit_tp = (
                    (direction == 1 and snapshot.high >= ctx.tp_target) or
                    (direction == -1 and snapshot.low <= ctx.tp_target)
                )
                if hit_tp:
                    ctx.state = TradeState.RUNNER_ACTIVE
                    # Lock in 2.0R
                    ctx.stop_loss = ctx.entry_price + direction * (ctx.atr_at_entry * 2.0)
                    
            # 3. TRAILING STOP (Only in Runner State, after min hold)
            if ctx.state == TradeState.RUNNER_ACTIVE:
                high_water = snapshot.high if direction == 1 else snapshot.low
                
                r_now = direction * (high_water - ctx.entry_price) / ctx.atr_at_entry
                
                # Tighter trail for bigger wins
                offset = 0.75 if r_now > 3.0 else 1.0
                new_stop = high_water - direction * (snapshot.atr * offset)

                if (
                    (direction == 1 and new_stop > ctx.stop_loss) or
                    (direction == -1 and new_stop < ctx.stop_loss)
                ):
                    ctx.stop_loss = new_stop

        # 4. TIME EXIT (after min hold, up to max hold)
        if elapsed_candles >= self.MIN_HOLD_CANDLES and elapsed_candles >= self.MAX_HOLD_CANDLES:
            pnl = direction * (snapshot.close - ctx.entry_price) * ctx.size
            r_multiple = pnl / (ctx.atr_at_entry * ctx.size)
            self._reset()
            return r_multiple, "Time"

        return None, None

    def _reset(self):
        self.context = None
