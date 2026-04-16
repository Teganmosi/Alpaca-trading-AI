import sys
import os

sys.path.append(os.path.dirname(__file__) + "/..")
from backtest_engine import BacktestEngine
import json

# Test configurations
strategies = [
    {"name": "Strategy A: 1H/4H", "entry": "1h", "trend": "4h"},
    {"name": "Strategy B: 30m/1H", "entry": "30m", "trend": "1h"},
    {"name": "Strategy C: 15m/1H", "entry": "15m", "trend": "1h"},
]

# Common parameters
common_params = {
    "trend_relax": True,
    "sl_buffer": 0.005,
    "breakeven_after_tp1": True,
}

results = []

for strat in strategies:
    print(f"Running {strat['name']}...")
    engine = BacktestEngine(
        start_date="2024-04-09",
        end_date="2026-04-09",
        initial_equity=10000,
        playbook_params=common_params,
        entry_timeframe=strat["entry"],
        trend_timeframe=strat["trend"],
    )
    res = engine.run_backtest()
    res["strategy"] = strat["name"]
    res["entry_tf"] = strat["entry"]
    res["trend_tf"] = strat["trend"]
    results.append(res)
    print(
        f"Completed {strat['name']}: {res['total_trades']} trades, PF {res['profit_factor']:.2f}"
    )

# Sort by profit factor
results.sort(key=lambda x: x["profit_factor"], reverse=True)

# Print comparison table
print("\n" + "=" * 80)
print("TIMEFRAME COMPARISON RESULTS")
print("=" * 80)
print(
    f"{'Strategy':<20} {'Entry TF':<8} {'Trend TF':<8} {'Trades':<6} {'Win Rate':<8} {'PF':<6} {'Sharpe':<6} {'Max DD':<8} {'Final Eq'}"
)
print("-" * 80)
for r in results:
    print(
        f"{r['strategy']:<20} {r['entry_tf']:<8} {r['trend_tf']:<8} {r['total_trades']:<6} {r['win_rate']:<8.1%} {r['profit_factor']:<6.2f} {r['sharpe']:<6.2f} {r['max_dd']:<8.1%} ${r['final_equity']:.0f}"
    )

print("\nBest Strategy:", results[0]["strategy"])
print(f"Profit Factor: {results[0]['profit_factor']:.2f}")
print(f"Win Rate: {results[0]['win_rate']:.1%}")
print(f"Total Trades: {results[0]['total_trades']}")

# Save results
with open("backtest_results/timeframe_comparison.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
