"""
The AKShare downloader, with AKShare's network calls replaced by fakes.

AKShare 下载器测试：AKShare 的网络请求全部替换为假函数。
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data import downloader as dl  # noqa: E402
from src.data.loader import DataLoader  # noqa: E402

DAYS = pd.bdate_range("2024-03-01", "2024-03-14")


def hist(n=len(DAYS), lots=1000):
    """fund_lof_hist_em-shaped frame, newest first to check sorting."""
    df = pd.DataFrame({"日期": [d.strftime("%Y-%m-%d") for d in DAYS[:n]], "开盘": 1.0, "收盘": 1.05,
                       "最高": 1.06, "最低": 0.99, "成交量": [lots * (i + 1) for i in range(n)],
                       "成交额": 1.0, "振幅": 0.0, "涨跌幅": 0.0, "涨跌额": 0.0, "换手率": 0.0})
    return df.iloc[::-1].reset_index(drop=True)


def nav():
    days = pd.bdate_range("2024-02-26", "2024-03-20")
    return pd.DataFrame({"净值日期": days.date, "单位净值": 1.0, "日增长率": 0.0})


def sina_hist():
    """fund_etf_hist_sina-shaped frame: full history, volume already in shares."""
    days = pd.bdate_range("2024-02-26", "2024-03-20")
    return pd.DataFrame({"date": days.date, "open": 1.0, "high": 1.06, "low": 0.99, "close": 1.05,
                         "volume": [1000 * (i + 1) for i in range(len(days))], "amount": 1.0})


class Fakes:
    """Stands in for AKShare; records what each call saw."""

    def __init__(self, board=None, fail=None, bans=0):
        self.board = board or {"161226": 0}
        self.fail = fail or set()
        self.bans = bans
        self.hist_calls, self.maps, self.agents = [], [], []

    def list_board(self):
        return dict(self.board)

    def fund_lof_hist_em(self, symbol, period, start_date, end_date, adjust):
        self.hist_calls.append((symbol, start_date, end_date, adjust))
        self.maps.append(dl._lof_em._fund_lof_code_id_map_em()[symbol])
        self.agents.append(requests.Session().headers["User-Agent"])
        if self.bans:
            self.bans -= 1
            raise dl.Push2RateLimitError("refused")
        if symbol in self.fail:
            raise KeyError(symbol)
        return hist()

    def fund_open_fund_info_em(self, symbol, indicator):
        assert indicator == "单位净值走势"
        return nav()


class DownloaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lof_dl_"))
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_dl(self, fakes, codes=None, refresh=False, ban_waits=(60, 120)):
        d = dl.RealDataDownloader(str(self.tmp), source="eastmoney", pause=0, nav_pause=0, ban_waits=ban_waits,
                                  sleep=self.sleeps.append)
        with mock.patch.object(dl._lof_em, "_fund_lof_code_id_map_em", fakes.list_board), \
                mock.patch.object(dl.ak, "fund_lof_hist_em", fakes.fund_lof_hist_em), \
                mock.patch.object(dl.ak, "fund_open_fund_info_em", fakes.fund_open_fund_info_em):
            result = d.download("2024-03-01", "2024-03-14", codes=codes, refresh=refresh)
        return d, result

    def report(self):
        return pd.read_csv(self.tmp / "download_report.csv", dtype={"ticker": str}).set_index("ticker")


class TestFrames(DownloaderTest):
    def test_market_frame_is_in_shares_sorted_with_ma5(self):
        df = dl.market_frame(hist(), "161226")
        self.assertEqual(list(df.columns), dl.MARKET_COLUMNS)
        self.assertTrue(df["date"].is_monotonic_increasing)
        self.assertEqual(df["volume"].tolist()[:3], [100_000.0, 200_000.0, 300_000.0])   # lots x 100
        self.assertEqual(df["volume_ma5"].iloc[0], 100_000.0)                           # filled like before
        self.assertEqual(df["volume_ma5"].iloc[4], 300_000.0)

    def test_nav_frame_cut_to_range(self):
        df = dl.nav_frame(nav(), "161226", "2024-03-01", "2024-03-14")
        self.assertEqual(df["date"].min(), pd.Timestamp("2024-03-01"))
        self.assertEqual(df["date"].max(), pd.Timestamp("2024-03-14"))

    def test_empty_inputs(self):
        self.assertTrue(dl.market_frame(pd.DataFrame(), "x").empty)
        self.assertTrue(dl.nav_frame(pd.DataFrame(), "x", "2024-01-01", "2024-12-31").empty)

    def test_exchange_from_code(self):
        self.assertEqual(dl.exchange_id("501210"), 1)
        self.assertEqual(dl.exchange_id("160326"), 0)
        self.assertEqual(dl.exchange_id("184801"), 0)
        self.assertEqual(dl.sina_symbol("501210"), "sh501210")
        self.assertEqual(dl.sina_symbol("161226"), "sz161226")

    def test_sina_frame_cut_to_range_volume_in_shares(self):
        df = dl.sina_frame(sina_hist(), "161226", "2024-03-01", "2024-03-14")
        self.assertEqual(list(df.columns), dl.MARKET_COLUMNS)
        self.assertEqual((df["date"].min(), df["date"].max()), (pd.Timestamp("2024-03-01"), pd.Timestamp("2024-03-14")))
        self.assertEqual(df["volume"].iloc[0], 5000.0)          # 2024-03-01 is the 5th day of the fake history
        self.assertEqual(df["volume_ma5"].iloc[0], 5000.0)      # the average starts after the cut


class TestDownload(DownloaderTest):
    def test_given_codes_need_no_board_and_delisted_use_the_code(self):
        fakes = Fakes()
        fakes.list_board = mock.Mock(side_effect=AssertionError("board requested"))
        _, (n, done) = self.run_dl(fakes, codes=["161226", "501210"])
        self.assertEqual((n, sorted(done)), (2, ["161226", "501210"]))
        self.assertEqual(fakes.maps, [0, 1])
        self.assertEqual(fakes.hist_calls[0], ("161226", "20240301", "20240314", ""))

    def test_browser_user_agent_only_inside_the_run(self):
        fakes = Fakes()
        self.run_dl(fakes, codes=["161226"])
        self.assertEqual(fakes.agents, [dl.BROWSER_UA])
        self.assertTrue(requests.Session().headers["User-Agent"].startswith("python-requests"))

    def test_default_is_todays_board(self):
        fakes = Fakes(board={"161226": 0, "501018": 1})
        _, (n, _) = self.run_dl(fakes)
        self.assertEqual(n, 2)
        self.assertEqual(sorted(c[0] for c in fakes.hist_calls), ["161226", "501018"])

    def test_output_is_what_the_loader_reads(self):
        self.run_dl(Fakes(), codes=["161226"])
        df = DataLoader(str(self.tmp)).load_bundle("161226").df
        self.assertEqual(len(df), len(DAYS))
        self.assertAlmostEqual(df["premium_rate"].iloc[-1], 0.05)
        self.assertEqual(self.report().loc["161226", "status"], "ok")

    def test_rerun_keeps_files_unless_refresh(self):
        self.run_dl(Fakes(), codes=["161226"])
        fakes = Fakes()
        self.run_dl(fakes, codes=["161226"])
        self.assertEqual(fakes.hist_calls, [])
        self.assertEqual(self.report().loc["161226", "status"], "kept")
        self.run_dl(fakes, codes=["161226"], refresh=True)
        self.assertEqual(len(fakes.hist_calls), 1)

    def test_one_bad_fund_does_not_stop_the_run(self):
        _, (n, done) = self.run_dl(Fakes(fail={"160326"}), codes=["160326", "161226"])
        self.assertEqual(done, ["161226"])
        self.assertTrue(self.report().loc["160326", "status"].startswith("error: KeyError"))

    def test_many_failures_in_a_row_stop_the_run(self):
        codes = ["160001", "160002", "160003", "160004", "160005", "160006", "161226"]
        fakes = Fakes(fail=set(codes[:6]))
        _, (n, done) = self.run_dl(fakes, codes=codes)
        self.assertEqual(n, 0)
        self.assertEqual(len(fakes.hist_calls), 5)              # stopped after five failures in a row

    def test_sina_source(self):
        calls = []

        def fake_sina(symbol):
            calls.append(symbol)
            return sina_hist()

        d = dl.RealDataDownloader(str(self.tmp), source="sina", sina_pause=0, nav_pause=0, sleep=self.sleeps.append)
        with mock.patch.object(dl.ak, "fund_etf_hist_sina", fake_sina), \
                mock.patch.object(dl.ak, "fund_lof_hist_em", mock.Mock(side_effect=AssertionError("eastmoney"))), \
                mock.patch.object(dl.ak, "fund_open_fund_info_em", Fakes().fund_open_fund_info_em):
            n, _ = d.download("2024-03-01", "2024-03-14", codes=["161226", "501210"])
        self.assertEqual((n, calls), (2, ["sz161226", "sh501210"]))
        self.assertEqual(self.report()["source"].tolist(), ["sina", "sina"])
        self.assertEqual(len(pd.read_parquet(self.tmp / "market" / "501210.parquet")), len(DAYS))

    def test_sina_is_the_default(self):
        self.assertEqual(dl.RealDataDownloader(str(self.tmp)).source, "sina")

    def test_sina_list_plus_eastmoney_board(self):
        sina_list = pd.DataFrame({"代码": ["sz161226", "sh501210"]})
        d = dl.RealDataDownloader(str(self.tmp), sina_pause=0)
        with mock.patch.object(dl.ak, "fund_etf_category_sina", return_value=sina_list), \
                mock.patch.object(dl._lof_em, "_fund_lof_code_id_map_em", lambda: {"161226": 0, "501018": 1}):
            self.assertEqual(d.fetch_all_lof_codes(), {"161226": 0, "501210": 1, "501018": 1})
        refused = mock.Mock(side_effect=dl.Push2RateLimitError("refused"))
        with mock.patch.object(dl.ak, "fund_etf_category_sina", return_value=sina_list), \
                mock.patch.object(dl._lof_em, "_fund_lof_code_id_map_em", refused):
            self.assertEqual(d.fetch_all_lof_codes(), {"161226": 0, "501210": 1})   # Eastmoney down: Sina alone
        self.assertEqual(self.sleeps, [])                                          # no ban waits for a Sina run

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            dl.RealDataDownloader(str(self.tmp), source="joinquant")


class TestRateLimit(DownloaderTest):
    def test_refusal_waits_slows_down_and_retries(self):
        fakes = Fakes(bans=1)
        d, (n, _) = self.run_dl(fakes, codes=["161226"])
        self.assertEqual(n, 1)
        self.assertEqual(self.sleeps, [60])
        self.assertEqual(len(fakes.hist_calls), 2)

    def test_pace_grows_after_a_refusal(self):
        d = dl.RealDataDownloader(str(self.tmp), pause=4, ban_waits=(1,), sleep=self.sleeps.append)
        calls = iter([dl.Push2RateLimitError("x"), "ok"])

        def call():
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        self.assertEqual(d._with_ban_waits(call, "t"), "ok")
        self.assertEqual(d.pause, 6.0)

    def test_stops_after_refusals_in_a_row_and_keeps_what_it_has(self):
        fakes = Fakes()
        orig = fakes.fund_lof_hist_em

        def second_fund_refused(symbol, *a, **k):
            if symbol == "501018":
                fakes.hist_calls.append((symbol,))
                raise dl.Push2RateLimitError("refused")
            return orig(symbol, *a, **k)

        fakes.fund_lof_hist_em = second_fund_refused
        _, (n, done) = self.run_dl(fakes, codes=["161226", "501018", "160216"])
        self.assertEqual(done, ["161226"])
        self.assertEqual(self.sleeps, [60, 120])
        self.assertTrue((self.tmp / "market" / "161226.parquet").exists())
        rep = self.report()
        self.assertEqual(rep.loc["501018", "status"], "stopped: rate limited")
        self.assertNotIn("160216", rep.index)          # never reached; a rerun continues from 501018


if __name__ == "__main__":
    unittest.main()
