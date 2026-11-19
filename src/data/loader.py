"""
DataLoader for LOF Fund Arbitrage Backtesting System.

Reads market data, NAV, subscription status and trading terms from disk and provides
unified data access for backtesting.

LOF基金套利回测系统的数据加载器。

从磁盘读取行情、净值、申购状态和交易条款，为回测提供统一的数据访问接口。

Layout of a data directory::

    market/<code>.parquet           date, open, high, low, close, volume
    nav/<code>.parquet              date, nav
    config/subscription_state.db    daily_status (scripts/build_timeline.py, or the mock generator)
    config/fund_terms.csv           optional; scripts/fund_terms.py

Subscription status comes from ``daily_status`` (redesign §5, phase D). Each day carries
``sub_status`` (open / limited / closed / unknown), ``status_source`` (change /
restatement / overlay / inferred_prior / inferred_open / default) and ``daily_limit`` --
the stated cap in yuan: inf when open, 0 when closed, the amount when limited, and NaN
when no number is known (unknown, or a limit without an amount). A day with no row, or
a directory without the table, is unknown. The loader applies no policy: the engine
decides what NaN and inferred states mean (BacktestConfig.unknown_policy).

Trading terms (``terms``, redesign §8.4, phase F) come from ``config/fund_terms.csv``
when it exists: per-fund subscription fee tiers, the day the subscribed shares can be
sold (``sell_days``) and the lag of the newest NAV visible at decision time
(``nav_lag``). Funds missing there, and ``terms="default"``, get the default terms:
1.5% (DEFAULT_FEES), sell at T+2, NAV lag 1. The loader adds ``premium_published`` --
close over that visible NAV -- next to the same-day ``premium_rate``; the engine picks
one (BacktestConfig.premium_basis).
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd

from src.data import fund_terms

logger = logging.getLogger(__name__)

TERMS_SOURCES = ("auto", "fund", "default")
DEFAULT_TERMS: Dict[str, Any] = {"sell_days": 2, "nav_lag": 1, "terms_source": "default"}

# Default fee tiers for LOF funds: < 50万 1.5%, < 200万 1.0%, else 1000 yuan per order
# LOF基金的默认费率：50万以下 1.5%，200万以下 1.0%，以上每笔 1000 元
DEFAULT_FEES: Dict[str, float] = {
    "fee_rate_tier_1": 0.015,
    "fee_limit_1": 500000.0,
    "fee_rate_tier_2": 0.01,
    "fee_limit_2": 2000000.0,
    "fee_fixed": 1000.0,
}


class BundleResult(NamedTuple):
    """Result of loading a ticker's data bundle.

    加载单个基金数据包的结果。

    Attributes:
        df: DataFrame with market data (open, high, low, close, volume, nav, premium_rate,
            nav_published, premium_published, daily_limit, sub_status, status_source). / 行情数据DataFrame
        fee_config: The fund's own fee tiers when fund_terms.csv has them, DEFAULT_FEES
            otherwise. / 费用配置字典
    """

    df: pd.DataFrame
    fee_config: Dict[str, Any]


def published_nav(nav: pd.Series, days: pd.DatetimeIndex, lag: int) -> np.ndarray:
    """For each day T, the lag-th latest NAV dated before T (NaN if there are fewer than lag).
    对每个交易日 T，取日期早于 T 的第 lag 个净值（不足 lag 个时为 NaN）。

    Counting on the NAV's own dates keeps the lookup right when the market has no row on some
    days: lag 1 is always the NAV of the previous NAV day, not of the previous traded day.
    在净值自己的日期上数，行情缺行时查找仍正确：lag 1 总是上一个净值日的净值，而不是上一个有成交日的净值。
    """
    nav = nav.dropna().sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    out = np.full(len(days), np.nan)
    if nav.empty:
        return out
    pos = nav.index.searchsorted(days, side="left") - lag
    ok = pos >= 0
    out[ok] = nav.to_numpy()[pos[ok]]
    return out


class DataLoader:
    """Loads and aligns LOF fund data from multiple sources.

    从多个数据源加载和对齐LOF基金数据。

    Attributes:
        data_dir: Root directory of the data (see the module docstring). / 数据根目录
        has_status: Whether config/subscription_state.db has a daily_status table. / 是否有每日状态表
        terms_mode: "fund" or "default" -- where trading terms come from. / 交易条款的来源
    """

    DEFAULT_FEES = DEFAULT_FEES

    def __init__(self, data_dir: str = "./data/mock", terms: str = "auto"):
        """Initialize DataLoader with data directory.

        使用数据目录初始化DataLoader。

        Args:
            data_dir: Path to the data directory. / 数据目录路径
            terms: "auto" (fund_terms.csv when it exists), "fund" or "default". / 交易条款的来源
        """
        if terms not in TERMS_SOURCES:
            raise ValueError(f"terms must be one of {TERMS_SOURCES}, got {terms!r}")
        self.data_dir = Path(data_dir)
        self._status_conn: Optional[sqlite3.Connection] = None
        self._terms: Optional[Dict[str, Dict]] = None

        # Validate directory structure  # 验证目录结构
        required_dirs = ["market", "nav", "config"]
        for dir_name in required_dirs:
            dir_path = self.data_dir / dir_name
            if not dir_path.exists():
                raise FileNotFoundError(f"Required directory not found: {dir_path}")
        self.has_status = self._has_status_table()
        if not self.has_status:
            logger.warning("no daily_status table in %s: every day is unknown (run scripts/build_timeline.py build, "
                           "or scripts/generate_mock.py for mock data)", self.status_db)
        if terms == "fund" and not self.terms_file.exists():
            raise FileNotFoundError(f"{self.terms_file} not found; run scripts/fund_terms.py fetch && build")
        self.terms_mode = "fund" if terms == "fund" or (terms == "auto" and self.terms_file.exists()) else "default"

    @property
    def status_db(self) -> Path:
        return self.data_dir / "config" / "subscription_state.db"

    @property
    def terms_file(self) -> Path:
        return self.data_dir / "config" / fund_terms.TERMS_FILE

    def _has_status_table(self) -> bool:
        if not self.status_db.exists():
            return False
        conn = sqlite3.connect(f"file:{self.status_db.as_posix()}?mode=ro", uri=True)
        try:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'daily_status'").fetchone() is not None
        finally:
            conn.close()

    def load_terms(self, ticker: str) -> Dict[str, Any]:
        """Trading terms of one fund; the default terms when it has none (see the module docstring)."""
        if self.terms_mode == "default":
            return dict(DEFAULT_TERMS)
        if self._terms is None:
            self._terms = fund_terms.read_terms(self.terms_file)
        row = self._terms.get(str(ticker))
        if row is None:
            return dict(DEFAULT_TERMS)
        return {"sell_days": row["sell_days"], "nav_lag": row["nav_lag"], "terms_source": row["source"],
                "sub_fee_tiers": row["sub_fee_tiers"], "fee_formula": "net"}

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

        # Forward fill market/NAV gaps only: a missing limit means "not known", never yesterday's value
        # 只对行情和净值前向填充：限额缺失表示"未知"，不能沿用前一天的值
        df = df.ffill()

        # Premium on the newest NAV a buyer can see at the T 15:00 cut-off (no look-ahead): the
        # nav_lag-th latest NAV dated before T, counted on the NAV's own dates, so a day without a
        # market row (no trades, suspension) does not push the lookup further back.
        # 决策时点可见的最新净值计算的溢价（无前视）：取日期早于 T 的第 nav_lag 个净值，
        # 在净值自己的日期上数，没有行情的日子（无成交、停牌）不会让查找多往前退。
        terms = self.load_terms(ticker)
        df["nav_published"] = published_nav(df_nav["nav"], df.index, terms["nav_lag"])
        df["premium_published"] = (df["close"] - df["nav_published"]) / df["nav_published"]

        # Subscription status per day  # 每日申购状态
        status = self.load_status(ticker, df.index)
        df["daily_limit"] = status["daily_limit"]
        df["sub_status"] = status["sub_status"]
        df["status_source"] = status["status_source"]

        # Apply date filtering if specified  # 如果指定了日期过滤则应用
        if start_date is not None or end_date is not None:
            df = df.loc[start_date:end_date]

        # Load fee configuration  # 加载费用配置
        fees = self.load_fees(ticker)

        return BundleResult(df=df, fee_config=fees)

    def load_fees(self, ticker: str) -> Dict[str, Any]:
        """Fee configuration of one fund: its own tiers (prospectus formula) or DEFAULT_FEES.

        某只基金的申购费配置：有交易条款时用它自己的费率表（外扣法），否则用默认费率。
        """
        terms = self.load_terms(ticker)
        if "sub_fee_tiers" in terms:
            return {"sub_fee_tiers": terms["sub_fee_tiers"], "fee_formula": terms["fee_formula"]}
        return dict(DEFAULT_FEES)

    def load_status(self, ticker: str, date_index: pd.DatetimeIndex) -> pd.DataFrame:
        """Subscription status of one fund on ``date_index``: daily_limit, sub_status, status_source.

        某只基金在给定交易日上的申购状态。
        """
        if not self.has_status:
            return pd.DataFrame({"daily_limit": np.nan, "sub_status": "unknown", "status_source": "default"},
                                index=date_index)
        if self._status_conn is None:
            self._status_conn = sqlite3.connect(f"file:{self.status_db.as_posix()}?mode=ro", uri=True,
                                                check_same_thread=False)
        rows = pd.read_sql_query("SELECT date, status, amount, source FROM daily_status WHERE fund_code = ?",
                                 self._status_conn, params=(str(ticker),))
        rows.index = pd.to_datetime(rows.pop("date"))
        rows = rows.reindex(date_index)
        status = rows["status"].fillna("unknown")
        cap = pd.Series(np.nan, index=date_index)
        cap[status == "open"] = np.inf
        cap[status == "closed"] = 0.0
        limited = status == "limited"
        cap[limited] = rows.loc[limited, "amount"].astype(float)
        return pd.DataFrame({"daily_limit": cap.to_numpy(), "sub_status": status.to_numpy(),
                             "status_source": rows["source"].fillna("default").to_numpy()}, index=date_index)

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
