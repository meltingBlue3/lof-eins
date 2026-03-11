"""
Comprehensive unit tests for NULL end_date handling in DataLoader.

DataLoader 中 NULL end_date 处理的综合单元测试。

Tests verify that open-ended limits (NULL end_date) are correctly applied to all
dates >= start_date, and that the is_open_ended computed column works as expected.
测试验证开放式限购（NULL end_date）正确应用于所有 >= start_date 的日期，
以及 is_open_ended 计算列按预期工作。
"""

import sys
import os
import unittest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Add project root to path  # 将项目根目录添加到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.loader import DataLoader


class TestOpenEndedLimits(unittest.TestCase):
    """Test suite for open-ended limit (NULL end_date) handling.
    开放式限购（NULL end_date）处理的测试套件。
    """

    def setUp(self):
        """Set up temporary test data directory with mock data.
        使用模拟数据设置临时测试数据目录。
        """
        self.temp_dir = tempfile.mkdtemp(prefix="lof_test_")
        self.data_dir = Path(self.temp_dir) / "data"

        # Create required directory structure  # 创建必需的目录结构
        (self.data_dir / "market").mkdir(parents=True)
        (self.data_dir / "nav").mkdir(parents=True)
        (self.data_dir / "config").mkdir(parents=True)

        self.ticker = "TEST001"
        self.date_range = pd.bdate_range(start="2024-01-01", end="2024-06-30", freq="B")

    def tearDown(self):
        """Clean up temporary test data."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_market_data(self, ticker: str, dates: pd.DatetimeIndex) -> None:
        """Create minimal market data for testing.
        为测试创建最小的行情数据。
        """
        n_days = len(dates)
        df = pd.DataFrame(
            {
                "date": dates,
                "ticker": ticker,
                "open": np.ones(n_days) * 1.0,
                "high": np.ones(n_days) * 1.1,
                "low": np.ones(n_days) * 0.9,
                "close": np.ones(n_days) * 1.0,
                "volume": np.ones(n_days, dtype=int) * 1000000,
            }
        )
        df.to_parquet(self.data_dir / "market" / f"{ticker}.parquet", index=False)

    def _create_nav_data(self, ticker: str, dates: pd.DatetimeIndex) -> None:
        """Create minimal NAV data for testing.
        为测试创建最小的净值数据。
        """
        n_days = len(dates)
        df = pd.DataFrame(
            {
                "date": dates,
                "ticker": ticker,
                "nav": np.ones(n_days) * 1.0,
            }
        )
        df.to_parquet(self.data_dir / "nav" / f"{ticker}.parquet", index=False)

    def _create_fee_config(self) -> None:
        """Create minimal fee configuration.
        创建最小的费率配置。
        """
        df = pd.DataFrame(
            {
                "ticker": [self.ticker],
                "fee_rate_tier_1": [0.015],
                "fee_limit_1": [500000.0],
                "fee_rate_tier_2": [0.010],
                "fee_limit_2": [2000000.0],
                "fee_fixed": [1000.0],
                "redeem_fee_7d": [0.015],
            }
        )
        df.to_csv(self.data_dir / "config" / "fees.csv", index=False)

    def _create_limit_events_db(self, events: list) -> None:
        """Create SQLite database with limit events.
        创建带有限购事件的 SQLite 数据库。
        """
        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create limit_events table with all columns including generated column  # 创建包含所有列（包括计算列）的 limit_events 表
        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # Insert events
        for event in events:
            cursor.execute(
                """
                INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.get("ticker", self.ticker),
                    event["start_date"],
                    event.get("end_date"),
                    event.get("max_amount", 100.0),
                    event.get("reason", "Test limit"),
                ),
            )

        conn.commit()
        conn.close()

    def test_null_end_date_applies_to_all_future_dates(self):
        """Test that NULL end_date correctly applies limit to all dates >= start_date.
        测试 NULL end_date 正确将限购应用于所有 >= start_date 的日期。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create open-ended limit starting from Feb 15  # 创建从 2 月 15 日开始的开放式限购
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-02-15",
                    "end_date": None,  # NULL - open-ended
                    "max_amount": 500.0,
                    "reason": "Open-ended limit test",
                }
            ]
        )

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: Before Feb 15, no limit (inf)  # 验证：2 月 15 日之前无限制（inf）
        before_limit = df.loc["2024-01-01":"2024-02-14"]
        self.assertTrue(
            (before_limit["daily_limit"] == float("inf")).all(),
            "Dates before limit start should have no limit (inf)",
        )

        # Verify: From Feb 15 onwards, limit applies  # 验证：从 2 月 15 日起限购生效
        during_limit = df.loc["2024-02-15":"2024-06-30"]
        self.assertTrue(
            (during_limit["daily_limit"] == 500.0).all(),
            "All dates from limit start should have the limit applied",
        )

    def test_regular_limit_with_end_date_regression(self):
        """Test that regular limits with end_date still work (regression test).
        测试带有 end_date 的常规限购仍然工作（回归测试）。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create closed limit from Feb 15 to Mar 15  # 创建从 2 月 15 日到 3 月 15 日的封闭式限购
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-02-15",
                    "end_date": "2024-03-15",  # Closed limit
                    "max_amount": 200.0,
                    "reason": "Closed limit test",
                }
            ]
        )

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: Before Feb 15, no limit
        before_limit = df.loc["2024-01-01":"2024-02-14"]
        self.assertTrue(
            (before_limit["daily_limit"] == float("inf")).all(),
            "Dates before limit start should have no limit",
        )

        # Verify: During limit period, limit applies
        during_limit = df.loc["2024-02-15":"2024-03-15"]
        self.assertTrue(
            (during_limit["daily_limit"] == 200.0).all(),
            "Dates within limit period should have limit applied",
        )

        # Verify: After limit end, no limit
        after_limit = df.loc["2024-03-16":"2024-06-30"]
        self.assertTrue(
            (after_limit["daily_limit"] == float("inf")).all(),
            "Dates after limit end should have no limit",
        )

    def test_mixed_open_and_closed_limits(self):
        """Test handling of both open-ended and closed limits for same ticker.
        测试同一标的的开放式和封闭式限购处理。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create multiple limit events
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-01-15",
                    "end_date": "2024-01-31",  # Closed limit
                    "max_amount": 100.0,
                    "reason": "First closed limit",
                },
                {
                    "start_date": "2024-03-01",
                    "end_date": None,  # Open-ended
                    "max_amount": 300.0,
                    "reason": "Open-ended limit",
                },
            ]
        )

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: Jan 15-31 has first limit
        jan_limit = df.loc["2024-01-15":"2024-01-31"]
        self.assertTrue(
            (jan_limit["daily_limit"] == 100.0).all(),
            "Jan 15-31 should have first limit (100.0)",
        )

        # Verify: Feb has no limit
        feb_no_limit = df.loc["2024-02-01":"2024-02-29"]
        self.assertTrue(
            (feb_no_limit["daily_limit"] == float("inf")).all(),
            "Feb should have no limit",
        )

        # Verify: Mar onwards has second (open-ended) limit
        mar_limit = df.loc["2024-03-01":"2024-06-30"]
        self.assertTrue(
            (mar_limit["daily_limit"] == 300.0).all(),
            "Mar onwards should have open-ended limit (300.0)",
        )

    def test_open_ended_limit_at_start_of_range(self):
        """Test open-ended limit that starts at beginning of date range.
        测试在日期范围开始处开始的开放式限购。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create open-ended limit starting from the first date  # 创建从第一个日期开始的开放式限购
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-01-01",  # First date in range
                    "end_date": None,  # Open-ended
                    "max_amount": 50.0,
                    "reason": "Early open-ended limit",
                }
            ]
        )

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: All dates should have the limit
        self.assertTrue(
            (df["daily_limit"] == 50.0).all(),
            "All dates should have limit when open-ended limit starts at first date",
        )

    def test_no_limits_all_infinity(self):
        """Test that with no limit events, all dates have infinite limits.
        测试没有限购事件时，所有日期的限购为无限。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create empty limit events database  # 创建空的限购事件数据库
        self._create_limit_events_db([])

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: All dates should have no limit (inf)
        self.assertTrue(
            (df["daily_limit"] == float("inf")).all(),
            "All dates should have no limit (inf) when no events exist",
        )

    def test_overlapping_limits_last_one_wins(self):
        """Test behavior when limits overlap (last limit in sequence should apply).
        测试限购重叠时的行为（序列中的最后一个限购应生效）。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create overlapping limits
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-02-01",
                    "end_date": "2024-04-30",
                    "max_amount": 100.0,
                },
                {
                    "start_date": "2024-03-01",
                    "end_date": None,  # Open-ended, starts during first limit
                    "max_amount": 250.0,
                },
            ]
        )

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: Feb has first limit
        feb = df.loc["2024-02-01":"2024-02-29"]
        self.assertTrue(
            (feb["daily_limit"] == 100.0).all(), "Feb should have first limit"
        )

        # Verify: Mar onwards has second (open-ended) limit
        # The second limit overwrites the first where they overlap  # 第二个限购在重叠处覆盖第一个
        mar_onwards = df.loc["2024-03-01":"2024-06-30"]
        self.assertTrue(
            (mar_onwards["daily_limit"] == 250.0).all(),
            "Mar onwards should have second (open-ended) limit",
        )

    def test_pd_isna_vs_none_handling(self):
        """Test that pd.isna() correctly handles both None and NaT.
        测试 pd.isna() 正确处理 None 和 NaT。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create database with both None and explicit NULL
        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # Insert with NULL end_date  # 插入 NULL end_date
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            (self.ticker, "2024-03-01", None, 150.0, "NULL end_date test"),
        )

        conn.commit()
        conn.close()

        # Load data
        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify: Mar onwards should have limit
        mar_onwards = df.loc["2024-03-01":"2024-06-30"]
        self.assertTrue(
            (mar_onwards["daily_limit"] == 150.0).all(),
            "NULL end_date should be handled correctly",
        )

    def test_is_open_ended_computed_column(self):
        """Test that the is_open_ended computed column correctly identifies open-ended limits.
        测试 is_open_ended 计算列正确识别开放式限购。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create mix of open and closed limits  # 创建开放式和封闭式限购的混合
        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # Insert open-ended limit  # 插入开放式限购
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            (self.ticker, "2024-02-01", None, 100.0, "Open-ended"),
        )

        # Insert closed limit  # 插入封闭式限购
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            (self.ticker, "2024-05-01", "2024-05-31", 200.0, "Closed"),
        )

        conn.commit()

        # Verify computed column values
        cursor.execute(
            "SELECT id, end_date, is_open_ended FROM limit_events ORDER BY id"
        )
        results = cursor.fetchall()

        # First row: NULL end_date -> is_open_ended should be 1  # 第一行：NULL end_date -> is_open_ended 应为 1
        self.assertEqual(results[0][2], 1, "NULL end_date should have is_open_ended=1")

        # Second row: non-NULL end_date -> is_open_ended should be 0  # 第二行：非 NULL end_date -> is_open_ended 应为 0
        self.assertEqual(
            results[1][2], 0, "Non-NULL end_date should have is_open_ended=0"
        )

        conn.close()

    def test_date_filtering_with_open_ended_limits(self):
        """Test that date filtering works correctly with open-ended limits.
        测试日期筛选在开放式限购下正常工作。
        """
        # Setup
        self._create_market_data(self.ticker, self.date_range)
        self._create_nav_data(self.ticker, self.date_range)
        self._create_fee_config()

        # Create open-ended limit
        self._create_limit_events_db(
            [
                {
                    "start_date": "2024-02-15",
                    "end_date": None,
                    "max_amount": 400.0,
                }
            ]
        )

        # Load data with date filtering
        loader = DataLoader(str(self.data_dir))
        df_filtered = loader.load_bundle(
            self.ticker, start_date="2024-03-01", end_date="2024-04-30"
        ).df

        # Verify: All filtered dates are within open-ended limit
        self.assertTrue(
            (df_filtered["daily_limit"] == 400.0).all(),
            "Filtered dates within open-ended limit should have limit applied",
        )

        # Verify date range
        self.assertGreaterEqual(df_filtered.index[0], pd.Timestamp("2024-03-01"))
        self.assertLessEqual(df_filtered.index[-1], pd.Timestamp("2024-04-30"))

    def test_multiple_tickers_different_limits(self):
        """Test that different tickers can have different limit configurations.
        测试不同标的可以有不同的限购配置。
        """
        tickers = ["TICKA", "TICKB"]

        for ticker in tickers:
            self._create_market_data(ticker, self.date_range)
            self._create_nav_data(ticker, self.date_range)

        self._create_fee_config()

        # Create database with different limits for each ticker
        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # TICKA: Open-ended limit  # TICKA：开放式限购
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            ("TICKA", "2024-02-01", None, 100.0, "Open-ended"),
        )

        # TICKB: Closed limit  # TICKB：封闭式限购
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            ("TICKB", "2024-03-01", "2024-04-30", 200.0, "Closed"),
        )

        conn.commit()
        conn.close()

        # Load and verify
        loader = DataLoader(str(self.data_dir))

        # TICKA: Feb onwards has open-ended limit
        df_a = loader.load_bundle("TICKA").df
        self.assertTrue(
            (df_a.loc["2024-02-01":"2024-06-30", "daily_limit"] == 100.0).all(),
            "TICKA should have open-ended limit",
        )

        # TICKB: Mar-Apr has limit, May onwards is unlimited  # TICKB：3-4 月有限购，5 月起无限制
        df_b = loader.load_bundle("TICKB").df
        self.assertTrue(
            (df_b.loc["2024-03-01":"2024-04-30", "daily_limit"] == 200.0).all(),
            "TICKB should have closed limit Mar-Apr",
        )
        self.assertTrue(
            (df_b.loc["2024-05-01":"2024-06-30", "daily_limit"] == float("inf")).all(),
            "TICKB should have no limit after Apr",
        )


class TestOpenEndedLimitsEdgeCases(unittest.TestCase):
    """Edge case tests for open-ended limit handling.
    开放式限购处理的边缘情况测试。
    """

    def setUp(self):
        """Set up temporary test data directory.
        设置临时测试数据目录。
        """
        self.temp_dir = tempfile.mkdtemp(prefix="lof_test_edge_")
        self.data_dir = Path(self.temp_dir) / "data"

        (self.data_dir / "market").mkdir(parents=True)
        (self.data_dir / "nav").mkdir(parents=True)
        (self.data_dir / "config").mkdir(parents=True)

        self.ticker = "EDGE001"
        self.date_range = pd.bdate_range(start="2024-01-01", end="2024-03-31", freq="B")

    def tearDown(self):
        """Clean up temporary test data."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_basic_data(self):
        """Create basic market and NAV data.
        创建基本的行情和净值数据。
        """
        n_days = len(self.date_range)

        # Market data  # 行情数据
        df_market = pd.DataFrame(
            {
                "date": self.date_range,
                "ticker": self.ticker,
                "open": np.ones(n_days),
                "high": np.ones(n_days) * 1.1,
                "low": np.ones(n_days) * 0.9,
                "close": np.ones(n_days),
                "volume": np.ones(n_days, dtype=int) * 1000000,
            }
        )
        df_market.to_parquet(
            self.data_dir / "market" / f"{self.ticker}.parquet", index=False
        )

        # NAV data  # 净值数据
        df_nav = pd.DataFrame(
            {
                "date": self.date_range,
                "ticker": self.ticker,
                "nav": np.ones(n_days),
            }
        )
        df_nav.to_parquet(self.data_dir / "nav" / f"{self.ticker}.parquet", index=False)

        # Fee config  # 费率配置
        df_fee = pd.DataFrame(
            {
                "ticker": [self.ticker],
                "fee_rate_tier_1": [0.015],
                "fee_limit_1": [500000.0],
                "fee_rate_tier_2": [0.010],
                "fee_limit_2": [2000000.0],
                "fee_fixed": [1000.0],
                "redeem_fee_7d": [0.015],
            }
        )
        df_fee.to_csv(self.data_dir / "config" / "fees.csv", index=False)

    def test_open_ended_limit_at_exact_start_date(self):
        """Test limit starting at exact first date of available data.
        测试从可用数据的确切第一个日期开始的限购。
        """
        self._create_basic_data()

        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        # Start exactly on first date  # 从第一个日期确切开始
        first_date = self.date_range[0].strftime("%Y-%m-%d")
        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            (self.ticker, first_date, None, 50.0, "Exact start date"),
        )

        conn.commit()
        conn.close()

        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # All dates should have limit  # 所有日期都应有限购
        self.assertTrue(
            (df["daily_limit"] == 50.0).all(),
            "All dates should have limit when starting at exact first date",
        )

    def test_very_short_date_range(self):
        """Test with very short date range (5 days).
        测试非常短的日期范围（5 天）。
        """
        short_range = pd.bdate_range(start="2024-01-01", periods=5, freq="B")
        n_days = len(short_range)

        # Create short data  # 创建短期数据
        df_market = pd.DataFrame(
            {
                "date": short_range,
                "ticker": self.ticker,
                "open": np.ones(n_days),
                "high": np.ones(n_days) * 1.1,
                "low": np.ones(n_days) * 0.9,
                "close": np.ones(n_days),
                "volume": np.ones(n_days, dtype=int) * 1000000,
            }
        )
        df_market.to_parquet(
            self.data_dir / "market" / f"{self.ticker}.parquet", index=False
        )

        df_nav = pd.DataFrame(
            {
                "date": short_range,
                "ticker": self.ticker,
                "nav": np.ones(n_days),
            }
        )
        df_nav.to_parquet(self.data_dir / "nav" / f"{self.ticker}.parquet", index=False)

        df_fee = pd.DataFrame(
            {
                "ticker": [self.ticker],
                "fee_rate_tier_1": [0.015],
                "fee_limit_1": [500000.0],
                "fee_rate_tier_2": [0.010],
                "fee_limit_2": [2000000.0],
                "fee_fixed": [1000.0],
                "redeem_fee_7d": [0.015],
            }
        )
        df_fee.to_csv(self.data_dir / "config" / "fees.csv", index=False)

        # Open-ended limit from day 3  # 从第 3 天开始的开放式限购
        db_path = self.data_dir / "config" / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
            VALUES (?, ?, ?, ?, ?)""",
            (self.ticker, "2024-01-03", None, 75.0, "Short range test"),
        )

        conn.commit()
        conn.close()

        loader = DataLoader(str(self.data_dir))
        df = loader.load_bundle(self.ticker).df

        # Verify split  # 验证分割
        self.assertEqual(df.loc["2024-01-01", "daily_limit"], float("inf"))
        self.assertEqual(df.loc["2024-01-02", "daily_limit"], float("inf"))
        self.assertEqual(df.loc["2024-01-03", "daily_limit"], 75.0)
        self.assertEqual(df.loc["2024-01-04", "daily_limit"], 75.0)


def run_tests():
    """Run all tests and print results.
    运行所有测试并打印结果。
    """
    # Create test suite  # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes  # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestOpenEndedLimits))
    suite.addTests(loader.loadTestsFromTestCase(TestOpenEndedLimitsEdgeCases))

    # Run tests  # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code  # 返回退出码
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
