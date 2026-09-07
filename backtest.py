"""
Backtest engine for simulating strategy performance and calculating metrics.
"""

from typing import Dict, List, Any
import pandas as pd
import numpy as np


class BacktestEngine:
    """
    Simulates trade execution from signals and computes performance metrics.
    """

    def __init__(self, initial_capital: float = 10000.0, cost_pct: float = 0.0005):
        """
        :param initial_capital: Starting portfolio balance (USD)
        :param cost_pct: Transaction cost per trade as a decimal (e.g. 0.0005 = 0.05%)
        """
        self.initial_capital = initial_capital
        self.cost_pct = cost_pct

    def run(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Runs backtest simulation on DataFrame containing 'signal', 'close', and 'open'.
        Returns dictionary containing trade details, equity curve, and summarized metrics.
        """
        if "signal" not in df.columns or "close" not in df.columns:
            raise ValueError("DataFrame must contain 'signal' and 'close' columns.")

        use_next_open = "open" in df.columns
        trades: List[Dict[str, Any]] = []
        position = 0  # 1 = Long, -1 = Short, 0 = Flat
        entry_price = 0.0
        entry_time = None
        entry_idx = 0

        capital = self.initial_capital
        equity_curve = [capital]

        # Iterate through candles
        for i in range(len(df) - 1):
            curr_row = df.iloc[i]
            next_row = df.iloc[i + 1]
            signal = curr_row["signal"]

            # Execution price for potential new trade entering on next bar open
            exec_price = next_row["open"] if use_next_open else curr_row["close"]
            exec_time = next_row.get("datetime", i + 1) if use_next_open else curr_row.get("datetime", i)

            # Signal 1: Buy / Go Long
            if signal == 1:
                # If currently short, close short first
                if position == -1:
                    pnl_pct = (entry_price - exec_price) / entry_price - (2 * self.cost_pct)
                    trade_pnl = capital * pnl_pct
                    capital += trade_pnl
                    trades.append({
                        "type": "SHORT",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": exec_time,
                        "exit_price": exec_price,
                        "pnl_pct": pnl_pct,
                        "pnl_usd": trade_pnl,
                    })
                    position = 0

                # Open long if flat
                if position == 0:
                    position = 1
                    entry_price = exec_price
                    entry_time = exec_time
                    entry_idx = i

            # Signal -1: Sell / Go Short / Exit
            elif signal == -1:
                # If currently long, close long
                if position == 1:
                    pnl_pct = (exec_price - entry_price) / entry_price - (2 * self.cost_pct)
                    trade_pnl = capital * pnl_pct
                    capital += trade_pnl
                    trades.append({
                        "type": "LONG",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": exec_time,
                        "exit_price": exec_price,
                        "pnl_pct": pnl_pct,
                        "pnl_usd": trade_pnl,
                    })
                    position = 0

                # Open short if flat
                if position == 0:
                    position = -1
                    entry_price = exec_price
                    entry_time = exec_time
                    entry_idx = i

            equity_curve.append(capital)

        # Close open position at end of data if any
        if position != 0:
            last_row = df.iloc[-1]
            exit_price = last_row["close"]
            exit_time = last_row.get("datetime", len(df) - 1)
            if position == 1:
                pnl_pct = (exit_price - entry_price) / entry_price - (2 * self.cost_pct)
            else:
                pnl_pct = (entry_price - exit_price) / entry_price - (2 * self.cost_pct)
            trade_pnl = capital * pnl_pct
            capital += trade_pnl
            trades.append({
                "type": "LONG" if position == 1 else "SHORT",
                "entry_time": entry_time,
                "entry_price": entry_price,
                "exit_time": exit_time,
                "exit_price": exit_price,
                "pnl_pct": pnl_pct,
                "pnl_usd": trade_pnl,
            })

        metrics = self._calculate_metrics(trades, equity_curve)
        metrics["trades"] = trades
        metrics["equity_curve"] = equity_curve

        return metrics

    def _calculate_metrics(self, trades: List[Dict[str, Any]], equity_curve: List[float]) -> Dict[str, Any]:
        """
        Calculates key trading performance metrics.
        """
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "net_pnl_pct": 0.0,
                "final_balance": self.initial_capital,
            }

        pnl_pcts = [t["pnl_pct"] for t in trades]
        winning_trades = [p for p in pnl_pcts if p > 0]
        losing_trades = [p for p in pnl_pcts if p < 0]

        win_rate_pct = (len(winning_trades) / total_trades) * 100.0
        avg_win_pct = np.mean(winning_trades) * 100.0 if winning_trades else 0.0
        avg_loss_pct = np.mean(losing_trades) * 100.0 if losing_trades else 0.0

        gross_profit = sum(winning_trades)
        gross_loss = abs(sum(losing_trades))

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # Maximum Drawdown calculation
        eq = np.array(equity_curve)
        peaks = np.maximum.accumulate(eq)
        drawdowns = (eq - peaks) / peaks
        max_drawdown_pct = np.min(drawdowns) * 100.0

        final_balance = equity_curve[-1]
        net_pnl_pct = ((final_balance - self.initial_capital) / self.initial_capital) * 100.0

        return {
            "total_trades": total_trades,
            "win_rate_pct": win_rate_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "net_pnl_pct": net_pnl_pct,
            "final_balance": final_balance,
        }

    def print_report(self, metrics: Dict[str, Any]):
        """
        Prints formatted backtest summary matching the specification in README.
        """
        pf_str = (
            f"{metrics['profit_factor']:.2f}"
            if metrics["profit_factor"] != float("inf")
            else "INF"
        )
        print("\n" + "=" * 45)
        print("         BACKTEST PERFORMANCE REPORT         ")
        print("=" * 45)
        print(f"Total trades       : {metrics['total_trades']}")
        print(f"Win rate           : {metrics['win_rate_pct']:.2f}%")
        print(
            f"Avg win / avg loss : {metrics['avg_win_pct']:.3f}% / {metrics['avg_loss_pct']:.3f}%"
        )
        print(f"Profit factor      : {pf_str}")
        print(f"Max drawdown       : {metrics['max_drawdown_pct']:.2f}%")
        print(f"Net P&L            : {metrics['net_pnl_pct']:.2f}%")
        print(f"Final balance      : ${metrics['final_balance']:,.2f}")
        print("=" * 45 + "\n")
