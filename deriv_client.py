"""
deriv_client.py

Thin wrapper around Deriv's public WebSocket API for pulling historical
candle data. This uses only the public "ticks_history" call, which does
NOT require an API token/login - fine for backtesting.

Placing live trades (later stage, after backtesting looks solid) requires
an authenticated connection with a per-user API token - that comes in a
later step, kept deliberately separate from this read-only data fetcher.

Docs: https://api.deriv.com  (see "ticks_history" and "Market: Synthetic Indices")

NOTE: This sandbox environment cannot reach api.deriv.com to test this
file live - test it on your own machine. The request/response shapes
below follow Deriv's published API spec.
"""

import asyncio
import json
import ssl
from datetime import datetime, timezone

import pandas as pd
import websockets

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"

# Deriv market symbols (Synthetic Indices & Forex Currency Pairs)
SYMBOLS = {
    "Volatility 10 Index": "R_10",
    "Volatility 25 Index": "R_25",
    "Volatility 50 Index": "R_50",
    "Volatility 75 Index": "R_75",
    "Volatility 100 Index": "R_100",
    "Volatility 75 (1s) Index": "1HZ75V",
    "Volatility 100 (1s) Index": "1HZ100V",
    "EUR/USD": "frxEURUSD",
    "GBP/USD": "frxGBPUSD",
    "USD/JPY": "frxUSDJPY",
    "AUD/USD": "frxAUDUSD",
    "EUR/GBP": "frxEURGBP",
}


async def fetch_candles(
    symbol: str = "R_75",
    granularity_seconds: int = 60,
    count: int = 5000,
    app_id: str = "1089",   # Deriv's public demo app_id, fine for read-only market data
) -> pd.DataFrame:
    """
    Fetch historical 1-min (or other granularity) candles from Deriv.
    """
    url = DERIV_WS_URL.format(app_id=app_id)

    request = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": granularity_seconds,
    }

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(url, ssl=ssl_context, timeout=8) as ws:
            await ws.send(json.dumps(request))
            raw_resp = await asyncio.wait_for(ws.recv(), timeout=8)
            response = json.loads(raw_resp)
    except Exception as e:
        raise ConnectionError(f"Deriv API connection failed: {str(e)}")

    if "error" in response:
        raise RuntimeError(f"Deriv API error: {response['error'].get('message')}")

    candles = response.get("candles", [])
    if not candles:
        raise RuntimeError("No candle data returned - check symbol/granularity/count.")

    df = pd.DataFrame(candles)
    df["epoch"] = pd.to_datetime(df["epoch"], unit="s", utc=True)
    df = df.rename(columns={"epoch": "time"}).set_index("time")
    df = df[["open", "high", "low", "close"]].astype(float)
    df = df.sort_index()
    return df


import time

_CANDLE_CACHE = {}
_CACHE_TTL_SECONDS = 120


def fetch_candles_sync(*args, **kwargs) -> pd.DataFrame:
    """Blocking convenience wrapper with 30s in-memory cache and offline fallback."""
    symbol = kwargs.get("symbol", args[0] if len(args) > 0 else "R_75")
    granularity = kwargs.get("granularity_seconds", args[1] if len(args) > 1 else 60)
    count = kwargs.get("count", args[2] if len(args) > 2 else 600)

    cache_key = (symbol, granularity, count)
    now = time.time()
    if cache_key in _CANDLE_CACHE:
        cached_df, timestamp = _CANDLE_CACHE[cache_key]
        if now - timestamp < _CACHE_TTL_SECONDS:
            return cached_df.copy()

    try:
        df = asyncio.run(fetch_candles(*args, **kwargs))
        _CANDLE_CACHE[cache_key] = (df, now)
        return df.copy()
    except (ConnectionError, OSError, TimeoutError, asyncio.TimeoutError) as e:
        # If offline or slow connection, fall back to cached data if available
        if cache_key in _CANDLE_CACHE:
            cached_df, _ = _CANDLE_CACHE[cache_key]
            return cached_df.copy()
        raise ConnectionError(f"Network connection offline: {str(e)}")



class DerivClient:
    """Class wrapper around fetch_candles_sync for object-oriented usage."""

    def __init__(self, app_id: str = "1089"):
        self.app_id = app_id

    def fetch_historical_candles(
        self, symbol: str = "R_75", granularity: int = 60, count: int = 5000
    ) -> pd.DataFrame:
        return fetch_candles_sync(
            symbol=symbol,
            granularity_seconds=granularity,
            count=count,
            app_id=self.app_id,
        )


if __name__ == "__main__":
    # Quick manual test - run this file directly on a machine with internet
    # access to confirm connectivity before wiring it into the rest of the app.
    df = fetch_candles_sync(symbol="R_75", granularity_seconds=60, count=200)
    print(df.tail())
    print(f"\nFetched {len(df)} candles for R_75.")
