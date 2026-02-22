# Alpaca Trading AI

A sophisticated AI-powered trading bot for cryptocurrency trading on Alpaca Exchange, featuring advanced features like backtesting, risk management, and real-time execution.

## Features

- **AI-Powered Trading**: Leverages machine learning models for trading decisions
- **Backtesting Framework**: Comprehensive backtesting capabilities with multiple strategies
- **Risk Management**: Built-in risk controls to protect capital
- **Real-time Execution**: Seamless integration with Alpaca Exchange API
- **Trade Journaling**: Detailed logging and tracking of all trades
- **Telemetry & Monitoring**: Performance tracking and system monitoring
- **Multi-Timeframe Analysis**: Support for different timeframes (15min, hourly)

## Project Structure

```
.
├── core/
│   ├── execution_engine.py    # Core execution logic for trading
│   ├── feature_engine.py      # Feature engineering for trading signals
│   ├── journal.py             # Trade journaling system
│   ├── logger.py              # Logging configuration
│   ├── models.py              # Data models and structures
│   ├── risk_manager.py        # Risk management rules
│   ├── state_machine.py       # Trading state management
│   ├── strategy_engine.py     # Strategy execution engine
│   └── telemetry.py           # Performance telemetry
├── main.py                    # Main entry point
├── setup_venv.py              # Virtual environment setup script
├── requirements.txt           # Python dependencies
├── connection_test.py         # API connection testing
├── day7_backtest.py           # Day 7 backtesting script
├── day8_backtest.py           # Day 8 backtesting script
├── day9_backtest.py           # Day 9 backtesting script
├── day10_stress_test.py       # Stress testing script
├── day11_production.py        # Production trading script
├── day12_management.py        # Portfolio management script
├── day13_protection.py        # Protection mechanisms script
├── verification_flow.py       # Verification and validation flow
├── btc_usd_15min.csv          # 15-minute BTC/USD data
├── btc_usd_hourly.csv         # Hourly BTC/USD data
└── trade_journal.csv          # Trade journal data
```

## Prerequisites

- Python 3.8 or higher
- Alpaca API account (https://alpaca.markets)
- API keys (API Key ID and Secret Key)

## Installation

1. Clone the repository:

```bash
git clone https://github.com/Teganmosi/Alpaca-trading-AI.git
cd Alpaca-trading-AI
```

2. Set up virtual environment:

```bash
python setup_venv.py
```

3. Activate virtual environment:

```bash
# On Windows
venv\Scripts\activate

# On macOS/Linux
source venv/bin/activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

1. Copy the example environment file:

```bash
copy .env.example .env
```

2. Edit `.env` with your Alpaca API credentials:

```
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
ALPACA_BASE_URL=https://api.alpaca.markets
```

3. Configure trading parameters in the respective scripts (main.py, day11_production.py, etc.)

## Usage

### Backtesting

Run backtesting scripts to test trading strategies:

```bash
python day7_backtest.py
python day8_backtest.py
python day9_backtest.py
```

### Production Trading

Run the production trading bot:

```bash
python main.py
```

### Connection Test

Test your Alpaca API connection:

```bash
python connection_test.py
```

### Portfolio Management

Manage your portfolio:

```bash
python day12_management.py
```

## API Reference

### Core Components

- **Execution Engine**: Handles trade execution and order management
- **Feature Engine**: Processes market data and generates trading signals
- **Risk Manager**: Implements risk control measures
- **Strategy Engine**: Executes trading strategies
- **Journal**: Tracks and logs all trades

### Backtesting Scripts

- **day7_backtest.py**: Initial backtesting framework
- **day8_backtest.py**: Enhanced backtesting with additional metrics
- **day9_backtest.py**: Advanced backtesting with optimization

### Production Scripts

- **day11_production.py**: Main production trading bot
- **day12_management.py**: Portfolio management tools
- **day13_protection.py**: Protection mechanisms and safeguards

## Performance Metrics

The system tracks:

- Win rate
- Total profit/loss
- Sharpe ratio
- Maximum drawdown
- Trade frequency
- Average trade duration

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License.

## Disclaimer

**Trading involves significant risk. This software is for educational purposes only. Use at your own risk. The authors are not responsible for any financial losses incurred.**

## Support

For issues and questions:

- Create an issue on GitHub
- Contact the repository owner

## Acknowledgments

- Alpaca Markets for providing the trading API
- Open source trading community for inspiration and tools
