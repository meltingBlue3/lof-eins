"""
Core data generation logic for LOF mock data.

LOF模拟数据的核心数据生成逻辑。
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

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
        np.random.seed(
            hash(ticker) % (2**32)
        )  # Reproducible per ticker  # 每个基金可复现

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
        np.random.seed(hash(ticker + "_price") % (2**32))

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


class FeeConfigGenerator:
    """Generates fee configuration CSV with tiered fee structure.

    生成带阶梯费率结构的费用配置CSV。
    """

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, output_path: Path) -> None:
        """Generate fee configuration CSV file.

        生成费用配置CSV文件。

        Args:
            output_path: Path to save fees.csv / fees.csv的保存路径
        """
        fee_data = []

        for ticker in self.config.tickers:
            # Tiered fee structure (common for public funds in China)
            # 阶梯费率结构（中国公募基金常见）
            # Tier 1: < 500k CNY -> 1.5% fee rate  # 第一档：< 50万人民币 -> 1.5%费率
            # Tier 2: 500k - 2M CNY -> 1.0% fee rate  # 第二档：50万 - 200万人民币 -> 1.0%费率
            # Tier 3: >= 2M CNY -> 1000 CNY fixed fee  # 第三档：>= 200万人民币 -> 固定1000元
            # Redemption fee (< 7 days): 1.5%  # 7天内赎回：1.5%

            fee_data.append(
                {
                    "ticker": ticker,
                    "fee_rate_tier_1": 0.015,  # 1.5%
                    "fee_limit_1": 500_000.0,  # 50万
                    "fee_rate_tier_2": 0.010,  # 1.0%
                    "fee_limit_2": 2_000_000.0,  # 200万
                    "fee_fixed": 1000.0,  # 固定1000元
                    "redeem_fee_7d": 0.015,  # 7天内赎回1.5%
                }
            )

        df = pd.DataFrame(fee_data)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")


class FundStatusGenerator:
    """Generates fund status events (purchase limits) based on premium rates.

    基于溢价率生成基金状态事件（申购限额）。
    """

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str, price_df: pd.DataFrame, output_db: Path) -> int:
        """Generate fund status events and store in SQLite database.

        生成基金状态事件并存储到SQLite数据库。

        Args:
            ticker: Fund ticker symbol. / 基金代码
            price_df: DataFrame with price data including premium_rate column. / 包含premium_rate列的价格数据DataFrame
            output_db: Path to SQLite database file. / SQLite数据库文件路径

        Returns:
            Number of limit events generated for this ticker. / 为此基金生成的限购事件数量
        """
        # Identify limit events based on premium rate  # 基于溢价率识别限购事件
        limit_events = self._identify_limit_events(ticker, price_df)

        # Store in database
        conn = sqlite3.connect(output_db)
        cursor = conn.cursor()

        # Create table if not exists  # 如果表不存在则创建
        # Note: end_date is nullable to support open-ended limits (limits without known end date)
        # 注意：end_date可为空，以支持开放式限购（无已知结束日期的限购）
        # Includes is_open_ended computed column and source_announcement_ids for audit trail
        # 包含is_open_ended计算列和source_announcement_ids用于审计跟踪
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,  -- NULL indicates open-ended limit
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # Create index on is_open_ended for efficient queries  # 为is_open_ended创建索引以提高查询效率
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)

        # Create announcement_parses table for LLM extraction results  # 为LLM提取结果创建announcement_parses表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcement_parses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                announcement_date DATE NOT NULL,
                pdf_filename TEXT NOT NULL,
                parse_result TEXT,
                parse_type TEXT,
                confidence REAL,
                processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for announcement_parses
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_ticker
            ON announcement_parses(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_processed
            ON announcement_parses(processed)
        """)

        # Insert limit events with source_announcement_ids (empty array for mock data)
        # 插入带source_announcement_ids的限购事件（模拟数据为空数组）
        for event in limit_events:
            cursor.execute(
                """
                INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason, source_announcement_ids)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    event["ticker"],
                    event["start_date"],
                    event["end_date"],
                    event["max_amount"],
                    event["reason"],
                    "[]",  # Empty JSON array for mock data (no real announcements)  # 模拟数据为空JSON数组（无真实公告）
                ),
            )

        conn.commit()
        conn.close()

        return len(limit_events)

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
