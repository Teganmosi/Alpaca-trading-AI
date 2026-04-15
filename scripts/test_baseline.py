import sys
import os
import logging

logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.dirname(__file__) + "/..")
from backtest_engine import BacktestEngine

baseline_engine = BacktestEngine(
    start_date="2024-04-09",
    end_date="2026-04-09",
    initial_equity=10000,
    playbook_params={"trend_relax": True},
)
baseline = baseline_engine.run_backtest()

print("Baseline Playbook Metrics:")
print(f"Total Trades: {baseline['total_trades']}")
print(f"Win Rate: {baseline['win_rate']:.2%}")
print(f"Profit Factor: {baseline['profit_factor']:.2f}")
print(f"Max Drawdown: {baseline['max_dd']:.2%}")
print(f"Final Equity: {baseline['final_equity']:.2f}")
