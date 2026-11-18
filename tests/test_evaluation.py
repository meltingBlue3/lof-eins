"""
Tests for src/evaluation: gold timeline validation/expansion, candidate
comparison, and the market red-flag detector.

src/evaluation 的测试：金标校验与展开、候选时间线对比、市场红旗检测。
"""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.candidates import status_from_cap
from src.evaluation.compare import (
    AGREE,
    CAND_UNKNOWN,
    TOO_PERMISSIVE,
    TOO_STRICT,
    classify,
    mismatch_kinds,
    mismatch_runs,
    summarize,
)
from src.evaluation.gold import (
    GOLD_COLUMNS,
    GoldValidationError,
    expand_daily,
    load_gold,
    validate_gold,
)
from src.evaluation.red_flags import find_red_flags

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def gold_frame(rows):
    """Build a raw (all-string) gold frame like pd.read_csv(dtype=str) would."""
    filled = []
    for r in rows:
        row = {c: "" for c in GOLD_COLUMNS}
        row.update({"confidence": "high", "source_pdf": "X/a.pdf", "evidence": "q"})
        row.update(r)
        filled.append(row)
    return pd.DataFrame(filled, columns=GOLD_COLUMNS)


def days(start, end):
    return pd.bdate_range(start, end)


def daily(index, statuses, amounts=None):
    amounts = amounts if amounts is not None else [np.nan] * len(statuses)
    return pd.DataFrame({"status": statuses, "amount": amounts}, index=index)


class TestValidateGold(unittest.TestCase):
    def test_clean_frame_has_no_problems(self):
        df = gold_frame([
            {"fund_code": "1", "layer": "baseline", "status": "closed",
             "valid_from": "2024-01-01", "valid_to": "2024-01-31"},
            {"fund_code": "1", "layer": "baseline", "status": "limited", "amount": "1000",
             "valid_from": "2024-02-01", "valid_to": "2024-02-29"},
            {"fund_code": "1", "layer": "overlay", "status": "closed", "evidence": "",
             "valid_from": "2024-02-05", "valid_to": "2024-02-05"},
        ])
        self.assertEqual(validate_gold(df), [])

    def test_overlapping_baselines_are_rejected(self):
        df = gold_frame([
            {"fund_code": "1", "layer": "baseline", "status": "open",
             "valid_from": "2024-01-01", "valid_to": "2024-01-31"},
            {"fund_code": "1", "layer": "baseline", "status": "closed",
             "valid_from": "2024-01-31", "valid_to": "2024-02-29"},
        ])
        problems = validate_gold(df)
        self.assertEqual(len(problems), 1)
        self.assertIn("overlap", problems[0])

    def test_limited_needs_positive_amount_and_others_need_none(self):
        df = gold_frame([
            {"fund_code": "1", "layer": "baseline", "status": "limited", "amount": "",
             "valid_from": "2024-01-01", "valid_to": "2024-01-02"},
            {"fund_code": "1", "layer": "baseline", "status": "open", "amount": "5",
             "valid_from": "2024-01-03", "valid_to": "2024-01-04"},
        ])
        self.assertEqual(len(validate_gold(df)), 2)

    def test_bad_enum_date_order_and_missing_evidence(self):
        df = gold_frame([
            {"fund_code": "1", "layer": "base", "status": "open",
             "valid_from": "2024-01-01", "valid_to": "2024-01-02"},
            {"fund_code": "1", "layer": "baseline", "status": "shut",
             "valid_from": "2024-01-03", "valid_to": "2024-01-04"},
            {"fund_code": "1", "layer": "baseline", "status": "open",
             "valid_from": "2024-02-02", "valid_to": "2024-02-01"},
            {"fund_code": "1", "layer": "baseline", "status": "open", "evidence": "",
             "valid_from": "2024-03-01", "valid_to": "2024-03-02"},
        ])
        self.assertEqual(len(validate_gold(df)), 4)

    def test_missing_columns_reported(self):
        df = pd.DataFrame({"fund_code": ["1"]})
        problems = validate_gold(df)
        self.assertEqual(len(problems), 1)
        self.assertIn("missing columns", problems[0])


class TestExpandDaily(unittest.TestCase):
    def test_overlay_overrides_baseline_and_uncovered_days_drop(self):
        raw = gold_frame([
            {"fund_code": "1", "layer": "baseline", "status": "limited", "amount": "1000",
             "valid_from": "2024-01-02", "valid_to": "2024-01-05"},
            {"fund_code": "1", "layer": "overlay", "status": "closed",
             "valid_from": "2024-01-03", "valid_to": "2024-01-03"},
        ])
        gold = load_gold_from_frame(raw)
        out = expand_daily(gold, "1", days("2024-01-01", "2024-01-09"))
        self.assertEqual(list(out.index.strftime("%m-%d")), ["01-02", "01-03", "01-04", "01-05"])
        self.assertEqual(list(out["status"]), ["limited", "closed", "limited", "limited"])
        self.assertEqual(out.loc["2024-01-02", "amount"], 1000)
        self.assertTrue(np.isnan(out.loc["2024-01-03", "amount"]))
        self.assertEqual(out.loc["2024-01-03", "layer"], "overlay")

    def test_other_funds_ignored(self):
        raw = gold_frame([
            {"fund_code": "2", "layer": "baseline", "status": "open",
             "valid_from": "2024-01-01", "valid_to": "2024-01-31"},
        ])
        out = expand_daily(load_gold_from_frame(raw), "1", days("2024-01-01", "2024-01-09"))
        self.assertTrue(out.empty)


def load_gold_from_frame(raw):
    """load_gold() equivalent for an in-memory frame (validates + types it)."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.csv")
        raw.to_csv(p, index=False)
        return load_gold(p)


class TestLoadGold(unittest.TestCase):
    def test_invalid_file_raises_with_all_problems(self):
        raw = gold_frame([
            {"fund_code": "1", "layer": "baseline", "status": "limited", "amount": "",
             "valid_from": "2024-01-01", "valid_to": "2024-01-02"},
            {"fund_code": "1", "layer": "baseline", "status": "nope",
             "valid_from": "2024-01-03", "valid_to": "2024-01-04"},
        ])
        with self.assertRaises(GoldValidationError) as ctx:
            load_gold_from_frame(raw)
        self.assertEqual(len(ctx.exception.problems), 2)

    def test_repository_gold_file_is_valid(self):
        """The committed gold set must always pass validation."""
        path = PROJECT_ROOT / "data" / "gold" / "timeline.csv"
        if not path.exists():
            self.skipTest("no gold file")
        gold = load_gold(path)
        self.assertGreater(len(gold), 0)


class TestStatusFromCap(unittest.TestCase):
    def test_inf_zero_and_amount(self):
        idx = days("2024-01-01", "2024-01-03")
        out = status_from_cap(pd.Series([np.inf, 0.0, 500.0], index=idx))
        self.assertEqual(list(out["status"]), ["open", "closed", "limited"])
        self.assertTrue(np.isnan(out["amount"].iloc[0]))
        self.assertEqual(out["amount"].iloc[2], 500.0)


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.idx = days("2024-01-01", "2024-01-05")  # Mon..Fri

    def test_categories(self):
        gold = daily(self.idx, ["closed", "limited", "limited", "open", "limited"],
                     [np.nan, 100, 1000, np.nan, 100])
        cand = daily(self.idx, ["open", "limited", "limited", "closed", "unknown"],
                     [np.nan, 1000, 100, np.nan, np.nan])
        out = classify(gold, cand)
        self.assertEqual(list(out["category"]),
                         [TOO_PERMISSIVE, TOO_PERMISSIVE, TOO_STRICT, TOO_STRICT, CAND_UNKNOWN])

    def test_agree_tolerates_float_noise(self):
        gold = daily(self.idx[:2], ["limited", "open"], [10000, np.nan])
        cand = daily(self.idx[:2], ["limited", "open"], [10000.2, np.nan])
        self.assertEqual(list(classify(gold, cand)["category"]), [AGREE, AGREE])

    def test_only_shared_days_compared(self):
        gold = daily(self.idx[:3], ["open"] * 3)
        cand = daily(self.idx[1:], ["open"] * 4)
        self.assertEqual(len(classify(gold, cand)), 2)

    def test_summarize_counts_relevant_days(self):
        gold = daily(self.idx, ["closed"] * 5)
        cand = daily(self.idx, ["open", "open", "closed", "closed", "open"])
        premium = pd.Series([0.10, 0.0, 0.10, 0.0, 0.02], index=self.idx)
        s = summarize(classify(gold, cand), premium=premium, threshold=0.017)
        self.assertEqual(s["days"], 5)
        self.assertEqual(s[AGREE], 2)
        self.assertEqual(s[TOO_PERMISSIVE], 3)
        self.assertEqual(s["relevant_days"], 3)          # premium > 1.7%
        self.assertEqual(s[f"relevant_{TOO_PERMISSIVE}"], 2)
        self.assertEqual(s[f"relevant_{AGREE}"], 1)

    def test_mismatch_runs_group_consecutive_identical_disagreements(self):
        gold = daily(self.idx, ["closed", "closed", "closed", "open", "closed"])
        cand = daily(self.idx, ["open", "open", "closed", "open", "open"])
        runs = mismatch_runs(classify(gold, cand))
        self.assertEqual([(r["start"], r["end"], r["days"]) for r in runs],
                         [("2024-01-01", "2024-01-02", 2), ("2024-01-05", "2024-01-05", 1)])
        self.assertEqual(runs[0]["category"], TOO_PERMISSIVE)

    def test_mismatch_kinds_count_across_agreeing_gaps(self):
        gold = daily(self.idx, ["limited", "limited", "closed", "limited", "open"],
                     [500, 500, np.nan, 500, np.nan])
        cand = daily(self.idx, ["limited", "limited", "closed", "limited", "closed"],
                     [50, 50, np.nan, 50, np.nan])
        kinds = mismatch_kinds(classify(gold, cand))
        self.assertEqual(len(kinds), 2)
        self.assertEqual((kinds[0]["days"], kinds[0]["first"], kinds[0]["last"]),
                         (3, "2024-01-01", "2024-01-04"))
        self.assertEqual((kinds[0]["gold_amount"], kinds[0]["cand_amount"]), (500, 50))
        self.assertEqual(kinds[1]["category"], TOO_STRICT)
        self.assertTrue(np.isnan(kinds[1]["gold_amount"]))

    def test_mismatch_kinds_empty_when_all_agree(self):
        gold = daily(self.idx, ["open"] * 5)
        self.assertEqual(mismatch_kinds(classify(gold, gold)), [])


class TestRedFlags(unittest.TestCase):
    def test_runs_of_permissive_high_premium_days(self):
        idx = days("2024-01-01", "2024-01-12")  # 10 business days
        frame = pd.DataFrame({
            "premium_rate": [0.06, 0.07, 0.08, 0.01, 0.09, 0.09, 0.10, 0.11, 0.06, 0.06],
            "volume": [1, 1, 1, 1, 1, 1, 1, 1, 0, 1],
        }, index=idx)
        cand = daily(idx, ["open"] * 4 + ["limited", "limited", "limited", "limited", "open", "open"],
                     [np.nan] * 4 + [200000, 200000, 500, 200000, np.nan, np.nan])
        runs = find_red_flags(frame, cand, min_premium=0.05, min_days=3, permissive_amount=100_000)
        # days 1-3 qualify (3 in a row); days 5-6 qualify but day 7 is a small limit -> run of 2;
        # day 8 alone; day 9 has zero volume; day 10 alone.
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["start"], runs[0]["end"], runs[0]["days"]), ("2024-01-01", "2024-01-03", 3))
        self.assertAlmostEqual(runs[0]["mean_premium"], 0.07)

    def test_no_flags_when_closed(self):
        idx = days("2024-01-01", "2024-01-05")
        frame = pd.DataFrame({"premium_rate": [0.2] * 5, "volume": [1] * 5}, index=idx)
        self.assertEqual(find_red_flags(frame, daily(idx, ["closed"] * 5)), [])


if __name__ == "__main__":
    unittest.main()
