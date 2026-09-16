"""
risk_manager.py

Risk management engine & safety kill-switches for live and paper trading.

Protects account capital by enforcing:
  - Max daily loss limit (auto-halts trading for the rest of the day)
  - Max concurrent open positions limit
  - ATR-based Stop Loss (SL) and Take Profit (TP) target calculation
  - Fixed-fractional risk position sizing per trade
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Tuple, Dict, Any


@dataclass
class RiskConfig:
    max_daily_loss_pct: float = 3.0       # Auto-halt trading if daily loss hits 3%
    max_concurrent_trades: int = 2        # Maximum parallel open positions
    max_account_risk_pct: float = 1.0     # Maximum % of account balance risked per trade
    atr_period: int = 14                  # ATR period for volatility calculation
    atr_sl_multiplier: float = 1.5        # Stop Loss = entry +/- (1.5 * ATR)
    atr_tp_multiplier: float = 3.0        # Take Profit = entry +/- (3.0 * ATR) -> 2:1 R:R


class RiskManager:
    def __init__(self, config: RiskConfig = None, initial_balance: float = 1000.0):
        self.config = config or RiskConfig()
        self.initial_balance = initial_balance
        self.daily_start_balance = initial_balance
        self.current_day: date = datetime.utcnow().date()
        self.daily_pnl_usd: float = 0.0
        self.active_trades_count: int = 0
        self.trading_halted: bool = False
        self.halt_reason: str = ""

    def _update_day(self, current_balance: float):
        """Resets daily P&L tracker at midnight UTC."""
        today = datetime.utcnow().date()
        if today != self.current_day:
            self.current_day = today
            self.daily_start_balance = current_balance
            self.daily_pnl_usd = 0.0
            self.trading_halted = False
            self.halt_reason = ""

    def can_open_trade(self, current_balance: float, stake: float = 10.0) -> Tuple[bool, str]:
        """
        Evaluates whether a new trade is permitted under safety risk rules.
        """
        self._update_day(current_balance)

        # 0. Enforce positive balance and sufficient stake
        if current_balance <= 0:
            return False, f"Balance is low (${current_balance:.2f}). Click 'Reset $1,000' on the left to add demo funds!"
        if current_balance < stake:
            return False, f"Balance too low (${current_balance:.2f}) for a ${stake:.2f} trade. Click 'Reset $1,000' to continue!"

        if self.trading_halted:
            return False, f"{self.halt_reason}. Click 'Reset $1,000' on the left to continue trading!"

        # 1. Check Max Daily Loss Limit
        max_loss_usd = self.daily_start_balance * (self.config.max_daily_loss_pct / 100.0)
        if self.daily_pnl_usd <= -max_loss_usd:
            self.trading_halted = True
            self.halt_reason = f"Daily loss limit reached (-${abs(self.daily_pnl_usd):.2f})"
            return False, f"{self.halt_reason}. Click 'Reset $1,000' on the left to continue trading!"

        # 2. Check Max Concurrent Positions
        if self.active_trades_count >= self.config.max_concurrent_trades:
            return False, f"Max concurrent trades limit reached ({self.active_trades_count}/{self.config.max_concurrent_trades})"

        return True, "Trade permitted"

    def calculate_levels_and_stake(
        self, entry_price: float, atr_value: float, balance: float, direction: int
    ) -> Dict[str, Any]:
        """
        Calculates ATR-based Stop Loss, Take Profit, and risk-adjusted position stake.

        direction: 1 for Long, -1 for Short
        """
        sl_distance = atr_value * self.config.atr_sl_multiplier
        tp_distance = atr_value * self.config.atr_tp_multiplier

        if direction == 1:
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        risk_amount = balance * (self.config.max_account_risk_pct / 100.0)
        stake = round(risk_amount, 2)

        return {
            "entry_price": entry_price,
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "risk_amount": risk_amount,
            "stake": stake,
            "direction": "BUY" if direction == 1 else "SELL",
        }

    def record_trade_open(self):
        """Increments active trades count."""
        self.active_trades_count += 1

    def record_trade_close(self, pnl_usd: float, current_balance: float):
        """
        Updates daily P&L and checks for safety halt.
        """
        self.active_trades_count = max(0, self.active_trades_count - 1)
        self.daily_pnl_usd += pnl_usd

        self.can_open_trade(current_balance)
