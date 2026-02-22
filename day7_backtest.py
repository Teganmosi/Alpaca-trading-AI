import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# ---------------- CONFIGURATION ----------------
SYMBOL = "BTC/USD"
DAYS_TO_FETCH = 100
# Keys from the notebook
API_KEY_ID = "PKTQNXUGD7WLC57ENS7A4A2HII" 
SECRET_KEY = "FEbe4ogC5NgWEe5PFn8bPPK6aTFw4SS5JJYBeeBGfgcm"

def fetch_data():
    print("Fetching data...")
    client = CryptoHistoricalDataClient(API_KEY_ID, SECRET_KEY)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_TO_FETCH)

    # 1. Fetch Hourly Data for Regime
    req_1h = CryptoBarsRequest(
        symbol_or_symbols=[SYMBOL],
        timeframe=TimeFrame.Hour,
        start=start_date,
        end=end_date
    )
    bars_1h = client.get_crypto_bars(req_1h).df
    bars_1h = bars_1h.droplevel(0)
    bars_1h.index = pd.to_datetime(bars_1h.index, utc=True).round('h') # 'h' for hour, updated from deprecated 'H'

    # 2. Fetch 15-min Data for Strategy
    req_15m = CryptoBarsRequest(
        symbol_or_symbols=[SYMBOL],
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        start=start_date,
        end=end_date
    )
    bars_15m = client.get_crypto_bars(req_15m).df
    bars_15m = bars_15m.droplevel(0)
    bars_15m.index = pd.to_datetime(bars_15m.index, utc=True).floor('15min') # 'min' updated from deprecated 'T'
    
    return bars_1h, bars_15m

def calculate_regime(df_1h):
    print("Calculating Regime...")
    df = df_1h.copy()
    
    EMA_FAST = 50
    EMA_SLOW = 200
    ATR_PERIOD = 14
    
    df['EMA50'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    # True Range
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    
    # ATR & ATR%
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean()
    df['ATR_pct'] = df['ATR'] / df['close'] * 100
    
    # EMA Slope
    df['EMA50_slope'] = df['EMA50'].pct_change() * 100
    
    def get_regime(row):
        if abs(row['EMA50_slope']) > 0.05:
            return 'Trend_Up' if row['EMA50_slope'] > 0 else 'Trend_Down'
        elif row['ATR_pct'] > 1.5:
            return 'Expansion'
        elif row['ATR_pct'] < 0.5:
            return 'Chaos' # or 'Range/LowVol'
        else:
            return 'Neutral'
            
    df['Regime'] = df.apply(get_regime, axis=1)
    return df[['Regime', 'ATR_pct']]

def prepare_strategy_data(df_15m, df_1h_regime):
    print("Preparing Strategy Data...")
    df = df_15m.copy()
    
    # Map Regime from 1H to 15m
    # We use floor('h') to align 15m candles to their parent hour
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime'])
    df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    
    # Indicators
    EMA_FAST = 15
    EMA_SLOW = 50
    ATR_PERIOD = 14
    STOCH_PERIOD = 14
    
    df['EMA15'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    # ATR
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean()
    
    # Stoch RSI
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    roll_up = up.rolling(STOCH_PERIOD).mean()
    roll_down = down.rolling(STOCH_PERIOD).mean()
    RS = roll_up / roll_down.replace(0, np.nan)
    RSI = 100 - (100 / (1 + RS))
    
    min_rsi = RSI.rolling(STOCH_PERIOD).min()
    max_rsi = RSI.rolling(STOCH_PERIOD).max()
    df['Stoch_RSI'] = (RSI - min_rsi) / (max_rsi - min_rsi)
    
    # Signals
    def get_signal(row):
         # Only trade in allowed regimes (Refining this later in filtering, but keeping base logic)
        if row['1H_Regime'] not in ['Trend_Up','Trend_Down','Expansion']:
             pass # We want to LOG all potential trades first, then filter. 
                  # But the prompt says "Modify backtest to label each trade".
                  # If we don't generate the signal, we can't label it.
                  # So let's relax the signal generation to allow ALL valid technical signals, 
                  # and then we will filter them out in the analysis phase.
        
        # Long
        if row['Stoch_RSI'] < 0.2 and row['EMA15'] > row['EMA50']:
            return 1
        # Short
        elif row['Stoch_RSI'] > 0.8 and row['EMA15'] < row['EMA50']:
            return -1
        return 0

    df['Signal'] = df.apply(get_signal, axis=1)
    return df

def get_session(dt):
    # Approximate sessions in UTC
    # Asia: 00-08, London: 08-16, NY: 13-21 (overlap)
    # Simplified non-overlapping for classification:
    # Asia: 22-07 UTC
    # London: 08-13 UTC
    # NY: 13-21 UTC
    # Mixing: 21-22 (Quiet)
    
    h = dt.hour
    if 0 <= h < 8: return 'Asia'
    elif 8 <= h < 13: return 'London'
    elif 13 <= h < 21: return 'NY'
    else: return 'Asia' # Late NY/Asian open

def get_entry_type(row, prev_rows=5):
    # Simple heuristic
    # Breakout: Close > recent high
    # Pullback: Close < EMA but Trend UP (Long)
    # Mean Reversion: Price far from EMA
    
    # For this exercise, we'll label based on signal context
    # Since our strategy is "Pullback" (StochRSI oversold in uptrend), 
    # most should be Pullback. 
    # But let's verify.
    
    # If High Volatility (Expansion) -> potentially Breakout-like behavior if momentum is strong
    
    if row['1H_Regime'] == 'Expansion':
        return 'Breakout'
    elif row['1H_Regime'] in ['Trend_Up', 'Trend_Down']:
        return 'Pullback'
    else:
        return 'Mean Reversion' # Trading in range/chaos

def run_backtest(df):
    print("Running Backtest...")
    trades = []
    
    INITIAL_EQUITY = 10000
    equity = INITIAL_EQUITY
    open_trade = None
    
    RISK_PER_TRADE = 0.005
    R_MULTIPLE = 2
    
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = df.index[i]
        
        if open_trade is None:
            if row['Signal'] != 0:
                # Open Trade
                position = row['Signal']
                atr = row['ATR']
                close = row['close']
                
                if np.isnan(atr) or atr == 0: continue
                
                stop_loss = close - position * atr * 1.0 # 1 ATR Stop
                take_profit = close + position * atr * R_MULTIPLE
                risk_amt = equity * RISK_PER_TRADE
                size = risk_amt / atr # simplified size calc
                
                open_trade = {
                    'entry_time': timestamp,
                    'entry_price': close,
                    'position': position,
                    'size': size,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'market_regime': row['1H_Regime'],
                    'volatility_pct': row['1H_ATR_pct'],
                    'session': get_session(timestamp),
                    'entry_type': get_entry_type(row)
                }
        else:
            # Manage Open Trade
            high = row['high']
            low = row['low']
            
            hit_tp = False
            hit_sl = False
            
            if open_trade['position'] == 1:
                if high >= open_trade['take_profit']: hit_tp = True
                elif low <= open_trade['stop_loss']: hit_sl = True
            else:
                if low <= open_trade['take_profit']: hit_tp = True
                elif high >= open_trade['stop_loss']: hit_sl = True
                
            if hit_tp or hit_sl:
                exit_price = open_trade['take_profit'] if hit_tp else open_trade['stop_loss']
                pnl = (exit_price - open_trade['entry_price']) * open_trade['size'] * open_trade['position']
                
                open_trade['exit_time'] = timestamp
                open_trade['exit_price'] = exit_price
                open_trade['pnl'] = pnl
                open_trade['return_pct'] = (pnl / (open_trade['entry_price'] * open_trade['size'])) * 100
                open_trade['direction'] = 'Long' if open_trade['position'] == 1 else 'Short'
                
                # Volatility State Classification
                vol_state = 'High' if open_trade['volatility_pct'] > 1.5 else ('Low' if open_trade['volatility_pct'] < 0.8 else 'Normal')
                open_trade['volatility_state'] = vol_state
                
                trades.append(open_trade)
                equity += pnl
                open_trade = None
                
    return pd.DataFrame(trades)

def analyze_and_filter(trades_df):
    if trades_df.empty:
        print("No trades generated.")
        return

    print("\n" + "="*40)
    print("📊 INITIAL SANS-FILTERING RESULTS")
    print("="*40)
    
    # METRICS FUNCTION
    def get_metrics(df, name="Dataset"):
        total = len(df)
        if total == 0: return
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]
        win_rate = len(wins) / total
        pf = wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) > 0 else 0
        avg_win = wins['pnl'].mean() if not wins.empty else 0
        avg_loss = abs(losses['pnl'].mean()) if not losses.empty else 0
        expectancy = df['pnl'].mean()
        
        # Max Drawdown (approximate on PnL series)
        cum_pnl = df['pnl'].cumsum()
        running_max = cum_pnl.cummax()
        dd = (cum_pnl - running_max).min()
        
        print(f"\n[{name}]")
        print(f"Total Trades: {total}")
        print(f"Win Rate: {win_rate:.2%}")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Expectancy: ${expectancy:.2f}")
        print(f"Avg Win/Loss Ratio: {avg_win/avg_loss:.2f}" if avg_loss > 0 else "Avg Win/Loss: N/A")
        print(f"Max Drawdown (approx): ${dd:.2f}")
        return total, win_rate, pf

    get_metrics(trades_df, "ALL TRADES")

    # A. REGIME ANALYSIS
    print("\n--- PnL by Regime ---")
    print(trades_df.groupby('market_regime')['pnl'].sum().sort_values())
    
    # B. SESSION ANALYSIS
    print("\n--- PnL by Session ---")
    print(trades_df.groupby('session')['pnl'].sum().sort_values())
    
    # C. VOLATILITY ANALYSIS
    print("\n--- PnL by Volatility State ---")
    print(trades_df.groupby('volatility_state')['pnl'].sum().sort_values())

    # 4. THE HARD CUT
    # "Disable trades that meet any ONE of these: Low volatility, Ranging market, Asia session"
    # Ranging/Chaos in our regime definition handles 'Neutral' and 'Chaos'
    
    print("\n" + "="*40)
    print("🚨 APPLYING THE HARD CUTS")
    print("="*40)
    
    # Condition: 
    # Keep if:
    # NOT (Chaos OR Neutral)  <- Ranging
    # AND NOT (Low Volatility)
    # AND NOT (Asia)
    
    # Let's see what we define as 'Ranging'. In our regime: 'Neutral' and 'Chaos' are non-trending.
    
    mask_ranging = trades_df['market_regime'].isin(['Neutral', 'Chaos'])
    mask_low_vol = trades_df['volatility_state'] == 'Low'
    mask_asia = trades_df['session'] == 'Asia'
    
    # Identifying removed trades
    removed_trades = trades_df[mask_ranging | mask_low_vol | mask_asia]
    
    # Filtered DF
    clean_df = trades_df[~(mask_ranging | mask_low_vol | mask_asia)]
    
    print(f"\nREMOVED {len(removed_trades)} trades based on filters.")
    
    print("\n--- Why they were removed (Overlap possible) ---")
    print(f"Ranging (Neutral/Chaos): {mask_ranging.sum()}")
    print(f"Low Volatility: {mask_low_vol.sum()}")
    print(f"Asia Session: {mask_asia.sum()}")
    
    # 5. SANITY CHECK
    get_metrics(clean_df, "AFTER FILTERING")
    
    print("\n✅ PLAIN ENGLISH SUMMARY")
    print("Which trades did I remove?")
    print("- Trades taken during the Asia session (often low volume/choppy for crypto/FX).")
    print("- Trades taken when the 1H market structure was undefined (Neutral) or Chaotic.")
    print("- Trades taken when relative volatility (ATR%) was very low.")

def main():
    try:
        # Load or Fetch
        if os.path.exists("btc_usd_hourly.csv") and os.path.exists("btc_usd_15min.csv"):
            print("Loading cached CSV data...")
            bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
            bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
        else:
            bars_1h, bars_15m = fetch_data()
            bars_1h.to_csv("btc_usd_hourly.csv")
            bars_15m.to_csv("btc_usd_15min.csv")

        # Step 1: Regime
        regime_df = calculate_regime(bars_1h)
        
        # Step 2: Strategy Prep
        strat_df = prepare_strategy_data(bars_15m, regime_df)
        
        # Step 3: Run Backtest
        trades_df = run_backtest(strat_df)
        
        # Step 4: Analysis
        trades_df.to_csv("trade_log_detailed.csv")
        analyze_and_filter(trades_df)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
