# Deriv MA Crossover Trading Bot

A fully functional, modular algorithmic trading bot for [Deriv Synthetic Indices](https://deriv.com) — built in Python with a Django web dashboard, live/paper trading support, multi-timeframe signal confirmation, and a parameter optimization engine.

---

## Features

| Feature | Description |
|---|---|
| **Strategy Engine** | MA Crossover (EMA/SMA) with configurable fast/slow periods |
| **Multi-Timeframe Filter** | Higher timeframe trend confirmation to filter false signals |
| **Backtest Engine** | Bar-by-bar simulation with honest P&L, drawdown, and profit factor metrics |
| **Cost Modelling** | Realistic spread + slippage cost modelling built in |
| **Parameter Optimizer** | Automated grid search across symbols, timeframes, and MA periods |
| **Paper Trading** | Safe live execution simulation with no real funds required |
| **Live Trading** | Authenticated Deriv WebSocket API order execution |
| **Risk Manager** | Max daily loss kill-switch, max concurrent trades cap, ATR stop-loss sizing |
| **Django Dashboard** | Web UI for Start/Stop, configuration, backtest chart, and trade log |
| **Docker** | One-command containerized deployment |

---

## Quick Start

### Option 1: Auto Setup
```bash
bash setup.sh
python3 manage.py runserver 8008
```
Open: [http://127.0.0.1:8008](http://127.0.0.1:8008)

### Option 2: Manual
```bash
pip3 install -r requirements.txt
python3 test_with_synthetic_data.py    # verify engine works offline
python3 run_backtest.py --symbol R_75 --granularity 60 --resample 5min --fast 10 --slow 30
```

### Option 3: Docker
```bash
docker-compose up --build
```
Open: [http://127.0.0.1:8008](http://127.0.0.1:8008)

---

## Configuration

All CLI scripts accept arguments. Common options:

| Argument | Default | Description |
|---|---|---|
| `--symbol` | `R_75` | Deriv symbol (R_10, R_25, R_50, R_75, R_100, 1HZ75V, 1HZ100V) |
| `--granularity` | `60` | Base candle size in seconds |
| `--resample` | `5min` | Target timeframe (5min, 15min, 1h) |
| `--fast` | `10` | Fast MA period |
| `--slow` | `30` | Slow MA period |
| `--ma-type` | `ema` | Moving average type: `ema` or `sma` |
| `--cost-pct` | `0.05` | Round-trip cost as % (spread + slippage) |

---

## Parameter Optimization

Run the optimizer to find consistently profitable parameter combinations:

```bash
python3 optimize.py --symbols R_75 R_100 R_10 --timeframes 5min 15min --mtf
```

Look for configurations with **Profit Factor ≥ 1.3** across multiple symbols.
Results are saved to `optimization_results.csv`.

---

## Understanding the Performance Report

```
Total trades       : 296
Win rate            : 27.36%
Avg win / avg loss  : 2.441% / -0.834%
Profit factor       : 1.1
Max drawdown        : -0.23%
Net P&L             : 0.18%
```

- **Win rate is NOT the target metric.** A 27% win rate can still be profitable if wins are larger than losses.
- **Profit factor** (gross profit ÷ gross loss) is what matters. Aim for > 1.3 consistently.
- **Max drawdown** tells you the worst losing streak your account would experience — critical for real trading.

---

## Project Structure

| File | Purpose |
|---|---|
| `indicators.py` | SMA, EMA, ATR calculations |
| `strategy.py` | MA Crossover logic + multi-timeframe confirmation + candle resampling |
| `backtest.py` | Backtest simulation engine with realistic cost modelling |
| `deriv_client.py` | Deriv public API — historical candle fetcher (no auth required) |
| `deriv_live_client.py` | Deriv authenticated client — live and paper order execution |
| `risk_manager.py` | Safety kill-switches, ATR stop-loss sizing, daily loss limits |
| `optimize.py` | Automated multi-symbol parameter grid optimizer |
| `run_backtest.py` | CLI entry point for single backtest run |
| `test_with_synthetic_data.py` | Offline engine validation without internet |
| `dashboard_settings.py` | Django settings |
| `dashboard_views.py` | Dashboard views and REST API endpoints |
| `dashboard_urls.py` | URL routing |
| `manage.py` | Django management script |
| `templates/dashboard.html` | Dark-mode web dashboard UI |
| `Dockerfile` | Docker build configuration |
| `docker-compose.yml` | Docker Compose deployment file |
| `setup.sh` | One-click setup script |

---

## Supported Symbols

| Symbol | Index |
|---|---|
| R_10 | Volatility 10 Index |
| R_25 | Volatility 25 Index |
| R_50 | Volatility 50 Index |
| R_75 | Volatility 75 Index |
| R_100 | Volatility 100 Index |
| 1HZ75V | Volatility 75 (1s) |
| 1HZ100V | Volatility 100 (1s) |

---

## Disclaimer

See [DISCLAIMER.md](DISCLAIMER.md) for full legal terms.

This software is provided for **educational and research purposes only**. Trading synthetic indices carries significant financial risk. Past backtested performance does not guarantee future results.
