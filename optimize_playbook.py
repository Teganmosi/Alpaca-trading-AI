import sys

sys.path.append(".")
from backtest_engine import BacktestEngine
import json
import itertools

# Grid search parameters
trend_relax_options = [False, True]
sl_buffer_options = [0.005, 0.01, 0.015, 0.02]
breakeven_options = [False, True]

combinations = list(
    itertools.product(trend_relax_options, sl_buffer_options, breakeven_options)
)

results = []

for trend_relax, sl_buffer, breakeven in combinations:
    engine = BacktestEngine(
        start_date="2025-01-01",
        end_date="2025-12-31",
        initial_equity=10000,
        playbook_params={
            "trend_relax": trend_relax,
            "sl_buffer": sl_buffer,
            "breakeven_after_tp1": breakeven,
        },
    )
    res = engine.run_backtest()
    results.append((trend_relax, sl_buffer, breakeven, res))

results.sort(key=lambda x: x[3]["profit_factor"], reverse=True)

top3 = results[:3]

with open("backtest_results/playbook_optimized.json", "w") as f:
    json.dump(
        [
            {
                "trend_relax": r[0],
                "sl_buffer": r[1],
                "breakeven_after_tp1": r[2],
                "metrics": r[3],
            }
            for r in top3
        ],
        f,
        indent=2,
        default=str,
    )

best = top3[0]

baseline_engine = BacktestEngine(
    start_date="2025-01-01", end_date="2025-12-31", initial_equity=10000
)
baseline = baseline_engine.run_backtest()

print("Baseline Playbook Metrics:")
print(f"Total Trades: {baseline['total_trades']}")
print(f"Win Rate: {baseline['win_rate']:.2%}")
print(f"Profit Factor: {baseline['profit_factor']:.2f}")
print(f"Max Drawdown: {baseline['max_dd']:.2%}")
print(f"Final Equity: {baseline['final_equity']:.2f}")

print("\nBest Optimized Configuration:")
print(f"Trend Relax: {best[0]}")
print(f"SL Buffer: {best[1]:.1%}")
print(f"Breakeven after TP1: {best[2]}")
print(f"Total Trades: {best[3]['total_trades']}")
print(f"Win Rate: {best[3]['win_rate']:.2%}")
print(f"Profit Factor: {best[3]['profit_factor']:.2f}")
print(f"Max Drawdown: {best[3]['max_dd']:.2%}")
print(f"Final Equity: {best[3]['final_equity']:.2f}")

improvement_pf = (
    (best[3]["profit_factor"] - baseline["profit_factor"])
    / baseline["profit_factor"]
    * 100
    if baseline["profit_factor"] > 0
    else 0
)
print(f"Profit Factor Improvement: {improvement_pf:.1f}%")
