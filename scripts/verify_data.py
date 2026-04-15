import pandas as pd
import os

csv_path = "data/btc_history.csv"
if not os.path.exists(csv_path):
    print(f"Error: {csv_path} does not exist. Run scripts/fetch_history.py first.")
    exit(1)

df = pd.read_csv(csv_path, parse_dates=["Datetime"], index_col="Datetime")
df.index = pd.to_datetime(df.index, utc=True)

print(f"Data shape: {df.shape}")
print(f"Total NaN values: {df.isna().sum().sum()}")
print(f"Date range: {df.index.min()} to {df.index.max()}")

expected_days = 365 * 2
actual_days = (df.index.max() - df.index.min()).days
print(f"Expected coverage: ~{expected_days} days, Actual: {actual_days} days")

print("\nFirst 5 rows:")
print(df.head())

print("\nLast 5 rows:")
print(df.tail())

# Check OHLCV columns
required_cols = ["open", "high", "low", "close", "volume"]
missing_cols = [col for col in required_cols if col not in df.columns]
if missing_cols:
    print(f"Missing columns: {missing_cols}")
else:
    print("All required OHLCV columns present.")
