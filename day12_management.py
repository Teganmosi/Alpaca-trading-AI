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
    df['H-PC'] = abs(df['high'] - df['close'].shift(1)); df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(ATR_PERIOD).mean(); df['ATR_pct'] = df['ATR'] / df['close'] * 100
    df['EMA50_slope'] = df['EMA50'].pct_change() * 100
    def get_regime(row):
        if abs(row['EMA50_slope']) > 0.05: return 'Trend_Up' if row['EMA50_slope'] > 0 else 'Trend_Down'
        elif row['ATR_pct'] > 1.5: return 'Expansion'
        elif row['ATR_pct'] < 0.5: return 'Chaos'
        else: return 'Neutral'
    df['Regime'] = df.apply(get_regime, axis=1)
    return df[['Regime', 'ATR_pct']]

def calculate_adx(df, period=14):
    df = df.copy(); alpha = 1/period; df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1)); df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['up_move'] = df['high'] - df['high'].shift(1); df['down_move'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
    df['TR_smooth'] = df['TR'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_dm_smooth'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean(); df['minus_dm_smooth'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_di'] = 100 * (df['plus_dm_smooth'] / df['TR_smooth']); df['minus_di'] = 100 * (df['minus_dm_smooth'] / df['TR_smooth'])
    df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
    df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()
    return df['adx']

def get_session(dt):
    h = dt.hour
    return 'Trading' if 8 <= h < 21 else 'Other' # London + NY

def prepare_strategy_data(df_15m, df_1h_regime):
    print("Preparing Strategy Data...")
    df = df_15m.copy()
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime']); df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    df['session'] = df.index.map(get_session)
    df['EMA15'] = df['close'].ewm(span=15, adjust=False).mean(); df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['H-L'] = df['high'] - df['low']; df['H-PC'] = abs(df['high'] - df['close'].shift(1)); df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1); df['ATR'] = df['TR'].rolling(14).mean(); df['ADX'] = calculate_adx(df)
    delta = df['close'].diff(); up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    roll_up, roll_down = up.rolling(14).mean(), down.rolling(14).mean()
    RS = roll_up / roll_down.replace(0, np.nan); RSI = 100 - (100 / (1 + RS))
    min_rsi, max_rsi = RSI.rolling(14).min(), RSI.rolling(14).max()
    df['Stoch_K'] = (RSI - min_rsi) / (max_rsi - min_rsi); df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()
    df['Setup'] = (df['Stoch_K'] < 0.2) & (df['EMA15'] > df['EMA50']) & (df['ADX'] > 20)
    df['Setup_Active'] = df['Setup'].rolling(6).max() > 0
    df['Cond_Zone'] = df['close'] > df['EMA15']; df['Cond_Cross'] = (df['Stoch_K'] > df['Stoch_D']) & (df['Stoch_K'].shift(1) < df['Stoch_D'].shift(1))
    df['Cond_ATR_Up'] = df['ATR'] > df['ATR'].shift(1); df['Confirm_Count'] = df[['Cond_Zone', 'Cond_Cross', 'Cond_ATR_Up']].sum(axis=1)
    df['Entry_Candidate'] = df['Setup_Active'] & (df['Confirm_Count'] >= 2) & (df['Stoch_K'] < 0.6)
    return df

def run_backtest(df, entry_offset=0):
    trades = []; equity = 10000; risk_pct = 0.01; open_trade = None; last_exit_idx = -999; last_regime = None; regime_buffer = 0; current_date = None; daily_losses = 0; daily_pnl = 0
    for i in range(len(df)):
        if i < 4: continue
        row = df.iloc[i]; timestamp = df.index[i]
        if timestamp.date() != current_date: current_date = timestamp.date(); daily_losses = 0; daily_pnl = 0
        if last_regime is not None and row['1H_Regime'] != last_regime: regime_buffer = 1
        last_regime = row['1H_Regime']; is_buffered = (regime_buffer > 0)
        if regime_buffer > 0: regime_buffer -= 1
        on_cooldown = (i - last_exit_idx) < 4; day_stopped = daily_losses >= 2 or daily_pnl <= -100
        entry_signal = (row['session'] == 'Trading') and (row['1H_Regime'] in ['Trend_Up', 'Expansion']) and (row['1H_ATR_pct'] >= 0.8) and (row['ADX'] > 20) and not is_buffered and not on_cooldown and not day_stopped and row['Entry_Candidate']
        
        entry_idx = i + entry_offset
        if entry_idx >= len(df): continue
        entry_row = df.iloc[entry_idx]
        
        if open_trade is None:
            if entry_signal:
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                # Risk 0.75% for better DD survival
                risk_pct = 0.0075 
                # Adaptive Activation based on Trend Strength
                r_target = 2.2 if row['ADX'] > 35 else 2.0
                open_trade = {
                    'entry_price': entry_row['close'], 
                    'size': (equity * risk_pct) / atr, 
                    'stop_loss': entry_row['close'] - atr, 
                    'tp_target': entry_row['close'] + (atr * r_target), 
                    'atr': atr, 
                    'idx': entry_idx, 
                    'active_runner': False
                }
        else:
            high, low, close = entry_row['high'], entry_row['low'], entry_row['close']
            
            if low <= open_trade['stop_loss']:
                pnl = (open_trade['stop_loss'] - open_trade['entry_price']) * open_trade['size']
                trades.append({'pnl': pnl, 'tag': 'SL' if not open_trade['active_runner'] else 'Runner'})
                equity += pnl; daily_pnl += pnl; daily_losses += (1 if pnl < 0 else 0); last_exit_idx = entry_idx; open_trade = None; continue
            
            if not open_trade['active_runner'] and high >= open_trade['tp_target']:
                open_trade['active_runner'] = True
                # Lock in most of the win (1.9R floor)
                open_trade['stop_loss'] = open_trade['entry_price'] + (open_trade['atr'] * 1.9)

            if open_trade['active_runner']:
                # Tighten trail for bigger wins
                current_pnl_r = (high - open_trade['entry_price']) / open_trade['atr']
                offset = 0.75 if current_pnl_r > 3.0 else 1.0
                new_trail = high - (entry_row['ATR'] * offset)
                if new_trail > open_trade['stop_loss']: open_trade['stop_loss'] = new_trail
            if (entry_idx - open_trade['idx']) >= 48:
                pnl = (close - open_trade['entry_price']) * open_trade['size']
                trades.append({'pnl': pnl, 'tag': 'Time'}); equity += pnl; daily_pnl += pnl; last_exit_idx = entry_idx; open_trade = None
    return pd.DataFrame(trades), equity

def analyze_results(trades_df, equity, title=""):
    if trades_df.empty: print(f"\n[{title}] No Trades."); return
    wr = len(trades_df[trades_df['pnl'] > 0]) / len(trades_df)
    pf = trades_df[trades_df['pnl'] > 0]['pnl'].sum() / abs(trades_df[trades_df['pnl'] <= 0]['pnl'].sum() or 0.1)
    cum = trades_df['pnl'].cumsum(); dd_r = (cum - cum.cummax()).min() / 100
    print(f"\n=== {title} ===\nTrades: {len(trades_df)} | Win Rate: {wr:.2%} | Profit Factor: {pf:.2f} | Max DD: {dd_r:.2f}R")
    if 'tag' in trades_df.columns: print("Tags:", trades_df['tag'].value_counts().to_dict())

def main():
    bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
    bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    regime = calculate_regime(bars_1h); strat = prepare_strategy_data(bars_15m, regime)
    analyze_results(run_backtest(strat, 0)[0], 10000, "DAY 12 FINAL")
    analyze_results(run_backtest(strat, -1)[0], 10000, "DAY 12 STRESS")
if __name__ == "__main__": main()
