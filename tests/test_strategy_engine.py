"""
The engine trades through the strategy: it asks BaseStrategy.generate_signals every fund-day
and enforces the purchase limit, liquidity, cash and per-order caps on what comes back.

引擎通过策略交易：每个基金日调用 generate_signals，再对返回的信号施加限额、流动性、现金和单笔上限。
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
from src.engine.backtest import BacktestEngine  # noqa: E402
from src.pipeline.timeline import DAILY_STATUS_SCHEMA  # noqa: E402
from src.strategy.base import BaseStrategy, Signal  # noqa: E402
from src.strategy.simple_lof import SimpleLOFStrategy  # noqa: E402

DAYS = pd.bdate_range("2024-03-01", "2024-03-29")


class Recorder(BaseStrategy):
    """Records what it is shown; trades nothing unless told to."""

    def __init__(self, buy_amount=None, buy_on=None, sell=False):
        self.calls = []
        self.buy_amount, self.buy_on, self.sell = buy_amount, buy_on, sell

    def generate_signals(self, row, positions, config):
        day = row.name.strftime("%Y-%m-%d")
        self.calls.append((day, row["ticker"], dict(positions), row["daily_limit"]))
        signals = []
        if self.sell and positions.get(row["ticker"], 0) > 0:
            signals.append(Signal("sell", row["ticker"], float("inf")))
        if self.buy_amount and (self.buy_on is None or day in self.buy_on):
            signals.append(Signal("buy", row["ticker"], self.buy_amount))
        return signals


class Engine(unittest.TestCase):
    """Flat close 1.05 and NAV 1.0 (a 5% premium every day), volume 10 million."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lof_strat_")
        self.dir = Path(self.tmp)
        for d in ("market", "nav", "config"):
            (self.dir / d).mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fund(self, ticker, status=None):
        """status: {date: (status, amount)}; days not listed are open."""
        n = len(DAYS)
        pd.DataFrame({"date": DAYS, "ticker": ticker, "open": 1.05, "high": 1.05, "low": 1.05,
                      "close": np.full(n, 1.05), "volume": np.full(n, 10_000_000.0)}).to_parquet(
            self.dir / "market" / f"{ticker}.parquet", index=False)
        pd.DataFrame({"date": DAYS, "ticker": ticker, "nav": np.full(n, 1.0)}).to_parquet(
            self.dir / "nav" / f"{ticker}.parquet", index=False)
        status = status or {}
        rows = [(ticker, d.strftime("%Y-%m-%d"), *status.get(d.strftime("%Y-%m-%d"), ("open", None)), "change")
                for d in DAYS]
        conn = sqlite3.connect(self.dir / "config" / "subscription_state.db")
        conn.executescript(DAILY_STATUS_SCHEMA)
        conn.executemany("INSERT INTO daily_status (fund_code, date, status, amount, source) VALUES (?, ?, ?, ?, ?)",
                         rows)
        conn.commit()
        conn.close()

    def run_with(self, strategy, tickers=("160001",), **kw):
        cfg = BacktestConfig(initial_cash=kw.pop("initial_cash", 1_000_000), buy_threshold=0.017, **kw)
        return BacktestEngine(cfg, strategy, DataLoader(str(self.dir))).run(list(tickers))

    @staticmethod
    def actions(result, action):
        logs = result.trade_logs
        return logs[logs["action"] == action] if not logs.empty else logs


class TestStrategyIsUsed(Engine):
    def test_called_every_fund_day_and_nothing_traded_without_signals(self):
        self.fund("160001")
        self.fund("160002")
        rec = Recorder()
        result = self.run_with(rec, tickers=("160001", "160002"))
        self.assertEqual(len(rec.calls), 2 * len(DAYS))
        self.assertTrue(result.trade_logs.empty)

    def test_a_strategy_can_hold(self):
        self.fund("160001")
        rec = Recorder(buy_amount=10_000, buy_on={"2024-03-04"})   # buy once, never sell
        result = self.run_with(rec)
        self.assertEqual(len(self.actions(result, "buy")), 1)
        self.assertEqual(len(self.actions(result, "sell")), 0)
        self.assertGreater(result.daily_perf["positions_value"].iloc[-1], 0)

    def test_positions_are_settled_shares_only(self):
        self.fund("160001")
        rec = Recorder(buy_amount=10_000, buy_on={"2024-03-04"})
        self.run_with(rec)
        seen = {day: pos.get("160001", 0) for day, _, pos, _ in rec.calls}
        self.assertEqual(seen["2024-03-05"], 0)        # pending: bought 03-04, sellable at T+2
        self.assertGreater(seen["2024-03-06"], 0)

    def test_signal_for_another_fund_is_an_error(self):
        self.fund("160001")

        class Wrong(BaseStrategy):
            def generate_signals(self, row, positions, config):
                return [Signal("buy", "999999", 100.0)]

        with self.assertRaises(ValueError):
            self.run_with(Wrong())


class TestEngineCaps(Engine):
    def test_limit_closed_and_per_order_caps_apply_to_any_strategy(self):
        self.fund("160001", {"2024-03-04": ("limited", 1000.0), "2024-03-05": ("closed", None)})
        rec = Recorder(buy_amount=1e9, buy_on={"2024-03-04", "2024-03-05", "2024-03-06"})
        buys = self.actions(self.run_with(rec), "buy")
        buys = buys.set_index(pd.to_datetime(buys["date"]))
        self.assertEqual(buys.loc["2024-03-04", "amount"], 1000.0)
        self.assertNotIn(pd.Timestamp("2024-03-05"), buys.index)
        self.assertEqual(buys.loc["2024-03-06", "amount"], 100_000.0)   # per-order cap
        self.assertEqual(rec.calls[0][3], np.inf)                        # the strategy sees the cap

    def test_buy_signals_for_one_fund_merge_into_one_order(self):
        self.fund("160001", {"2024-03-04": ("limited", 1000.0)})

        class Twice(BaseStrategy):
            def generate_signals(self, row, positions, config):
                if row.name == pd.Timestamp("2024-03-04"):
                    return [Signal("buy", row["ticker"], 600.0), Signal("buy", row["ticker"], 700.0)]
                return []

        buys = self.actions(self.run_with(Twice()), "buy")
        self.assertEqual(buys["amount"].tolist(), [1000.0])

    def test_buys_go_highest_premium_first(self):
        self.fund("160001")
        self.fund("160002")
        n = len(DAYS)
        pd.DataFrame({"date": DAYS, "ticker": "160002", "open": 1.10, "high": 1.10, "low": 1.10,
                      "close": np.full(n, 1.10), "volume": np.full(n, 10_000_000.0)}).to_parquet(
            self.dir / "market" / "160002.parquet", index=False)
        logs = self.actions(self.run_with(SimpleLOFStrategy(), tickers=("160001", "160002"), initial_cash=50_000),
                            "buy")
        first_day = logs[logs["date"] == logs["date"].min()]
        self.assertEqual(first_day["ticker"].tolist(), ["160002"])        # the cash went to the 10% premium


class TestSimpleStrategy(Engine):
    def test_max_premium_rate_is_a_strategy_rule(self):
        self.fund("160001")
        self.assertFalse(self.actions(self.run_with(SimpleLOFStrategy()), "buy").empty)
        self.assertTrue(self.run_with(SimpleLOFStrategy(), max_premium_rate=0.03).trade_logs.empty)


if __name__ == "__main__":
    unittest.main()
