from backtest_engine import BacktestEngine
import json
import itertools

# Define ranges
rsi_periods = [10, 14, 18]
rsi_overboughts = [65, 70, 75]
rsi_oversolds = [25, 30, 35]
atr_multipliers = [1.5, 2.0, 2.5]
lookback_periods = [50, 100, 150]

combinations = list(
    itertools.product(
        rsi_periods, rsi_overboughts, rsi_oversolds, atr_multipliers, lookback_periods
    )
)

results = []

for rp, ro, rs, am, lp in combinations:
    engine = BacktestEngine(
        start_date="2025-01-01",
        end_date="2025-04-15",  # Limited for speed
        rsi_period=rp,
        rsi_overbought=ro,
        rsi_oversold=rs,
        atr_multiplier=am,
        lookback_period=lp,
    )
    res = engine.run_backtest()
    if res["total_trades"] >= 10:  # Lower for test
        results.append((rp, ro, rs, am, lp, res["profit_factor"], res))

results.sort(key=lambda x: x[5], reverse=True)

top5 = results[:5]

with open("backtest_results/optimized_params.json", "w") as f:
    json.dump(
        [
            {
                "rsi_period": r[0],
                "rsi_overbought": r[1],
                "rsi_oversold": r[2],
                "atr_multiplier": r[3],
                "lookback_period": r[4],
                "profit_factor": r[5],
            }
            for r in top5
        ],
        f,
        indent=2,
    )

# Baseline
baseline_engine = BacktestEngine(start_date="2025-01-01", end_date="2025-04-15")
baseline = baseline_engine.run_backtest()

print(f"Baseline Profit Factor: {baseline['profit_factor']}")
if top5:
    print(f"Best Profit Factor: {top5[0][5]}")
    improvement = (
        (top5[0][5] - baseline["profit_factor"]) / abs(baseline["profit_factor"]) * 100
        if baseline["profit_factor"] != 0
        else 0
    )
    print(f"Improvement: {improvement:.2f}%")
    print(
        f"Best performing parameter set: RSI_PERIOD={top5[0][0]}, RSI_OVERBOUGHT={top5[0][1]}, RSI_OVERSOLD={top5[0][2]}, ATR_MULTIPLIER={top5[0][3]}, LOOKBACK_PERIOD={top5[0][4]}"
    )

# Update .env.example
if top5:
    best = top5[0]
    with open(".env.example", "a") as f:
        f.write(
            f"\n# Optimized Parameters\nRSI_PERIOD={best[0]}\nRSI_OVERBOUGHT={best[1]}\nRSI_OVERSOLD={best[2]}\nATR_MULTIPLIER={best[3]}\nLOOKBACK_PERIOD={best[4]}\n"
        )
