"""
Phase F: trading terms -- fee tiers, sell days, and the decision premium without look-ahead.

阶段 F：交易条款（申购费率、可卖日）与无前视的决策溢价。
"""

import math
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
from src.data import fund_terms  # noqa: E402
from src.data.loader import DataLoader  # noqa: E402
from src.engine.backtest import BacktestEngine, calculate_subscription_fee  # noqa: E402
from src.evaluation.attribution import fee_band  # noqa: E402
from src.pipeline.timeline import DAILY_STATUS_SCHEMA  # noqa: E402
from src.strategy.simple_lof import SimpleLOFStrategy  # noqa: E402

DAYS = pd.bdate_range("2024-03-01", "2024-03-29")


def page(name, fund_type, confirm, fee_rows):
    """A minimal jjfl page: the bits the parser reads, wrapped in tags like the real one."""
    confirm_html = (f"<td>买入确认日</td><td>T+{confirm}</td><td>卖出确认日</td><td>T+{confirm}</td>"
                    if confirm else "<p>交易确认日</p><p>该基金尚未开通天天基金代销，暂无相关数据。</p>")
    rows = "".join(f"<tr><td>{c}</td><td>{r}&nbsp;&nbsp;|&nbsp;&nbsp;0.15%</td></tr>" for c, r in fee_rows)
    return (f"<html><body><div>天天基金网 &nbsp;>&nbsp; 基金档案 &nbsp;>&nbsp;{name} 手机访问当前基金品种页</div>"
            f"<p>类型：</p><p>{fund_type}</p>{confirm_html}<h4>认购费率</h4><table><tr><td>适用金额</td><td>费率</td></tr>"
            f"<tr><td>小于100万元</td><td>1.20%</td></tr></table><h4>申购费率</h4><table><tr><td>适用金额</td>"
            f"<td>原费率 | 天天基金优惠费率</td></tr>{rows}</table><p>友情提示：</p><h4>赎回费率</h4>"
            f"<tr><td>小于7天</td><td>1.50%</td></tr></body></html>")


DOMESTIC = page("某某成长混合(LOF)A", "混合型-偏股", 1,
                [("小于100万元", "1.50%"), ("大于等于100万元，小于500万元", "1.00%"), ("大于等于500万元", "每笔1000元")])
QDII = page("某某原油(QDII-LOF)", "QDII-商品", 2, [("小于50万元", "1.20%"), ("大于等于50万元", "每笔1000元")])


class TestParser(unittest.TestCase):
    def test_domestic_page(self):
        t = fund_terms.parse_fee_page("160001", DOMESTIC)
        self.assertEqual((t.name, t.fund_type, t.buy_confirm_days, t.error), ("某某成长混合(LOF)A", "混合型-偏股", 1, ""))
        self.assertEqual(t.sub_fee_tiers, [[1_000_000.0, 0.015, None], [5_000_000.0, 0.01, None], [None, None, 1000.0]])
        self.assertEqual((t.sell_days, t.nav_lag, t.sell_days_basis), (2, 1, "confirm"))

    def test_qdii_page(self):
        t = fund_terms.parse_fee_page("160002", QDII)
        self.assertEqual(t.sub_fee_tiers[0], [500_000.0, 0.012, None])
        self.assertEqual((t.sell_days, t.nav_lag), (3, 2))

    def test_single_row_table_and_missing_confirmation(self):
        t = fund_terms.parse_fee_page("160003", page("某某定开混合", "QDII-普通股票", None, [("---", "1.20%")]))
        self.assertEqual(t.sub_fee_tiers, [[None, 0.012, None]])
        self.assertEqual((t.buy_confirm_days, t.sell_days, t.sell_days_basis, t.nav_lag), (None, 3, "type", 2))

    def test_zero_fee_only_on_c_shares(self):
        c = fund_terms.parse_fee_page("160005", page("某某债券(LOF)C", "债券型-混合一级", 1, [("---", "0.00%")]))
        self.assertEqual((c.sub_fee_tiers, c.error), ([[None, 0.0, None]], ""))
        a = fund_terms.parse_fee_page("160006", page("某某指数(LOF)A", "指数型-股票", 1, [("---", "0.00%")]))
        self.assertIn("zero fee", a.error)
        self.assertEqual(fund_terms.parse_fee_page("160004", "<html>维护中</html>").error, "no subscription fee table")

    def test_csv_round_trip(self):
        tmp = Path(tempfile.mkdtemp(prefix="lof_f_"))
        try:
            (tmp / "jjfl_160001.html").write_text(DOMESTIC, encoding="utf-8")
            (tmp / "jjfl_160004.html").write_text("<html></html>", encoding="utf-8")
            df = fund_terms.build_terms(["160001", "160004", "160009"], tmp)
            self.assertEqual(df.set_index("ticker").loc["160009", "error"], "page not fetched")
            df.to_csv(tmp / "fund_terms.csv", index=False)
            terms = fund_terms.read_terms(tmp / "fund_terms.csv")
            self.assertEqual(set(terms), {"160001"})                  # rows with errors are dropped
            self.assertEqual(terms["160001"]["sub_fee_tiers"][-1], [math.inf, None, 1000.0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fee_change_notices(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE announcements (fund_code TEXT, announce_date TEXT, title TEXT)")
        conn.executemany("INSERT INTO announcements VALUES (?, ?, ?)", [
            ("160001", "2024-05-01", "关于调低旗下部分基金申购费率并修订基金合同的公告"),
            ("160001", "2024-06-01", "关于旗下基金参加某银行申购费率优惠活动的公告"),
            ("160001", "2021-06-01", "关于调低旗下部分基金申购费率的公告")])
        self.assertEqual(fund_terms.fee_change_notices(conn, "2022-01-01", "2024-12-31")["announce_date"].tolist(),
                         ["2024-05-01"])


class TestFee(unittest.TestCase):
    TIERS = {"sub_fee_tiers": [[1_000_000.0, 0.012, None], [math.inf, None, 1000.0]], "fee_formula": "net"}

    def test_fund_tiers_use_the_prospectus_formula(self):
        self.assertAlmostEqual(calculate_subscription_fee(100_000, self.TIERS), 100_000 - 100_000 / 1.012)
        self.assertEqual(calculate_subscription_fee(2_000_000, self.TIERS), 1000.0)

    def test_discount_scales_rates_not_fixed_fees(self):
        self.assertAlmostEqual(calculate_subscription_fee(100_000, self.TIERS, 0.1), 100_000 - 100_000 / 1.0012)
        self.assertEqual(calculate_subscription_fee(2_000_000, self.TIERS, 0.1), 1000.0)

    def test_legacy_fees_unchanged(self):
        self.assertAlmostEqual(calculate_subscription_fee(100_000, {}), 1500.0)
        self.assertAlmostEqual(calculate_subscription_fee(3_000_000, {}), 1000.0)

    def test_fee_band_reads_both_formulas(self):
        # 0%, 0.8% net, 1.2% net, 1.5% net, 1.5% legacy, 1.0% net
        trips = pd.DataFrame({"fee": [0, 0.794, 1.186, 1.478, 1.5, 0.990], "invested": [100.0] * 6})
        self.assertEqual(fee_band(trips).tolist(), ["0%", "0~1%", "1%~1.5%", "≥1.5%", "≥1.5%", "1%~1.5%"])

    def test_config_validation(self):
        for bad in ({"premium_basis": "close"}, {"fees": "csv"}, {"settlement": "t3"}, {"fee_discount": 1.5}):
            with self.assertRaises(ValueError):
                BacktestConfig(**bad)


class TempData(unittest.TestCase):
    """Two funds over March 2024 with an open status every day: 160001 domestic, 160002 QDII."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lof_f_")
        self.dir = Path(self.tmp)
        for d in ("market", "nav", "config"):
            (self.dir / d).mkdir()
        conn = sqlite3.connect(self.dir / "config" / "subscription_state.db")
        conn.executescript(DAILY_STATUS_SCHEMA)
        conn.executemany("INSERT INTO daily_status (fund_code, date, status, amount, source) VALUES (?, ?, ?, ?, ?)",
                         [(t, d.strftime("%Y-%m-%d"), "open", None, "change") for t in ("160001", "160002")
                          for d in DAYS])
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fund(self, ticker, close, nav):
        n = len(DAYS)
        close, nav = np.broadcast_to(close, n).astype(float), np.broadcast_to(nav, n).astype(float)
        pd.DataFrame({"date": DAYS, "ticker": ticker, "open": close, "high": close, "low": close, "close": close,
                      "volume": np.full(n, 10_000_000.0)}).to_parquet(self.dir / "market" / f"{ticker}.parquet",
                                                                      index=False)
        pd.DataFrame({"date": DAYS, "ticker": ticker, "nav": nav}).to_parquet(
            self.dir / "nav" / f"{ticker}.parquet", index=False)

    def terms_csv(self):
        pages = self.dir / "pages"
        pages.mkdir()
        (pages / "jjfl_160001.html").write_text(DOMESTIC, encoding="utf-8")
        (pages / "jjfl_160002.html").write_text(QDII, encoding="utf-8")
        fund_terms.build_terms(["160001", "160002"], pages).to_csv(self.dir / "config" / "fund_terms.csv", index=False)

    def run_cfg(self, tickers, **kw):
        cfg = BacktestConfig(initial_cash=100_000, buy_threshold=0.017, **kw)
        return BacktestEngine(cfg, SimpleLOFStrategy(), DataLoader(str(self.dir))).run(tickers)

    @staticmethod
    def buys(result):
        logs = result.trade_logs
        return logs[logs["action"] == "buy"] if not logs.empty else logs


class TestLoaderTerms(TempData):
    def test_published_premium_uses_each_funds_nav_lag(self):
        nav = np.linspace(1.0, 1.2, len(DAYS))
        self.fund("160001", 1.1, nav)
        self.fund("160002", 1.1, nav)
        self.terms_csv()
        loader = DataLoader(str(self.dir))
        self.assertEqual(loader.terms_mode, "fund")
        dom, qdii = loader.load_bundle("160001").df, loader.load_bundle("160002").df
        np.testing.assert_allclose(dom["nav_published"].iloc[1:], nav[:-1])
        np.testing.assert_allclose(qdii["nav_published"].iloc[2:], nav[:-2])
        self.assertTrue(qdii["premium_published"].iloc[:2].isna().all())
        self.assertEqual(loader.load_terms("160002")["sell_days"], 3)
        self.assertEqual(loader.load_terms("169999"), {"sell_days": 2, "nav_lag": 1, "terms_source": "default"})
        self.assertEqual(DataLoader(str(self.dir), terms="default").load_terms("160002")["sell_days"], 2)

    def test_published_nav_ignores_days_without_a_market_row(self):
        # No trades on 03-06 and 03-07: the market file has no rows, the NAV is still published.
        nav = np.linspace(1.0, 1.2, len(DAYS))
        self.fund("160001", 1.1, nav)
        market_path = self.dir / "market" / "160001.parquet"
        m = pd.read_parquet(market_path)
        m[~m["date"].isin(pd.to_datetime(["2024-03-06", "2024-03-07"]))].to_parquet(market_path, index=False)
        df = DataLoader(str(self.dir)).load_bundle("160001").df
        nav_by_day = pd.Series(nav, index=DAYS)
        self.assertNotIn(pd.Timestamp("2024-03-06"), df.index)
        # On 03-08 the newest visible NAV is 03-07's, not 03-05's (the previous traded day).
        self.assertAlmostEqual(df.loc["2024-03-08", "nav_published"], nav_by_day["2024-03-07"])

    def test_fund_terms_required_when_asked(self):
        self.fund("160001", 1.1, 1.0)
        self.assertEqual(DataLoader(str(self.dir)).terms_mode, "default")
        with self.assertRaises(FileNotFoundError):
            DataLoader(str(self.dir), terms="fund")


class TestEngineTerms(TempData):
    def test_no_look_ahead(self):
        # The NAV drops 5% on 03-11 while the price stays: a 5% premium that is only visible after the close.
        nav = np.where(DAYS >= "2024-03-11", 0.95, 1.0)
        self.fund("160001", 1.0, nav)
        same = set(self.buys(self.run_cfg(["160001"], premium_basis="same_day"))["date"].astype(str))
        published = self.buys(self.run_cfg(["160001"]))
        self.assertIn("2024-03-11", same)
        self.assertNotIn("2024-03-11", set(published["date"].astype(str)))
        self.assertEqual(published["date"].astype(str).iloc[0], "2024-03-12")    # seen the next day
        self.assertAlmostEqual(published["decision_premium"].iloc[0], 1 / 0.95 - 1)

    def test_sell_days_and_fees_follow_the_fund(self):
        self.fund("160002", 1.05, 1.0)
        self.terms_csv()
        r = self.run_cfg(["160002"])
        buy = self.buys(r).iloc[0]
        sell = r.trade_logs[r.trade_logs["action"] == "sell"].iloc[0]
        self.assertEqual((buy["sell_days"], buy["fee_source"]), (3, fund_terms.SOURCE))
        self.assertEqual(DAYS.get_loc(pd.Timestamp(sell["date"])) - DAYS.get_loc(pd.Timestamp(buy["date"])), 3)
        self.assertAlmostEqual(buy["fee"], buy["amount"] - buy["amount"] / 1.012)
        old = self.buys(self.run_cfg(["160002"], fees="default", settlement="t2")).iloc[0]
        self.assertEqual((old["sell_days"], old["fee_source"]), (2, "default"))
        self.assertAlmostEqual(old["fee"], old["amount"] * 0.015)


if __name__ == "__main__":
    unittest.main()
