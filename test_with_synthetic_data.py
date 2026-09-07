"""
Sanity-check the strategy + backtest engine using synthetic (fake) price data.

We don't have network access to Deriv's API in this sandbox, so this proves
the LOGIC is correct before we wire in real market data. Run this yourself
locally too - if the numbers look sane here, you can trust the engine.
"""

import numpy as np
import pandas as pd
from strategy import MACrossoverStrategy, StrategyConfig, resample_candles
from backtest import Backtester, BacktestConfig, print_report

np.random.seed(42)

# --- Build a fake 1-minute OHLC price series (random walk + slight upward drift) ---
n_minutes = 60 * 24 * 30  # 30 days of 1-min candles
minutes = pd.date_range("2026-01-01", periods=n_minutes, freq="1min")
returns = np.random.normal(loc=0.00002, scale=0.0015, size=n_minutes)
close = 100 * np.exp(np.cumsum(returns))

df = pd.DataFrame({
    "open": close,
    "high": close * (1 + np.random.uniform(0, 0.001, n_minutes)),
    "low": close * (1 - np.random.uniform(0, 0.001, n_minutes)),
    "close": close,
}, index=minutes)

print(f"Generated {len(df)} synthetic 1-min candles.\n")

# --- Resample to a 5-minute timeframe (proving "configurable timeframe" works) ---
df_5min = resample_candles(df, "5min")
print(f"Resampled to {len(df_5min)} 5-min candles.\n")

# --- Run the MA crossover strategy ---
strategy = MACrossoverStrategy(StrategyConfig(fast_period=10, slow_period=30, ma_type="ema"))
signals = strategy.generate_signals(df_5min)

print("Signal counts:")
print(signals["signal"].value_counts())
print()

# --- Backtest it ---
backtester = Backtester(BacktestConfig(
    initial_balance=1000,
    risk_per_trade_pct=1.0,
    cost_per_trade_pct=0.05,
))
results = backtester.run(signals)
print_report(results)
