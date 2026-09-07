"""
run_backtest.py

Entry point: pulls real historical data from Deriv, runs the MA crossover
strategy, and prints an honest performance report.

Usage examples:
    python run_backtest.py
    python run_backtest.py --symbol R_75 --granularity 300 --fast 10 --slow 30
    python run_backtest.py --symbol R_100 --granularity 60 --fast 5 --slow 20 --count 5000

Run this on a machine that has internet access to api.deriv.com
(this sandbox environment does not).
"""

import argparse
from deriv_client import fetch_candles_sync, SYMBOLS
from strategy import MACrossoverStrategy, StrategyConfig, resample_candles
from backtest import Backtester, BacktestConfig, print_report


def main():
    parser = argparse.ArgumentParser(description="Backtest an MA crossover strategy on Deriv data")
    parser.add_argument("--symbol", default="R_75", help="Deriv symbol, e.g. R_75, R_100 (see SYMBOLS in deriv_client.py)")
    parser.add_argument("--granularity", type=int, default=60, help="Candle size in seconds fetched from Deriv (60=1min)")
    parser.add_argument("--resample", default=None, help="Optional pandas resample rule, e.g. '5min','15min','1H'")
    parser.add_argument("--count", type=int, default=5000, help="Number of candles to fetch (Deriv max ~5000/request)")
    parser.add_argument("--fast", type=int, default=10, help="Fast MA period")
    parser.add_argument("--slow", type=int, default=30, help="Slow MA period")
    parser.add_argument("--ma-type", default="ema", choices=["ema", "sma"])
    parser.add_argument("--balance", type=float, default=1000.0, help="Starting balance for backtest")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="Risk per trade as % of balance")
    parser.add_argument("--cost-pct", type=float, default=0.05, help="Round-trip spread+slippage cost as %% of price")

    args = parser.parse_args()

    print(f"Fetching {args.count} candles for {args.symbol} @ {args.granularity}s granularity...")
    df = fetch_candles_sync(symbol=args.symbol, granularity_seconds=args.granularity, count=args.count)
    print(f"Got {len(df)} candles from {df.index[0]} to {df.index[-1]}\n")

    if args.resample:
        df = resample_candles(df, args.resample)
        print(f"Resampled to {args.resample}: {len(df)} candles\n")

    strategy = MACrossoverStrategy(StrategyConfig(
        fast_period=args.fast,
        slow_period=args.slow,
        ma_type=args.ma_type,
    ))
    signals = strategy.generate_signals(df)

    backtester = Backtester(BacktestConfig(
        initial_balance=args.balance,
        risk_per_trade_pct=args.risk_pct,
        cost_per_trade_pct=args.cost_pct,
    ))
    results = backtester.run(signals)
    print_report(results)


if __name__ == "__main__":
    main()
