"""
Deriv API client for fetching historical candle data via WebSocket.
"""

import json
import ssl
import pandas as pd
import websocket


class DerivClient:
    """
    Client for interacting with Deriv's public WebSocket API.
    Does not require authentication for public tick/candle history.
    """

    WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

    def __init__(self, ws_url: str = None):
        self.ws_url = ws_url or self.WS_URL

    def fetch_historical_candles(
        self, symbol: str = "R_75", granularity: int = 60, count: int = 5000
    ) -> pd.DataFrame:
        """
        Fetches historical OHLC candles for a given symbol and granularity.

        :param symbol: Deriv symbol (e.g. 'R_75', 'R_10', 'R_100', '1HZ10V')
        :param granularity: Candle timeframe in seconds (e.g. 60 for 1-minute candles)
        :param count: Number of candles to fetch (max 5000 per request)
        :return: pandas DataFrame containing ['epoch', 'open', 'high', 'low', 'close', 'datetime']
        """
        request_msg = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": granularity,
        }

        try:
            ssl_context = ssl._create_unverified_context()
            ws = websocket.create_connection(
                self.ws_url, timeout=15, sslopt={"cert_reqs": ssl.CERT_NONE}
            )
            ws.send(json.dumps(request_msg))

            raw_response = ws.recv()
            ws.close()

            response = json.loads(raw_response)

            if "error" in response:
                raise RuntimeError(
                    f"Deriv API error ({response['error'].get('code')}): {response['error'].get('message')}"
                )

            if "candles" not in response:
                raise RuntimeError(
                    f"Unexpected response format from Deriv API: {response}"
                )

            candles = response["candles"]
            if not candles:
                raise ValueError(f"No candles returned for symbol {symbol}")

            df = pd.DataFrame(candles)
            # Standardize numeric columns
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            df["datetime"] = pd.to_datetime(df["epoch"], unit="s")
            df = df[["epoch", "datetime", "open", "high", "low", "close"]].sort_values("epoch").reset_index(drop=True)

            return df

        except Exception as e:
            raise RuntimeError(f"Failed to fetch historical data from Deriv API: {str(e)}")
