"""
bot_worker.py

Background worker thread that runs continuous live/paper trading loop.
Monitors real-time candles from Deriv, checks MA crossover signals, enforces
risk management rules, and executes trades via DerivLiveClient.
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
    Manages continuous background polling, signal evaluation, and order execution.
    """

    def __init__(self, bot_state: Dict[str, Any], risk_mgr: RiskManager):
        self.bot_state = bot_state
        self.risk_mgr = risk_mgr
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_candle_timestamp = None
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
                                    "mode": trade_result.get("mode", "PAPER"),
                                    "status": "OPEN",
                                }
                                live_trades.insert(0, trade_entry)
                                self.bot_state["active_trades"] = len([t for t in live_trades if t.get("status") == "OPEN"])
                                self.log(f"Order executed! Contract ID: {trade_entry['contract_id']}")
                        else:
                            if int(time.time()) % 60 < 11:
                                self.log(f"Monitoring {symbol} ({timeframe}) | Signal: {signal_text} | Price: {price:.4f}")
            except Exception as e:
                self.log(f"Worker Loop Error: {str(e)}")

            self._stop_event.wait(10.0)
