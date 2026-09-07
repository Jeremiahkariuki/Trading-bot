"""
optimize.py

Automated parameter grid optimizer to sweep symbols, timeframes, and MA periods
on historical Deriv candle data to discover strategies with Profit Factor > 1.3.
"""

import argparse
import sys
from itertools import product
import pandas as pd

from deriv_client import fetch_candles_sync, SYMBOLS
from strategy import MACrossoverStrategy, StrategyConfig, resample_candles
from backtest import Backtester, BacktestConfig


def run_grid_search(
    symbols: list,
    timeframes: list,
    fast_periods: list,
    slow_periods: list,
    use_htf: bool = False,
    count: int = 5000,
) -> pd.DataFrame:
    results = []

    for symbol in symbols:
        print(f"\n[Data Pull] Fetching {count} base candles for '{symbol}'...")
        try:
            df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=count)
        except Exception as e:
            print(f"Failed to fetch data for {symbol}: {e}")
            continue

        for tf in timeframes:
            if tf != "1min":
                df_tf = resample_candles(df_base, tf)
            else:
                df_tf = df_base

            for fast, slow in product(fast_periods, slow_periods):
                if fast >= slow:
                    continue

                config = StrategyConfig(
                    fast_period=fast,
                    slow_period=slow,
                    ma_type="ema",
                    use_htf_filter=use_htf,
                    htf_timeframe="15min" if tf in ["1min", "5min"] else "1h",
                )
                strategy = MACrossoverStrategy(config)
                signals = strategy.generate_signals(df_tf, base_df=df_base)

                backtester = Backtester(BacktestConfig(
                    initial_balance=1000.0,
                    risk_per_trade_pct=1.0,
                    cost_per_trade_pct=0.05,
                ))
                metrics = backtester.run(signals)

                if metrics["total_trades"] > 0:
                    pf = metrics["profit_factor"]
                    pf_val = float(pf) if isinstance(pf, (int, float)) and pf != float("inf") else (999.0 if pf == float("inf") or pf == "inf" else 0.0)

                    results.append({
                        "symbol": symbol,
                        "timeframe": tf,
                        "fast_ma": fast,
                        "slow_ma": slow,
                        "use_htf": use_htf,
                        "total_trades": metrics["total_trades"],
                        "win_rate_pct": metrics["win_rate_pct"],
                        "profit_factor": pf_val,
                        "max_drawdown_pct": metrics["max_drawdown_pct"],
                        "net_pnl_pct": metrics["net_pnl_pct"],
                        "final_balance": metrics["final_balance"],
                    })

    res_df = pd.DataFrame(results)
    if not res_df.empty:
        res_df.sort_values(by="profit_factor", ascending=False, inplace=True)
    return res_df


def main():
    parser = argparse.ArgumentParser(description="Deriv MA Crossover Strategy Grid Search Optimizer")
    parser.add_argument("--symbols", nargs="+", default=["R_75", "R_100", "R_10"], help="Symbols to test")
    parser.add_argument("--timeframes", nargs="+", default=["5min", "15min"], help="Timeframes to test")
    parser.add_argument("--count", type=int, default=3000, help="Candle count per request")
    parser.add_argument("--mtf", action="store_true", help="Enable Multi-Timeframe Confirmation filter")

    args = parser.parse_args()

    fast_periods = [5, 10, 15]
    slow_periods = [20, 30, 50]

    print("=========================================================")
    print("      DERIV STRATEGY PARAMETER OPTIMIZATION SWEEP       ")
    print("=========================================================")
    print(f"Symbols      : {args.symbols}")
    print(f"Timeframes   : {args.timeframes}")
    print(f"MTF Filter   : {args.mtf}")

    df_results = run_grid_search(
        symbols=args.symbols,
        timeframes=args.timeframes,
        fast_periods=fast_periods,
        slow_periods=slow_periods,
        use_htf=args.mtf,
        count=args.count,
    )

    if df_results.empty:
        print("No valid results found.")
        return

    csv_path = "optimization_results.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\nSaved full grid search results to '{csv_path}'.")

    # Filter top performing configurations (Profit factor >= 1.3)
    top_performers = df_results[df_results["profit_factor"] >= 1.3]

    print("\n" + "=" * 65)
    print("          TOP PERFORMING STRATEGIES (Profit Factor >= 1.3)     ")
    print("=" * 65)
    if top_performers.empty:
        print("No parameter combinations met the strict Profit Factor >= 1.3 bar.")
        print("Top 5 overall configurations:")
        print(df_results.head(5)[["symbol", "timeframe", "fast_ma", "slow_ma", "total_trades", "win_rate_pct", "profit_factor", "net_pnl_pct"]].to_string(index=False))
    else:
        print(top_performers[["symbol", "timeframe", "fast_ma", "slow_ma", "total_trades", "win_rate_pct", "profit_factor", "max_drawdown_pct", "net_pnl_pct"]].to_string(index=False))
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
