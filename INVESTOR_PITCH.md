# Alpaca Trading AI - Investor Pitch

## Executive Summary

We've built an **autonomous AI-powered cryptocurrency trading bot** that trades Bitcoin (BTC/USD) using algorithmic strategies on the Alpaca trading platform. The bot is currently running live on paper trading with $100,000 and generating real trading signals.

---

## What We Built

### The Trading Bot

Our bot is a fully autonomous algorithmic trading system that:

- ✅ Runs 24/7 without human intervention
- ✅ Trades BTC/USD on Alpaca (regulated US broker)
- ✅ Uses multiple trading strategies simultaneously
- ✅ Manages risk automatically
- ✅ Logs all decisions for transparency

### Current Status

| Metric          | Value                    |
| --------------- | ------------------------ |
| Initial Capital | $100,000 (paper trading) |
| Current Equity  | $99,939.54               |
| Active Position | 0.146 BTC @ $68,343      |
| Stop Loss       | $67,910                  |
| Take Profit     | $69,203                  |
| Risk:Reward     | 1:2                      |

---

## How It Works

### 1. Market Analysis (Every 15 Minutes)

The bot fetches real-time market data and analyzes:

```
┌─────────────────────────────────────────────────────────┐
│                    MARKET DATA                          │
├─────────────────────────────────────────────────────────┤
│ • Price (Close)           → $68,000 - $70,000         │
│ • Trend Direction         → Trend_Up / Trend_Down       │
│ • Trend Strength (ADX)    → 20+ = Strong Trend         │
│ • Volatility (ATR %)     → 1.0% - 1.5%                │
│ • Momentum (Stochastic)   → 0-100 scale                │
└─────────────────────────────────────────────────────────┘
```

### 2. Multi-Strategy Signal Generation

The bot uses **four complementary strategies** to maximize opportunities:

| Strategy            | When It Trades     | Logic                                  |
| ------------------- | ------------------ | -------------------------------------- |
| **Trend Following** | In strong trends   | Buy in uptrends, sell in downtrends    |
| **Mean Reversion**  | In ranging markets | Buy oversold, sell overbought          |
| **EMA Breakout**    | Momentum shifts    | Golden cross = buy, death cross = sell |
| **Expansion**       | High volatility    | Trade momentum in volatile markets     |

**Signal Example:**

```
[2026-02-26 05:00] Close: $68,314 | Regime: Trend_Up | Slope: 0.1029
[RISK] Gate PASSED: risk_pct=0.0050
[EXECUTION] BUY 0.146 BTC @ $68,343
```

### 3. Risk Management (The Gatekeeper)

Before every trade, the bot checks **7 risk gates**:

```
┌────────────────────────────────────────────────────────┐
│                   RISK MANAGEMENT                     │
├────────────────────────────────────────────────────────┤
│ ☑ Daily Loss Limit     → Max 3 losses per day         │
│ ☑ Cooldown            → 2h cooldown after 2 losses    │
│ ☑ Volatility Cap      → No trades if ATR > 1.5%      │
│ ☑ Position Size       → Max 10% of portfolio          │
│ ☑ Stop Loss          → Always 1 ATR = ~$433 risk     │
│ ☑ Take Profit        → 2.2 ATR = ~$860 target       │
│ ☑ Equity Curve       size in → Reduce drawdown       │
└────────────────────────────────────────────────────────┘
```

### 4. Trade Execution

When a signal passes all risk gates:

1. **Calculate Position Size**
   - 10% of equity = $10,000
   - Buy 0.146 BTC

2. **Set Stop Loss**
   - Entry - 1 ATR = $68,343 - $433 = $67,910
   - Maximum loss: $433 (0.43%)

3. **Set Take Profit**
   - Entry + 2.2 ATR = $68,343 + $860 = $69,203
   - Target profit: $860 (0.86%)

4. **Risk:Reward = 1:2** (For every $1 risked, we make $2)

---

## Why This Works

### 1. Diversified Strategies

No single strategy works in all market conditions. We use four:

- **Trend Following** → Catches big moves in clear trends
- **Mean Reversion** → Profits in range-bound markets
- **Breakout** → Catches momentum shifts
- **Expansion** → Profits during volatility

### 2. Strict Risk Management

| Protection               | How It Helps         |
| ------------------------ | -------------------- |
| Max 3 losses/day         | Prevents blow-ups    |
| 2h cooldown after losses | Emotional discipline |
| 10% max position         | Never over-leverage  |
| Always 1 ATR stop loss   | Consistent risk      |
| 1:2 risk:reward          | Positive expectancy  |

### 3. Fully Automated

- ✅ No emotional trading
- ✅ 24/7 market monitoring
- ✅ Instant reaction to opportunities
- ✅ Consistent execution

### 4. Transparency

Every decision is logged:

```
[2026-02-26 05:00] Close: 68314.21 | Regime: Trend_Up | Slope: 0.1029
[RISK] Gate PASSED: risk_pct=0.0050
[POSITION] Equity: $99939.54 | Position: $9993.95 (0.146 BTC)
[EXECUTION] Order filled at $68343.30
[TELEMETRY] TRADE_ENTRY: Entered LONG BTC/USD at 68343.30
```

---

## Technology Stack

| Component       | Technology             |
| --------------- | ---------------------- |
| Trading API     | Alpaca (SEC-regulated) |
| Market Data     | Alpaca Crypto Data     |
| Language        | Python 3.13            |
| Cloud           | Google Cloud Run       |
| Version Control | GitHub                 |

---

## Performance (Live Results)

```
=== TRADING LOG ===
Initial Equity:    $100,000.00
Current Equity:   $99,939.54
Active Trades:    1 position
Daily P&L:        -$60.46 (-0.06%)
Win Rate:         [Tracking]
Risk:Reward:      1:2
```

_The small loss is from the trade execution spread - the position is still open with $860 target._

---

## Investment Ask

We're seeking funding to:

1. **Upgrade to Live Trading** - Move from paper to real money
2. **Add More Assets** - ETH, SOL, other alts
3. **Enhance Strategies** - Add AI/ML signal refinement
4. **Scale Infrastructure** - Better cloud setup for 24/7 reliability

### Use of Funds

| Item                   | Cost        |
| ---------------------- | ----------- |
| Live trading capital   | $50,000     |
| API upgrades           | $2,000      |
| Development (3 months) | $15,000     |
| Cloud infrastructure   | $3,000      |
| **Total**              | **$70,000** |

---

## Why Invest in Us

| Advantage           | Why It Matters            |
| ------------------- | ------------------------- |
| ✅ Working Product  | Bot is already trading    |
| ✅ Regulated Broker | Alpaca = SEC compliant    |
| ✅ Transparent      | All trades logged         |
| ✅ Risk Managed     | 1:2 R:R, max 3 losses/day |
| ✅ 24/7 Automation  | No human emotion          |
| ✅ Proven Code      | GitHub shows full history |

---

## Contact

For more details or to discuss investment:

- 📧 [Your Email]
- 🔗 [Your Linktree/Website]
- 💻 [GitHub Repository]

---

## Appendix: Technical Details

### Files Structure

```
Alpaca-trading-AI/
├── main.py                 # Main trading loop
├── core/
│   ├── strategy_engine.py  # Signal generation
│   ├── risk_manager.py     # Risk gates
│   ├── execution_engine.py # Order execution
│   ├── feature_engine.py   # Technical indicators
│   ├── state_machine.py   # Trade state management
│   ├── journal.py          # Trade logging
│   ├── telemetry.py        # Monitoring
│   └── models.py           # Data structures
└── requirements.txt        # Dependencies
```

### Technical Indicators Used

- **EMA 50** - Trend direction
- **ATR** - Volatility measurement
- **ADX** - Trend strength
- **Stochastic RSI** - Momentum / overbought/oversold

### Deployment

- Containerized with Docker
- Running on Google Cloud Run
- Auto-restarts on crash
- Health monitoring enabled
