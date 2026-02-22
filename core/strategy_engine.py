from core.models import FeatureSnapshot, Signal

class StrategyEngine:
    @staticmethod
    def get_signal(snapshot: FeatureSnapshot) -> Signal:
        """Determines if a trade setup is valid based strictly on features."""
        
        # 1. Base LONG Entry Signal (Day 11+ logic)
        long_qualifies = (
            snapshot.regime == 'Trend_Up' and 
            snapshot.slope > 0.02 and 
            snapshot.setup_active and 
            snapshot.confirm_count >= 2 and 
            snapshot.adx > 25 and
            snapshot.stoch < 0.5
        )
        
        if long_qualifies:
            return Signal.LONG
        
        # Note: Strategy logic for SHORT can be added here once defined.
        # Currently, the system is SHORT-safe but LONG-biased.
        
        return Signal.NONE
