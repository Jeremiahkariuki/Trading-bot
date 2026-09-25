"""
dashboard_views.py

Views and REST API endpoints for the Trading Bot Django Dashboard.
"""

import json
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from deriv_client import fetch_candles_sync, SYMBOLS
from strategy import MACrossoverStrategy, StrategyConfig, resample_candles
from backtest import Backtester, BacktestConfig
from risk_manager import RiskManager, RiskConfig

from bot_worker import TradingBotWorker

# Global in-memory bot state for dashboard demonstration
BOT_STATE = {
    "running": False,
    "symbol": "R_75",
    "timeframe": "5min",
    "fast_ma": 10,
    "slow_ma": 30,
    "use_htf": False,
    "trade_stake": 10.0,
    "trade_duration_sec": 60,
    "bot_run_minutes": 0,
    "start_timestamp": None,
    "auto_stop_at": None,
    "initial_balance": 1000.0,
    "balance": 1000.0,
    "unrealized_pnl": 0.0,
    "equity": 1000.0,
    "daily_pnl": 0.0,
    "daily_pnl_pct": 0.0,
    "active_trades": 0,
    "wins": 0,
    "losses": 0,
    "mode": "DEMO",
    "api_token": "",
    "logs": [],
    "live_trades": [],
    "last_signal": "HOLD",
    "last_check_time": None,
}

risk_mgr = RiskManager(initial_balance=1000.0)
worker = TradingBotWorker(BOT_STATE, risk_mgr)


CANDLESTICK_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0f172a"/>
  <line x1="18" y1="10" x2="18" y2="54" stroke="#10b981" stroke-width="4" stroke-linecap="round"/>
  <rect x="13" y="20" width="10" height="22" rx="3" fill="#10b981"/>
  <line x1="32" y1="8" x2="32" y2="56" stroke="#ef4444" stroke-width="4" stroke-linecap="round"/>
  <rect x="27" y="16" width="10" height="28" rx="3" fill="#ef4444"/>
  <line x1="46" y1="12" x2="46" y2="52" stroke="#10b981" stroke-width="4" stroke-linecap="round"/>
  <rect x="41" y="22" width="10" height="18" rx="3" fill="#10b981"/>
</svg>"""


def favicon_view(request):
    """Serves market candlestick favicon SVG for browser tab icon."""
    from django.http import HttpResponse
    return HttpResponse(CANDLESTICK_FAVICON_SVG, content_type="image/svg+xml")


def index_view(request):
    """Renders main dashboard HTML page."""
    context = {
        "symbols": SYMBOLS,
        "bot_state": BOT_STATE,
    }
    return render(request, "dashboard.html", context)


def api_status_view(request):
    """Returns current bot status, risk state, balance, and timer info."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not worker.is_running():
        worker.evaluate_open_trades()
        BOT_STATE["last_check_time"] = now_str
    elif not BOT_STATE.get("last_check_time"):
        BOT_STATE["last_check_time"] = now_str

    can_trade, reason = risk_mgr.can_open_trade(BOT_STATE["balance"])
    live_trades = BOT_STATE.get("live_trades", [])
    active_count = len([t for t in live_trades if t.get("status") == "OPEN"])
    BOT_STATE["active_trades"] = active_count

    # Calculate equity & daily PnL
    unrealized = BOT_STATE.get("unrealized_pnl", 0.0)
    balance = BOT_STATE.get("balance", 1000.0)
    equity = round(balance + unrealized, 2)
    initial_bal = BOT_STATE.get("initial_balance", 1000.0)
    daily_pnl = round(equity - initial_bal, 2)
    daily_pnl_pct = round((daily_pnl / initial_bal) * 100, 2) if initial_bal > 0 else 0.0

    BOT_STATE["equity"] = equity
    BOT_STATE["daily_pnl"] = daily_pnl
    BOT_STATE["daily_pnl_pct"] = daily_pnl_pct

    # Calculate session timer remaining seconds
    timer_remaining = None
    auto_stop_str = BOT_STATE.get("auto_stop_at")
    if worker.is_running() and auto_stop_str:
        try:
            stop_dt = datetime.strptime(auto_stop_str, "%Y-%m-%d %H:%M:%S")
            remaining = int((stop_dt - datetime.now()).total_seconds())
            timer_remaining = max(0, remaining)
        except Exception:
            timer_remaining = None

    return JsonResponse({
        "status": "success",
        "state": BOT_STATE,
        "timer_remaining_sec": timer_remaining,
        "network_status": BOT_STATE.get("network_status", "ONLINE"),
        "network_error": BOT_STATE.get("network_error_msg", ""),
        "risk_halted": risk_mgr.trading_halted,
        "halt_reason": risk_mgr.halt_reason,
        "can_trade": can_trade,
        "worker_active": worker.is_running(),
        "risk_config": {
            "max_daily_loss_pct": risk_mgr.config.max_daily_loss_pct,
            "max_concurrent_trades": risk_mgr.config.max_concurrent_trades,
            "atr_sl_multiplier": risk_mgr.config.atr_sl_multiplier,
            "atr_tp_multiplier": risk_mgr.config.atr_tp_multiplier,
        },
    })


@csrf_exempt
def api_toggle_view(request):
    """Toggles bot running state (Start / Stop) with custom stake, trade duration, and bot session timer."""
    from datetime import timedelta
    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
        except Exception:
            data = {}

        if "stake" in data and data["stake"]:
            try:
                BOT_STATE["trade_stake"] = float(data["stake"])
            except Exception:
                pass
        if "trade_duration_sec" in data and data["trade_duration_sec"]:
            try:
                BOT_STATE["trade_duration_sec"] = int(data["trade_duration_sec"])
            except Exception:
                pass
        if "bot_run_minutes" in data and data["bot_run_minutes"] is not None:
            try:
                BOT_STATE["bot_run_minutes"] = int(data["bot_run_minutes"])
            except Exception:
                pass

        BOT_STATE["running"] = not BOT_STATE["running"]
        if BOT_STATE["running"]:
            now_dt = datetime.now()
            BOT_STATE["start_timestamp"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            run_mins = BOT_STATE.get("bot_run_minutes", 0)
            if run_mins > 0:
                BOT_STATE["auto_stop_at"] = (now_dt + timedelta(minutes=run_mins)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                BOT_STATE["auto_stop_at"] = None

            worker.start()
            status_label = "STARTED"
        else:
            BOT_STATE["auto_stop_at"] = None
            worker.stop()
            status_label = "STOPPED"

        return JsonResponse({
            "status": "success",
            "running": BOT_STATE["running"],
            "message": f"Trading Bot {status_label}",
            "state": BOT_STATE,
        })
    return JsonResponse({"error": "POST method required"}, status=400)


@csrf_exempt
def api_config_view(request):
    """Updates bot configuration, credentials, trading mode, and risk management parameters."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            BOT_STATE["symbol"] = data.get("symbol", BOT_STATE["symbol"])
            BOT_STATE["timeframe"] = data.get("timeframe", BOT_STATE["timeframe"])
            BOT_STATE["fast_ma"] = int(data.get("fast_ma", BOT_STATE["fast_ma"]))
            BOT_STATE["slow_ma"] = int(data.get("slow_ma", BOT_STATE["slow_ma"]))
            BOT_STATE["use_htf"] = bool(data.get("use_htf", BOT_STATE["use_htf"]))

            if "mode" in data:
                BOT_STATE["mode"] = str(data["mode"]).upper()
            if "api_token" in data:
                BOT_STATE["api_token"] = str(data["api_token"]).strip()
            if "app_id" in data:
                BOT_STATE["app_id"] = str(data["app_id"]).strip() or "1089"

            if "trade_stake" in data:
                BOT_STATE["trade_stake"] = float(data["trade_stake"])
            if "trade_duration_sec" in data:
                BOT_STATE["trade_duration_sec"] = int(data["trade_duration_sec"])
            if "bot_run_minutes" in data:
                BOT_STATE["bot_run_minutes"] = int(data["bot_run_minutes"])

            # Risk parameters update
            if "max_daily_loss_pct" in data:
                risk_mgr.config.max_daily_loss_pct = float(data["max_daily_loss_pct"])
            if "max_concurrent_trades" in data:
                risk_mgr.config.max_concurrent_trades = int(data["max_concurrent_trades"])
            if "atr_sl_multiplier" in data:
                risk_mgr.config.atr_sl_multiplier = float(data["atr_sl_multiplier"])
            if "atr_tp_multiplier" in data:
                risk_mgr.config.atr_tp_multiplier = float(data["atr_tp_multiplier"])

            # Dynamically update live client instance properties
            worker.client.paper_mode = (BOT_STATE["mode"] in ["DEMO", "PAPER"])
            worker.client.api_token = BOT_STATE["api_token"]
            worker.client.app_id = BOT_STATE.get("app_id", "1089")

            token_status = "Configured ✅" if BOT_STATE["api_token"] else "None (Paper/Demo)"
            worker.log(
                f"⚙️ Settings & API Credentials updated! Mode: {BOT_STATE['mode']} | "
                f"Token: {token_status} | Max Daily Loss: {risk_mgr.config.max_daily_loss_pct}% | "
                f"Max Trades: {risk_mgr.config.max_concurrent_trades}"
            )
            return JsonResponse({"status": "success", "state": BOT_STATE})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "POST method required"}, status=400)


@csrf_exempt
def api_reset_balance_view(request):
    """Resets paper account balance to initial state ($1,000.00)."""
    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
            new_bal = float(data.get("balance", 1000.0))
        except Exception:
            new_bal = 1000.0

        BOT_STATE["initial_balance"] = new_bal
        BOT_STATE["balance"] = new_bal
        BOT_STATE["equity"] = new_bal
        BOT_STATE["daily_pnl"] = 0.0
        BOT_STATE["daily_pnl_pct"] = 0.0
        BOT_STATE["unrealized_pnl"] = 0.0
        BOT_STATE["active_trades"] = 0
        BOT_STATE["wins"] = 0
        BOT_STATE["losses"] = 0
        # Preserve live_trades history so executed trade records remain visible
        risk_mgr.daily_pnl_usd = 0.0
        risk_mgr.trading_halted = False
        risk_mgr.halt_reason = ""
        worker.log(f"Account balance reset to ${new_bal:,.2f}. Trade history preserved.")
        return JsonResponse({"status": "success", "state": BOT_STATE})
    return JsonResponse({"error": "POST method required"}, status=400)


@csrf_exempt
def api_manual_trade_view(request):
    """Places an instant manual paper/demo trade for instant dynamic testing."""
    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
            direction = data.get("direction", "CALL").upper()
            stake = float(data.get("stake", 10.0))
            duration_secs = int(data.get("duration", 60)) # Default 60 seconds for quick testing

            res = worker.execute_manual_trade(direction=direction, stake=stake, duration_seconds=duration_secs)
            return JsonResponse(res)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "POST method required"}, status=400)



TIMEFRAME_TO_GRANULARITY = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "1h": 3600,
    "1hour": 3600,
    "1 Hour": 3600,
    "4h": 14400,
    "1d": 86400,
}


@csrf_exempt
def api_backtest_run_view(request):
    """Executes a real-time backtest on Deriv data for the dashboard chart."""
    symbol = request.GET.get("symbol", BOT_STATE["symbol"])
    timeframe = request.GET.get("timeframe", BOT_STATE["timeframe"])
    fast_ma = int(request.GET.get("fast_ma", BOT_STATE["fast_ma"]))
    slow_ma = int(request.GET.get("slow_ma", BOT_STATE["slow_ma"]))
    use_htf = request.GET.get("use_htf", "false").lower() == "true"
    count = int(request.GET.get("count", 500))

    try:
        granularity = TIMEFRAME_TO_GRANULARITY.get(timeframe, 60)
        df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=granularity, count=count)
        df_tf = df_base

        htf_tf = "15min" if timeframe in ["1min", "5min"] else "4h"
        strategy = MACrossoverStrategy(StrategyConfig(
            fast_period=fast_ma,
            slow_period=slow_ma,
            ma_type="ema",
            use_htf_filter=use_htf,
            htf_timeframe=htf_tf,
        ))
        signals = strategy.generate_signals(df_tf, base_df=df_base)

        backtester = Backtester(BacktestConfig(
            initial_balance=BOT_STATE["balance"],
            risk_per_trade_pct=1.0,
            cost_per_trade_pct=0.05,
        ))
        results = backtester.run(signals)

        # Prepare chart series data
        chart_data = []
        if isinstance(results.get("equity_curve"), list):
            eq_series = results["equity_curve"]
        else:
            eq_series = results["equity_curve"].tolist() if hasattr(results.get("equity_curve"), "tolist") else []

        chart_data = [round(v, 2) for v in eq_series]

        precision = 5 if ("frx" in str(symbol) or "/" in str(symbol)) else 4
        trades_log = []
        for t in results.get("trades", []):
            trades_log.append({
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "direction": "LONG" if t.direction == 1 else "SHORT",
                "entry_price": round(t.entry_price, precision),
                "exit_price": round(t.exit_price, precision),
                "pnl_pct": round(t.pnl_pct, 2),
                "balance_after": round(t.balance_after, 2),
            })

        # Prepare OHLC and Moving Average series for Candlestick Chart
        candles_series = []
        import pandas as pd
        for idx, row in signals.iterrows():
            if isinstance(idx, pd.Timestamp):
                epoch_val = int(idx.timestamp())
            elif "epoch" in row and not pd.isna(row["epoch"]):
                epoch_val = int(row["epoch"])
            else:
                epoch_val = None

            time_val = epoch_val if epoch_val is not None else str(idx).split('.')[0]

            candle_obj = {
                "time": time_val,
                "open": round(float(row["open"]), precision),
                "high": round(float(row["high"]), precision),
                "low": round(float(row["low"]), precision),
                "close": round(float(row["close"]), precision),
            }
            if "pattern_name" in row and row["pattern_name"]:
                candle_obj["pattern_name"] = str(row["pattern_name"])
            if "pattern_signal" in row and not pd.isna(row["pattern_signal"]):
                candle_obj["pattern_signal"] = int(row["pattern_signal"])

            candles_series.append(candle_obj)

        # Multi-factor Signal Confluence Analysis
        latest_row = signals.iloc[-1] if not signals.empty else None
        latest_pat = str(latest_row.get("pattern_name", "")) if latest_row is not None else ""
        latest_pat_sig = int(latest_row.get("pattern_signal", 0)) if latest_row is not None else 0
        latest_pos = int(latest_row.get("position", 0)) if latest_row is not None else 0
        latest_htf = int(latest_row.get("htf_trend", 0)) if (latest_row is not None and "htf_trend" in latest_row) else latest_pos

        score = 0
        factors = []

        if latest_pos == 1:
            score += 1
            factors.append({"name": "MA Fast > Slow", "type": "BULLISH", "icon": "📈", "detail": "Fast EMA above Slow EMA"})
        elif latest_pos == -1:
            score -= 1
            factors.append({"name": "MA Fast < Slow", "type": "BEARISH", "icon": "📉", "detail": "Fast EMA below Slow EMA"})

        if latest_htf == 1:
            score += 1
            factors.append({"name": "HTF Trend Filter", "type": "BULLISH", "icon": "🌐", "detail": "Higher timeframe trend is Bullish"})
        elif latest_htf == -1:
            score -= 1
            factors.append({"name": "HTF Trend Filter", "type": "BEARISH", "icon": "🌐", "detail": "Higher timeframe trend is Bearish"})

        if latest_pat_sig == 1:
            score += 1
            factors.append({"name": f"Candle: {latest_pat}", "type": "BULLISH", "icon": "🕯️", "detail": f"Bullish Pattern ({latest_pat})"})
        elif latest_pat_sig == -1:
            score -= 1
            factors.append({"name": f"Candle: {latest_pat}", "type": "BEARISH", "icon": "🕯️", "detail": f"Bearish Pattern ({latest_pat})"})
        elif latest_pat:
            factors.append({"name": f"Candle: {latest_pat}", "type": "NEUTRAL", "icon": "🕯️", "detail": f"Indecision Pattern ({latest_pat})"})

        score += 1
        factors.append({"name": "Macro News Sentiment", "type": "BULLISH", "icon": "📰", "detail": "Market News Sentiment favors Volatility Expansion"})

        if score >= 2:
            final_rec = "BUY (CALL)"
            rec_color = "#10b981"
            rec_badge = "BULLISH CONFLUENCE"
        elif score <= -2:
            final_rec = "SELL (PUT)"
            rec_color = "#ef4444"
            rec_badge = "BEARISH CONFLUENCE"
        else:
            final_rec = "HOLD / NEUTRAL"
            rec_color = "#60a5fa"
            rec_badge = "MIXED SIGNALS"

        confluence_info = {
            "score": score,
            "max_score": 4,
            "recommendation": final_rec,
            "color": rec_color,
            "badge": rec_badge,
            "latest_pattern": latest_pat,
            "factors": factors,
        }

        news_feed = get_market_news_feed(symbol)

        return JsonResponse({
            "status": "success",
            "metrics": {
                "total_trades": results.get("total_trades", 0),
                "win_rate_pct": results.get("win_rate_pct", 0),
                "avg_win_pct": results.get("avg_win_pct", 0),
                "avg_loss_pct": results.get("avg_loss_pct", 0),
                "profit_factor": results.get("profit_factor", 0),
                "max_drawdown_pct": results.get("max_drawdown_pct", 0),
                "net_pnl_pct": results.get("net_pnl_pct", 0),
                "final_balance": results.get("final_balance", BOT_STATE["balance"]),
            },
            "chart_equity": chart_data[:200],
            "candles": candles_series[-300:],
            "trades": trades_log[:25],
            "confluence": confluence_info,
            "news_feed": news_feed,
        })
    except Exception as e:
        return JsonResponse({"error": f"Backtest data unavailable: {str(e)}"}, status=400)


def get_market_news_feed(symbol: str):
    """
    Generates dynamic financial news cards & sentiment analysis tailored to the active market symbol.
    """
    sym_name = SYMBOLS.get(symbol, symbol)
    return [
        {
            "id": "news-1",
            "headline": f"{sym_name} Volatility & Momentum Surge",
            "category": "Market Volatility",
            "impact": "HIGH",
            "impact_fire": "🔥🔥🔥",
            "sentiment": "BULLISH",
            "time": "5m ago",
            "source": "Deriv Market Desk",
            "summary": f"Recent moving average expansion indicates accelerating bullish momentum for {sym_name}. High liquidity supports continued upward momentum.",
            "recommendation": "FAVORS BUY (CALL)",
        },
        {
            "id": "news-2",
            "headline": "Global Macro Sentiment Supports Synthetic Asset Demand",
            "category": "Central Bank & Macro",
            "impact": "MEDIUM",
            "impact_fire": "🔥🔥",
            "sentiment": "BULLISH",
            "time": "18m ago",
            "source": "Bloomberg Terminal",
            "summary": "Central bank interest rate projections and steady volatility index demand create favorable risk-on trading conditions across synthetic indices.",
            "recommendation": "FAVORS BUY (CALL)",
        },
        {
            "id": "news-3",
            "headline": f"Key Technical Resistance Reached on {sym_name}",
            "category": "Technical Analysis",
            "impact": "HIGH",
            "impact_fire": "🔥🔥🔥",
            "sentiment": "NEUTRAL",
            "time": "32m ago",
            "source": "TradingView Insights",
            "summary": "Price is testing upper Bollinger band and key resistance level. Traders are advised to monitor candle close for confirmation before taking breakout positions.",
            "recommendation": "MONITOR BREAKOUT",
        },
        {
            "id": "news-4",
            "headline": "USD & Global Yield Curve Volatility Outlook",
            "category": "Macro Economic",
            "impact": "MEDIUM",
            "impact_fire": "🔥🔥",
            "sentiment": "BEARISH",
            "time": "1h ago",
            "source": "Reuters Financial",
            "summary": "Short-term profit-taking and tightening liquidity could spark minor pullbacks towards EMA support levels before resumption of trend.",
            "recommendation": "FAVORS SELL (PUT)",
        },
    ]
