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
    """Calculates ADX for momentum confirmation."""
    df = df.copy()
    alpha = 1/period
    
    # TR
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    
    # Directional Movement
    df['up_move'] = df['high'] - df['high'].shift(1)
    df['down_move'] = df['low'].shift(1) - df['low']
    
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
    
    # Smooth
    # Using simple EWMA for smoothing similar to Welles Wilder
    # Actually standard pandas ewm check:
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
    
    # 1. Map Context
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime'])
    df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    df['session'] = df.index.map(get_session)
    
    # 2. Indicators
    EMA_FAST = 15
    EMA_SLOW = 50
    ATR_PERIOD = 14
    STOCH_PERIOD = 14
    
    df['EMA15'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    # ATR & ADX
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
    
    # 3. Strategy Logic (Day 8 Rules)
    def get_signal(row):
        # 1. FILTER: Session (London Only)
        if row['session'] != 'London': return 0
        
        # 2. FILTER: Regime (No Neutral/Chaos)
        if row['1H_Regime'] in ['Neutral', 'Chaos']: return 0
        
        # 3. FILTER: Low Volatility (No Low Vol)
        # Using the classification from Day 7: Low Vol was ATR% < 0.8 likely (implied from walkthrough)
        # Let's use the explicit check: 1H_ATR_pct < 0.8 is Low. 
        # But wait, 1H_Regime 'Chaos' and 'Neutral' already capture non-trending.
        # Let's ensure we skip if ATR_pct is very low even if labeled Trend?
        if row['1H_ATR_pct'] < 0.8: return 0
        
        # 4. FILTER: Direction (LONG ONLY)
        # 5. CONFIRMATION: Momentum (ADX > 20)
        if row['ADX'] <= 20: return 0
        
        # ENTRY TRIGGER (Long Only)
        # Stoch RSI < 0.2 (Oversold Pullback) AND Uptrend
        if row['Stoch_RSI'] < 0.2 and row['EMA15'] > row['EMA50']:
            return 1
            
        return 0

    df['Signal'] = df.apply(get_signal, axis=1)
    return df

def run_backtest(df):
    print("Running Backtest...")
    trades = []
    equity = 10000
    open_trade = None
    RISK_PER_TRADE = 0.005
    R_MULTIPLE = 2
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        if open_trade is None:
            if row['Signal'] == 1: # Long Only
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                
                entry_price = row['close']
                stop_loss = entry_price - (atr * 1.0)
                take_profit = entry_price + (atr * R_MULTIPLE)
                size = (equity * RISK_PER_TRADE) / atr
                
                open_trade = {
                    'entry_time': df.index[i],
                    'entry_price': entry_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                }
        else:
            # Manage Trade
            if row['high'] >= open_trade['take_profit']:
                pnl = (open_trade['take_profit'] - open_trade['entry_price']) * open_trade['size']
                trades.append({'pnl': pnl, 'result': 'win', 'exit_time': df.index[i]})
                equity += pnl
                open_trade = None
            elif row['low'] <= open_trade['stop_loss']:
                pnl = (open_trade['stop_loss'] - open_trade['entry_price']) * open_trade['size']
                trades.append({'pnl': pnl, 'result': 'loss', 'exit_time': df.index[i]})
                equity += pnl
                open_trade = None
                
    return pd.DataFrame(trades), equity

def main():
    if os.path.exists("btc_usd_hourly.csv"):
        bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
        bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    else:
        bars_1h, bars_15m = fetch_data()
        
    regime_df = calculate_regime(bars_1h)
    strat_df = prepare_strategy_data(bars_15m, regime_df)
    results, final_equity = run_backtest(strat_df)
    
    if results.empty:
        print("No trades found matching Day 8 criteria.")
        return

    # Metrics
    wins = results[results['pnl'] > 0]
    losses = results[results['pnl'] <= 0]
    
    total_trades = len(results)
    win_rate = len(wins) / total_trades
    profit_factor = wins['pnl'].sum() / abs(losses['pnl'].sum()) if not losses.empty else 0
    expectancy = results['pnl'].mean()
    
    cum_pnl = results['pnl'].cumsum()
    running_max = cum_pnl.cummax()
    dd = (cum_pnl - running_max).min()
    
    print("\n" + "="*30)
    print("DAY 8 RESULTS")
    print("="*30)
    print(f"Trades: {total_trades}")
    print(f"Win Rate: {win_rate:.2%}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Expectancy: ${expectancy:.2f}")
    print(f"Max DD: ${dd:.2f}")
    print(f"Final Equity: ${final_equity:.2f}")

if __name__ == "__main__":
    main()
