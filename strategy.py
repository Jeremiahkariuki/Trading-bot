"""
MA Crossover strategy logic and timeframe resampling.
"""

import pandas as pd
import numpy as np
from indicators import sma, ema, atr


def resample_candles(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample 60-second (or base) candles into higher timeframes (e.g., '5min', '15min', '1H').
    Expects df to have 'epoch' or 'datetime' and ['open', 'high', 'low', 'close'].
    """
    if df.empty:
        return df

    df_copy = df.copy()

    if "datetime" in df_copy.columns:
        df_copy["dt"] = pd.to_datetime(df_copy["datetime"])
    elif "epoch" in df_copy.columns:
        df_copy["dt"] = pd.to_datetime(df_copy["epoch"], unit="s")
    else:
        raise ValueError("DataFrame must contain 'datetime' or 'epoch' column.")

    df_copy.set_index("dt", inplace=True)
    df_copy.sort_index(inplace=True)

    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last"
    }

    resampled = df_copy.resample(timeframe).agg(agg_dict)
    resampled.dropna(subset=["open", "high", "low", "close"], inplace=True)
    resampled.reset_index(inplace=True)
    resampled.rename(columns={"dt": "datetime"}, inplace=True)

    return resampled


class MACrossoverStrategy:
    """
    Moving Average Crossover Strategy.
    Generates trading signals when Fast MA crosses Slow MA.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30, ma_type: str = "ema"):
        if fast_period >= slow_period:
            raise ValueError("fast_period must be smaller than slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type.lower()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates indicators and generates signals on the provided DataFrame.
        Adds columns: 'fast_ma', 'slow_ma', 'signal', 'position'.
        """
        if len(df) < self.slow_period:
            raise ValueError(
                f"DataFrame length ({len(df)}) is less than slow_period ({self.slow_period})."
            )

        df_out = df.copy()

        # 1. Calculate MAs
        if self.ma_type == "sma":
            df_out["fast_ma"] = sma(df_out["close"], self.fast_period)
            df_out["slow_ma"] = sma(df_out["close"], self.slow_period)
        elif self.ma_type == "ema":
            df_out["fast_ma"] = ema(df_out["close"], self.fast_period)
            df_out["slow_ma"] = ema(df_out["close"], self.slow_period)
        else:
            raise ValueError(f"Unsupported ma_type: {self.ma_type}. Use 'sma' or 'ema'.")

        # 2. Identify Crossovers (using previous bar shift to prevent lookahead)
        prev_fast = df_out["fast_ma"].shift(1)
        prev_slow = df_out["slow_ma"].shift(1)
        curr_fast = df_out["fast_ma"]
        curr_slow = df_out["slow_ma"]

        # Crossover Bullish (Fast crosses above Slow)
        bullish_cross = (prev_fast < prev_slow) & (curr_fast >= curr_slow)
        # Crossover Bearish (Fast crosses below Slow)
        bearish_cross = (prev_fast > prev_slow) & (curr_fast <= curr_slow)

        df_out["signal"] = 0
        df_out.loc[bullish_cross, "signal"] = 1
        df_out.loc[bearish_cross, "signal"] = -1

        # Position status: 1 = Long, -1 = Short/Exit, 0 = Flat
        # Forward fill signals to maintain position state
        df_out["position"] = df_out["signal"].replace(0, np.nan).ffill().fillna(0)

        return df_out
