"""
DataLoader for LOF Fund Arbitrage Backtesting System.

Reads market data, NAV, limit events, and fees from disk and provides
unified data access for backtesting.

LOF基金套利回测系统的数据加载器。

从磁盘读取行情数据、净值、限购事件和费用信息，为回测提供统一的数据访问接口。
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd


class BundleResult(NamedTuple):
    """Result of loading a ticker's data bundle.

    加载单个基金数据包的结果。

    Attributes:
        df: DataFrame with market data (open, high, low, close, volume, nav,
            premium_rate, daily_limit). / 行情数据DataFrame
        fee_config: Fee configuration dict for the ticker. / 费用配置字典
    """

    df: pd.DataFrame
    fee_config: Dict[str, float]


class DataLoader:
    """Loads and aligns LOF fund data from multiple sources.

    从多个数据源加载和对齐LOF基金数据。

    Attributes:
        data_dir: Root directory containing mock data. / 包含模拟数据的根目录
        _fees_cache: Cached fee configuration DataFrame. / 缓存的费用配置DataFrame
    """

    def __init__(self, data_dir: str = "./data/mock"):
        """Initialize DataLoader with data directory.

        使用数据目录初始化DataLoader。

        Args:
            data_dir: Path to directory containing mock data. / 包含模拟数据的目录路径
        """
        self.data_dir = Path(data_dir)
        self._fees_cache: Optional[pd.DataFrame] = None

        # Validate directory structure  # 验证目录结构
        required_dirs = ["market", "nav", "config"]
        for dir_name in required_dirs:
            dir_path = self.data_dir / dir_name
            if not dir_path.exists():
                raise FileNotFoundError(f"Required directory not found: {dir_path}")

    def load_bundle(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BundleResult:
        """Load and merge all data for a single ticker.

        加载并合并单个基金的所有数据。

        Args:
            ticker: Fund ticker symbol (e.g., '161005'). / 基金代码
            start_date: Optional start date filter (format: 'YYYY-MM-DD'). / 可选起始日期
            end_date: Optional end date filter (format: 'YYYY-MM-DD'). / 可选结束日期

        Returns:
            BundleResult with df (DataFrame indexed by date) and fee_config dict.
            BundleResult，包含df（按日期索引的DataFrame）和fee_config字典

        Raises:
            FileNotFoundError: If market or NAV data files don't exist. / 行情或净值数据文件不存在
        """
        # Load market data  # 加载行情数据
        market_path = self.data_dir / "market" / f"{ticker}.parquet"
        if not market_path.exists():
            raise FileNotFoundError(f"Market data not found: {market_path}")
        df_market = pd.read_parquet(market_path)

        # Load NAV data  # 加载净值数据
        nav_path = self.data_dir / "nav" / f"{ticker}.parquet"
        if not nav_path.exists():
            raise FileNotFoundError(f"NAV data not found: {nav_path}")
        df_nav = pd.read_parquet(nav_path)

        # Set date as index for both DataFrames  # 将日期设置为两个DataFrame的索引
        df_market = df_market.set_index("date")
        df_nav = df_nav.set_index("date")

        # Ensure index is DatetimeIndex for proper matching in backtest  # 确保索引为DatetimeIndex以便在回测中正确匹配
        df_market.index = pd.to_datetime(df_market.index)
        df_nav.index = pd.to_datetime(df_nav.index)

        # Merge market and NAV data on date index  # 在日期索引上合并行情和净值数据
        df = pd.merge(
            df_market[["open", "high", "low", "close", "volume"]],
            df_nav[["nav"]],
            left_index=True,
            right_index=True,
            how="inner",
        )

        # Calculate premium rate  # 计算溢价率
        df["premium_rate"] = (df["close"] - df["nav"]) / df["nav"]

        # Load and resample limit events to daily series  # 加载限购事件并重采样为日序列
        daily_limits = self._resample_limits_to_daily(ticker, df.index)
        df["daily_limit"] = daily_limits

        # Apply forward fill to handle any NaN values  # 前向填充处理NaN值
        df = df.ffill()

        # Apply date filtering if specified  # 如果指定了日期过滤则应用
        if start_date is not None or end_date is not None:
            df = df.loc[start_date:end_date]

        # Load fee configuration  # 加载费用配置
        fees = self.load_fees(ticker)

        return BundleResult(df=df, fee_config=fees)

    # Default fee configuration for LOF funds  # LOF基金的默认费用配置
    DEFAULT_FEES: Dict[str, float] = {
        "fee_rate_tier_1": 0.015,
        "fee_limit_1": 500000.0,
        "fee_rate_tier_2": 0.01,
        "fee_limit_2": 2000000.0,
        "fee_fixed": 1000.0,
        "redeem_fee_7d": 0.015,
    }

    def load_fees(self, ticker: str) -> Dict[str, float]:
        """Load fee configuration for a specific ticker.

        加载特定基金的费用配置。

        Args:
            ticker: Fund ticker symbol. / 基金代码

        Returns:
            Dictionary containing fee configuration: / 包含费用配置的字典：
            {
                'fee_rate_tier_1': float,  # 第一档费率
                'fee_limit_1': float,      # 第一档限额
                'fee_rate_tier_2': float,  # 第二档费率
                'fee_limit_2': float,      # 第二档限额
                'fee_fixed': float,        # 固定费用
                'redeem_fee_7d': float     # 7天内赎回费率
            }

        Note:
            Returns default fees if ticker not found in configuration.
            如果配置中找不到该基金，返回默认费用。
        """
        # Load and cache fees CSV on first call  # 首次调用时加载并缓存费用CSV
        if self._fees_cache is None:
            fees_path = self.data_dir / "config" / "fees.csv"
            if not fees_path.exists():
                # No fee config file, use defaults for all tickers  # 无费用配置文件，对所有基金使用默认值
                return self.DEFAULT_FEES.copy()
            self._fees_cache = pd.read_csv(fees_path)
            # Convert ticker column to string for consistent comparison  # 将基金代码列转换为字符串以便一致比较
            self._fees_cache["ticker"] = self._fees_cache["ticker"].astype(str)

        # Filter for the specific ticker  # 过滤特定基金
        ticker_fees = self._fees_cache[self._fees_cache["ticker"] == str(ticker)]

        if ticker_fees.empty:
            # Ticker not in config, return defaults  # 基金不在配置中，返回默认值
            return self.DEFAULT_FEES.copy()

        # Convert to dictionary (first row only)  # 转换为字典（仅第一行）
        fee_dict = ticker_fees.iloc[0].to_dict()
        # Remove ticker from dict as it's not a fee parameter  # 从字典中移除基金代码（不是费用参数）
        fee_dict.pop("ticker", None)

        return fee_dict

    def _resample_limits_to_daily(
        self, ticker: str, date_index: pd.DatetimeIndex
    ) -> pd.Series:
        """Resample limit events to daily time series.

        将限购事件重采样为日时间序列。

        For each date in the index: / 对于索引中的每个日期：
        - If date falls within a limit event period, returns the max_amount
          如果日期在限购期间内，返回max_amount
        - Otherwise, returns float('inf') indicating no limit
          否则返回float('inf')表示无限购

        Args:
            ticker: Fund ticker symbol. / 基金代码
            date_index: DatetimeIndex for which to generate daily limits. / 要生成日限额的DatetimeIndex

        Returns:
            Series indexed by date with daily_limit values. / 按日期索引的Series，包含daily_limit值
        """
        # Initialize all dates with no limit (infinity)  # 初始化所有日期为无限购（无穷大）
        daily_limits = pd.Series(float("inf"), index=date_index, name="daily_limit")

        # Load limit events from SQLite  # 从SQLite加载限购事件
        db_path = self.data_dir / "config" / "fund_status.db"
        if not db_path.exists():
            # No limit events database, return all unlimited  # 无限购事件数据库，返回全部无限购
            return daily_limits

        conn = sqlite3.connect(db_path)

        # Query limit events for this ticker  # 查询该基金的限购事件
        query = """
            SELECT start_date, end_date, max_amount
            FROM limit_events
            WHERE ticker = ?
        """

        try:
            df_limits = pd.read_sql(query, conn, params=(ticker,))
        finally:
            conn.close()

        # If no limit events found, return all unlimited  # 如果未找到限购事件，返回全部无限购
        if df_limits.empty:
            return daily_limits

        # Convert date columns to datetime  # 将日期列转换为datetime
        df_limits["start_date"] = pd.to_datetime(df_limits["start_date"])
        df_limits["end_date"] = pd.to_datetime(df_limits["end_date"])

        # For each limit event, set daily_limit for dates in range  # 对每个限购事件，为范围内的日期设置daily_limit
        for _, event in df_limits.iterrows():
            start = event["start_date"]
            end = event["end_date"]
            max_amount = event["max_amount"]

            # Create mask for dates within this limit period  # 为此限购期间内的日期创建掩码
            # Handle open-ended limits (NULL/NaT end_date) - applies to all dates >= start_date
            # 处理开放式限购（NULL/NaT end_date）- 适用于所有 >= start_date 的日期
            if pd.isna(end):
                mask = date_index >= start
            else:
                mask = (date_index >= start) & (date_index <= end)
            daily_limits.loc[mask] = daily_limits.loc[mask].clip(upper=max_amount)

        return daily_limits

    def list_available_tickers(self) -> List[str]:
        """Discover all tickers available in the data directory.

        发现数据目录中所有可用的基金代码。

        Scans both market and nav directories for parquet files and returns
        only tickers that have both market AND nav data.

        扫描market和nav目录中的parquet文件，仅返回同时具有行情和净值数据的基金代码。

        Returns:
            Sorted list of ticker codes available in the data directory.
            数据目录中可用基金代码的排序列表
        """
        market_dir = self.data_dir / "market"
        nav_dir = self.data_dir / "nav"

        market_tickers = {f.stem for f in market_dir.glob("*.parquet")}
        nav_tickers = {f.stem for f in nav_dir.glob("*.parquet")}

        # Only return tickers that have both market and nav data  # 仅返回同时具有行情和净值数据的基金代码
        valid_tickers = market_tickers & nav_tickers
        return sorted(valid_tickers)
