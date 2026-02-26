from core.models import FeatureSnapshot, Signal

class StrategyEngine:
    """
    Multi-mode strategy engine with trend alignment to prevent whipsaws.
    """
    
    # Thresholds
    ADX_TREND_THRESHOLD = 20
    STOCH_OVERSOLD = 0.30
    STOCH_OVERBOUGHT = 0.70
    SLOPE_WEAK = 0.005
    
    @staticmethod
    def get_signal(snapshot: FeatureSnapshot, previous_snapshot: FeatureSnapshot = None) -> Signal:
        """
        Determines signal with trend alignment to prevent whipsaws.
        
        Key improvements:
        1. Trade WITH the trend (1h trend direction)
        2. Require confirmation (not just one bar)
        """
        
        # Determine allowed direction based on regime
        # Trend_Up -> only LONG
        # Trend_Down -> only SHORT  
        # Expansion -> allow both
        allowed_directions = []
        
        if snapshot.regime in ['Trend_Up', 'Neutral']:
            allowed_directions.append('LONG')
        if snapshot.regime in ['Trend_Down', 'Neutral']:
            allowed_directions.append('SHORT')
        if snapshot.regime == 'Expansion':
            allowed_directions = ['LONG', 'SHORT']
        
        # === MODE 1: TREND FOLLOWING ===
        # LONG only in uptrend/expansion with positive slope
        if 'LONG' in allowed_directions:
            if snapshot.slope > StrategyEngine.SLOPE_WEAK:
                if snapshot.adx > StrategyEngine.ADX_TREND_THRESHOLD and snapshot.stoch < 0.65:
                    # Check confirmation from previous bar if available
                    if previous_snapshot is None or previous_snapshot.stoch < snapshot.stoch:
                        return Signal.LONG
                        
        # SHORT only in downtrend/expansion with negative slope
        if 'SHORT' in allowed_directions:
            if snapshot.slope < -StrategyEngine.SLOPE_WEAK:
                if snapshot.adx > StrategyEngine.ADX_TREND_THRESHOLD and snapshot.stoch > 0.35:
                    # Check confirmation from previous bar if available
                    if previous_snapshot is None or previous_snapshot.stoch > snapshot.stoch:
                        return Signal.SHORT
        
        # === MODE 2: MEAN REVERSION ===
        # Only in weak trends (ADX < 35) and aligned with regime
        if snapshot.adx < 35:
            # Oversold = LONG
            if 'LONG' in allowed_directions:
                if snapshot.stoch < StrategyEngine.STOCH_OVERSOLD:
                    return Signal.LONG
                    
            # Overbought = SHORT
            if 'SHORT' in allowed_directions:
                if snapshot.stoch > StrategyEngine.STOCH_OVERBOUGHT:
                    return Signal.SHORT
        
        # === MODE 3: EMA CROSSOVER ===
        if snapshot.adx > 15 and snapshot.atr_pct > 0.7:
            # Golden cross = LONG
            if 'LONG' in allowed_directions:
                if snapshot.ema_fast > snapshot.ema_slow:
                    return Signal.LONG
                    
            # Death cross = SHORT
            if 'SHORT' in allowed_directions:
                if snapshot.ema_fast < snapshot.ema_slow:
                    return Signal.SHORT
        
        # === MODE 4: EXPANSION MOMENTUM ===
        if snapshot.regime == 'Expansion':
            if snapshot.slope > 0.02 and snapshot.stoch < 0.5 and 'LONG' in allowed_directions:
                return Signal.LONG
            if snapshot.slope < -0.02 and snapshot.stoch > 0.5 and 'SHORT' in allowed_directions:
                return Signal.SHORT
        
        return Signal.NONE
    
    @staticmethod
    def get_signal_verbose(snapshot: FeatureSnapshot) -> tuple:
        """Returns signal with explanation for debugging."""
        
        regimes = {
            'Trend_Up': 'BULL',
            'Trend_Down': 'BEAR', 
            'Expansion': 'VOLATILE',
            'Neutral': 'FLAT'
        }
        
        regime_str = regimes.get(snapshot.regime, 'UNKNOWN')
        
        # Check trend following
        if snapshot.regime in ['Trend_Up', 'Expansion'] and snapshot.slope > 0.005:
            if snapshot.adx > 20 and snapshot.stoch < 0.65:
                return Signal.LONG, f"TREND_LONG: {regime_str}, slope={snapshot.slope:.4f}"
                
        if snapshot.regime in ['Trend_Down', 'Expansion'] and snapshot.slope < -0.005:
            if snapshot.adx > 20 and snapshot.stoch > 0.35:
                return Signal.SHORT, f"TREND_SHORT: {regime_str}, slope={snapshot.slope:.4f}"
        
        # Mean reversion
        if snapshot.stoch < 0.30 and snapshot.adx < 35:
            return Signal.LONG, f"REVERSION: Stoch={snapshot.stoch:.2f}"
            
        if snapshot.stoch > 0.70 and snapshot.adx < 35:
            return Signal.SHORT, f"REVERSION: Stoch={snapshot.stoch:.2f}"
        
        return Signal.NONE, f"NO_SIGNAL: {regime_str} regime"
