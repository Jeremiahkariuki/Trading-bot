"""
strategy.py

Moving Average Crossover strategy with optional Multi-Timeframe Confirmation (Option A).

Signal logic:
  - fast MA crosses ABOVE slow MA  -> BUY  (enter long / close short)
  - fast MA crosses BELOW slow MA  -> SELL (enter short / close long)

Multi-Timeframe Confirmation (Option A):
  - Uses a higher timeframe (HTF e.g. 15min / 1H) to confirm macro trend direction.
  - LTF Buy signals are only taken when HTF trend is bullish (HTF Fast MA > HTF Slow MA).
  - LTF Sell signals are only taken when HTF trend is bearish (HTF Fast MA < HTF Slow MA).
  - Filters out false counter-trend signals.
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np
from indicators import sma, ema


@dataclass
class StrategyConfig:
    fast_period: int = 10
    slow_period: int = 50
    ma_type: str = "ema"          # "sma" or "ema"
    price_column: str = "close"   # which price to base MAs on

    # Multi-Timeframe Filter Settings (Option A)
    use_htf_filter: bool = False
    htf_timeframe: str = "15min"
    htf_fast_period: int = 10
    htf_slow_period: int = 50


class MACrossoverStrategy:
    def __init__(
        self,
        config: StrategyConfig = None,
        fast_period: int = None,
        slow_period: int = None,
        ma_type: str = None,
        use_htf_filter: bool = None,
        htf_timeframe: str = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = StrategyConfig(
                fast_period=fast_period if fast_period is not None else 10,
                slow_period=slow_period if slow_period is not None else 50,
                ma_type=ma_type if ma_type is not None else "ema",
                use_htf_filter=use_htf_filter if use_htf_filter is not None else False,
                htf_timeframe=htf_timeframe if htf_timeframe is not None else "15min",
            )

        if self.config.fast_period >= self.config.slow_period:
            raise ValueError("fast_period must be smaller than slow_period")

    def _ma_func(self):
        return ema if self.config.ma_type.lower() == "ema" else sma

    def generate_signals(self, df: pd.DataFrame, base_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        df: must contain columns ['open','high','low','close'], sorted ascending.
        base_df: optional raw 1-min / base granularity candle df for multi-timeframe resampling.

        Returns a copy of df with added columns:
            fast_ma, slow_ma, htf_trend (if HTF enabled),
            position (1 = long, -1 = short, 0 = flat),
            signal (1 = buy, -1 = sell, 0 = none)
        """
        out = df.copy()
        ma_func = self._ma_func()
        price = out[self.config.price_column]

        out["fast_ma"] = ma_func(price, self.config.fast_period)
        out["slow_ma"] = ma_func(price, self.config.slow_period)

        # raw directional state: +1 when fast above slow, -1 when below
        state = (out["fast_ma"] > out["slow_ma"]).astype(int)
        state = state.where(out["fast_ma"].notna() & out["slow_ma"].notna())
        state = state.map({1: 1, 0: -1})  # 1 = fast above slow, -1 = fast below slow

        # a "signal" fires only on the bar where the state actually changes
        prev_state = state.shift(1)
        signal = pd.Series(0, index=out.index)
        signal[(state == 1) & (prev_state == -1)] = 1     # crossed up -> buy
        signal[(state == -1) & (prev_state == 1)] = -1    # crossed down -> sell

        # Multi-Timeframe Confirmation Filter (Option A)
        if self.config.use_htf_filter:
            source_df = base_df if base_df is not None else out
            htf_df = resample_candles(source_df, self.config.htf_timeframe)

            htf_fast = ma_func(htf_df[self.config.price_column], self.config.htf_fast_period)
            htf_slow = ma_func(htf_df[self.config.price_column], self.config.htf_slow_period)
            htf_trend = (htf_fast > htf_slow).map({True: 1, False: -1})
            htf_df["htf_trend"] = htf_trend

            # Align HTF trend to LTF bars using backward fill / forward fill on Datetime index
            htf_series = htf_df["htf_trend"]
            if isinstance(out.index, pd.DatetimeIndex):
                aligned_htf = htf_series.reindex(out.index, method="ffill")
            else:
                aligned_htf = pd.Series(htf_series.values, index=out.index).ffill()

            out["htf_trend"] = aligned_htf

            # Filter LTF signals against HTF trend direction
            # Buy signal requires HTF == 1; Sell signal requires HTF == -1
            filtered_signal = pd.Series(0, index=out.index)
            filtered_signal[(signal == 1) & (out["htf_trend"] == 1)] = 1
            filtered_signal[(signal == -1) & (out["htf_trend"] == -1)] = -1
            signal = filtered_signal

        out["position"] = state.fillna(0).astype(int)
        out["signal"] = signal

        return out


def resample_candles(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample raw 1-minute (or tick-derived) OHLC candles into a different
    timeframe, e.g. '5min', '15min', '1h'.
    """
    # Normalize timeframe for pandas 3.0+ compatibility ('1H' -> '1h')
    timeframe_norm = timeframe.replace("H", "h")
    df_copy = df.copy()
    if not isinstance(df_copy.index, pd.DatetimeIndex):
        if "datetime" in df_copy.columns:
            df_copy["datetime"] = pd.to_datetime(df_copy["datetime"])
            df_copy.set_index("datetime", inplace=True)
        elif "epoch" in df_copy.columns:
            df_copy["datetime"] = pd.to_datetime(df_copy["epoch"], unit="s")
            df_copy.set_index("datetime", inplace=True)

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df_copy.columns:
        agg["volume"] = "sum"

    resampled = df_copy.resample(timeframe_norm).agg(agg)
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    return resampled
