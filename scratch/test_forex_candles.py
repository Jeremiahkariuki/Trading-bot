import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import pandas as pd
from deriv_client import fetch_candles_sync, SYMBOLS
from strategy import MACrossoverStrategy, StrategyConfig

def test_forex_candles():
    print("Testing Forex Currency Pairs...")
    forex_symbols = [v for k, v in SYMBOLS.items() if "frx" in v]
    print("Forex Symbols:", forex_symbols)

    for sym in forex_symbols:
        try:
            print(f"\n--- Fetching {sym} ---")
            df = fetch_candles_sync(symbol=sym, granularity_seconds=60, count=300)
            print(f"Fetched {len(df)} candles for {sym}.")
            print(df.tail(2))
            
            strategy = MACrossoverStrategy(StrategyConfig(fast_period=10, slow_period=30))
            signals = strategy.generate_signals(df)
            buy_count = (signals["signal"] == 1).sum()
            sell_count = (signals["signal"] == -1).sum()
            print(f"Signals for {sym}: Buy={buy_count}, Sell={sell_count}")
        except Exception as e:
            print(f"Error fetching {sym}: {e}")

if __name__ == "__main__":
    test_forex_candles()
