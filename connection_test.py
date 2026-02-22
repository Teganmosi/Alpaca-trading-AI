import os
from core.execution_engine import ExecutionEngine
from core.feature_engine import FeatureEngine
from dotenv import load_dotenv
load_dotenv()

from alpaca.data.historical import CryptoHistoricalDataClient
from datetime import datetime, timezone, timedelta
import pandas as pd
from day15_paper_loop import fetch_latest_data, fetch_hourly_data, calculate_latest_regime

# ---------------- CONFIGURATION ----------------
SYMBOL = "BTC/USD"
API_KEY_ID = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

def test_connectivity():
    print("=== ALPACA CONNECTIVITY TEST (SECURE) ===")
    
    if not API_KEY_ID or not SECRET_KEY:
        print("[FAIL] Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in environment variables.")
        return

    try:
        exec_engine = ExecutionEngine(API_KEY_ID, SECRET_KEY, paper=True)
        equity = exec_engine.get_account_equity()
        print(f"1. Account Connection: SUCCESS | Equity: ${equity:.2f}")
        
        has_pos = exec_engine.has_open_position(SYMBOL)
        print(f"2. Broker Truth Check: SUCCESS | Symbol: {SYMBOL} | In Position: {has_pos}")
        
        data_client = CryptoHistoricalDataClient(API_KEY_ID, SECRET_KEY)
        df_15m = fetch_latest_data(data_client, SYMBOL)
        print(f"3. 15m Data Fetch: SUCCESS | Rows: {len(df_15m)}")
        
        regime, slope, atr_pct = calculate_latest_regime(fetch_hourly_data(data_client, SYMBOL))
        print(f"4. Regime Calculation: SUCCESS | Regime: {regime} | Slope: {slope:.4f}")
        
        print("\nALL SYSTEMS OPERATIONAL (HARDENED). Bot is ready for Day 16.")
        
    except Exception as e:
        print(f"\nCONNECTIVITY TEST FAILED: {e}")

if __name__ == "__main__":
    test_connectivity()
