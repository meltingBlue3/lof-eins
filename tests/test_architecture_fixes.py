"""
Tests verifying architecture and design fixes.

架构和设计修复的验证测试。

Covers:
覆盖：
- BundleResult NamedTuple from DataLoader  # DataLoader 的 BundleResult NamedTuple
- generate_mock_data with custom output_dir  # 带自定义 output_dir 的 generate_mock_data
- T+2 settlement sell-all-settled behavior  # T+2 结算的卖出已结算份额行为
- Trade markers case consistency  # 交易标记的大小写一致性
"""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.loader import DEFAULT_FEES, BundleResult, DataLoader
from src.engine.account import Account
from src.engine.backtest import (
    BacktestEngine,
    BacktestResult,
    calculate_subscription_fee,
)
from src.config import BacktestConfig
from src.pipeline.timeline import DAILY_STATUS_SCHEMA
from src.strategy.simple_lof import SimpleLOFStrategy


def write_status(base: Path, ticker: str, dates, status: str = "open") -> None:
    """daily_status rows for one fund, one per date, all with the same status."""
    conn = sqlite3.connect(base / "config" / "subscription_state.db")
    conn.executescript(DAILY_STATUS_SCHEMA)
    conn.executemany("INSERT INTO daily_status (fund_code, date, status, amount, source) VALUES (?, ?, ?, NULL, 'change')",
                     [(ticker, d.strftime("%Y-%m-%d"), status) for d in dates])
    conn.commit()
    conn.close()


def write_terms(base: Path, tiers_by_ticker: dict) -> None:
    """A fund_terms.csv as scripts/fund_terms.py writes it, for domestic funds."""
    import json

    rows = [{"ticker": t, "name": "", "fund_type": "", "buy_confirm_days": 1, "sub_fee_tiers": json.dumps(tiers),
             "error": "", "sell_days": 2, "sell_days_basis": "confirm", "nav_lag": 1,
             "sub_fee_rate_1": tiers[0][1], "source": "eastmoney_jjfl", "fetched_at": "2026-11-19"}
            for t, tiers in tiers_by_ticker.items()]
    pd.DataFrame(rows).to_csv(base / "config" / "fund_terms.csv", index=False)


class TestBundleResult(unittest.TestCase):
    """Test that BundleResult NamedTuple works correctly.
    测试 BundleResult NamedTuple 正常工作。
    """

    def test_bundle_result_is_namedtuple(self):
        """BundleResult should be a NamedTuple with df and fee_config fields.
        BundleResult 应该是带有 df 和 fee_config 字段的 NamedTuple。
        """
        df = pd.DataFrame({"a": [1, 2]})
        fees = {"fee_rate_tier_1": 0.015}
        result = BundleResult(df=df, fee_config=fees)

        self.assertIs(result.df, df)
        self.assertIs(result.fee_config, fees)
        # Destructuring should work  # 解构应该工作
        unpacked_df, unpacked_fees = result
        self.assertIs(unpacked_df, df)
        self.assertIs(unpacked_fees, fees)

    def test_bundle_result_fee_config_survives_df_operations(self):
        """Fee config should not be lost when the DataFrame is copied/sliced.
        当 DataFrame 被复制/切片时，费率配置不应丢失。
        """
        df = pd.DataFrame({"close": [1.0, 2.0], "nav": [0.9, 1.8]})
        fees = {"fee_rate_tier_1": 0.015, "fee_limit_1": 500000}
        result = BundleResult(df=df, fee_config=fees)

        # Simulate operations that would lose df.attrs  # 模拟会导致 df.attrs 丢失的操作
        new_df = result.df.copy()
        new_df = new_df[new_df["close"] > 1.0]

        # fee_config is still accessible from the original result  # fee_config 仍可从原始结果访问
        self.assertEqual(result.fee_config["fee_rate_tier_1"], 0.015)


class TestDataLoaderReturnsBundleResult(unittest.TestCase):
    """Test that DataLoader.load_bundle returns BundleResult.
    测试 DataLoader.load_bundle 返回 BundleResult。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        base = Path(self.tmpdir)

        # Create directory structure  # 创建目录结构
        (base / "market").mkdir()
        (base / "nav").mkdir()
        (base / "config").mkdir()

        # Create market data  # 创建行情数据
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        market_df = pd.DataFrame(
            {
                "date": dates,
                "open": [1.0] * 5,
                "high": [1.1] * 5,
                "low": [0.9] * 5,
                "close": [1.05] * 5,
                "volume": [10000] * 5,
            }
        )
        market_df.to_parquet(base / "market" / "TEST01.parquet", index=False)

        # Create NAV data  # 创建净值数据
        nav_df = pd.DataFrame(
            {
                "date": dates,
                "nav": [1.0] * 5,
            }
        )
        nav_df.to_parquet(base / "nav" / "TEST01.parquet", index=False)

        # Trading terms for TEST01 only, and an open status every day  # 仅 TEST01 有交易条款；每天都可申购
        write_terms(base, {"TEST01": [[1_000_000.0, 0.012, None], [None, None, 1000.0]]})
        write_status(base, "TEST01", dates)

        self.loader = DataLoader(data_dir=self.tmpdir)

    def test_load_bundle_returns_bundle_result(self):
        """load_bundle should return a BundleResult.
        load_bundle 应该返回 BundleResult。
        """
        result = self.loader.load_bundle("TEST01")
        self.assertIsInstance(result, BundleResult)
        self.assertIsInstance(result.df, pd.DataFrame)
        self.assertIsInstance(result.fee_config, dict)

    def test_load_bundle_fee_config_has_correct_values(self):
        """Fee config is the fund's own tiers from fund_terms.csv, or the defaults.
        费率配置是 fund_terms.csv 中该基金自己的费率表，没有时用默认费率。
        """
        result = self.loader.load_bundle("TEST01")
        self.assertEqual(result.fee_config["sub_fee_tiers"][0], [1_000_000.0, 0.012, None])
        self.assertEqual(result.fee_config["fee_formula"], "net")
        self.assertEqual(self.loader.load_fees("OTHER"), DEFAULT_FEES)

    def test_load_bundle_df_has_expected_columns(self):
        """DataFrame should have all expected columns.
        DataFrame 应该包含所有预期的列。
        """
        result = self.loader.load_bundle("TEST01")
        expected_cols = {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "nav",
            "premium_rate",
            "daily_limit",
        }
        self.assertTrue(expected_cols.issubset(set(result.df.columns)))


class TestGenerateMockDataOutputDir(unittest.TestCase):
    """Test that generate_mock_data accepts custom output_dir.
    测试 generate_mock_data 接受自定义 output_dir。
    """

    def test_custom_output_dir(self):
        """generate_mock_data should write to the specified output_dir.
        generate_mock_data 应该写入指定的 output_dir。
        """
        from src.data.generator import MockConfig, generate_mock_data

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MockConfig(
                tickers=["TEST01"],
                start_date="2024-01-01",
                end_date="2024-03-01",
            )
            generate_mock_data(config, output_dir=tmpdir)

            # Verify files were created in the custom directory  # 验证文件已在自定义目录中创建
            self.assertTrue((Path(tmpdir) / "market" / "TEST01.parquet").exists())
            self.assertTrue((Path(tmpdir) / "nav" / "TEST01.parquet").exists())
            db = Path(tmpdir) / "config" / "subscription_state.db"
            self.assertTrue(db.exists())
            self.assertFalse((Path(tmpdir) / "config" / "fees.csv").exists())
            conn = sqlite3.connect(db)
            n_days = len(pd.read_parquet(Path(tmpdir) / "market" / "TEST01.parquet"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_status WHERE fund_code = 'TEST01'").fetchone()[0],
                             n_days)
            conn.close()


class TestT2SettlementSellBehavior(unittest.TestCase):
    """Test that the backtest engine correctly sells only T+2 settled shares.
    测试回测引擎正确地仅卖出 T+2 已结算份额。
    """

    def test_sell_only_settled_shares(self):
        """Shares bought on T should only be sold on T+2, not earlier.
        在 T 日买入的份额只能从 T+2 日起卖出，不能更早。
        """
        account = Account(cash=100000.0)
        trading_days = [
            date(2024, 1, 1),
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 4),
            date(2024, 1, 5),
        ]

        # Day 1: Buy
        account.update_date(trading_days[0])
        shares_d1 = account.buy(
            ticker="TEST",
            amount=50000,
            nav=1.0,
            fee=750,
            trading_days=trading_days,
        )

        # Day 2: Buy again, check nothing settled yet  # 第 2 天：再次买入，检查尚无已结算
        account.update_date(trading_days[1])
        self.assertEqual(account.get_available_shares("TEST"), 0.0)
        shares_d2 = account.buy(
            ticker="TEST",
            amount=30000,
            nav=1.0,
            fee=450,
            trading_days=trading_days,
        )

        # Day 3 (T+2 for day 1 purchase): Only day-1 shares should be settled  # 第 3 天（第 1 天买入的 T+2）：仅第 1 天份额应已结算
        account.update_date(trading_days[2])
        available = account.get_available_shares("TEST")
        self.assertAlmostEqual(available, shares_d1)

        # Day 4 (T+2 for day 2 purchase): Now day-2 shares also settle  # 第 4 天（第 2 天买入的 T+2）：现在第 2 天份额也已结算
        account.update_date(trading_days[3])
        available = account.get_available_shares("TEST")
        self.assertAlmostEqual(available, shares_d1 + shares_d2)

    def test_sell_does_not_affect_pending_shares(self):
        """Selling settled shares should not touch pending shares.
        卖出已结算份额不应影响待结算份额。
        """
        account = Account(cash=100000.0)
        trading_days = [
            date(2024, 1, 1),
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 4),
            date(2024, 1, 5),
        ]

        # Day 1: Buy
        account.update_date(trading_days[0])
        shares_d1 = account.buy(
            ticker="TEST",
            amount=50000,
            nav=1.0,
            fee=750,
            trading_days=trading_days,
        )

        # Day 2: Buy again
        account.update_date(trading_days[1])
        shares_d2 = account.buy(
            ticker="TEST",
            amount=30000,
            nav=1.0,
            fee=450,
            trading_days=trading_days,
        )

        # Day 3: Sell all settled (day-1 shares only)  # 第 3 天：卖出所有已结算份额（仅第 1 天份额）
        account.update_date(trading_days[2])
        settled = account.get_available_shares("TEST")
        self.assertAlmostEqual(settled, shares_d1)
        account.sell(ticker="TEST", shares=settled, price=1.05, commission_rate=0.0003)

        # After selling, pending (day-2) shares should still be there  # 卖出后，待结算（第 2 天）份额应仍在
        pending = account.get_pending_shares("TEST")
        self.assertAlmostEqual(pending, shares_d2)
        self.assertAlmostEqual(account.get_available_shares("TEST"), 0.0)

        # Day 4: Day-2 shares settle  # 第 4 天：第 2 天份额已结算
        account.update_date(trading_days[3])
        self.assertAlmostEqual(account.get_available_shares("TEST"), shares_d2)


class TestTradeLogActionCase(unittest.TestCase):
    """Test that trade log actions use lowercase consistently.
    测试交易日志操作一致使用小写。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        base = Path(self.tmpdir)

        (base / "market").mkdir()
        (base / "nav").mkdir()
        (base / "config").mkdir()

        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        market_df = pd.DataFrame(
            {
                "date": dates,
                "open": np.random.uniform(0.9, 1.1, 10),
                "high": np.random.uniform(1.0, 1.2, 10),
                "low": np.random.uniform(0.8, 1.0, 10),
                "close": [1.1]
                * 10,  # Always above NAV to trigger buys  # 始终高于净值以触发买入
                "volume": [100000] * 10,
            }
        )
        market_df.to_parquet(base / "market" / "TEST01.parquet", index=False)

        nav_df = pd.DataFrame(
            {
                "date": dates,
                "nav": [1.0] * 10,
            }
        )
        nav_df.to_parquet(base / "nav" / "TEST01.parquet", index=False)

        write_status(base, "TEST01", dates)

    def test_trade_actions_are_lowercase(self):
        """All trade log action values should be lowercase 'buy' or 'sell'.
        所有交易日志操作值应为小写的 'buy' 或 'sell'。
        """
        config = BacktestConfig(
            initial_cash=100000,
            buy_threshold=0.05,
            liquidity_ratio=0.1,
        )
        engine = BacktestEngine(
            config=config,
            strategy=SimpleLOFStrategy(),
            data_loader=DataLoader(data_dir=self.tmpdir),
        )
        result = engine.run("TEST01")

        self.assertFalse(result.trade_logs.empty)
        if not result.trade_logs.empty:
            actions = result.trade_logs["action"].unique()
            for action in actions:
                self.assertIn(
                    action, ("buy", "sell"), f"Action '{action}' should be lowercase"
                )


class TestCalculateSubscriptionFee(unittest.TestCase):
    """Test that calculate_subscription_fee works with plain dict (not df.attrs).
    测试 calculate_subscription_fee 使用普通字典（而非 df.attrs）工作。
    """

    def test_tier_1(self):
        fee_config = {
            "fee_rate_tier_1": 0.015,
            "fee_limit_1": 500000,
            "fee_limit_2": 2000000,
            "fee_fixed": 1000,
        }
        self.assertAlmostEqual(calculate_subscription_fee(100000, fee_config), 1500.0)

    def test_tier_2(self):
        fee_config = {
            "fee_rate_tier_1": 0.015,
            "fee_limit_1": 500000,
            "fee_rate_tier_2": 0.01,
            "fee_limit_2": 2000000,
            "fee_fixed": 1000,
        }
        self.assertAlmostEqual(calculate_subscription_fee(1000000, fee_config), 10000.0)

    def test_fixed_tier(self):
        fee_config = {
            "fee_rate_tier_1": 0.015,
            "fee_limit_1": 500000,
            "fee_rate_tier_2": 0.01,
            "fee_limit_2": 2000000,
            "fee_fixed": 1000,
        }
        self.assertAlmostEqual(calculate_subscription_fee(3000000, fee_config), 1000.0)

    def test_default_values_on_empty_dict(self):
        """Should use defaults when fee_config is empty.
        当 fee_config 为空时应使用默认值。
        """
        fee = calculate_subscription_fee(100000, {})
        self.assertAlmostEqual(fee, 100000 * 0.015)


if __name__ == "__main__":
    unittest.main()
