import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# ---------------- CONFIGURATION ----------------
SYMBOL = "BTC/USD"
DAYS_TO_FETCH = 300 # Kept from Day 8 Verification
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
    
    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    roll_up, roll_down = up.rolling(STOCH_PERIOD).mean(), down.rolling(STOCH_PERIOD).mean()
    RS = roll_up / roll_down.replace(0, np.nan)
    RSI = 100 - (100 / (1 + RS))
    min_rsi, max_rsi = RSI.rolling(STOCH_PERIOD).min(), RSI.rolling(STOCH_PERIOD).max()
    df['Stoch_RSI'] = (RSI - min_rsi) / (max_rsi - min_rsi)
    
    def get_signal(row):
        if row['session'] != 'London': return 0
        if row['1H_Regime'] in ['Neutral', 'Chaos']: return 0
        if row['1H_ATR_pct'] < 0.8: return 0
        if row['ADX'] <= 20: return 0
        if row['Stoch_RSI'] < 0.2 and row['EMA15'] > row['EMA50']:
            return 1
        return 0

    df['Signal'] = df.apply(get_signal, axis=1)
    return df

def run_backtest(df, risk_pct=0.005):
    # print(f"Running Backtest with Risk: {risk_pct*100}%...")
    trades = []
    equity = 10000
    open_trade = None
    R_MULTIPLE = 2
    
    # Circuit Breaker Tracking
    current_date = None
    daily_pnl = 0
    daily_losses = 0
    
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = df.index[i]
        
        # New Day Reset
        trade_date = timestamp.date()
        if trade_date != current_date:
            current_date = trade_date
            daily_pnl = 0
            daily_losses = 0
            
        # Circuit Breaker Logic
        # Stop if 2 consecutive losses OR daily PnL <= -1R
        # Note: -1R = -1 * (equity * risk_pct). We estimate equity at start of day approx or current equity.
        # Strict rule: "-1R on the day"
        one_r_amount = equity * risk_pct
        if daily_losses >= 2 or daily_pnl <= -1 * one_r_amount:
            # Skip this iteration (no new trades)
            # But we must continue managing open trades if any (though logic below implies sequential)
            if open_trade is None:
                continue
        
        if open_trade is None:
            if row['Signal'] == 1:
                atr = row['ATR']
                if np.isnan(atr) or atr == 0: continue
                
                entry_price = row['close']
                stop_loss = entry_price - (atr * 1.0)
                take_profit = entry_price + (atr * R_MULTIPLE)
                size = (equity * risk_pct) / atr
                
                open_trade = {
                    'entry_time': timestamp,
                    'entry_price': entry_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_pct': risk_pct
                }
        else:
            # Manage Trade
            pnl = 0
            result = None
            
            if row['high'] >= open_trade['take_profit']:
                pnl = (open_trade['take_profit'] - open_trade['entry_price']) * open_trade['size']
                result = 'win'
            elif row['low'] <= open_trade['stop_loss']:
                pnl = (open_trade['stop_loss'] - open_trade['entry_price']) * open_trade['size']
                result = 'loss'
                
            if result:
                trades.append({
                    'pnl': pnl, 
                    'result': result, 
                    'exit_time': timestamp,
                    'equity_after': equity + pnl
                })
                equity += pnl
                
                # Update Circuit Breaker stats
                daily_pnl += pnl
                if result == 'loss':
                    daily_losses += 1
                else:
                    daily_losses = 0 # Reset consecutive streak on win
                
                open_trade = None
                
    return pd.DataFrame(trades), equity

def analyze_stats(trades_df, equity_result, risk_pct):
    if trades_df.empty:
        return {
            'Risk %': f"{risk_pct*100}%",
            'Trades': 0,
            'Win Rate': "0%",
            'PF': 0,
            'Expectancy': 0,
            'Max DD': 0,
            'Final Equity': equity_result,
            'Return/DD': 0
        }
        
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]
    
    total_trades = len(trades_df)
    win_rate = len(wins) / total_trades
    profit_factor = wins['pnl'].sum() / abs(losses['pnl'].sum()) if not losses.empty else 999
    expectancy = trades_df['pnl'].mean()
    
    # Drawdown
    cum_pnl = trades_df['pnl'].cumsum()
    running_max = cum_pnl.cummax()
    dd_series = cum_pnl - running_max
    max_dd = dd_series.min()
    
    # Return per Unit of Drawdown (Absolute Return / Max Drawdown)
    total_return = equity_result - 10000
    ret_dd = total_return / abs(max_dd) if max_dd != 0 else 999
    
    # Losing Streak
    trades_df['is_loss'] = trades_df['pnl'] <= 0
    # Group by consecutive similar results
    # Ref: https://stackoverflow.com/questions/40802800/
    # But simple iteration is safer without helpers
    current_streak = 0
    max_losing_streak = 0
    for res in trades_df['is_loss']:
        if res:
            current_streak += 1
            max_losing_streak = max(max_losing_streak, current_streak)
        else:
            current_streak = 0
            
    # Trade Frequency (Avg days between trades)
    trades_df['exit_date'] = pd.to_datetime(trades_df['exit_time'])
    date_diffs = trades_df['exit_date'].diff().dt.days
    avg_days_between = date_diffs.mean() if len(trades_df) > 1 else 0

    print(f"Risk {risk_pct*100}% -> Streak: {max_losing_streak} losses. Avg Gap: {avg_days_between:.1f} days.")

    return {
        'Risk %': f"{risk_pct*100}%",
        'Trades': total_trades,
        'Win Rate': f"{win_rate:.2%}",
        'PF': round(profit_factor, 2),
        'Expectancy': round(expectancy, 2),
        'Max DD': round(max_dd, 2),
        'Final Equity': round(equity_result, 2),
        'Ret/DD': round(ret_dd, 2)
    }

def main():
    if os.path.exists("btc_usd_hourly.csv"):
        bars_1h = pd.read_csv("btc_usd_hourly.csv", index_col=0, parse_dates=True)
        bars_15m = pd.read_csv("btc_usd_15min.csv", index_col=0, parse_dates=True)
    else:
        bars_1h, bars_15m = fetch_data()
        bars_1h.to_csv("btc_usd_hourly.csv")
        bars_15m.to_csv("btc_usd_15min.csv")
        
    regime_df = calculate_regime(bars_1h)
    strat_df = prepare_strategy_data(bars_15m, regime_df)
    
    print("\n" + "="*60)
    print("🧪 DAY 9 RISK SWEEP & SAFETY CHECKS")
    print("="*60)
    
    risks = [0.0025, 0.005, 0.0075, 0.010]
    results = []
    
    for r in risks:
        trades, final_eq = run_backtest(strat_df, risk_pct=r)
        stats = analyze_stats(trades, final_eq, r)
        results.append(stats)
        
    results_df = pd.DataFrame(results)
    
    print("\n" + "="*60)
    print("DAY 9 RISK SWEEP RESULTS")
    print("="*60)
    print(results_df.to_string(index=False))
    
    # Save for user review
    results_df.to_csv("day9_sweep_results.csv", index=False)

if __name__ == "__main__":
    main()
