import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import pandas as pd
from deriv_client import fetch_candles_sync, SYMBOLS
from strategy import MACrossoverStrategy, StrategyConfig

def test_forex_signal_regularity():
    print("==================================================")
    print("VERIFYING FOREX CURRENCY PAIRS SIGNAL REGULARITY")
    print("==================================================")
    forex_symbols = [v for k, v in SYMBOLS.items() if "frx" in v]
    timeframes = ["1min", "5min", "15min", "1h"]
    granularity_map = {"1min": 60, "5min": 300, "15min": 900, "1h": 3600}

    for sym in forex_symbols:
        print(f"\n>>> SYMBOL: {sym}")
        for tf in timeframes:
            g = granularity_map[tf]
            try:
                df = fetch_candles_sync(symbol=sym, granularity_seconds=g, count=500)
                strategy = MACrossoverStrategy(StrategyConfig(fast_period=10, slow_period=30))
                signals = strategy.generate_signals(df)
                
                buy_signals = signals[signals["signal"] == 1]
                sell_signals = signals[signals["signal"] == -1]
                
                print(f"  [{tf.upper():5s}] Candles: {len(df):3d} | Buys: {len(buy_signals):2d} | Sells: {len(sell_signals):2d} | Total Signals: {len(buy_signals)+len(sell_signals):2d}")
                if len(buy_signals) > 0:
                    latest_buy_ts = buy_signals.index[-1]
                    print(f"         Latest BUY  Entry: {latest_buy_ts} @ price {buy_signals.iloc[-1]['close']:.5f}")
                if len(sell_signals) > 0:
                    latest_sell_ts = sell_signals.index[-1]
                    print(f"         Latest SELL Entry: {latest_sell_ts} @ price {sell_signals.iloc[-1]['close']:.5f}")
            except Exception as e:
                print(f"  [{tf.upper():5s}] Error: {e}")

if __name__ == "__main__":
    test_forex_signal_regularity()
