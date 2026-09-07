"""
Offline validation test script using synthetic OHLC data.
Validates strategy calculation, resampling, and backtest engine without internet connection.
"""

import sys
import numpy as np
import pandas as pd

from strategy import MACrossoverStrategy, resample_candles
from backtest import BacktestEngine


def generate_synthetic_candles(num_candles: int = 1500) -> pd.DataFrame:
    """
    Generates realistic synthetic OHLC candles with trend & cycles
    to trigger moving average crossover events.
    """
    np.random.seed(42)
    start_epoch = 1700000000

    epochs = [start_epoch + i * 60 for i in range(num_candles)]

    # Generate synthetic price path with wave cycles + drift + noise
    t = np.linspace(0, 8 * np.pi, num_candles)
    trend = 1000.0 + (t * 5.0) + (np.sin(t) * 25.0) + (np.cos(t * 0.5) * 15.0)
    noise = np.random.normal(0, 1.5, num_candles)
    close_prices = trend + noise

    data = []
    for i in range(num_candles):
        close_p = float(close_prices[i])
        open_p = float(close_prices[i - 1] if i > 0 else close_p - 0.5)
        high_p = max(open_p, close_p) + abs(float(np.random.normal(0.8, 0.3)))
        low_p = min(open_p, close_p) - abs(float(np.random.normal(0.8, 0.3)))

        data.append({
            "epoch": epochs[i],
            "datetime": pd.to_datetime(epochs[i], unit="s"),
            "open": round(open_p, 4),
            "high": round(high_p, 4),
            "low": round(low_p, 4),
            "close": round(close_p, 4),
        })

    return pd.DataFrame(data)


def main():
    print("=== Deriv MA Crossover Bot: Offline Synthetic Data Test ===")
    print("Generating 1,500 synthetic 60s candles...")
    df_raw = generate_synthetic_candles(1500)
    print(f"Generated {len(df_raw)} 60s base candles.")

    # 1. Test Candle Resampling
    print("\n[Step 1] Resampling 60s candles to 5min timeframe...")
    df_5m = resample_candles(df_raw, "5min")
    print(f"Resampled to {len(df_5m)} 5-minute candles.")
    assert len(df_5m) > 0, "Resampling produced empty DataFrame"

    # 2. Test Strategy Signal Generation
    print("\n[Step 2] Calculating indicators & crossover signals (Fast=10, Slow=30)...")
    strategy = MACrossoverStrategy(fast_period=10, slow_period=30, ma_type="ema")
    df_signals = strategy.generate_signals(df_5m)

    buy_signals = (df_signals["signal"] == 1).sum()
    sell_signals = (df_signals["signal"] == -1).sum()
    print(f"Generated {buy_signals} BUY signals and {sell_signals} SELL signals.")

    # 3. Test Backtest Engine
    print("\n[Step 3] Running backtest simulation with 0.05% cost per trade...")
    engine = BacktestEngine(initial_capital=10000.0, cost_pct=0.0005)
    results = engine.run(df_signals)

    # Sanity checks
    assert "total_trades" in results
    assert "win_rate_pct" in results
    assert "profit_factor" in results
    assert "max_drawdown_pct" in results
    assert "net_pnl_pct" in results

    print("\n[SUCCESS] Engine pipeline sanity check passed.")
    engine.print_report(results)


if __name__ == "__main__":
    main()
