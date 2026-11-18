"""
Core data generation logic for LOF mock data.

LOF模拟数据的核心数据生成逻辑。
"""

import sqlite3
import zlib
from typing import Dict, List

import numpy as np
import pandas as pd

from .config import MockConfig


class NAVGenerator:
    """Generates Net Asset Value (NAV) data using geometric Brownian motion.

    使用几何布朗运动生成净值数据。
    """

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str) -> pd.DataFrame:
        """Generate NAV time series for a given ticker.

        为指定基金生成净值时间序列。

        Args:
            ticker: Fund ticker symbol. / 基金代码

        Returns:
            DataFrame with columns: date, ticker, nav / 包含date、ticker、nav列的DataFrame
        """
        dates = pd.bdate_range(
            start=self.config.start_date,
            end=self.config.end_date,
            freq="B",  # Business days only  # 仅工作日
        )

        n_days = len(dates)

        # Geometric Brownian Motion for NAV  # 净值的几何布朗运动
        # dS = μ*S*dt + σ*S*dW  # dS = μ*S*dt + σ*S*dW
        # Reproducible per ticker across processes (str hash() is salted per process)
        # 每个基金可复现，跨进程也一样（字符串的 hash() 每个进程不同）
        np.random.seed(zlib.crc32(ticker.encode()))

        returns = np.random.normal(
            self.config.nav_drift, self.config.nav_volatility, n_days
        )

        nav_series = self.config.initial_nav * np.exp(np.cumsum(returns))

        df = pd.DataFrame({"date": dates, "ticker": ticker, "nav": nav_series})

        return df


class PriceGenerator:
    """Generates market price data (OHLCV) with premium rate spikes.

    生成带溢价率突增的市场价格数据（OHLCV）。
    """

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str, nav_df: pd.DataFrame) -> pd.DataFrame:
        """Generate market price data based on NAV with premium rates.

        基于净值和溢价率生成市场价格数据。

        Args:
            ticker: Fund ticker symbol. / 基金代码
            nav_df: DataFrame with NAV data. / 净值数据DataFrame

        Returns:
            DataFrame with columns: date, ticker, open, high, low, close, volume
            包含date、ticker、open、high、low、close、volume列的DataFrame
        """
        np.random.seed(zlib.crc32((ticker + "_price").encode()))

        n_days = len(nav_df)
        premium_rates = np.zeros(n_days)

        # Generate premium rates with spike mechanism  # 生成带突增机制的溢价率
        in_spike = False
        spike_decay = 0.0

        for i in range(n_days):
            if not in_spike:
                # Check for spike event  # 检查突增事件
                if np.random.random() < self.config.spike_probability:
                    # Trigger premium spike  # 触发溢价率突增
                    premium_rates[i] = np.random.uniform(0.10, 0.25)
                    in_spike = True
                    spike_decay = premium_rates[i]
                else:
                    # Normal premium fluctuation  # 正常溢价率波动
                    premium_rates[i] = np.random.normal(
                        0.0, self.config.premium_volatility
                    )
            else:
                # Mean reversion after spike  # 突增后的均值回归
                spike_decay *= np.random.uniform(0.85, 0.95)  # Decay factor  # 衰减因子
                noise = np.random.normal(0.0, self.config.premium_volatility * 0.5)
                premium_rates[i] = spike_decay + noise

                # Exit spike mode when premium drops low enough  # 溢价率足够低时退出突增模式
                if premium_rates[i] < self.config.limit_release_threshold * 1.5:
                    in_spike = False

        # Calculate close prices based on NAV and premium  # 基于净值和溢价率计算收盘价
        close_prices = nav_df["nav"].values * (1 + premium_rates)

        # Generate OHLC based on close  # 基于收盘价生成OHLC
        intraday_volatility = 0.01  # 1% intraday volatility  # 1%日内波动率

        open_prices = close_prices * (
            1 + np.random.normal(0, intraday_volatility, n_days)
        )
        high_prices = np.maximum(open_prices, close_prices) * (
            1 + np.abs(np.random.normal(0, intraday_volatility * 0.5, n_days))
        )
        low_prices = np.minimum(open_prices, close_prices) * (
            1 - np.abs(np.random.normal(0, intraday_volatility * 0.5, n_days))
        )

        # Generate volume (correlated with premium rate)  # 生成成交量（与溢价率相关）
        # Higher premium -> higher volume  # 高溢价 -> 高成交量
        base_volume = 1_000_000  # Base volume in shares  # 基础成交量（股）
        volume_multiplier = (
            1 + np.abs(premium_rates) * 5
        )  # 5x volume increase at high premium  # 高溢价时5倍成交量增长
        volumes = np.random.lognormal(
            np.log(base_volume) + np.log(volume_multiplier), 0.5, n_days
        ).astype(int)

        df = pd.DataFrame(
            {
                "date": nav_df["date"],
                "ticker": ticker,
                "open": open_prices,
                "high": high_prices,
                "low": low_prices,
                "close": close_prices,
                "volume": volumes,
                "premium_rate": premium_rates,  # Keep for limit event generation  # 保留用于限购事件生成
            }
        )

        return df


class StatusGenerator:
    """Generates daily subscription status (the daily_status table) from premium rates.

    基于溢价率生成每日申购状态（daily_status 表）。

    High premiums trigger a limit of ``limit_max_amount`` from the next trading day until
    the premium falls below the release threshold (that day included). Other days are
    open, or limited at ``normal_max_amount`` when it is positive and finite. Every row
    has source ``change``: the mock data stands for announced, proven states.
    """

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str, price_df: pd.DataFrame, conn: sqlite3.Connection) -> int:
        """Insert one fund's daily_status rows; returns the number of limit periods.

        Args:
            ticker: Fund ticker symbol. / 基金代码
            price_df: DataFrame with date and premium_rate columns. / 包含 date、premium_rate 列的价格数据
            conn: Connection to a database that already has the daily_status table. / 已建好 daily_status 表的连接
        """
        periods = self._identify_limit_events(ticker, price_df)
        dates = pd.to_datetime(price_df["date"])
        limited = pd.Series(False, index=dates.index)
        for p in periods:
            end = dates >= pd.Timestamp(p["start_date"])
            if p["end_date"] is not None:
                end &= dates <= pd.Timestamp(p["end_date"])
            limited |= end
        normal = self.config.normal_max_amount
        normal_open = normal is None or normal < 0 or not np.isfinite(normal)
        rows = []
        for d, lim in zip(dates, limited):
            if lim:
                rows.append((ticker, d.strftime("%Y-%m-%d"), "limited", self.config.limit_max_amount, "change"))
            elif normal_open:
                rows.append((ticker, d.strftime("%Y-%m-%d"), "open", None, "change"))
            else:
                rows.append((ticker, d.strftime("%Y-%m-%d"), "limited", float(normal), "change"))
        conn.executemany("INSERT INTO daily_status (fund_code, date, status, amount, source) VALUES (?, ?, ?, ?, ?)",
                         rows)
        return len(periods)

    def _identify_limit_events(self, ticker: str, price_df: pd.DataFrame) -> List[Dict]:
        """Identify periods when purchase limits should be triggered.

        识别应触发申购限额的时段。

        Logic: / 逻辑：
        - If premium_rate > threshold for consecutive_days, trigger limit on T+1
          如果premium_rate > threshold持续consecutive_days天，在T+1触发限购
        - Limit remains active until premium_rate < release_threshold
          限购保持激活直到premium_rate < release_threshold
        - During limit: max_amount = limit_max_amount (very low)
          限购期间：max_amount = limit_max_amount（很低）
        - During normal: max_amount = normal_max_amount (high or unlimited)
          正常期间：max_amount = normal_max_amount（高或无限）

        Args:
            ticker: Fund ticker symbol. / 基金代码
            price_df: DataFrame with premium_rate data. / 包含premium_rate数据的DataFrame

        Returns:
            List of limit event dictionaries. / 限购事件字典列表
        """
        events = []

        premium_rates = price_df["premium_rate"].values
        dates = price_df["date"].values

        in_limit = False
        high_premium_days = 0
        limit_start = None

        for i, (date, premium) in enumerate(zip(dates, premium_rates)):
            if not in_limit:
                # Check if premium exceeds trigger threshold  # 检查溢价是否超过触发阈值
                if premium > self.config.limit_trigger_threshold:
                    high_premium_days += 1

                    # Trigger limit if consecutive days reached  # 如果连续天数达到则触发限购
                    if high_premium_days >= self.config.consecutive_days:
                        in_limit = True
                        # Limit starts on next trading day  # 限购从下一个交易日开始
                        if i + 1 < len(dates):
                            limit_start = pd.Timestamp(dates[i + 1]).strftime(
                                "%Y-%m-%d"
                            )
                        else:
                            limit_start = pd.Timestamp(date).strftime("%Y-%m-%d")
                        high_premium_days = 0
                else:
                    high_premium_days = 0
            else:
                # Check if premium falls below release threshold  # 检查溢价是否低于解除阈值
                if premium < self.config.limit_release_threshold:
                    # End limit period  # 结束限购期间
                    limit_end = pd.Timestamp(date).strftime("%Y-%m-%d")

                    events.append(
                        {
                            "ticker": ticker,
                            "start_date": limit_start,
                            "end_date": limit_end,
                            "max_amount": self.config.limit_max_amount,
                            "reason": f"High premium (>{self.config.limit_trigger_threshold * 100:.0f}%) for {self.config.consecutive_days} consecutive days",
                        }
                    )

                    in_limit = False
                    limit_start = None

        # Handle case where limit extends to end of data  # 处理限购延伸到数据末尾的情况
        # Use None for end_date to represent a genuinely open-ended limit  # 使用None作为end_date表示真正的开放式限购
        if in_limit and limit_start:
            events.append(
                {
                    "ticker": ticker,
                    "start_date": limit_start,
                    "end_date": None,
                    "max_amount": self.config.limit_max_amount,
                    "reason": f"High premium (>{self.config.limit_trigger_threshold * 100:.0f}%) for {self.config.consecutive_days} consecutive days",
                }
            )

        return events
