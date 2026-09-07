"""
CLI entry point to fetch real historical data from Deriv API, run MA Crossover strategy,
and print performance report.
"""

import argparse
import sys
from deriv_client import DerivClient
from strategy import MACrossoverStrategy, resample_candles
from backtest import BacktestEngine


def main():
    parser = argparse.ArgumentParser(
        description="Deriv MA Crossover Strategy Backtester"
    )
    parser.add_argument(
        "--symbol", type=str, default="R_75", help="Deriv symbol (default: R_75)"
    )
    parser.add_argument(
        "--granularity",
        type=int,
        default=60,
        help="Base candle granularity in seconds (default: 60)",
    )
    parser.add_argument(
        "--resample",
        type=str,
        default="5min",
        help="Timeframe to resample base candles to (e.g. 5min, 15min, 1H)",
    )
    parser.add_argument(
        "--fast", type=int, default=10, help="Fast MA period (default: 10)"
    )
    parser.add_argument(
        "--slow", type=int, default=30, help="Slow MA period (default: 30)"
    )
    parser.add_argument(
        "--ma-type",
        type=str,
        default="ema",
        choices=["sma", "ema"],
        help="Type of moving average: 'sma' or 'ema' (default: ema)",
    )
    parser.add_argument(
        "--cost-pct",
        type=float,
        default=0.0005,
        help="Transaction cost per trade as decimal (default: 0.0005 = 0.05%%)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5000,
        help="Number of base candles to fetch (default: 5000)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital balance (default: 10000.0)",
    )

    args = parser.parse_args()

    print(f"Fetching {args.count} historical candles for symbol '{args.symbol}' (granularity: {args.granularity}s)...")
    try:
        client = DerivClient()
        df_base = client.fetch_historical_candles(
            symbol=args.symbol, granularity=args.granularity, count=args.count
        )
        print(f"Successfully fetched {len(df_base)} candles from Deriv API.")
    except Exception as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        sys.exit(1)

    # Timeframe resampling (Option B)
    if args.resample and args.resample.lower() != "none":
        print(f"Resampling candles to timeframe: {args.resample}...")
        df_candles = resample_candles(df_base, args.resample)
        print(f"Resampled to {len(df_candles)} {args.resample} candles.")
    else:
        df_candles = df_base

    # Generate strategy signals
    print(f"Running strategy ({args.ma_type.upper()} fast={args.fast}, slow={args.slow})...")
    strategy = MACrossoverStrategy(
        fast_period=args.fast, slow_period=args.slow, ma_type=args.ma_type
    )
    df_signals = strategy.generate_signals(df_candles)

    # Run backtest simulation
    print("Simulating trades...")
    engine = BacktestEngine(initial_capital=args.capital, cost_pct=args.cost_pct)
    results = engine.run(df_signals)

    # Print report
    engine.print_report(results)


if __name__ == "__main__":
    main()
