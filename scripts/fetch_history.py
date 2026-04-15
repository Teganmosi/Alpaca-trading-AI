import pandas as pd
import os
import yfinance as yf

os.makedirs("data", exist_ok=True)

end_date = pd.Timestamp.now()

start_date = end_date - pd.DateOffset(years=2)

try:
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from config import get_config

    config = get_config()

    client = CryptoHistoricalDataClient(config["API_KEY_ID"], config["SECRET_KEY"])

    request = CryptoBarsRequest(
        symbol_or_symbols=["BTC/USD"],
        timeframe=TimeFrame.Hour,  # Changed to 1h for compatibility
        start=start_date,
        end=end_date,
    )

    bars = client.get_crypto_bars(request).df

    bars = bars.droplevel(0)  # Remove symbol level if present

    bars.index = pd.to_datetime(bars.index, utc=True)

    print(f"Downloaded {len(bars)} hourly bars from Alpaca")

    bars.reset_index().to_csv("data/btc_history.csv", index=False)

except Exception as e:
    print(f"Alpaca failed: {e}. Using yfinance fallback.")

    data = yf.download("BTC-USD", start=start_date, end=end_date, interval="1h")

    bars = data.droplevel(1, axis=1).rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    print(f"Downloaded {len(bars)} hourly bars from yfinance")

    bars.reset_index().to_csv("data/btc_history.csv", index=False)

print(
    f"Saved to data/btc_history.csv, date range: {bars.index.min()} to {bars.index.max()}"
)
