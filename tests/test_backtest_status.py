"""
Phase E: the backtest on daily_status -- loader, unknown_policy, n_accounts, bounds attribution.

阶段 E：回测接入 daily_status。
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import BacktestConfig  # noqa: E402
from src.data.loader import DataLoader  # noqa: E402
from src.engine.backtest import BacktestEngine, effective_daily_limit  # noqa: E402
from src.evaluation.attribution import pnl_by, trips_with_status  # noqa: E402
from src.pipeline.timeline import DAILY_STATUS_SCHEMA  # noqa: E402
from src.strategy.simple_lof import SimpleLOFStrategy  # noqa: E402

DAYS = pd.bdate_range("2024-03-01", "2024-03-29")


class TempData(unittest.TestCase):
    """A data dir with flat prices, NAV 1.0 and close 1.05 (a 5% premium every day)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lof_e_")
        self.dir = Path(self.tmp)
        for d in ("market", "nav", "config"):
            (self.dir / d).mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fund(self, ticker, close=1.05, nav=1.0, nav_gap=None):
        n = len(DAYS)
        pd.DataFrame({"date": DAYS, "ticker": ticker, "open": close, "high": close, "low": close,
                      "close": np.full(n, close), "volume": np.full(n, 10_000_000.0)}).to_parquet(
            self.dir / "market" / f"{ticker}.parquet", index=False)
        navs = np.full(n, nav)
        if nav_gap is not None:
            navs[nav_gap] = np.nan
        pd.DataFrame({"date": DAYS, "ticker": ticker, "nav": navs}).to_parquet(
            self.dir / "nav" / f"{ticker}.parquet", index=False)

    def status(self, ticker, rows):
        """rows: {date: (status, amount, source)}; days not listed are absent from the table."""
        conn = sqlite3.connect(self.dir / "config" / "subscription_state.db")
        conn.executescript(DAILY_STATUS_SCHEMA)
        conn.executemany("INSERT INTO daily_status (fund_code, date, status, amount, source) VALUES (?, ?, ?, ?, ?)",
                         [(ticker, d, s, a, src) for d, (s, a, src) in rows.items()])
        conn.commit()
        conn.close()


class TestLoader(TempData):
    def test_auto_uses_daily_status_and_keeps_unknown_as_nan(self):
        self.fund("160723", nav_gap=3)
        self.status("160723", {"2024-03-01": ("open", None, "change"), "2024-03-04": ("limited", 100.0, "change"),
                               "2024-03-05": ("limited", None, "restatement"), "2024-03-06": ("unknown", None, "default"),
                               "2024-03-07": ("closed", None, "overlay")})
        loader = DataLoader(str(self.dir))
        self.assertEqual(loader.limits, "daily_status")
        df = loader.load_bundle("160723").df
        self.assertEqual(df.loc["2024-03-01", "daily_limit"], np.inf)
        self.assertEqual(df.loc["2024-03-04", "daily_limit"], 100.0)
        self.assertTrue(np.isnan(df.loc["2024-03-05", "daily_limit"]))       # limit without an amount
        self.assertTrue(np.isnan(df.loc["2024-03-06", "daily_limit"]))       # unknown: not yesterday's 100
        self.assertEqual(df.loc["2024-03-07", "daily_limit"], 0.0)
        self.assertEqual(df.loc["2024-03-08", "sub_status"], "unknown")      # no row at all
        self.assertEqual(df.loc["2024-03-08", "status_source"], "default")
        self.assertEqual(df.loc["2024-03-06", "nav"], 1.0)                   # market/NAV gaps are still filled

    def test_legacy_fallback_and_explicit_source(self):
        self.fund("160723")
        loader = DataLoader(str(self.dir))
        self.assertEqual(loader.limits, "legacy")
        df = loader.load_bundle("160723").df
        self.assertTrue((df["daily_limit"] == np.inf).all())
        self.assertEqual(set(df["status_source"]), {"legacy"})
        with self.assertRaises(FileNotFoundError):
            DataLoader(str(self.dir), limits="daily_status")
        with self.assertRaises(ValueError):
            DataLoader(str(self.dir), limits="gold")


class TestPolicy(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({
            "daily_limit":   [np.inf, 0.0, 100.0, np.nan, np.nan, np.inf, 500.0, 0.0, 300.0],
            "status_source": ["change", "overlay", "change", "default", "restatement", "inferred_open",
                              "inferred_prior", "inferred_prior", "legacy"],
        })

    def test_conservative_bound_buys_only_on_proven_days(self):
        cap = effective_daily_limit(self.frame(), "closed", 1).tolist()
        self.assertEqual(cap, [np.inf, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 300.0])

    def test_optimistic_bound_and_accounts(self):
        cap = effective_daily_limit(self.frame(), "open", 2).tolist()
        self.assertEqual(cap, [np.inf, 0.0, 200.0, np.inf, np.inf, np.inf, 1000.0, 0.0, 600.0])

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            BacktestConfig(unknown_policy="maybe")
        with self.assertRaises(ValueError):
            BacktestConfig(n_accounts=0)


class TestEngine(TempData):
    def run_policy(self, policy, **kw):
        cfg = BacktestConfig(initial_cash=100_000, buy_threshold=0.017, unknown_policy=policy, **kw)
        return BacktestEngine(cfg, SimpleLOFStrategy(), DataLoader(str(self.dir))).run(["160723"])

    def test_bounds_differ_only_on_unproven_days(self):
        self.fund("160723")
        rows = {d.strftime("%Y-%m-%d"): ("unknown", None, "default") for d in DAYS}
        rows["2024-03-04"] = ("limited", 1000.0, "change")
        rows["2024-03-11"] = ("open", None, "inferred_open")
        rows["2024-03-18"] = ("closed", None, "overlay")
        self.status("160723", rows)
        buys = lambda r: r.trade_logs[r.trade_logs["action"] == "buy"]
        low = buys(self.run_policy("closed"))
        self.assertEqual(low["date"].astype(str).tolist(), ["2024-03-04"])
        self.assertEqual(low["amount"].tolist(), [1000.0])
        self.assertEqual((low["sub_status"].tolist(), low["status_source"].tolist()), (["limited"], ["change"]))
        high = set(buys(self.run_policy("open"))["date"].astype(str))
        self.assertNotIn("2024-03-18", high)                    # closed stays closed
        self.assertTrue({"2024-03-05", "2024-03-11"} <= high)   # an unknown day and an inferred_open day
        self.assertNotIn("2024-03-01", high)                    # no NAV visible yet on the first day
        self.assertEqual(buys(self.run_policy("closed", n_accounts=3))["amount"].tolist(), [3000.0])

    def test_same_data_same_result(self):
        self.fund("160723")
        self.status("160723", {d.strftime("%Y-%m-%d"): ("limited", 5000.0, "change") for d in DAYS})
        a, b = self.run_policy("closed"), self.run_policy("closed")
        pd.testing.assert_frame_equal(a.trade_logs, b.trade_logs)
        pd.testing.assert_frame_equal(a.daily_perf, b.daily_perf)

    def test_attribution_by_status_source(self):
        self.fund("160723")
        rows = {d.strftime("%Y-%m-%d"): ("limited", 1000.0, "change") for d in DAYS}
        rows["2024-03-11"] = ("open", None, "inferred_open")
        self.status("160723", rows)
        trips = trips_with_status(self.run_policy("open").trade_logs)
        by = pnl_by(trips, "status_source").set_index("status_source")
        self.assertEqual(int(by.loc["inferred_open", "trips"]), 1)
        self.assertEqual(int(by["trips"].sum()), len(trips))


if __name__ == "__main__":
    unittest.main()
