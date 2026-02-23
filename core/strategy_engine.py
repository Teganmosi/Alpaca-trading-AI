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
        
        # 2. Base SHORT Entry Signal (Opposite of LONG)
        short_qualifies = (
            snapshot.regime == 'Trend_Down' and 
            snapshot.slope < -0.02 and 
            snapshot.setup_active and 
            snapshot.confirm_count >= 2 and 
            snapshot.adx > 25 and
            snapshot.stoch > 0.5
        )
        
        if short_qualifies:
            return Signal.SHORT
        
        return Signal.NONE
