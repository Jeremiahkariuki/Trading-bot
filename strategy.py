"""
strategy.py

Moving Average Crossover strategy.

Signal logic:
  - fast MA crosses ABOVE slow MA  -> BUY  (enter long / close short)
  - fast MA crosses BELOW slow MA  -> SELL (enter short / close long)

This is intentionally simple: 2 parameters (fast_period, slow_period) and
one indicator type choice (SMA or EMA). Fewer parameters = less risk of
overfitting to historical noise, and it's easy to explain to a buyer.

Timeframe is NOT decided in here - this class works on whatever candle
data (OHLC dataframe) you pass to it. Resample your raw ticks/candles to
the timeframe you want BEFORE calling this (see resample_candles below).
That's what makes the timeframe "configurable" (Option B from our plan).
"""

from dataclasses import dataclass
import pandas as pd
from indicators import sma, ema


@dataclass
class StrategyConfig:
    fast_period: int = 10
    slow_period: int = 50
    ma_type: str = "ema"          # "sma" or "ema"
    price_column: str = "close"   # which price to base MAs on


class MACrossoverStrategy:
    def __init__(
        self,
        config: StrategyConfig = None,
        fast_period: int = None,
        slow_period: int = None,
        ma_type: str = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = StrategyConfig(
                fast_period=fast_period if fast_period is not None else 10,
                slow_period=slow_period if slow_period is not None else 50,
                ma_type=ma_type if ma_type is not None else "ema",
            )

        if self.config.fast_period >= self.config.slow_period:
            raise ValueError("fast_period must be smaller than slow_period")

    def _ma_func(self):
        return ema if self.config.ma_type.lower() == "ema" else sma

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        df: must contain columns ['open','high','low','close'] indexed by time,
            sorted ascending (oldest first).

        Returns a copy of df with added columns:
            fast_ma, slow_ma, position (1 = long, -1 = short, 0 = flat),
            signal (1 = buy triggered this bar, -1 = sell triggered this bar, 0 = none)
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

        out["position"] = state.fillna(0).astype(int)
        out["signal"] = signal

        return out


def resample_candles(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample raw 1-minute (or tick-derived) OHLC candles into a different
    timeframe, e.g. '5min', '15min', '1H'.

    df must be indexed by a DatetimeIndex with columns open, high, low, close
    (and optionally volume).
    """
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

    resampled = df_copy.resample(timeframe).agg(agg)
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    resampled.reset_index(inplace=True)
    return resampled
