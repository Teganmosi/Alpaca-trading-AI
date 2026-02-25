from core.models import FeatureSnapshot, Signal

class StrategyEngine:
    """
    Multi-mode strategy engine that generates signals across different market conditions.
    Includes: Trend Following, Mean Reversion, and Breakout modes.
    """
    
    # Thresholds (tuned for 15min BTC)
    ADX_TREND_THRESHOLD = 20  # Lowered from 25 for more signals
    STOCH_OVERSOLD = 0.30     # More lenient for oversold
    STOCH_OVERBOUGHT = 0.70   # More lenient for overbought
    SLOPE_WEAK = 0.005        # Very low threshold for slope
    
    @staticmethod
    def get_signal(snapshot: FeatureSnapshot) -> Signal:
        """Determines if a trade setup is valid based on multi-mode analysis."""
        
        # === MODE 1: TREND FOLLOWING ===
        # LONG in uptrend/expansion with positive slope
        if snapshot.regime in ['Trend_Up', 'Expansion'] and snapshot.slope > StrategyEngine.SLOPE_WEAK:
            if snapshot.adx > StrategyEngine.ADX_TREND_THRESHOLD and snapshot.stoch < 0.65:
                return Signal.LONG
                
        # SHORT in downtrend/expansion with negative slope
        if snapshot.regime in ['Trend_Down', 'Expansion'] and snapshot.slope < -StrategyEngine.SLOPE_WEAK:
            if snapshot.adx > StrategyEngine.ADX_TREND_THRESHOLD and snapshot.stoch > 0.35:
                return Signal.SHORT
        
        # === MODE 2: MEAN REVERSION ===
        # Oversold = LONG (expect bounce)
        if snapshot.stoch < StrategyEngine.STOCH_OVERSOLD and snapshot.adx < 35:
            return Signal.LONG
            
        # Overbought = SHORT (expect pullback)
        if snapshot.stoch > StrategyEngine.STOCH_OVERBOUGHT and snapshot.adx < 35:
            return Signal.SHORT
        
        # === MODE 3: EMA CROSSOVER BREAKOUT ===
        # Golden cross (fast above slow) = LONG
        if snapshot.ema_fast > snapshot.ema_slow and snapshot.adx > 15:
            if snapshot.atr_pct > 0.7:  # Some volatility
                return Signal.LONG
                
        # Death cross (fast below slow) = SHORT
        if snapshot.ema_fast < snapshot.ema_slow and snapshot.adx > 15:
            if snapshot.atr_pct > 0.7:
                return Signal.SHORT
        
        # === MODE 4: VOLATILE EXPANSION (Always in Expansion regime) ===
        # In high volatility expansion, look for momentum continuation
        if snapshot.regime == 'Expansion':
            if snapshot.slope > 0.02 and snapshot.stoch < 0.5:
                return Signal.LONG
            if snapshot.slope < -0.02 and snapshot.stoch > 0.5:
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
        
        # Mode 1: Trend Following
        if snapshot.regime in ['Trend_Up', 'Expansion'] and snapshot.slope > 0.005:
            if snapshot.adx > 20 and snapshot.stoch < 0.65:
                return Signal.LONG, f"TREND_LONG: {regime_str} regime, slope={snapshot.slope:.4f}, ADX={snapshot.adx:.1f}, Stoch={snapshot.stoch:.2f}"
                
        if snapshot.regime in ['Trend_Down', 'Expansion'] and snapshot.slope < -0.005:
            if snapshot.adx > 20 and snapshot.stoch > 0.35:
                return Signal.SHORT, f"TREND_SHORT: {regime_str} regime, slope={snapshot.slope:.4f}, ADX={snapshot.adx:.1f}, Stoch={snapshot.stoch:.2f}"
        
        # Mode 2: Mean Reversion
        if snapshot.stoch < 0.30 and snapshot.adx < 35:
            return Signal.LONG, f"REVERSION_LONG: Stoch={snapshot.stoch:.2f} oversold, ADX={snapshot.adx:.1f}"
            
        if snapshot.stoch > 0.70 and snapshot.adx < 35:
            return Signal.SHORT, f"REVERSION_SHORT: Stoch={snapshot.stoch:.2f} overbought, ADX={snapshot.adx:.1f}"
        
        # Mode 3: EMA Breakout
        if snapshot.ema_fast > snapshot.ema_slow and snapshot.adx > 15 and snapshot.atr_pct > 0.7:
            return Signal.LONG, f"BREAKOUT_LONG: EMA cross, ADX={snapshot.adx:.1f}, ATR%={snapshot.atr_pct:.1f}"
            
        if snapshot.ema_fast < snapshot.ema_slow and snapshot.adx > 15 and snapshot.atr_pct > 0.7:
            return Signal.SHORT, f"BREAKOUT_SHORT: EMA cross, ADX={snapshot.adx:.1f}, ATR%={snapshot.atr_pct:.1f}"
        
        # Mode 4: Expansion momentum
        if snapshot.regime == 'Expansion':
            if snapshot.slope > 0.02 and snapshot.stoch < 0.5:
                return Signal.LONG, f"EXPANSION_LONG: slope={snapshot.slope:.4f}, Stoch={snapshot.stoch:.2f}"
            if snapshot.slope < -0.02 and snapshot.stoch > 0.5:
                return Signal.SHORT, f"EXPANSION_SHORT: slope={snapshot.slope:.4f}, Stoch={snapshot.stoch:.2f}"
        
        return Signal.NONE, f"NO_SIGNAL: regime={regime_str}, slope={snapshot.slope:.4f}, stoch={snapshot.stoch:.2f}, adx={snapshot.adx:.1f}, ema_diff={snapshot.ema_fast - snapshot.ema_slow:.2f}"
