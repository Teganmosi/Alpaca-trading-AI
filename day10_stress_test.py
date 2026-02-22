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
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime'])
    df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    df['session'] = df.index.map(get_session)
    
    EMA_FAST, EMA_SLOW, ATR_PERIOD, STOCH_PERIOD = 15, 50, 14, 14
    
    df['EMA15'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean()
    df['ADX'] = calculate_adx(df)
    
    # Stoch RSI
    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    roll_up, roll_down = up.rolling(STOCH_PERIOD).mean(), down.rolling(STOCH_PERIOD).mean()
    RS = roll_up / roll_down.replace(0, np.nan)
    RSI = 100 - (100 / (1 + RS))
    min_rsi, max_rsi = RSI.rolling(STOCH_PERIOD).min(), RSI.rolling(STOCH_PERIOD).max()
    df['Stoch_RSI'] = (RSI - min_rsi) / (max_rsi - min_rsi)
    
    return df

def run_stress_test(df, scenario_name, entry_offset=0, friction_pct=0.0, bad_regime_mode=False):
    # print(f"Running Scenario: {scenario_name}")
    trades = []
    equity = 10000
    risk_pct = 0.01 # Fixed 1% Risk as per Day 9 conclusion
    open_trade = None
    R_MULTIPLE = 2
    
    # Circuit Breaker Logic (Include it, it's part of the 'Survive' test)
    current_date = None
    daily_pnl = 0
    daily_losses = 0
    
    for i in range(len(df)):
        # Handle Shift
        # Use 'i' for signal check, but use 'i + entry_offset' for actual entry price/execution
        # Need boundary check
        entry_idx = i + entry_offset
        if entry_idx < 0 or entry_idx >= len(df):
            continue
            
        row = df.iloc[i] # Signal Row
        entry_row = df.iloc[entry_idx] # Execution Row
        timestamp = entry_row.name # Use execution time
        
        # New Day Reset
        trade_date = timestamp.date()
        if trade_date != current_date:
            current_date = trade_date
            daily_pnl = 0
            daily_losses = 0
            
        # Circuit Breaker
        one_r_amount = equity * risk_pct
        if daily_losses >= 2 or daily_pnl <= -1 * one_r_amount:
            if open_trade is None:
                continue
        
        # Signal Generation Logic inside Loop to handle Force Bad Mode
        signal = 0
        if not bad_regime_mode:
            # NORMAL LOGIC
            if row['session'] == 'London' and \
               row['1H_Regime'] not in ['Neutral', 'Chaos'] and \
               row['1H_ATR_pct'] >= 0.8 and \
               row['ADX'] > 20 and \
               row['Stoch_RSI'] < 0.2 and row['EMA15'] > row['EMA50']:
                signal = 1
        else:
            # BAD REGIME SHOCK LOGIC
            # Force trade ONLY if it is potentially risky but technically a signal
            # Let's say we only take signals if Regime IS Neutral OR Chaos
            # We still need the technical trigger (Stoch/EMA) otherwise it's just random
            if row['session'] == 'London' and \
               row['1H_Regime'] in ['Neutral', 'Chaos'] and \
               row['Stoch_RSI'] < 0.2 and row['EMA15'] > row['EMA50']:
                signal = 1
        
        if open_trade is None:
            if signal == 1:
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                
                # EXECUTION at entry_idx
                # Note: System is usually "Close of Signal Candle".
                # If offset=0, price = entry_row['close']
                # If offset=1, price = entry_row['close'] (which is next candle close) - Effectively 15m lag?
                # User said: "+1 candle". usually means entering on Open/Close of NEXT candle.
                # Here: i=Signal. if offset=1, we use price at i+1.
                
                entry_price = entry_row['close'] 
                stop_loss = entry_price - (atr * 1.0)
                take_profit = entry_price + (atr * R_MULTIPLE)
                size = (equity * risk_pct) / atr
                
                # Apply Slippage to Entry? usually slippage hurts PnL, not price?
                # Let's simulate slippage by adjusting entry price slightly worse
                # Long only: Buy Higher
                effective_entry = entry_price * (1 + (friction_pct/2)) # half friction on entry
                
                open_trade = {
                    'entry_time': timestamp,
                    'entry_price': effective_entry, 
                    'raw_entry': entry_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'friction': friction_pct
                }
        else:
            # Manage Trade
            # Check High/Low of CURRENT candle (entry_idx)
            # If entry_idx is the *entry* candle, we usually don't exit same candle in backtest loop unless detailed
            # But proceed standard
            
            pnl = 0
            result = None
            
            # Apply friction to exit price too?
            
            if entry_row['high'] >= open_trade['take_profit']:
                # Win
                exit_price = open_trade['take_profit']
                effective_exit = exit_price * (1 - (open_trade['friction']/2)) # half friction on exit
                pnl = (effective_exit - open_trade['entry_price']) * open_trade['size']
                result = 'win'
            elif entry_row['low'] <= open_trade['stop_loss']:
                # Loss
                exit_price = open_trade['stop_loss']
                effective_exit = exit_price * (1 - (open_trade['friction']/2))
                pnl = (effective_exit - open_trade['entry_price']) * open_trade['size']
                result = 'loss'
                
            if result:
                trades.append({
                    'pnl': pnl, 
                    'result': result, 
                    'exit_time': timestamp,
                    'equity_after': equity + pnl
                })
                equity += pnl
                
                daily_pnl += pnl
                if result == 'loss':
                    daily_losses += 1
                else:
                    daily_losses = 0
                
                open_trade = None

    return pd.DataFrame(trades), equity

def analyze_results(trades_df, equity, scenario):
    if trades_df.empty:
        return {'Scenario': scenario, 'Trades': 0, 'Win Rate': '0%', 'PF': 0, 'Max DD': 0}
        
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]
    win_rate = len(wins) / len(trades_df)
    pf = wins['pnl'].sum() / abs(losses['pnl'].sum()) if not losses.empty else 999
    
    cum_pnl = trades_df['pnl'].cumsum()
    running_max = cum_pnl.cummax()
    dd = (cum_pnl - running_max).min()
    
    # 1R approx $100 (1% of 10k)
    dd_r = dd / 100 
    
    return {
        'Scenario': scenario,
        'Trades': len(trades_df),
        'Win Rate': f"{win_rate:.2%}",
        'PF': round(pf, 2),
        'Max DD': round(dd, 2),
        'Max DD (R)': round(dd_r, 2)
    }

def main():
    if os.path.exists("btc_usd_hourly.csv"):
        bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
        bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    else:
        bars_1h, bars_15m = fetch_data()
        
    regime_df = calculate_regime(bars_1h)
    strat_df = prepare_strategy_data(bars_15m, regime_df)
    
    print("\n" + "="*60)
    print("🧪 DAY 10 STRESS TEST RESULTS")
    print("="*60)
    
    scenarios = [
        ("Baseline", 0, 0, False),
        ("Late Entry (+1)", 1, 0, False),
        ("Early Entry (-1)", -1, 0, False),
        # Fee/Slip: 0.05% slip + 0.1% fee = 0.15% = 0.0015
        ("Friction Stress (0.15%)", 0, 0.0015, False),
        ("Regime Shock (Chaos Only)", 0, 0, True)
    ]
    
    results = []
    
    for name, off, frict, bad_mode in scenarios:
        t, eq = run_stress_test(strat_df, name, entry_offset=off, friction_pct=frict, bad_regime_mode=bad_mode)
        stats = analyze_results(t, eq, name)
        results.append(stats)
        
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))
    res_df.to_csv("day10_stress_results.csv", index=False)

if __name__ == "__main__":
    main()
