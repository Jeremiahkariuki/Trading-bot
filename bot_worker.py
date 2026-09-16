"""
bot_worker.py

Background worker thread that runs continuous live/paper trading loop.
Monitors real-time candles from Deriv, checks MA crossover signals, enforces
risk management rules, executes trades, and dynamically updates settled balance & daily P&L.
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


class TradingBotWorker:
    """
    Manages continuous background polling, signal evaluation, trade settlement,
    and real-time account balance / equity / daily P&L dynamic tracking.
    """

    def __init__(self, bot_state: Dict[str, Any], risk_mgr: RiskManager):
        self.bot_state = bot_state
        self.risk_mgr = risk_mgr
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_candle_timestamp = None
        self.last_net_error_log_time = 0
        self.bot_state["network_status"] = "ONLINE"
        self.bot_state["network_error_msg"] = ""
        self.client = DerivLiveClient(
            api_token=bot_state.get("api_token", ""),
            paper_mode=(bot_state.get("mode", "PAPER") == "PAPER"),
        )

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        print(f"[BotWorker] {entry}")
        logs = self.bot_state.setdefault("logs", [])
        logs.append(entry)
        if len(logs) > 100:
            self.bot_state["logs"] = logs[-100:]

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("Background Trading Worker STARTED.")

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self.log("Background Trading Worker STOPPING...")
            self._thread.join(timeout=3.0)
            self.log("Background Trading Worker STOPPED.")

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

                if latest_price and latest_price > 0 and entry_price > 0:
                    if contract_type == "CALL":
                        is_itm = latest_price > entry_price
                    else:
                        is_itm = latest_price < entry_price

                    if is_itm:
                        unrealized = round(stake * 0.95, 2)
                    else:
                        unrealized = round(-stake, 2)

                    t["current_price"] = latest_price
                    t["unrealized_pnl"] = unrealized
                else:
                    unrealized = t.get("unrealized_pnl", 0.0)

                # Check if trade duration expired
                if elapsed >= duration_sec:
                    if latest_price and latest_price > 0 and entry_price > 0:
                        if latest_price == entry_price:
                            outcome = "DRAW"
                            final_pnl = 0.0
                        elif (contract_type == "CALL" and latest_price > entry_price) or \
                             (contract_type == "PUT" and latest_price < entry_price):
                            outcome = "WON"
                            final_pnl = round(stake * 0.95, 2)
                        else:
                            outcome = "LOST"
                            final_pnl = round(-stake, 2)
                    else:
                        outcome = "WON" if (now.microsecond % 2 == 0) else "LOST"
                        final_pnl = round(stake * 0.95, 2) if outcome == "WON" else round(-stake, 2)

                    t["status"] = outcome
                    t["exit_price"] = latest_price or entry_price
                    t["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    t["pnl"] = final_pnl
                    t["unrealized_pnl"] = 0.0

                    # Update settled balance & win/loss stats
                    current_bal = self.bot_state.get("balance", 1000.0)
                    new_bal = round(current_bal + final_pnl, 2)
                    self.bot_state["balance"] = new_bal

                    if outcome == "WON":
                        self.bot_state["wins"] = self.bot_state.get("wins", 0) + 1
                    elif outcome == "LOST":
                        self.bot_state["losses"] = self.bot_state.get("losses", 0) + 1

                    self.risk_mgr.record_trade_close(final_pnl, new_bal)

                    pnl_sign = "+" if final_pnl >= 0 else ""
                    self.log(
                        f"Trade #{t['contract_id']} [{contract_type}] SETTLED -> {outcome}! "
                        f"Entry: {entry_price:.4f} | Exit: {t['exit_price']:.4f} | P&L: {pnl_sign}${final_pnl:.2f} | Balance: ${new_bal:,.2f}"
                    )
                else:
                    unrealized_sum += unrealized
                    open_count += 1

        self.bot_state["active_trades"] = open_count
        self.bot_state["unrealized_pnl"] = round(unrealized_sum, 2)
        bal = self.bot_state.get("balance", 1000.0)
        eq = round(bal + unrealized_sum, 2)
        self.bot_state["equity"] = eq
        initial = self.bot_state.get("initial_balance", 1000.0)
        dpnl = round(eq - initial, 2)
        self.bot_state["daily_pnl"] = dpnl
        self.bot_state["daily_pnl_pct"] = round((dpnl / initial) * 100, 2) if initial > 0 else 0.0

    def execute_manual_trade(self, direction: str = "CALL", stake: float = 10.0, duration_seconds: int = 60) -> Dict[str, Any]:
        """
        Executes a manual test trade instantly so the user can test floating P&L and dynamic balance updates.
        """
        symbol = self.bot_state.get("symbol", "R_75")
        df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=2)
        entry_price = float(df_base.iloc[-1].get("close", 1000.0)) if (df_base is not None and not df_base.empty) else 1000.0

        contract_id = f"DEMO_{int(time.time() * 1000)}"
        trade_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contract_id": contract_id,
            "symbol": symbol,
            "type": direction.upper(),
            "price": entry_price,
            "stake": stake,
            "duration_seconds": duration_seconds,
            "mode": self.bot_state.get("mode", "PAPER"),
            "status": "OPEN",
            "current_price": entry_price,
            "unrealized_pnl": 0.0,
        }

        live_trades = self.bot_state.setdefault("live_trades", [])
        live_trades.insert(0, trade_entry)
        self.log(f"Manual {direction} order placed on {symbol} @ {entry_price:.4f} (Stake: ${stake:.2f}, Duration: {duration_seconds}s). ID: {contract_id}")

        self.evaluate_open_trades(entry_price)
        return {
            "status": "success",
            "trade": trade_entry,
            "state": self.bot_state,
        }

    def _run_loop(self):
        self.client.paper_mode = (self.bot_state.get("mode", "PAPER") == "PAPER")
        self.client.api_token = self.bot_state.get("api_token", "")

        while not self._stop_event.is_set() and self.bot_state.get("running", False):
            try:
                symbol = self.bot_state.get("symbol", "R_75")
                timeframe = self.bot_state.get("timeframe", "5min")
                fast_ma = int(self.bot_state.get("fast_ma", 10))
                slow_ma = int(self.bot_state.get("slow_ma", 30))
                use_htf = bool(self.bot_state.get("use_htf", False))

                df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=300)
                self.bot_state["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if df_base is not None and not df_base.empty:
                    if self.bot_state.get("network_status") == "OFFLINE":
                        self.log("🟢 Internet Connection Restored! Reconnected to Deriv market feed.")
                    self.bot_state["network_status"] = "ONLINE"
                    self.bot_state["network_error_msg"] = ""

                    latest_price = float(df_base.iloc[-1].get("close", 0.0))

                    # 1. Monitor & settle active trades
                    self.evaluate_open_trades(latest_price)

                    # 2. Check strategy signals
                    df_tf = resample_candles(df_base, timeframe) if timeframe != "1min" else df_base

                    strategy = MACrossoverStrategy(StrategyConfig(
                        fast_period=fast_ma,
                        slow_period=slow_ma,
                        ma_type="ema",
                        use_htf_filter=use_htf,
                        htf_timeframe="15min" if timeframe in ["1min", "5min"] else "1h",
                    ))
                    signals = strategy.generate_signals(df_tf, base_df=df_base)

                    if not signals.empty:
                        latest_row = signals.iloc[-1]
                        current_candle_ts = latest_row.get("epoch", str(latest_row.name))
                        signal_val = latest_row.get("signal", 0)
                        price = float(latest_row.get("close", 0.0))

                        signal_text = "BUY (CALL)" if signal_val == 1 else ("SELL (PUT)" if signal_val == -1 else "HOLD")
                        self.bot_state["last_signal"] = signal_text

                        if current_candle_ts != self.last_candle_timestamp and signal_val in [1, -1]:
                            self.last_candle_timestamp = current_candle_ts

                            can_trade, reason = self.risk_mgr.can_open_trade(self.bot_state["balance"])
                            if not can_trade:
                                self.log(f"Signal {signal_text} ignored: {reason}")
                            else:
                                contract_type = "CALL" if signal_val == 1 else "PUT"
                                stake = round(self.bot_state["balance"] * 0.01, 2)
                                if stake < 1.0:
                                    stake = 1.0

                                self.log(f"Signal confirmed: {signal_text} on {symbol} @ {price:.4f}. Executing order (Stake: ${stake:.2f})...")

                                trade_result = asyncio.run(
                                    self.client.execute_trade(
                                        symbol=symbol,
                                        contract_type=contract_type,
                                        stake=stake,
                                        duration=5,
                                        duration_unit="m",
                                    )
                                )

                                live_trades = self.bot_state.setdefault("live_trades", [])
                                trade_entry = {
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "contract_id": trade_result.get("contract_id", "N/A"),
                                    "symbol": symbol,
                                    "type": contract_type,
                                    "price": price,
                                    "stake": stake,
                                    "duration_seconds": 120, # 2 minutes duration
                                    "mode": trade_result.get("mode", "PAPER"),
                                    "status": "OPEN",
                                    "current_price": price,
                                    "unrealized_pnl": 0.0,
                                }
                                live_trades.insert(0, trade_entry)
                                self.log(f"Order executed! Contract ID: {trade_entry['contract_id']}")
                                self.evaluate_open_trades(price)
                        else:
                            if int(time.time()) % 60 < 11:
                                self.log(f"Monitoring {symbol} ({timeframe}) | Signal: {signal_text} | Price: {price:.4f} | Equity: ${self.bot_state.get('equity', 1000):,.2f}")
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

            self._stop_event.wait(5.0) # Check every 5 seconds for smooth balance updating

