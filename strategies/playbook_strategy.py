import pandas as pd
import numpy as np
from core.models import Signal


class PlaybookStrategy:
    def __init__(
        self,
        df_daily,
        df_4h,
        trend_relax=False,
        sl_buffer=0.005,
        breakeven_after_tp1=False,
    ):
        self.df_daily = df_daily
        self.df_4h = df_4h
        self.trend_relax = trend_relax
        self.sl_buffer = sl_buffer
        self.breakeven_after_tp1 = breakeven_after_tp1
        # Calculate pivots on daily
        self.df_daily = self.calculate_pivots(self.df_daily)
        # Add StochRSI to 4h
        self.df_4h = self.add_stoch_rsi(self.df_4h)

    def calculate_pivots(self, df):
        df = df.copy()
        df["P"] = (df["high"] + df["low"] + df["close"]) / 3
        df["R1"] = 2 * df["P"] - df["low"]
        df["R2"] = df["P"] + (df["high"] - df["low"])
        df["S1"] = 2 * df["P"] - df["high"]
        df["S2"] = df["P"] - (df["high"] - df["low"])
        return df

    def add_stoch_rsi(self, df):
        df = df.copy()
        rsi = self.calculate_rsi(df["close"], 14)
        stoch_k = (rsi - rsi.rolling(14).min()) / (
            rsi.rolling(14).max() - rsi.rolling(14).min()
        )
        stoch_k_smooth = stoch_k.rolling(3).mean()
        df["stoch_rsi"] = stoch_k_smooth
        df["stoch_rsi_prev"] = df["stoch_rsi"].shift(1)
        return df

    def calculate_rsi(self, series, period):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def detect_trend(self, current_date):
        # Get last 5 daily candles
        recent = self.df_daily[self.df_daily.index <= current_date].tail(5)
        if len(recent) < 5:
            return "NEUTRAL"
        highs = recent["high"]
        lows = recent["low"]
        higher_highs = highs.iloc[-1] > highs.iloc[-2] > highs.iloc[-3]
        higher_lows = lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3]
        lower_highs = highs.iloc[-1] < highs.iloc[-2] < highs.iloc[-3]
        lower_lows = lows.iloc[-1] < lows.iloc[-2] < lows.iloc[-3]
        if higher_highs and higher_lows:
            return "BULLISH"
        elif lower_highs and lower_lows:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def get_pivot_levels(self, current_date):
        # Get previous daily close
        prev_day = self.df_daily[self.df_daily.index < current_date].tail(1)
        if prev_day.empty:
            return {}
        row = prev_day.iloc[0]
        return {
            "P": row["P"],
            "R1": row["R1"],
            "R2": row["R2"],
            "S1": row["S1"],
            "S2": row["S2"],
        }

    def calculate_confluence(self, idx, direction):
        row = self.df_4h.iloc[idx]
        close = row["close"]
        prev_close = self.df_4h.iloc[idx - 1]["close"] if idx > 0 else close
        stoch_rsi = row["stoch_rsi"]
        stoch_rsi_prev = row["stoch_rsi_prev"]
        current_date = row.name
        pivots = self.get_pivot_levels(current_date)

        if not pivots:
            return 0

        # Determine conditions based on direction
        stoch_condition = (
            (stoch_rsi < 0.2 and stoch_rsi > stoch_rsi_prev)
            if direction == "LONG"
            else (stoch_rsi > 0.8 and stoch_rsi < stoch_rsi_prev)
        )

        pivot_levels = ["S1", "S2", "P"] if direction == "LONG" else ["R1", "R2", "P"]
        pivot_condition = any(
            abs(close - pivots.get(level, close)) / (pivots.get(level, close) or 1)
            <= 0.01
            for level in pivot_levels
        )

        candle_condition = (
            (prev_close < close) if direction == "LONG" else (prev_close > close)
        )

        score = sum([stoch_condition, pivot_condition, candle_condition])
        return score

    def _can_go_long(self, trend, idx):
        return trend == "BULLISH" or (
            trend == "NEUTRAL"
            and self.trend_relax
            and self.calculate_confluence(idx, "LONG") >= 3
        )

    def _can_go_short(self, trend, idx):
        return trend == "BEARISH" or (
            trend == "NEUTRAL"
            and self.trend_relax
            and self.calculate_confluence(idx, "SHORT") >= 3
        )

    def _check_long_conditions(
        self, close, prev_close, stoch_rsi, stoch_rsi_prev, pivots
    ):
        stoch_ok = stoch_rsi < 0.2 and stoch_rsi > stoch_rsi_prev
        pivot_ok = any(
            abs(close - pivots[level]) / (pivots[level] or 1) <= 0.01
            for level in ["S1", "S2", "P"]
        )
        candle_ok = prev_close < close
        return stoch_ok and pivot_ok and candle_ok

    def _check_short_conditions(
        self, close, prev_close, stoch_rsi, stoch_rsi_prev, pivots
    ):
        stoch_ok = stoch_rsi > 0.8 and stoch_rsi < stoch_rsi_prev
        pivot_ok = any(
            abs(close - pivots[level]) / (pivots[level] or 1) <= 0.01
            for level in ["R1", "R2", "P"]
        )
        candle_ok = prev_close > close
        return stoch_ok and pivot_ok and candle_ok

    def get_signal(self, idx):
        row = self.df_4h.iloc[idx]
        current_date = row.name

        trend = self.detect_trend(current_date)
        pivots = self.get_pivot_levels(current_date)

        if not pivots:
            return Signal.NONE

        close = row["close"]
        prev_close = self.df_4h.iloc[idx - 1]["close"] if idx > 0 else close
        stoch_rsi = row["stoch_rsi"]
        stoch_rsi_prev = row["stoch_rsi_prev"]

        if self._can_go_long(trend, idx) and self._check_long_conditions(
            close, prev_close, stoch_rsi, stoch_rsi_prev, pivots
        ):
            return Signal.LONG

        if self._can_go_short(trend, idx) and self._check_short_conditions(
            close, prev_close, stoch_rsi, stoch_rsi_prev, pivots
        ):
            return Signal.SHORT

        return Signal.NONE

    def get_stop_loss(self, direction, idx, entry_price=None):
        # Recent swing low/high
        lookback = 10
        recent = self.df_4h.iloc[max(0, idx - lookback) : idx + 1]
        if direction == "LONG":
            swing_low = recent["low"].min()
            sl = swing_low * (1 - self.sl_buffer)  # minus buffer %
            if self.breakeven_after_tp1 and entry_price:
                sl = max(sl, entry_price)  # breakeven
            return sl
        else:
            swing_high = recent["high"].max()
            sl = swing_high * (1 + self.sl_buffer)
            if self.breakeven_after_tp1 and entry_price:
                sl = min(sl, entry_price)
            return sl

    def get_take_profits(self, direction, pivots):
        if direction == "LONG":
            tp1 = pivots["P"]
            tp2 = pivots["R1"]
        else:
            tp1 = pivots["P"]
            tp2 = pivots["S1"]
        return tp1, tp2

    # For backtest, need to handle partial exits
    # But since backtest_engine needs to be updated, perhaps return more info
    def get_exit_signals(self, position, idx):
        # position: dict with direction, entry_price, etc.
        row = self.df_4h.iloc[idx]
        close = row["close"]
        direction = position["direction"]
        entry_price = position["entry_price"]
        pivots = self.get_pivot_levels(row.name)

        exits = []
        tp1_hit = position.get("tp1_hit", False)
        if direction == "LONG":
            exits = self._get_long_exits(idx, close, entry_price, pivots, tp1_hit)
        else:
            exits = self._get_short_exits(idx, close, entry_price, pivots, tp1_hit)
        return exits

    def _get_long_exits(self, idx, close, entry_price, pivots, tp1_hit):
        exits = []
        tp1, tp2 = self.get_take_profits("LONG", pivots)
        sl = self.get_stop_loss(
            "LONG",
            idx,
            entry_price if tp1_hit and self.breakeven_after_tp1 else None,
        )
        if not tp1_hit and close >= tp1:
            exits.append(("TP1", tp1))
        if close >= tp2:
            exits.append(("TP2", tp2))
        if close <= sl:
            exits.append(("SL", sl))
        return exits

    def _get_short_exits(self, idx, close, entry_price, pivots, tp1_hit):
        exits = []
        tp1, tp2 = self.get_take_profits("SHORT", pivots)
        sl = self.get_stop_loss(
            "SHORT",
            idx,
            entry_price if tp1_hit and self.breakeven_after_tp1 else None,
        )
        if not tp1_hit and close <= tp1:
            exits.append(("TP1", tp1))
        if close <= tp2:
            exits.append(("TP2", tp2))
        if close >= sl:
            exits.append(("SL", sl))
        return exits
