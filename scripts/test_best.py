import sys
import os
import logging

logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.dirname(__file__) + "/..")
from backtest_engine import BacktestEngine

engine = BacktestEngine(
    start_date="2024-04-09",
    end_date="2026-04-09",
    initial_equity=10000,
    playbook_params={
        "trend_relax": True,
        "sl_buffer": 0.005,
        "breakeven_after_tp1": True,
    },
)
res = engine.run_backtest()

print("Best Optimized Configuration:")
print(f"Trend Relax: True")
print(f"SL Buffer: 0.005")
print(f"Breakeven after TP1: True")
print(f"Total Trades: {res['total_trades']}")
print(f"Win Rate: {res['win_rate']:.2%}")
print(f"Profit Factor: {res['profit_factor']:.2f}")
print(f"Max Drawdown: {res['max_dd']:.2%}")
print(f"Final Equity: {res['final_equity']:.2f}")
