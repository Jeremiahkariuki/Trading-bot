"""
indicators.py

Basic technical indicators used by the strategy engine.
Kept separate from strategy logic so you can add RSI, Bollinger Bands,
ATR, etc. later without touching the strategy or backtest code.
"""

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (reacts faster to recent price changes)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range - needed later for ATR-based stop losses / position sizing.
    Expects df with columns: high, low, close
    """
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range - a volatility measure, useful for stop-loss sizing."""
    return true_range(df).rolling(window=period, min_periods=period).mean()


# Backward-compatible aliases for strategy imports
calculate_sma = sma
calculate_ema = ema
calculate_atr = atr
