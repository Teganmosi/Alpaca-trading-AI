import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# ---------------- CONFIGURATION ----------------
SYMBOL = "BTC/USD"
DAYS_TO_FETCH = 300
API_KEY_ID = "PKTQNXUGD7WLC57ENS7A4A2HII" 
SECRET_KEY = "FEbe4ogC5NgWEe5PFn8bPPK6aTFw4SS5JJYBeeBGfgcm"

def fetch_data():
    print("Fetching data...")
    client = CryptoHistoricalDataClient(API_KEY_ID, SECRET_KEY)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_TO_FETCH)

    req_1h = CryptoBarsRequest(symbol_or_symbols=[SYMBOL], timeframe=TimeFrame.Hour, start=start_date, end=end_date)
    bars_1h = client.get_crypto_bars(req_1h).df.droplevel(0)
    bars_1h.index = pd.to_datetime(bars_1h.index, utc=True).round('h')

    req_15m = CryptoBarsRequest(symbol_or_symbols=[SYMBOL], timeframe=TimeFrame(15, TimeFrameUnit.Minute), start=start_date, end=end_date)
    bars_15m = client.get_crypto_bars(req_15m).df.droplevel(0)
    bars_15m.index = pd.to_datetime(bars_15m.index, utc=True).floor('15min')
    
    return bars_1h, bars_15m

def calculate_regime(df_1h):
    df = df_1h.copy()
    EMA_FAST, EMA_SLOW, ATR_PERIOD = 50, 200, 14
    
    df['EMA50'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean()
    df['ATR_pct'] = df['ATR'] / df['close'] * 100
    df['EMA50_slope'] = df['EMA50'].pct_change() * 100
    
    def get_regime(row):
        if abs(row['EMA50_slope']) > 0.05: return 'Trend_Up' if row['EMA50_slope'] > 0 else 'Trend_Down'
        elif row['ATR_pct'] > 1.5: return 'Expansion'
        elif row['ATR_pct'] < 0.5: return 'Chaos'
        else: return 'Neutral'
            
    df['Regime'] = df.apply(get_regime, axis=1)
    return df[['Regime', 'ATR_pct']]

def calculate_adx(df, period=14):
    df = df.copy()
    alpha = 1/period
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['up_move'] = df['high'] - df['high'].shift(1)
    df['down_move'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
    df['TR_smooth'] = df['TR'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_dm_smooth'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['minus_dm_smooth'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_di'] = 100 * (df['plus_dm_smooth'] / df['TR_smooth'])
    df['minus_di'] = 100 * (df['minus_dm_smooth'] / df['TR_smooth'])
    df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
    df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()
    return df['adx']

def get_session(dt):
    h = dt.hour
    if 0 <= h < 8: return 'Asia'
    elif 8 <= h < 13: return 'London'
    elif 13 <= h < 21: return 'NY'
    else: return 'Asia'

def prepare_strategy_data(df_15m, df_1h_regime):
    print("Preparing Strategy Data...")
    df = df_15m.copy()
    
    # Context
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime'])
    df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    df['session'] = df.index.map(get_session)
    
    # Indicators
    EMA_FAST, EMA_SLOW, ATR_PERIOD, STOCH_PERIOD = 15, 50, 14, 14
    
    df['EMA15'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean()
    df['ADX'] = calculate_adx(df)
    
    # Stoch RSI (K and D)
    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    roll_up, roll_down = up.rolling(STOCH_PERIOD).mean(), down.rolling(STOCH_PERIOD).mean()
    RS = roll_up / roll_down.replace(0, np.nan)
    RSI = 100 - (100 / (1 + RS))
    min_rsi, max_rsi = RSI.rolling(STOCH_PERIOD).min(), RSI.rolling(STOCH_PERIOD).max()
    df['Stoch_K'] = (RSI - min_rsi) / (max_rsi - min_rsi)
    df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()
    
    # 1. Base Setup: Strict Pullback in Trend (Day 9 core)
    df['Setup'] = (df['Stoch_K'] < 0.2) & (df['EMA15'] > df['EMA50']) & (df['ADX'] > 20)
    # Window of 6 gives enough time for a complex bottoming pattern to confirm
    df['Setup_Active'] = df['Setup'].rolling(6).max() > 0
    
    # 2. Day 11 Confirmations (2 of 3)
    # A. Candle close beyond EMA zone
    df['Cond_Zone'] = df['close'] > df['EMA15']
    # B. Stoch RSI crossing after candle close (Event)
    df['Cond_Cross'] = (df['Stoch_K'] > df['Stoch_D']) & (df['Stoch_K'].shift(1) < df['Stoch_D'].shift(1))
    # C. Range expansion (ATR rising)
    df['Cond_ATR_Up'] = df['ATR'] > df['ATR'].shift(1)
    
    # 3. Decision: Setup + 2 of 3 Confirmations
    df['Confirm_Count'] = df[['Cond_Zone', 'Cond_Cross', 'Cond_ATR_Up']].sum(axis=1)
    # Ensure we don't buy "too late" (K < 0.6)
    df['Entry_Candidate'] = df['Setup_Active'] & (df['Confirm_Count'] >= 2) & (df['Stoch_K'] < 0.6)
    
    return df

def run_backtest(df, stress_test_mode=False, entry_offset=0):
    trades = []
    equity = 10000
    risk_pct = 0.01 
    open_trade = None
    R_MULTIPLE = 2
    
    # State Trackers
    last_regime = None
    regime_buffer = 0 
    last_exit_idx = -999 
    
    current_date = None
    daily_losses = 0
    daily_pnl = 0

    for i in range(len(df)):
        if i < 4: continue
        
        row = df.iloc[i]
        timestamp = df.index[i]
        
        # --- 1. STATE MANAGEMENT ---
        if timestamp.date() != current_date:
            current_date = timestamp.date()
            daily_losses = 0
            daily_pnl = 0
            
        curr_regime = row['1H_Regime']
        if last_regime is not None and curr_regime != last_regime:
            regime_buffer = 1 
        
        last_regime = curr_regime
        is_buffered = False
        if regime_buffer > 0:
            is_buffered = True
            regime_buffer -= 1
            
        on_cooldown = False
        if (i - last_exit_idx) < 4:
            on_cooldown = True
            
        # --- 2. CIRCUIT BREAKER ---
        day_stopped = False
        if daily_losses >= 2 or daily_pnl <= -1 * (equity * risk_pct):
            day_stopped = True
            
        # --- 3. SIGNAL GENERATION ---
        # Base Filters
        is_london = row['session'] == 'London'
        valid_regime = row['1H_Regime'] in ['Trend_Up', 'Expansion'] and row['1H_ATR_pct'] >= 0.8
        valid_adx = row['ADX'] > 20
        
        entry_signal = False
        if is_london and valid_regime and valid_adx and not is_buffered and not on_cooldown and not day_stopped:
            if row['Entry_Candidate']:
                entry_signal = True
                
        # --- 4. EXECUTION (With Offset Logic) ---
        entry_idx = i + entry_offset
        if entry_idx >= len(df): continue
        entry_row = df.iloc[entry_idx]
        
        if open_trade is None:
            if entry_signal:
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                
                # Exec Price
                entry_price = entry_row['close']
                stop_loss = entry_price - (atr * 1.0)
                take_profit = entry_price + (atr * R_MULTIPLE)
                size = (equity * risk_pct) / atr
                
                open_trade = {
                    'entry_time': entry_row.name,
                    'entry_price': entry_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                }
        else:
            # Manage Trade
            high = entry_row['high']
            low = entry_row['low']
            
            pnl = 0
            result = None
            
            if high >= open_trade['take_profit']:
                pnl = (open_trade['take_profit'] - open_trade['entry_price']) * open_trade['size']
                result = 'win'
            elif low <= open_trade['stop_loss']:
                pnl = (open_trade['stop_loss'] - open_trade['entry_price']) * open_trade['size']
                result = 'loss'
                
            if result:
                trades.append({
                    'pnl': pnl, 
                    'result': result, 
                    'exit_time': entry_row.name,
                })
                equity += pnl
                last_exit_idx = entry_idx # Mark exit time for cooldown
                
                daily_pnl += pnl
                if result == 'loss': daily_losses += 1
                else: daily_losses = 0 # Reset streak? Or count total daily? Usually streak.
                
                open_trade = None
                
    return pd.DataFrame(trades), equity

def analyze_results(trades_df, equity, title=""):
    if trades_df.empty:
        print(f"\n[{title}] No Trades.")
        return
        
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]
    wr = len(wins) / len(trades_df)
    pf = wins['pnl'].sum() / abs(losses['pnl'].sum()) if not losses.empty else 999
    
    cum = trades_df['pnl'].cumsum()
    dd = (cum - cum.cummax()).min()
    dd_r = dd / 100 # Approx 1R=$100
    
    months = (trades_df['exit_time'].max() - trades_df['exit_time'].min()).days / 30
    freq = len(trades_df) / months if months > 0 else 0
    
    print(f"\n=== {title} ===")
    print(f"Trades: {len(trades_df)} ({freq:.1f}/mo)")
    print(f"Win Rate: {wr:.2%}")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Max DD: {dd_r:.2f}R")
    print(f"Final Equity: ${equity:.2f}")
    
    return {'pf': pf, 'dd_r': dd_r, 'freq': freq}

def main():
    if os.path.exists("btc_usd_hourly.csv"):
        bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
        bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    else:
        bars_1h, bars_15m = fetch_data()
        
    regime_df = calculate_regime(bars_1h)
    strat_df = prepare_strategy_data(bars_15m, regime_df)
    
    # 1. Baseline Validation
    trades, eq = run_backtest(strat_df, entry_offset=0)
    analyze_results(trades, eq, "DAY 11 BASELINE")
    
    # 2. Stress Test: Early Entry (-1) re-run
    # Can the "2 of 3" rule save us from the PF 0.19 disaster?
    trades_stress, eq_stress = run_backtest(strat_df, entry_offset=-1)
    analyze_results(trades_stress, eq_stress, "DAY 11 STRESS TEST (Early Entry -1)")

if __name__ == "__main__":
    main()
