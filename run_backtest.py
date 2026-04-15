from backtest_engine import BacktestEngine
import json
import os
import pandas as pd

os.makedirs("backtest_results", exist_ok=True)

# Run main backtest
engine = BacktestEngine()
results = engine.run_backtest()

# Save results
with open("backtest_results/report.json", "w") as f:
    json.dump({k: v for k, v in results.items() if k != "trades"}, f, indent=2)

# Save trades
trades_df = pd.DataFrame(results["trades"])
trades_df.to_csv("backtest_results/trades.csv", index=False)

# Walk-forward
wf_results = engine.walk_forward_analysis()
with open("backtest_results/walk_forward.json", "w") as f:
    json.dump(wf_results, f, default=str, indent=2)

# Monte Carlo
mc_results = engine.monte_carlo_simulation(10)  # Small number for speed
with open("backtest_results/monte_carlo.json", "w") as f:
    json.dump(mc_results, f, default=str, indent=2)

print(f"Total trades: {results['total_trades']}")
print(f"Sharpe ratio: {results['sharpe']:.2f}")
print(f"Max drawdown: {results['max_dd']:.2%}")
print(f"Win rate: {results['win_rate']:.2%}")
print(f"Profit factor: {results['profit_factor']:.2f}")
print("Results saved to backtest_results/")
