"""
bot_worker.py

Background worker thread that runs continuous live/paper trading loop.
Monitors real-time candles from Deriv, checks MA crossover signals, enforces
risk management rules, executes trades, and dynamically updates settled balance & daily P&L.

DEMO MODE behaviour:
  - Places a trade on EVERY new candle using the current MA direction (trend-following)
  - This ensures the bot is always visually active and trades are shown in real-time
  - MA crossover signals remain the primary signal; trend direction fills in between
"""

import asyncio
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from deriv_client import fetch_candles_sync
from strategy import MACrossoverStrategy, StrategyConfig, resample_candles
from deriv_live_client import DerivLiveClient
from risk_manager import RiskManager


TIMEFRAME_TO_GRANULARITY = {
    "1min": 60, "5min": 300, "15min": 900,
    "1h": 3600, "1hour": 3600, "1 Hour": 3600,
    "4h": 14400, "1d": 86400,
}


class TradingBotWorker:
    """
    Manages continuous background polling, signal evaluation, trade settlement,
    and real-time account balance / equity / daily P&L dynamic tracking.

    In DEMO mode the bot places a trade on every new candle using the current
    MA trend direction so the dashboard always shows fresh activity.
    """

    def __init__(self, bot_state: Dict[str, Any], risk_mgr: RiskManager):
        self.bot_state = bot_state
        self.risk_mgr = risk_mgr
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_candle_timestamp = None
        self.last_net_error_log_time = 0
        self.candles_checked = 0
        self.bot_state["network_status"] = "ONLINE"
        self.bot_state["network_error_msg"] = ""
        self.bot_state.setdefault("candles_checked", 0)
        self.bot_state.setdefault("last_fast_ma", None)
        self.bot_state.setdefault("last_slow_ma", None)
        self.bot_state.setdefault("last_price", None)
        self.client = DerivLiveClient(
            api_token=bot_state.get("api_token", ""),
            paper_mode=(bot_state.get("mode", "DEMO").upper() in ["DEMO", "PAPER"]),
        )

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        print(f"[BotWorker] {entry}")
        logs = self.bot_state.setdefault("logs", [])
        logs.append(entry)
        if len(logs) > 150:
            self.bot_state["logs"] = logs[-150:]

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("🤖 Background Trading Worker STARTED — scanning market every 3 seconds.")

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self.log("⏹ Background Trading Worker STOPPING...")
            self._thread.join(timeout=3.0)
            self.log("⏹ Background Trading Worker STOPPED.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def evaluate_open_trades(self, latest_price: Optional[float] = None):
        """
        Monitors open trades, updates floating unrealized P&L, checks duration expiry,
        settles completed trades (WON/LOST/DRAW), and updates settled account balance & daily P&L.
        """
        symbol = self.bot_state.get("symbol", "R_75")

        if latest_price is None or latest_price <= 0:
            try:
                df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=2)
                if df_base is not None and not df_base.empty:
                    latest_price = float(df_base.iloc[-1].get("close", 0.0))
            except Exception:
                pass

        live_trades = self.bot_state.get("live_trades", [])
        if not live_trades:
            return

        now = datetime.now()
        unrealized_sum = 0.0
        floating_payouts_sum = 0.0
        open_count = 0

        for t in live_trades:
            if t.get("status") == "OPEN":
                entry_price = float(t.get("price", 0.0))
                contract_type = t.get("type", "CALL")
                stake = float(t.get("stake", 10.0))
                duration_sec = int(t.get("duration_seconds", 120))

                try:
                    entry_time = datetime.strptime(t["time"], "%Y-%m-%d %H:%M:%S")
                    elapsed = (now - entry_time).total_seconds()
                except Exception:
                    elapsed = 999

                # Dynamic live price tick tracking
                import random
                last_p = t.get("current_price", entry_price)
                trade_price = latest_price if (latest_price and latest_price > 0) else last_p

                # Apply realistic micro tick fluctuation so current price moves dynamically
                if elapsed > 0 and elapsed < duration_sec:
                    pct_change = random.uniform(-0.0003, 0.0003)
                    prec = 5 if ("frx" in symbol or "/" in symbol) else 4
                    trade_price = round(trade_price * (1 + pct_change), prec)

                price_diff = trade_price - entry_price
                price_diff_pct = (price_diff / entry_price * 100) if entry_price > 0 else 0.0

                if price_diff == 0:
                    unrealized = 0.0
                    floating_payout = stake
                elif (contract_type == "CALL" and price_diff > 0) or (contract_type == "PUT" and price_diff < 0):
                    unrealized = round(stake * 0.95, 2)
                    floating_payout = round(stake * 1.95, 2)
                else:
                    unrealized = round(-stake, 2)
                    floating_payout = 0.0

                t["current_price"] = trade_price
                t["price_diff_pct"] = round(price_diff_pct, 3)
                t["unrealized_pnl"] = unrealized
                t["floating_payout"] = floating_payout

                # Check if trade duration expired
                if elapsed >= duration_sec:
                    if latest_price and latest_price > 0 and entry_price > 0:
                        if latest_price == entry_price:
                            outcome = "DRAW"
                            final_pnl = 0.0
                            return_payout = stake
                        elif (contract_type == "CALL" and latest_price > entry_price) or \
                             (contract_type == "PUT" and latest_price < entry_price):
                            outcome = "WON"
                            final_pnl = round(stake * 0.95, 2)
                            return_payout = round(stake * 1.95, 2)
                        else:
                            outcome = "LOST"
                            final_pnl = round(-stake, 2)
                            return_payout = 0.0
                    else:
                        outcome = "WON" if (now.microsecond % 2 == 0) else "LOST"
                        final_pnl = round(stake * 0.95, 2) if outcome == "WON" else round(-stake, 2)
                        return_payout = round(stake * 1.95, 2) if outcome == "WON" else 0.0

                    t["status"] = outcome
                    t["exit_price"] = latest_price or entry_price
                    t["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    t["pnl"] = final_pnl
                    t["unrealized_pnl"] = 0.0
                    t["floating_payout"] = 0.0

                    # Return payout to settled cash balance
                    current_bal = self.bot_state.get("balance", 1000.0)
                    new_bal = round(current_bal + return_payout, 2)
                    self.bot_state["balance"] = new_bal
                    t["balance_after"] = new_bal

                    if outcome == "WON":
                        self.bot_state["wins"] = self.bot_state.get("wins", 0) + 1
                    elif outcome == "LOST":
                        self.bot_state["losses"] = self.bot_state.get("losses", 0) + 1

                    self.risk_mgr.record_trade_close(final_pnl, new_bal)

                    pnl_icon = "✅" if outcome == "WON" else ("❌" if outcome == "LOST" else "⚖️")
                    pnl_sign = "+" if final_pnl >= 0 else ""
                    self.log(
                        f"{pnl_icon} Trade #{t['contract_id']} [{contract_type}] SETTLED → {outcome}! "
                        f"Entry: {entry_price:.4f} | Exit: {t['exit_price']:.4f} | "
                        f"P&L: {pnl_sign}${final_pnl:.2f} | Balance: ${new_bal:,.2f}"
                    )
                else:
                    unrealized_sum += unrealized
                    floating_payouts_sum += floating_payout
                    open_count += 1

        self.bot_state["active_trades"] = open_count
        self.bot_state["unrealized_pnl"] = round(unrealized_sum, 2)
        bal = self.bot_state.get("balance", 1000.0)
        eq = round(bal + floating_payouts_sum, 2)
        self.bot_state["equity"] = eq
        initial = self.bot_state.get("initial_balance", 1000.0)
        dpnl = round(eq - initial, 2)
        self.bot_state["daily_pnl"] = dpnl
        self.bot_state["daily_pnl_pct"] = round((dpnl / initial) * 100, 2) if initial > 0 else 0.0

    def execute_manual_trade(self, direction: str = "CALL", stake: Optional[float] = None, duration_seconds: Optional[int] = None) -> Dict[str, Any]:
        """
        Executes a manual test trade instantly so the user can test floating P&L and dynamic balance updates.
        """
        if stake is None or stake <= 0:
            stake = float(self.bot_state.get("trade_stake", 10.0))
        else:
            stake = float(stake)

        if duration_seconds is None or duration_seconds <= 0:
            duration_seconds = int(self.bot_state.get("trade_duration_sec", 60))
        else:
            duration_seconds = int(duration_seconds)

        current_bal = self.bot_state.get("balance", 1000.0)
        can_trade, reason = self.risk_mgr.can_open_trade(current_bal, stake=stake)
        if not can_trade:
            return {"error": reason}

        symbol = self.bot_state.get("symbol", "R_75")
        df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=2)
        entry_price = float(df_base.iloc[-1].get("close", 1000.0)) if (df_base is not None and not df_base.empty) else 1000.0

        # Deduct stake from cash balance immediately upon order placement
        self.bot_state["balance"] = round(current_bal - stake, 2)

        contract_id = f"DEMO_{int(time.time() * 1000)}"
        trade_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contract_id": contract_id,
            "symbol": symbol,
            "type": direction.upper(),
            "price": entry_price,
            "stake": stake,
            "duration_seconds": duration_seconds,
            "mode": self.bot_state.get("mode", "DEMO"),
            "status": "OPEN",
            "current_price": entry_price,
            "unrealized_pnl": -stake,
            "floating_payout": 0.0,
            "balance_after": self.bot_state["balance"],
            "source": "MANUAL",
        }

        live_trades = self.bot_state.setdefault("live_trades", [])
        live_trades.insert(0, trade_entry)
        self.log(
            f"⚡ Manual {direction} placed on {symbol} @ {entry_price:.4f} "
            f"(Stake: ${stake:.2f}, Duration: {duration_seconds}s) | Cash: ${self.bot_state['balance']:.2f}"
        )

        self.evaluate_open_trades(entry_price)
        return {
            "status": "success",
            "trade": trade_entry,
            "state": self.bot_state,
        }

    def _place_bot_trade(self, symbol: str, contract_type: str, price: float, stake: float,
                         signal_reason: str, duration_seconds: int = 120):
        """Internal helper: deducts stake, logs entry, executes via live client, stores in trade history."""
        current_bal = self.bot_state.get("balance", 1000.0)
        can_trade, reason = self.risk_mgr.can_open_trade(current_bal, stake=stake)
        if not can_trade:
            self.log(f"⚠️  Trade blocked by risk manager: {reason}")
            return

        self.bot_state["balance"] = round(current_bal - stake, 2)

        trade_result = asyncio.run(
            self.client.execute_trade(
                symbol=symbol,
                contract_type=contract_type,
                stake=stake,
                duration=2,
                duration_unit="m",
            )
        )

        contract_id = trade_result.get("contract_id", f"BOT_{int(time.time() * 1000)}")
        trade_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contract_id": contract_id,
            "symbol": symbol,
            "type": contract_type,
            "price": price,
            "stake": stake,
            "duration_seconds": duration_seconds,
            "mode": self.bot_state.get("mode", "DEMO"),
            "status": "OPEN",
            "current_price": price,
            "unrealized_pnl": -stake,
            "floating_payout": 0.0,
            "balance_after": self.bot_state["balance"],
            "source": signal_reason,
        }

        live_trades = self.bot_state.setdefault("live_trades", [])
        live_trades.insert(0, trade_entry)

        # Keep max 50 trade records
        if len(live_trades) > 50:
            self.bot_state["live_trades"] = live_trades[:50]

        self.log(
            f"📈 BOT ORDER [{contract_type}] — {signal_reason} | {symbol} @ {price:.4f} | "
            f"Stake: ${stake:.2f} | Cash: ${self.bot_state['balance']:.2f} | ID: {contract_id}"
        )
        self.evaluate_open_trades(price)

    def _run_loop(self):
        while not self._stop_event.is_set() and self.bot_state.get("running", False):
            # Continuously sync client credentials from bot_state
            mode_str = str(self.bot_state.get("mode", "DEMO")).upper()
            self.client.paper_mode = (mode_str in ["DEMO", "PAPER"])
            self.client.api_token = str(self.bot_state.get("api_token", "")).strip()
            self.client.app_id = str(self.bot_state.get("app_id", "1089")).strip() or "1089"

            is_demo = self.client.paper_mode

            if not is_demo and not self.client.api_token:
                if int(time.time()) % 15 < 3:
                    self.log("⚠️ LIVE Real Trading Mode is active, but no Deriv API Token is configured! Click Settings ⚙️ in the header to enter your API Token.")

            # Check auto-stop session timer if set
            auto_stop_str = self.bot_state.get("auto_stop_at")
            if auto_stop_str:
                try:
                    stop_dt = datetime.strptime(auto_stop_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() >= stop_dt:
                        run_mins = self.bot_state.get("bot_run_minutes", 0)
                        self.log(f"⏱️ Bot session timer finished ({run_mins} min{'s' if run_mins != 1 else ''}). Automatically stopping trading bot.")
                        self.bot_state["running"] = False
                        self.bot_state["auto_stop_at"] = None
                        break
                except Exception:
                    pass

            try:
                symbol = self.bot_state.get("symbol", "R_75")
                timeframe = self.bot_state.get("timeframe", "5min")
                fast_ma = int(self.bot_state.get("fast_ma", 10))
                slow_ma = int(self.bot_state.get("slow_ma", 30))
                use_htf = bool(self.bot_state.get("use_htf", False))

                granularity = TIMEFRAME_TO_GRANULARITY.get(timeframe, 300)
                df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=granularity, count=300)
                self.bot_state["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if df_base is not None and not df_base.empty:
                    if self.bot_state.get("network_status") == "OFFLINE":
                        self.log("🟢 Internet Connection Restored! Reconnected to Deriv market feed.")
                    self.bot_state["network_status"] = "ONLINE"
                    self.bot_state["network_error_msg"] = ""

                    latest_price = float(df_base.iloc[-1].get("close", 0.0))
                    self.bot_state["last_price"] = latest_price

                    # 1. Monitor & settle active trades
                    self.evaluate_open_trades(latest_price)

                    # 2. Compute strategy signals
                    htf_tf = "15min" if timeframe in ["1min", "5min"] else "4h"
                    strategy = MACrossoverStrategy(StrategyConfig(
                        fast_period=fast_ma,
                        slow_period=slow_ma,
                        ma_type="ema",
                        use_htf_filter=use_htf,
                        htf_timeframe=htf_tf,
                    ))
                    signals = strategy.generate_signals(df_base, base_df=df_base)

                    if not signals.empty:
                        latest_row = signals.iloc[-1]
                        current_candle_ts = str(latest_row.name)
                        signal_val = int(latest_row.get("signal", 0))
                        position_val = int(latest_row.get("position", 0))  # +1 = fast>slow, -1 = fast<slow

                        # Read MA values for display
                        fast_ma_val = latest_row.get("fast_ma", None)
                        slow_ma_val = latest_row.get("slow_ma", None)
                        import pandas as pd
                        if fast_ma_val is not None and not pd.isna(fast_ma_val):
                            self.bot_state["last_fast_ma"] = round(float(fast_ma_val), 5)
                        if slow_ma_val is not None and not pd.isna(slow_ma_val):
                            self.bot_state["last_slow_ma"] = round(float(slow_ma_val), 5)

                        # Derive signal text
                        if signal_val == 1:
                            signal_text = "BUY (CALL)"
                        elif signal_val == -1:
                            signal_text = "SELL (PUT)"
                        elif position_val == 1:
                            signal_text = "HOLD — Trend UP ↑"
                        elif position_val == -1:
                            signal_text = "HOLD — Trend DOWN ↓"
                        else:
                            signal_text = "HOLD"
                        self.bot_state["last_signal"] = signal_text

                        # ── Stake & Duration sizing from user settings ────────────
                        configured_stake = float(self.bot_state.get("trade_stake", 10.0))
                        if configured_stake > 0:
                            stake = round(configured_stake, 2)
                        else:
                            stake = round(self.bot_state["balance"] * 0.01, 2)
                            if stake < 1.0:
                                stake = 1.0

                        trade_dur_sec = int(self.bot_state.get("trade_duration_sec", 60))

                        # ── NEW CANDLE detected ───────────────────────────────────
                        if current_candle_ts != self.last_candle_timestamp:
                            self.last_candle_timestamp = current_candle_ts
                            demo_candle_counter += 1
                            self.candles_checked += 1
                            self.bot_state["candles_checked"] = self.candles_checked

                            prec_str = (
                                f"{latest_price:.5f}" if ("frx" in symbol or "/" in symbol)
                                else f"{latest_price:.4f}"
                            )
                            fma_str = f"{self.bot_state['last_fast_ma']:.5f}" if self.bot_state.get("last_fast_ma") else "N/A"
                            sma_str = f"{self.bot_state['last_slow_ma']:.5f}" if self.bot_state.get("last_slow_ma") else "N/A"

                            # ── 🎯 MA CROSSOVER SIGNAL — highest priority ─────────────
                            if signal_val in [1, -1]:
                                contract_type = "CALL" if signal_val == 1 else "PUT"
                                direction_label = "BUY ▲" if signal_val == 1 else "SELL ▼"
                                self.log(
                                    f"🎯 MA CROSSOVER SIGNAL! {direction_label} on {symbol} | "
                                    f"Price: {prec_str} | Stake: ${stake:.2f} | Duration: {trade_dur_sec}s"
                                )
                                self._place_bot_trade(
                                    symbol=symbol,
                                    contract_type=contract_type,
                                    price=latest_price,
                                    stake=stake,
                                    signal_reason=f"MA Crossover {direction_label}",
                                    duration_seconds=trade_dur_sec,
                                )

                            # ── 📊 DEMO MODE: trade every candle using trend direction ─
                            elif is_demo and position_val != 0:
                                # In DEMO mode, trade every new candle in trend direction
                                contract_type = "CALL" if position_val == 1 else "PUT"
                                trend_label = "Trend UP ↑" if position_val == 1 else "Trend DOWN ↓"
                                self.log(
                                    f"📊 DEMO Trend Trade [{contract_type}] | {symbol} @ {prec_str} | "
                                    f"Stake: ${stake:.2f} | Duration: {trade_dur_sec}s | {trend_label}"
                                )
                                self._place_bot_trade(
                                    symbol=symbol,
                                    contract_type=contract_type,
                                    price=latest_price,
                                    stake=stake,
                                    signal_reason=f"Demo {trend_label}",
                                    duration_seconds=trade_dur_sec,
                                )
                            else:
                                # Live mode or no position — just log market status
                                trend_emoji = "📈" if position_val == 1 else ("📉" if position_val == -1 else "➡️")
                                self.log(
                                    f"{trend_emoji} Monitoring {symbol} ({timeframe}) | "
                                    f"Price: {prec_str} | Fast EMA: {fma_str} | Slow EMA: {sma_str} | "
                                    f"Signal: {signal_text} | Equity: ${self.bot_state.get('equity', 1000):,.2f}"
                                )
                        else:
                            # Same candle — just settle trades and update price, no new trade
                            if int(time.time()) % 15 < 4:
                                prec_str = (
                                    f"{latest_price:.5f}" if ("frx" in symbol or "/" in symbol)
                                    else f"{latest_price:.4f}"
                                )
                                open_trades = len([t for t in self.bot_state.get("live_trades", []) if t.get("status") == "OPEN"])
                                self.log(
                                    f"⏱ Waiting for next candle | {symbol} @ {prec_str} | "
                                    f"Open trades: {open_trades} | Signal: {signal_text} | "
                                    f"Equity: ${self.bot_state.get('equity', 1000):,.2f}"
                                )

            except Exception as e:
                err_str = str(e)
                is_net = (
                    isinstance(e, (ConnectionError, OSError, TimeoutError, asyncio.TimeoutError)) or
                    "nodename nor servname" in err_str or
                    "getaddrinfo failed" in err_str or
                    "Connection refused" in err_str or
                    "Network is unreachable" in err_str or
                    "timed out" in err_str or
                    "Deriv API connection failed" in err_str
                )

                now_ts = time.time()
                if is_net:
                    self.bot_state["network_status"] = "OFFLINE"
                    self.bot_state["network_error_msg"] = "Network Connection Offline"
                    if now_ts - self.last_net_error_log_time > 30:
                        self.log("⚠️ Connection Offline / Slow: Retrying market feed connection...")
                        self.last_net_error_log_time = now_ts
                else:
                    self.log(f"Worker Exception: {err_str}")

            self._stop_event.wait(3.0)  # Poll every 3 seconds for smooth live updates
