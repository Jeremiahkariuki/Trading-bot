"""
dashboard_views.py

Views and REST API endpoints for the Trading Bot Django Dashboard.
"""

import json
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
    "balance": 1000.0,
    "daily_pnl": 0.0,
    "active_trades": 0,
    "mode": "PAPER",
    "api_token": "",
    "logs": [],
    "live_trades": [],
    "last_signal": "HOLD",
    "last_check_time": None,
}

risk_mgr = RiskManager(initial_balance=1000.0)
worker = TradingBotWorker(BOT_STATE, risk_mgr)


def index_view(request):
    """Renders main dashboard HTML page."""
    context = {
        "symbols": SYMBOLS,
        "bot_state": BOT_STATE,
    }
    return render(request, "dashboard.html", context)


def api_status_view(request):
    """Returns current bot status, risk state, and balance."""
    can_trade, reason = risk_mgr.can_open_trade(BOT_STATE["balance"])
    return JsonResponse({
        "status": "success",
        "state": BOT_STATE,
        "risk_halted": risk_mgr.trading_halted,
        "halt_reason": risk_mgr.halt_reason,
        "can_trade": can_trade,
        "worker_active": worker.is_running(),
    })


@csrf_exempt
def api_toggle_view(request):
    """Toggles bot running state (Start / Stop) and controls background worker."""
    if request.method == "POST":
        BOT_STATE["running"] = not BOT_STATE["running"]
        if BOT_STATE["running"]:
            worker.start()
            status_label = "STARTED"
        else:
            worker.stop()
            status_label = "STOPPED"
        return JsonResponse({"status": "success", "running": BOT_STATE["running"], "message": f"Trading Bot {status_label}"})
    return JsonResponse({"error": "POST method required"}, status=400)


@csrf_exempt
def api_config_view(request):
    """Updates bot configuration parameters."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            BOT_STATE["symbol"] = data.get("symbol", BOT_STATE["symbol"])
            BOT_STATE["timeframe"] = data.get("timeframe", BOT_STATE["timeframe"])
            BOT_STATE["fast_ma"] = int(data.get("fast_ma", BOT_STATE["fast_ma"]))
            BOT_STATE["slow_ma"] = int(data.get("slow_ma", BOT_STATE["slow_ma"]))
            BOT_STATE["use_htf"] = bool(data.get("use_htf", BOT_STATE["use_htf"]))
            return JsonResponse({"status": "success", "state": BOT_STATE})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "POST method required"}, status=400)


@csrf_exempt
def api_backtest_run_view(request):
    """Executes a real-time backtest on Deriv data for the dashboard chart."""
    symbol = request.GET.get("symbol", BOT_STATE["symbol"])
    timeframe = request.GET.get("timeframe", BOT_STATE["timeframe"])
    fast_ma = int(request.GET.get("fast_ma", BOT_STATE["fast_ma"]))
    slow_ma = int(request.GET.get("slow_ma", BOT_STATE["slow_ma"]))
    use_htf = request.GET.get("use_htf", "false").lower() == "true"
    count = int(request.GET.get("count", 3000))

    try:
        df_base = fetch_candles_sync(symbol=symbol, granularity_seconds=60, count=count)
        df_tf = resample_candles(df_base, timeframe) if timeframe != "1min" else df_base

        strategy = MACrossoverStrategy(StrategyConfig(
            fast_period=fast_ma,
            slow_period=slow_ma,
            ma_type="ema",
            use_htf_filter=use_htf,
            htf_timeframe="15min" if timeframe in ["1min", "5min"] else "1h",
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

        trades_log = []
        for t in results.get("trades", []):
            trades_log.append({
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "direction": "LONG" if t.direction == 1 else "SHORT",
                "entry_price": round(t.entry_price, 4),
                "exit_price": round(t.exit_price, 4),
                "pnl_pct": round(t.pnl_pct, 2),
                "balance_after": round(t.balance_after, 2),
            })

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
            "chart_equity": chart_data[:100],  # sample 100 points for smooth charting
            "trades": trades_log[:25],
        })
    except Exception as e:
        return JsonResponse({"error": f"Backtest failed: {str(e)}"}, status=500)
