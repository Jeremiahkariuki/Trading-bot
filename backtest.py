"""
backtest.py

Turns strategy signals into simulated trades and computes the metrics that
actually matter for judging a trading bot - NOT just win rate.

Reports:
  - total trades
  - win rate
  - average win / average loss
  - profit factor (gross profit / gross loss)
  - max drawdown (%)
  - net P&L (in price units and %)

Includes basic transaction cost modelling (spread + slippage) because a
strategy that looks great with zero costs can lose money once real costs
are included - this is the single most common way beginners fool themselves
in backtests.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class BacktestConfig:
    initial_balance: float = 1000.0
    risk_per_trade_pct: float = 1.0     # % of balance risked per trade
    cost_per_trade_pct: float = 0.05    # spread + slippage, as % of price (round trip)
    allow_short: bool = True


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int          # 1 = long, -1 = short
    entry_price: float
    exit_price: float
    pnl_pct: float          # return on this trade, as a % (after costs)
    balance_after: float


class Backtester:
    def __init__(
        self,
        config: BacktestConfig = None,
        initial_capital: float = None,
        initial_balance: float = None,
        cost_pct: float = None,
        cost_per_trade_pct: float = None,
    ):
        if config is not None:
            self.config = config
        else:
            init_bal = (
                initial_balance
                if initial_balance is not None
                else (initial_capital if initial_capital is not None else 1000.0)
            )

            c_pct = cost_per_trade_pct if cost_per_trade_pct is not None else cost_pct
            if c_pct is not None and c_pct < 0.01:
                # Convert decimal (e.g. 0.0005) to percentage (0.05)
                c_pct = c_pct * 100.0
            elif c_pct is None:
                c_pct = 0.05

            self.config = BacktestConfig(
                initial_balance=init_bal,
                cost_per_trade_pct=c_pct,
            )

    def run(self, signals_df: pd.DataFrame) -> dict:
        """
        signals_df: output of MACrossoverStrategy.generate_signals()
                    must contain columns: close, position, signal

        Trade logic:
          - We enter/flip position on the bar where `signal` != 0.
          - We hold until the opposite signal fires (fully invested, one
            position at a time - simplest possible model for a first version).
          - Position sizing is fixed-fractional risk (risk_per_trade_pct),
            not "bet the whole balance" - real risk management, not gambling.
        """
        cfg = self.config
        balance = cfg.initial_balance
        equity_curve = [balance]
        equity_times = [signals_df.index[0]]

        trades: list[Trade] = []
        open_trade = None  # dict: direction, entry_time, entry_price

        cost_frac = cfg.cost_per_trade_pct / 100.0
        risk_frac = cfg.risk_per_trade_pct / 100.0

        for ts, row in signals_df.iterrows():
            sig = row["signal"]
            price = row["close"]

            if pd.isna(price):
                continue

            # Close existing trade if an opposite (or any) new signal fires
            if open_trade is not None and sig != 0 and sig != open_trade["direction"]:
                direction = open_trade["direction"]
                entry_price = open_trade["entry_price"]

                raw_return = (price - entry_price) / entry_price * direction
                net_return = raw_return - cost_frac  # round-trip cost

                # fixed-fractional sizing: we only put risk_frac of balance at stake
                pnl_amount = balance * risk_frac * net_return
                balance += pnl_amount

                trades.append(Trade(
                    entry_time=open_trade["entry_time"],
                    exit_time=ts,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=net_return * 100,
                    balance_after=balance,
                ))
                open_trade = None

            # Open a new trade on a fresh signal
            if sig != 0 and open_trade is None:
                if sig == -1 and not cfg.allow_short:
                    pass
                else:
                    open_trade = {
                        "direction": int(sig),
                        "entry_time": ts,
                        "entry_price": price,
                    }

            equity_curve.append(balance)
            equity_times.append(ts)

        return self._compute_metrics(trades, equity_curve, equity_times, cfg.initial_balance)

    def _compute_metrics(self, trades, equity_curve, equity_times, initial_balance) -> dict:
        n = len(trades)
        equity = pd.Series(equity_curve, index=equity_times)

        if n == 0:
            return {
                "total_trades": 0,
                "message": "No trades were generated - try different MA periods, "
                           "a different timeframe, or check you have enough data.",
                "equity_curve": equity,
            }

        pnl_pcts = np.array([t.pnl_pct for t in trades])
        wins = pnl_pcts[pnl_pcts > 0]
        losses = pnl_pcts[pnl_pcts <= 0]

        win_rate = len(wins) / n * 100
        avg_win = wins.mean() if len(wins) else 0.0
        avg_loss = losses.mean() if len(losses) else 0.0

        gross_profit = wins.sum() if len(wins) else 0.0
        gross_loss = abs(losses.sum()) if len(losses) else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        # Max drawdown from the equity curve
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max * 100
        max_drawdown = drawdown.min()

        final_balance = equity.iloc[-1]
        net_pnl_pct = (final_balance - initial_balance) / initial_balance * 100

        return {
            "total_trades": n,
            "win_rate_pct": round(win_rate, 2),
            "avg_win_pct": round(avg_win, 3),
            "avg_loss_pct": round(avg_loss, 3),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(max_drawdown, 2),
            "initial_balance": initial_balance,
            "final_balance": round(final_balance, 2),
            "net_pnl_pct": round(net_pnl_pct, 2),
            "trades": trades,
            "equity_curve": equity,
        }

    def print_report(self, results: dict):
        print_report(results)


def print_report(results: dict):
    if results.get("total_trades", 0) == 0:
        print(results.get("message", "No trades."))
        return

    print("=" * 45)
    print("BACKTEST REPORT")
    print("=" * 45)
    print(f"Total trades       : {results['total_trades']}")
    print(f"Win rate            : {results['win_rate_pct']}%")
    print(f"Avg win / avg loss  : {results['avg_win_pct']}% / {results['avg_loss_pct']}%")
    print(f"Profit factor       : {results['profit_factor']}")
    print(f"Max drawdown        : {results['max_drawdown_pct']}%")
    print(f"Initial balance     : ${results['initial_balance']:,.2f}")
    print(f"Final balance       : ${results['final_balance']:,.2f}")
    print(f"Net P&L             : {results['net_pnl_pct']}%")
    print("=" * 45)
    if isinstance(results["profit_factor"], (int, float)) and results["profit_factor"] < 1.3:
        print("Note: profit factor below ~1.3 is generally too thin to survive")
        print("real-world costs and slippage reliably. Treat this as a starting")
        print("point to refine, not a finished product.")


# Backward-compatible alias
BacktestEngine = Backtester
