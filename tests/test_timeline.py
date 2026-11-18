"""
Phase D: resolution of state assertions into daily_status (src/pipeline/timeline.py).
"""

import json
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import db, timeline  # noqa: E402
from src.pipeline.timeline import Assertion, Calendar, State, resolve_fund, stricter  # noqa: E402

DAYS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-03-01", "2024-03-29")]
CAL = Calendar(DAYS)
_ids = iter(range(1, 10_000))


def mk(status, valid_from, valid_to=None, *, kind="change", observed=None, prior=None, amount=None,
       channel="all", sha="doc", evidence="本基金暂停申购"):
    return Assertion(next(_ids), sha, "160723", status, amount, valid_from, valid_to,
                     "overlay" if valid_to else "baseline", kind, observed or valid_from, prior, channel, evidence)


def states(tl, *days):
    out = []
    for d in days:
        x = tl.days[d]
        out.append(f"{x.status} {x.amount:g}" if x.status == "limited" and x.amount is not None else x.status)
    return out


def kinds(tl):
    return sorted(a["kind"] for a in tl.anomalies)


class TestValues(unittest.TestCase):
    def test_stricter(self):
        self.assertEqual(stricter(State("open"), State("closed")), State("closed"))
        self.assertEqual(stricter(State("limited", 100), State("limited", 50)), State("limited", 50))
        self.assertEqual(stricter(State("limited"), State("limited", 50)), State("limited", 50))
        self.assertEqual(stricter(State("limited", 1e6), State("open")), State("limited", 1e6))

    def test_calendar_adjacent(self):
        self.assertTrue(CAL.adjacent("2024-03-08", "2024-03-11"))      # over a weekend
        self.assertFalse(CAL.adjacent("2024-03-08", "2024-03-12"))
        self.assertTrue(CAL.adjacent("2024-12-31", "2025-01-02"))      # past the calendar: calendar days
        self.assertFalse(CAL.adjacent("2024-03-11", "2024-03-11"))

    def test_institution_only(self):
        self.assertTrue(timeline.institution_only("调整机构投资者单日单个基金账户申购限额为100,000元"))
        self.assertFalse(timeline.institution_only("投资者（包括个人投资者和机构投资者）单日累计高于5000万元"))
        self.assertTrue(timeline.institution_only("对非个人投资者的申购进行限制"))


class TestResolve(unittest.TestCase):
    def test_changes_and_unknown_before(self):
        tl = resolve_fund("160723", [mk("closed", "2024-03-05"), mk("open", "2024-03-12", sha="b")], CAL)
        self.assertEqual(states(tl, "2024-03-04", "2024-03-05", "2024-03-11", "2024-03-12"),
                         ["unknown", "closed", "closed", "open"])
        self.assertEqual(tl.days["2024-03-04"].source, "default")

    def test_inferred_prior_and_long_inference(self):
        tl = resolve_fund("160723", [mk("open", "2024-03-12", prior="closed")], CAL)
        self.assertEqual(states(tl, "2024-03-01", "2024-03-12"), ["closed", "open"])
        self.assertEqual(tl.days["2024-03-01"].source, "inferred_prior")
        self.assertEqual(kinds(tl), [])   # 11 days, not long

    def test_window_prior_closes_the_years_before(self):
        # 160128: open once every three years; the opening notice is the only one in the corpus
        tl = resolve_fund("160723", [mk("open", "2024-03-11", "2024-03-15", sha="w", prior="closed"),
                                     mk("closed", "2024-03-18", sha="w")], CAL)
        self.assertEqual(states(tl, "2024-03-01", "2024-03-11", "2024-03-18"), ["closed", "open", "closed"])
        self.assertEqual(tl.days["2024-03-01"].source, "inferred_prior")

    def test_inferred_open_from_temporary_suspensions(self):
        tl = resolve_fund("160723", [mk("closed", "2024-03-08", "2024-03-08", observed="2024-03-05", sha="h1")], CAL)
        self.assertEqual(states(tl, "2024-03-01", "2024-03-05", "2024-03-08", "2024-03-11"),
                         ["open", "open", "closed", "open"])   # 30 days back from the notice
        self.assertEqual(states(resolve_fund("160723", [mk("closed", "2024-04-30", "2024-04-30", sha="h")], CAL),
                                "2024-03-29"), ["unknown"])
        self.assertEqual(tl.days["2024-03-11"].source, "inferred_open")
        # a baseline claim that failed its evidence check stops the inference (164906 2022-02-28)
        tl = resolve_fund("160723", [mk("closed", "2024-03-08", "2024-03-08", observed="2024-03-05", sha="h1")], CAL,
                          unverified=[mk("limited", "2024-03-11", sha="garbled", amount=1000)])
        self.assertEqual(states(tl, "2024-03-07", "2024-03-11"), ["open", "unknown"])
        # an explicit prior wins over the inference
        tl = resolve_fund("160723", [mk("closed", "2024-03-08", "2024-03-08", observed="2024-03-05", sha="h1"),
                                     mk("open", "2024-03-20", sha="r", prior="closed")], CAL)
        self.assertEqual(states(tl, "2024-03-11"), ["closed"])
        # a limited prior takes the amount the same notice restates ("由 1000 元调整为 100 元")
        tl = resolve_fund("160723", [mk("limited", "2024-03-20", sha="adj", prior="limited", amount=100),
                                     mk("limited", "2024-03-20", sha="adj", kind="restatement", amount=1000)], CAL)
        self.assertEqual(states(tl, "2024-03-11", "2024-03-20"), ["limited 1000", "limited 100"])

    def test_unstated_amount_is_not_a_conflict(self):
        # 161005: a 2023 notice cites the 2022-01-27 notice ("limited", no amount) -- not a contradiction of 20,000
        tl = resolve_fund("160723", [
            mk("limited", "2021-02-18", kind="restatement", observed="2024-03-04", amount=10000, sha="a"),
            mk("limited", "2024-03-05", observed="2024-03-04", amount=20000, sha="a"),
            mk("limited", "2024-03-04", kind="restatement", observed="2024-03-20", sha="b"),
        ], CAL)
        self.assertEqual(states(tl, "2024-03-04", "2024-03-05", "2024-03-20"),
                         ["limited 10000", "limited 20000", "limited 20000"])
        self.assertEqual(kinds(tl), [])

    def test_overlay_over_baseline(self):
        tl = resolve_fund("160723", [mk("limited", "2024-03-01", amount=1000),
                                     mk("closed", "2024-03-08", "2024-03-11", sha="h")], CAL)
        self.assertEqual(states(tl, "2024-03-07", "2024-03-08", "2024-03-11", "2024-03-12"),
                         ["limited 1000", "closed", "closed", "limited 1000"])
        self.assertEqual(tl.days["2024-03-08"].source, "overlay")

    def test_opening_window_keeps_baseline_limit(self):
        win = [mk("open", "2024-03-11", "2024-03-15", sha="w", prior="closed"),
               mk("closed", "2024-03-18", sha="w")]
        tl = resolve_fund("160723", [mk("closed", "2024-03-01", sha="c")] + win, CAL)
        self.assertEqual(states(tl, "2024-03-08", "2024-03-11", "2024-03-15", "2024-03-18"),
                         ["closed", "open", "open", "closed"])
        tl = resolve_fund("160723", [mk("limited", "2024-03-01", sha="c", amount=100)] + win, CAL)
        self.assertEqual(states(tl, "2024-03-11"), ["limited 100"])

    def test_cancel_overlay_falls_back_to_baseline(self):
        tl = resolve_fund("160723", [
            mk("limited", "2024-03-01", amount=500, sha="base"),
            mk("closed", "2024-03-14", "2024-03-15", sha="annual", observed="2024-03-01"),
            mk("open", "2024-03-15", "2024-03-15", sha="adjust", observed="2024-03-10"),
        ], CAL)
        self.assertEqual(states(tl, "2024-03-14", "2024-03-15"), ["closed", "limited 500"])

    def test_holiday_resumption_is_ignored_and_prior_dropped(self):
        holiday = [mk("closed", "2024-03-08", "2024-03-08", sha="h"),
                   mk("open", "2024-03-11", sha="h", prior="closed")]
        tl = resolve_fund("160723", [mk("limited", "2024-03-01", amount=300, sha="lim", channel="agency")] + holiday, CAL)
        self.assertEqual(states(tl, "2024-03-08", "2024-03-11"), ["closed", "limited 300"])
        self.assertEqual(kinds(tl), ["ignored_resume"])
        # a new limit after the holiday stays, but its prior (the overlay) is not inferred backwards
        tl = resolve_fund("160723", [mk("closed", "2024-03-08", "2024-03-08", sha="h"),
                                     mk("limited", "2024-03-11", sha="h", prior="closed", amount=100)], CAL)
        self.assertEqual(states(tl, "2024-03-07", "2024-03-11"), ["open", "limited 100"])
        self.assertEqual(tl.days["2024-03-07"].source, "inferred_open")   # not inferred_prior "closed"

    def test_restatement_is_an_implied_change(self):
        tl = resolve_fund("160723", [mk("closed", "2020-03-16", kind="restatement", observed="2024-03-20"),
                                     mk("open", "2024-03-25", sha="r", prior="closed")], CAL)
        self.assertEqual(states(tl, "2024-03-01", "2024-03-22", "2024-03-25"), ["closed", "closed", "open"])
        self.assertEqual(tl.days["2024-03-01"].source, "restatement")

    def test_limit_without_amount_inherits(self):
        tl = resolve_fund("160723", [mk("limited", "2024-03-01", amount=20000),
                                     mk("limited", "2024-03-12", sha="rule"),
                                     mk("limited", "2024-03-20", sha="re", kind="restatement")], CAL)
        self.assertEqual(states(tl, "2024-03-12", "2024-03-20"), ["limited 20000", "limited 20000"])

    def test_institution_only_is_not_on_target(self):
        tl = resolve_fund("160723", [mk("limited", "2024-03-01", amount=1e5, evidence="调整机构投资者申购限额为10万元"),
                                     mk("open", "2024-03-12", sha="b", evidence="取消机构投资者申购上限")], CAL)
        self.assertEqual(states(tl, "2024-03-05", "2024-03-12"), ["unknown", "unknown"])
        self.assertEqual(kinds(tl), ["investor_scope", "investor_scope"])

    def test_same_day_conflict_uses_stricter(self):
        # 164906 2022-05-23: "恢复申购" and "限额 500 元" from one notice
        tl = resolve_fund("160723", [mk("open", "2024-03-11", observed="2024-03-08", prior="closed"),
                                     mk("limited", "2024-03-11", observed="2024-03-08", amount=500)], CAL)
        self.assertEqual(states(tl, "2024-03-11"), ["limited 500"])
        self.assertEqual(kinds(tl), ["conflict_same_day"])

    def test_leapfrog_uses_stricter(self):
        # 160723 2024-12: announced 12-20 effective 12-27 (5 万) vs announced 12-26 effective 12-26 (1000)
        tl = resolve_fund("160723", [mk("limited", "2024-03-20", observed="2024-03-12", amount=50000, sha="a"),
                                     mk("limited", "2024-03-18", observed="2024-03-15", amount=1000, sha="b")], CAL)
        self.assertEqual(states(tl, "2024-03-18", "2024-03-20"), ["limited 1000", "limited 1000"])
        self.assertEqual(kinds(tl), ["conflict_leapfrog"])

    def test_restatement_contradicting_an_earlier_change(self):
        tl = resolve_fund("160723", [mk("open", "2024-03-05", observed="2024-03-04", sha="a"),
                                     mk("closed", "2024-03-01", kind="restatement", observed="2024-03-15", sha="b")], CAL)
        self.assertEqual(states(tl, "2024-03-05", "2024-03-15", "2024-03-18"), ["closed", "closed", "open"])
        self.assertEqual(kinds(tl), ["conflict_restatement"])
        # a looser restatement does not override, and is not an anomaly
        tl = resolve_fund("160723", [mk("limited", "2024-03-05", observed="2024-03-04", sha="a", amount=100),
                                     mk("open", "2014-01-28", kind="restatement", observed="2024-03-15", sha="b")], CAL)
        self.assertEqual(states(tl, "2024-03-12"), ["limited 100"])
        self.assertEqual(kinds(tl), [])

    def test_later_change_overrides_an_opening_window(self):
        tl = resolve_fund("160723", [mk("open", "2024-03-11", "2024-03-22", sha="w", observed="2024-03-05"),
                                     mk("closed", "2024-03-25", sha="w", observed="2024-03-05"),
                                     mk("closed", "2024-03-18", sha="stop", observed="2024-03-15")], CAL)
        self.assertEqual(states(tl, "2024-03-15", "2024-03-18"), ["open", "closed"])
        self.assertEqual(kinds(tl), ["overlay_overridden"])


class TestBuild(unittest.TestCase):
    def test_build_writes_daily_status_for_target_path_only(self):
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO extractions (id, sha256, prompt_version, model, status) VALUES (1, 's', 'v', 'm', 'ok')")
        rows = [  # (share_codes, channel, businesses, status, amount, from, to, layer, kind, evidence_ok)
            (["160723"], "agency", ["purchase"], "limited", 1000, "2024-03-04", None, "baseline", "change", 1),
            (["160723"], "direct", ["purchase"], "limited", 5000, "2024-03-04", None, "baseline", "change", 1),
            (["005665"], "all", ["purchase"], "closed", None, "2024-03-04", None, "baseline", "change", 1),
            (["*"], "all", ["redemption"], "closed", None, "2024-03-04", None, "baseline", "change", 1),
            (["*"], "all", ["purchase"], "closed", None, "2024-03-08", "2024-03-08", "overlay", "change", 1),
            (["*"], "all", ["purchase"], "open", None, "2024-03-11", None, "baseline", "change", 0),
        ]
        for i, (sh, ch, bz, st, amt, vf, vt, layer, kind, ok) in enumerate(rows, 1):
            conn.execute("INSERT INTO state_assertions (id, extraction_id, sha256, fund_code, share_codes, channel, "
                         "businesses, status, amount, currency, valid_from, valid_to, layer, kind, observed_on, evidence, "
                         "evidence_ok) VALUES (?, 1, 's', '160723', ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, '2024-03-01', 'x', ?)",
                         (i, json.dumps(sh), ch, json.dumps(bz), st, amt, vf, vt, layer, kind, ok))
        counts = timeline.build(conn, ["160723", "161129"], DAYS)
        self.assertEqual((counts["funds"], counts["days"]), (2, 2 * len(DAYS)))
        got = {r["date"]: (r["status"], r["amount"], r["source"], json.loads(r["assertion_ids"]))
               for r in conn.execute("SELECT * FROM daily_status WHERE fund_code = '160723'")}
        # the holiday notice (observed 03-01) implies purchase was otherwise possible
        self.assertEqual(got["2024-03-01"], ("open", None, "inferred_open", []))
        self.assertEqual(got["2024-03-04"], ("limited", 1000.0, "change", [1]))
        self.assertEqual(got["2024-03-08"], ("closed", None, "overlay", [5, 1]))
        self.assertEqual(got["2024-03-11"][0], "limited")   # evidence-failing "open" is not used
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_status WHERE fund_code = '161129' AND status = 'unknown'")
                         .fetchone()[0], len(DAYS))
        timeline.build(conn, ["160723"], DAYS)   # rebuild replaces, never appends
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_status").fetchone()[0], len(DAYS))


if __name__ == "__main__":
    unittest.main()
