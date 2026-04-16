import pandas as pd
from datetime import datetime
import numpy as np
import os
from core.strategy_engine import StrategyEngine
from core.feature_engine import FeatureEngine
from core.models import Signal
from strategies.playbook_strategy import PlaybookStrategy
import logging


class BacktestEngine:
    def __init__(
        self,
        symbol="BTC-USD",
        start_date="2025-01-01",
        end_date="2025-12-31",
        initial_equity=10000,
        slippage=0.001,
        fee=0.001,
        rsi_period=14,
        rsi_overbought=60,
        rsi_oversold=40,
        atr_multiplier=2.2,
        lookback_period=50,
        playbook_params=None,
        entry_timeframe="1h",
        trend_timeframe="4h",
    ):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.initial_equity = initial_equity
        self.slippage = slippage
        self.fee = fee
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.atr_multiplier = atr_multiplier
        self.lookback_period = lookback_period
        self.playbook_params = playbook_params or {}
        self.entry_timeframe = entry_timeframe
        self.trend_timeframe = trend_timeframe

    def load_data(self):
        data_path = os.path.join(os.path.dirname(__file__), "data", "btc_history.csv")
        df_15m = pd.read_csv(data_path, parse_dates=["Datetime"], index_col="Datetime")
        # Filter to date range
        start = pd.to_datetime(self.start_date).tz_localize("UTC")
        end = pd.to_datetime(self.end_date).tz_localize("UTC")
        df_15m = df_15m[(df_15m.index >= start) & (df_15m.index <= end)]
        return df_15m

    def resample_to_4h(self, df_15m):
        df_4h = (
            df_15m.resample("4h")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        return df_4h

    def resample_to_1h(self, df_15m):
        df_1h = (
            df_15m.resample("1h")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        return df_1h

    def resample_to_30m(self, df_15m):
        df_30m = (
            df_15m.resample("30min")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        return df_30m

    def resample_to_15m(self, df_15m):
        # Already 15m, but ensure consistent
        return df_15m

    def resample_to_daily(self, df_15m):
        df_daily = (
            df_15m.resample("D")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        return df_daily

    def calculate_regime(self, df):
        if len(df) < self.lookback_period:
            return "Neutral", 0, 0
        ema = df["close"].ewm(span=self.lookback_period, adjust=False).mean()
        slope = (
            (ema.iloc[-1] - ema.iloc[-2]) / ema.iloc[-2] * 100 if len(ema) > 1 else 0
        )
        atr_pct = (
            df["atr"].iloc[-1] / df["close"].iloc[-1] * 100
            if "atr" in df.columns
            else 0
        )
        rsi = df["rsi"].iloc[-1] if "rsi" in df.columns else 50
        stoch_k = df["stoch_k"].iloc[-1] if "stoch_k" in df.columns else 0.5
        adx = df["adx"].iloc[-1] if "adx" in df.columns else 20
        if rsi > self.rsi_overbought:
            regime = "Overbought"
        elif rsi < self.rsi_oversold:
            regime = "Oversold"
        elif slope > 0.02 and adx > 15:
            regime = "Trend_Up"
        elif slope < -0.02 and adx > 15:
            regime = "Trend_Down"
        elif atr_pct > 1.3:
            regime = "Expansion"
        elif stoch_k > 0.8 or stoch_k < 0.2:
            regime = "Momentum"
        else:
            regime = "Neutral"
        return regime, slope, atr_pct

    def run_backtest(self):
        df_15m = self.load_data()
        df_daily = self.resample_to_daily(df_15m)

        # Resample trend and entry dataframes
        if self.trend_timeframe == "4h":
            df_trend = self.resample_to_4h(df_15m)
        elif self.trend_timeframe == "1h":
            df_trend = self.resample_to_1h(df_15m)
        else:
            raise ValueError(f"Unsupported trend_timeframe: {self.trend_timeframe}")

        if self.entry_timeframe == "1h":
            df_entry = self.resample_to_1h(df_15m)
        elif self.entry_timeframe == "30m":
            df_entry = self.resample_to_30m(df_15m)
        elif self.entry_timeframe == "15m":
            df_entry = self.resample_to_15m(df_15m)
        else:
            raise ValueError(f"Unsupported entry_timeframe: {self.entry_timeframe}")

        strategy = PlaybookStrategy(
            df_daily, df_trend, df_entry, **self.playbook_params
        )
        equity = self.initial_equity
        peak_equity = equity
        trades = []
        position = None
        for i in range(len(df_entry)):
            row = df_entry.iloc[i]
            signal = strategy.get_signal(i)
            if position:
                exits = strategy.get_exit_signals(position, i)
                for exit_type, exit_price in exits:
                    if exit_type == "TP1" and not position.get("tp1_hit", False):
                        close_size = position["size"] * 0.5
                        position["tp1_hit"] = True
                        position["size"] -= close_size
                    elif exit_type == "TP2":
                        close_size = position["size"]
                        position["size"] = 0
                    elif exit_type == "SL":
                        close_size = position["size"]
                        position["size"] = 0
                    else:
                        continue
                    exit_price_adj = exit_price * (
                        1 + self.slippage
                        if position["direction"] == "SHORT"
                        else 1 - self.slippage
                    )
                    pnl = (
                        (exit_price_adj - position["entry_price"])
                        * close_size
                        * (1 if position["direction"] == "LONG" else -1)
                    )
                    pnl -= self.fee * abs(exit_price_adj * close_size)
                    equity += pnl
                    peak_equity = max(peak_equity, equity)
                    trades.append(
                        {
                            "entry_time": position["entry_time"],
                            "exit_time": row.name,
                            "direction": position["direction"],
                            "entry_price": position["entry_price"],
                            "exit_price": exit_price_adj,
                            "pnl": pnl,
                            "size": close_size,
                            "exit_type": exit_type,
                        }
                    )
                    if position["size"] == 0:
                        position = None
                        break
            else:
                if signal != Signal.NONE:
                    entry_price = row["close"] * (
                        1 + self.slippage
                        if signal == Signal.LONG
                        else 1 - self.slippage
                    )
                    size = (equity * 0.05) / entry_price
                    position = {
                        "direction": signal.name,
                        "entry_price": entry_price,
                        "size": size,
                        "entry_time": row.name,
                        "tp1_hit": False,
                    }
                    equity -= self.fee * (entry_price * size)
        # Close any remaining position at end
        if position:
            exit_price = df_entry.iloc[-1]["close"] * (
                1 + self.slippage
                if position["direction"] == "SHORT"
                else 1 - self.slippage
            )
            pnl = (
                (exit_price - position["entry_price"])
                * position["size"]
                * (1 if position["direction"] == "LONG" else -1)
            )
            pnl -= self.fee * abs(exit_price * position["size"])
            equity += pnl
            peak_equity = max(peak_equity, equity)
            trades.append(
                {
                    "entry_time": position["entry_time"],
                    "exit_time": df_entry.index[-1],
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "size": position["size"],
                    "exit_type": "END",
                }
            )
        if not trades:
            return {
                "total_trades": 0,
                "sharpe": 0,
                "max_dd": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "average_r_multiple": 0,
            }
        returns = [t["pnl"] for t in trades]
        cumulative = np.cumsum([0] + returns)
        max_dd = (
            (max(cumulative) - min(cumulative)) / self.initial_equity
            if len(cumulative) > 1
            else 0
        )
        wins = [r for r in returns if r > 0]
        win_rate = len(wins) / len(returns) if returns else 0
        gross_profit = sum(wins)
        gross_loss = abs(sum(r for r in returns if r < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        average_r_multiple = (
            np.mean([t["pnl"] / (self.initial_equity * 0.05) for t in trades])
            if trades
            else 0
        )  # assuming risk 5%
        if len(returns) > 1:
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            # Calculate trades per day based on timeframe
            if self.entry_timeframe == "1h":
                trades_per_day = 24
            elif self.entry_timeframe == "30m":
                trades_per_day = 48
            elif self.entry_timeframe == "15m":
                trades_per_day = 96
            else:
                trades_per_day = 24  # default
            sharpe = (
                mean_return / std_return * np.sqrt(252 * trades_per_day)
                if std_return > 0
                else 0
            )
        else:
            sharpe = 0
        return {
            "total_trades": len(trades),
            "sharpe": sharpe,
            "max_dd": max_dd,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "average_r_multiple": average_r_multiple,
            "trades": trades,
            "final_equity": equity,
        }

    def check_exit(self, snapshot, position):
        elapsed = (snapshot.timestamp - position["entry_time"]).total_seconds() / 3600
        if elapsed >= 20:
            return True
        sl_pct = 0.01  # 1%
        tp_pct = 0.02  # 2%
        if position["direction"] == "LONG":
            if snapshot.close >= position["entry_price"] * (
                1 + tp_pct
            ) or snapshot.close <= position["entry_price"] * (1 - sl_pct):
                return True
        else:
            if snapshot.close <= position["entry_price"] * (
                1 - tp_pct
            ) or snapshot.close >= position["entry_price"] * (1 + sl_pct):
                return True
        return False

    def walk_forward_analysis(self, window_years=1):
        # Simple walk-forward
        results = []
        start = pd.to_datetime(self.start_date)
        end = pd.to_datetime(self.end_date)
        while start < end:
            test_end = min(start + pd.DateOffset(years=window_years), end)
            engine = BacktestEngine(
                self.symbol,
                start.strftime("%Y-%m-%d"),
                test_end.strftime("%Y-%m-%d"),
                self.initial_equity,
            )
            result = engine.run_backtest()
            results.append(result)
            start = test_end
        return results

    def monte_carlo_simulation(self, num_simulations=100):
        results = []
        for _ in range(num_simulations):
            # Add noise to signals or prices
            engine = BacktestEngine(
                self.symbol, self.start_date, self.end_date, self.initial_equity
            )
            # For simplicity, just run multiple times, but since deterministic, same
            # To simulate, perhaps randomize slippage slightly
            engine.slippage = self.slippage * (0.9 + 0.2 * np.random.random())
            result = engine.run_backtest()
            results.append(result)
        return results
