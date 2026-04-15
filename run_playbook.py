from backtest_engine import BacktestEngine
import json

# Run Playbook Strategy Backtest
engine = BacktestEngine(
    start_date="2025-01-01",
    end_date="2025-12-31",
    initial_equity=10000,
)

result = engine.run_backtest()

with open("backtest_results/playbook_report.json", "w") as f:
    json.dump(result, f, indent=2, default=str)

print("Playbook Backtest Results:")
print(f"Total Trades: {result['total_trades']}")
print(f"Win Rate: {result['win_rate']:.2%}")
print(f"Profit Factor: {result['profit_factor']:.2f}")
print(f"Max Drawdown: {result['max_dd']:.2%}")
print(f"Average R-multiple: {result['average_r_multiple']:.2f}")
print(f"Sharpe Ratio: {result['sharpe']:.2f}")
print(f"Final Equity: {result['final_equity']:.2f}")
