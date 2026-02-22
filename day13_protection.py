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
    df['TR'] = (df['high'] - df['low']).rolling(ATR_PERIOD).mean()
    df['ATR_pct'] = df['TR'] / df['close'] * 100
    df['EMA50_slope'] = df['EMA50'].pct_change() * 100
    def get_regime(row):
        if row['EMA50_slope'] > 0.05: return 'Trend_Up'
        elif row['EMA50_slope'] < -0.05: return 'Trend_Down'
        elif row['ATR_pct'] > 1.3: return 'Expansion'
        else: return 'Neutral'
    df['Regime'] = df.apply(get_regime, axis=1)
    return df[['Regime', 'ATR_pct', 'EMA50_slope']]

def calculate_adx(df, period=14):
    df = df.copy(); alpha = 1/period; df['TR'] = (df['high'] - df['low']).rolling(1).mean()
    df['up_move'] = df['high'] - df['high'].shift(1); df['down_move'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
    df['plus_di'] = 100 * (df['plus_dm'].ewm(alpha=alpha).mean() / df['TR'].ewm(alpha=alpha).mean().replace(0, 0.001))
    df['minus_di'] = 100 * (df['minus_dm'].ewm(alpha=alpha).mean() / df['TR'].ewm(alpha=alpha).mean().replace(0, 0.001))
    dx = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']).replace(0, 0.001)
    return dx.ewm(alpha=alpha).mean()

def get_session(dt):
    h = dt.hour
    return 'Trading' if 8 <= h < 21 else 'Other' 

def prepare_strategy_data(df_15m, df_1h_regime):
    print("Preparing Strategy Data...")
    df = df_15m.copy()
    df['1H_Regime'] = df.index.floor('h').map(df_1h_regime['Regime'])
    df['1H_ATR_pct'] = df.index.floor('h').map(df_1h_regime['ATR_pct'])
    df['1H_slope'] = df.index.floor('h').map(df_1h_regime['EMA50_slope'])
    df['session'] = df.index.map(get_session)
    df['EMA15'] = df['close'].ewm(span=15, adjust=False).mean(); df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ATR'] = (df['high'] - df['low']).rolling(14).mean(); df['ADX'] = calculate_adx(df)
    delta = df['close'].diff(); up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    RS = up.rolling(14).mean() / down.rolling(14).mean().replace(0, 0.001); RSI = 100 - (100 / (1 + RS))
    df['Stoch_K'] = (RSI - RSI.rolling(14).min()) / (RSI.rolling(14).max() - RSI.rolling(14).min()).replace(0, 0.001); df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()
    df['Setup'] = (df['Stoch_K'] < 0.2) & (df['EMA15'] > df['EMA50']) & (df['ADX'] > 20)
    df['Setup_Active'] = df['Setup'].rolling(6).max() > 0
    df['Cond_Zone'] = df['close'] > df['EMA15']; df['Cond_Cross'] = (df['Stoch_K'] > df['Stoch_D']) & (df['Stoch_K'].shift(1) < df['Stoch_D'].shift(1))
    df['Cond_ATR_Up'] = df['ATR'] > df['ATR'].shift(1); df['Confirm_Count'] = df[['Cond_Zone', 'Cond_Cross', 'Cond_ATR_Up']].sum(axis=1)
    df['Entry_Candidate'] = df['Setup_Active'] & (df['Confirm_Count'] >= 2) & (df['Stoch_K'] < 0.5) # Tightened K
    return df

def run_backtest(df, entry_offset=0, friction_pct=0.0):
    trades = []; equity = 10000; peak_equity = 10000; open_trade = None; last_exit_idx = -999; current_date = None; daily_losses = 0; daily_pnl = 0
    consecutive_sl = 0; cooldown_until = None
    
    for i in range(len(df)):
        if i < 4: continue
        row = df.iloc[i]; timestamp = df.index[i]
        if timestamp.date() != current_date:
            current_date = timestamp.date(); daily_losses = 0; daily_pnl = 0
            
        peak_equity = max(peak_equity, equity)
        if cooldown_until and timestamp < cooldown_until: continue
            
        # PROTECTION: DAILY LOSS LIMIT (1.0R Shutdown)
        # 1R = 0.5% = $50.
        day_stopped = daily_losses >= 1 or daily_pnl <= -50
        on_cooldown = (i - last_exit_idx) < 4
        
        # VOLATILITY PROTECTION (1.2% Cap)
        atr_pct = row['1H_ATR_pct']
        if atr_pct > 1.2: continue 
            
        base_risk = 0.005 
        risk_pct = base_risk
        # Equity Guard: Slash risk by 90% if in any DD from peak
        if equity < peak_equity: risk_pct *= 0.1 
            
        entry_qualifies = (row['session'] == 'Trading') and (row['1H_Regime'] == 'Trend_Up') and (row['1H_slope'] > 0.02) and not on_cooldown and not day_stopped and row['Entry_Candidate'] and (row['ADX'] > 25)

        entry_idx = i + entry_offset
        if entry_idx >= len(df): continue
        entry_row = df.iloc[entry_idx]
        
        if open_trade is None:
            if entry_qualifies:
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                open_trade = {
                    'entry_price': entry_row['close'] * (1 + friction_pct), 
                    'size': (equity * risk_pct) / atr, 
                    'stop_loss': entry_row['close'] - atr, 
                    'tp_target': entry_row['close'] + (atr * 2.2), 
                    'atr': atr, 
                    'idx': entry_idx, 
                    'active_runner': False
                }
        else:
            high, low, close = entry_row['high'], entry_row['low'], entry_row['close']
            if low <= open_trade['stop_loss']:
                exit_price = open_trade['stop_loss'] * (1 - friction_pct)
                pnl = (exit_price - open_trade['entry_price']) * open_trade['size']
                tag = 'SL' if not open_trade['active_runner'] else 'Runner'
                trades.append({'pnl': pnl, 'exit_time': entry_row.name, 'tag': tag})
                equity += pnl; daily_pnl += pnl
                if tag == 'SL':
                    consecutive_sl += 1
                    if consecutive_sl >= 1: cooldown_until = timestamp + timedelta(hours=24) # Aggressive 24h shutdown
                else: consecutive_sl = 0 
                if pnl < 0: daily_losses += 1
                last_exit_idx = entry_idx; open_trade = None; continue

            if not open_trade['active_runner'] and high >= open_trade['tp_target']:
                open_trade['active_runner'] = True
                open_trade['stop_loss'] = open_trade['entry_price'] + (open_trade['atr'] * 2.0)

            if open_trade['active_runner']:
                new_trail = high - (entry_row['ATR'] * 0.7) # Aggressive trail
                if new_trail > open_trade['stop_loss']: open_trade['stop_loss'] = new_trail
            if (entry_idx - open_trade['idx']) >= 32: # Fast timeout
                exit_p = close * (1 - friction_pct)
                pnl = (exit_p - open_trade['entry_price']) * open_trade['size']
                trades.append({'pnl': pnl, 'exit_time': entry_row.name, 'tag': 'Time'})
                equity += pnl; daily_pnl += pnl; last_exit_idx = entry_idx; open_trade = None
    return pd.DataFrame(trades), equity

def analyze_results(trades_df, equity, title=""):
    if trades_df.empty: print(f"\n[{title}] No Trades."); return
    wins = trades_df[trades_df['pnl'] > 0]; losses = trades_df[trades_df['pnl'] <= 0]
    wr = len(wins) / len(trades_df); pf = wins['pnl'].sum() / abs(losses['pnl'].sum()) if not losses.empty else 999
    cum = trades_df['pnl'].cumsum(); dd_r = (cum - cum.cummax()).min() / 50 
    print(f"\n=== {title} ===\nTrades: {len(trades_df)} | Win Rate: {wr:.2%} | Profit Factor: {pf:.2f} | Max DD: {dd_r:.2f}R")
    if 'tag' in trades_df.columns: print("Tags:", trades_df['tag'].value_counts().to_dict())

def main():
    bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
    bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    regime = calculate_regime(bars_1h); strat = prepare_strategy_data(bars_15m, regime)
    analyze_results(run_backtest(strat, 0)[0], 10000, "DAY 13 FINAL VERIFICATION")
    analyze_results(run_backtest(strat, -1)[0], 10000, "DAY 13 STRESS (Early Entry)")
if __name__ == "__main__": main()
