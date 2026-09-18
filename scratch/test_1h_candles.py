import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import pandas as pd
from deriv_client import fetch_candles_sync
from strategy import MACrossoverStrategy, StrategyConfig

def test_1h_candles():
    print("Fetching 1h candles (granularity 3600)...")
    try:
        df_1h = fetch_candles_sync(symbol="R_75", granularity_seconds=3600, count=500)
        print(f"Fetched {len(df_1h)} 1-hour candles.")
        print(df_1h.tail())

        strategy = MACrossoverStrategy(StrategyConfig(fast_period=10, slow_period=30))
        signals = strategy.generate_signals(df_1h)
        
        buy_signals = signals[signals["signal"] == 1]
        sell_signals = signals[signals["signal"] == -1]
        
        print(f"Total Buy Signals: {len(buy_signals)}")
        print(f"Total Sell Signals: {len(sell_signals)}")
        if len(buy_signals) > 0:
            print("\nSample Buy signal row:")
            print(buy_signals[["open", "close", "fast_ma", "slow_ma", "signal"]].tail(2))
        if len(sell_signals) > 0:
            print("\nSample Sell signal row:")
            print(sell_signals[["open", "close", "fast_ma", "slow_ma", "signal"]].tail(2))

    except Exception as e:
        print("Error fetching 1h candles:", e)

if __name__ == "__main__":
    test_1h_candles()
