import pandas as pd
import numpy as np
from core.models import FeatureSnapshot

class FeatureEngine:
    @staticmethod
    def calculate_metrics(df: pd.DataFrame) -> pd.DataFrame:
        """Centralized indicator calculations for the Feature Engine."""
        df = df.copy()
        
        # EMA
        df['ema_fast'] = df['close'].ewm(span=15, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # ATR / Volatility
        df['H-L'] = df['high'] - df['low']
        df['H-PC'] = abs(df['high'] - df['close'].shift(1))
        df['L-PC'] = abs(df['low'] - df['close'].shift(1))
        df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
        df['atr'] = df['TR'].rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100
        
        # ADX (Directional Index)
        alpha = 1/14
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
        tr_smooth = df['TR'].ewm(alpha=alpha, adjust=False).mean()
        plus_di = 100 * (df['plus_dm'].ewm(alpha=alpha, adjust=False).mean() / tr_smooth.replace(0, 0.001))
        minus_di = 100 * (df['minus_dm'].ewm(alpha=alpha, adjust=False).mean() / tr_smooth.replace(0, 0.001))
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 0.001)
        df['adx'] = dx.ewm(alpha=alpha, adjust=False).mean()
        
        # Stoch RSI (K)
        delta = df['close'].diff()
        up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
        roll_up, roll_down = up.rolling(14).mean(), down.rolling(14).mean()
        RS = roll_up / roll_down.replace(0, np.nan)
        RSI = 100 - (100 / (1 + RS))
        min_rsi, max_rsi = RSI.rolling(14).min(), RSI.rolling(14).max()
        df['stoch_k'] = (RSI - min_rsi) / (max_rsi - min_rsi)
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()
        
        # Setup & Confirmation logic (Calculated here to maintain stateless StrategyEngine)
        df['setup'] = (df['stoch_k'] < 0.2) & (df['ema_fast'] > df['ema_slow']) & (df['adx'] > 20)
        df['setup_active'] = df['setup'].rolling(6).max() > 0
        # Confirmation logic: Price Zone + Momentum + Volatility Confirmation
        df['cond_zone'] = df['close'] > df['ema_fast']  # Bullish zone
        df['cond_cross'] = (df['stoch_k'] > df['stoch_d']) # Positive momentum
        df['cond_trend'] = df['close'] > df['ema_slow'] # Macro Trend confirmation
        df['confirm_count'] = df[['cond_zone', 'cond_cross', 'cond_trend']].sum(axis=1)
        
        return df

    @staticmethod
    def get_snapshot(df: pd.DataFrame, idx: int, regime: str, slope: float) -> FeatureSnapshot:
        row = df.iloc[idx]
        return FeatureSnapshot(
            timestamp=df.index[idx],
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            ema_fast=row['ema_fast'],
            ema_slow=row['ema_slow'],
            atr=row['atr'],
            atr_pct=row['atr_pct'],
            stoch=row['stoch_k'],
            adx=row['adx'],
            regime=regime,
            slope=slope,
            setup_active=row['setup_active'],
            confirm_count=row['confirm_count']
        )
