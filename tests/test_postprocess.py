"""
Tests for src/data/postprocess.py's validation gate and interval-building logic.

Tests cover:
- The validation gate: validate() findings block postprocess()'s write to
  limit_events, and the CLI (scripts/parse_announcements.py) surfaces the
  block with a non-zero exit code and every issue printed.
- The pass side: a clean run writes limit_events and exits 0.
- Boundary behavior of the 180-day staleness check.
- Empty-input shapes: build_limit_events([]), validate([]), and postprocess()
  against a database with zero subscription_restrictions rows.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta

from src.data.postprocess import (
    KNOWN_RESTRICTION_TYPES,
    ValidationBlockedError,
    build_limit_events,
    fix_resume_type,
    load_records,
    postprocess,
    validate,
    write_limit_events,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PostprocessDBTestCase(unittest.TestCase):
    """Shared real-temp-SQLite harness for postprocess.py tests.

    Builds a data/config/fund_status.db tree matching the layout
    scripts/parse_announcements.py expects (--data-dir points at the parent
    of config/fund_status.db), with subscription_restrictions and
    limit_events tables created with the exact production schema.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="lof_test_")
        self.data_dir = Path(self.temp_dir) / "data"
        (self.data_dir / "config").mkdir(parents=True)
        self.db_path = self.data_dir / "config" / "fund_status.db"

        conn = sqlite3.connect(self.db_path)
        # Schema copied verbatim from src/data/downloader.py's
        # subscription_restrictions CREATE TABLE statement.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscription_restrictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                fund_name TEXT,
                announcement_date DATE NOT NULL,
                effective_date DATE NOT NULL,
                end_date DATE,
                action TEXT NOT NULL CHECK(action IN (
                    'restrict', 'suspend', 'resume', 'invalidate', 'adjust_rule'
                )),
                restriction_type TEXT CHECK(restriction_type IN (
                    'amount_limit', 'full_suspension', 'holiday_suspension',
                    'pre_holiday_suspension', 'application_invalid', 'rule_change'
                )),
                scope TEXT CHECK(scope IN ('large_only', 'all', 'partial_channel')),
                limit_amount REAL,
                affected_business TEXT DEFAULT '[]',
                reason TEXT,
                source_file TEXT NOT NULL,
                fund_company TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sr_fund_code
            ON subscription_restrictions(fund_code)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sr_fund_date
            ON subscription_restrictions(fund_code, effective_date)
        """)

        # Schema copied verbatim from src/data/postprocess.py's
        # write_limit_events() CREATE TABLE statement.
        conn.execute("""
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_ticker
            ON limit_events(ticker)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_subscription_restrictions(self, rows):
        """Insert a list of dicts into subscription_restrictions, binding
        every value through placeholder parameters."""
        conn = sqlite3.connect(self.db_path)
        for row in rows:
            columns = list(row.keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_sql = ", ".join(columns)
            conn.execute(
                f"INSERT INTO subscription_restrictions ({col_sql}) VALUES ({placeholders})",
                [row[c] for c in columns],
            )
        conn.commit()
        conn.close()

    def _seed_limit_events(self, rows):
        """Insert directly into limit_events so a 'previous run's table' can
        be established."""
        conn = sqlite3.connect(self.db_path)
        for row in rows:
            columns = list(row.keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_sql = ", ".join(columns)
            conn.execute(
                f"INSERT INTO limit_events ({col_sql}) VALUES ({placeholders})",
                [row[c] for c in columns],
            )
        conn.commit()
        conn.close()

    def _read_limit_events(self):
        """Return the current limit_events rows as a list of tuples,
        ordered by id."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT * FROM limit_events ORDER BY id"
        ).fetchall()
        conn.close()
        return rows

    def _table_names(self):
        """Return the set of table names currently in sqlite_master."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}

    def _run_cli(self, *args):
        """Invoke scripts/parse_announcements.py as a subprocess, returning
        the CompletedProcess with stdout/stderr decoded as UTF-8."""
        script = PROJECT_ROOT / "scripts" / "parse_announcements.py"
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            env=env,
        )
        result.stdout = result.stdout.decode("utf-8", errors="replace")
        result.stderr = result.stderr.decode("utf-8", errors="replace")
        return result


class TestValidationGate(PostprocessDBTestCase):
    """The tracer: a run with a validation finding blocks the write."""

    def test_blocked_run_leaves_limit_events_untouched(self):
        sentinel_rows = [
            {
                "ticker": "999999",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "max_amount": 0.0,
                "reason": "sentinel-1",
                "source_announcement_ids": "[]",
            },
            {
                "ticker": "888888",
                "start_date": "2020-02-01",
                "end_date": None,
                "max_amount": 500000.0,
                "reason": "sentinel-2",
                "source_announcement_ids": "[]",
            },
        ]
        self._seed_limit_events(sentinel_rows)
        before = self._read_limit_events()

        self._seed_subscription_restrictions([
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-20",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "source_file": "test_bad_dates.pdf",
            }
        ])

        result = self._run_cli(
            "--postprocess-only", "--data-dir", str(self.data_dir)
        )
        combined = result.stdout + result.stderr

        self.assertEqual(result.returncode, 1)
        self.assertIn("160105", combined)
        self.assertIn("2022-01-14", combined)
        self.assertIn("2022-01-20", combined)

        after = self._read_limit_events()
        self.assertEqual(before, after)

    def test_clean_run_writes_limit_events_and_replaces_sentinel(self):
        """Pass-side counterpart of the tracer: no validation findings ->
        CLI exits 0, limit_events is populated from the seeded records, and
        the previous sentinel row is replaced (not merged with)."""
        sentinel_rows = [
            {
                "ticker": "999999",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "max_amount": 0.0,
                "reason": "sentinel-1",
                "source_announcement_ids": "[]",
            }
        ]
        self._seed_limit_events(sentinel_rows)

        self._seed_subscription_restrictions([
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-10",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 1000000,
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-18",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ])

        result = self._run_cli(
            "--postprocess-only", "--data-dir", str(self.data_dir)
        )

        self.assertEqual(result.returncode, 0)

        rows = self._read_limit_events()
        fund_rows = [r for r in rows if r[1] == "160105"]
        self.assertEqual(len(fund_rows), 1)
        _, ticker, start_date, end_date, max_amount, _reason, _src, _open = fund_rows[0]
        self.assertEqual(ticker, "160105")
        self.assertEqual(start_date, "2022-01-14")
        self.assertEqual(end_date, "2022-01-18")
        self.assertEqual(max_amount, 1000000)

        # The sentinel row is gone, replaced by the fresh build.
        self.assertNotIn("sentinel-1", [r[5] for r in rows])


class TestValidationBoundaries(PostprocessDBTestCase):
    """Pins the exact 180-day staleness boundary in validate(), called
    directly against in-memory record dicts built from datetime.now() so
    the tests do not rot."""

    @staticmethod
    def _open_suspend_record(fund_code, days_ago):
        now = datetime.now()
        eff = now - timedelta(days=days_ago)
        # announcement_date one day before effective_date so the
        # date-ordering rule never fires here -- only the staleness rule
        # is under test.
        ann = eff - timedelta(days=1)
        return {
            "fund_code": fund_code,
            "announcement_date": ann.strftime("%Y-%m-%d"),
            "effective_date": eff.strftime("%Y-%m-%d"),
            "action": "suspend",
            "restriction_type": "full_suspension",
            "source_file": f"boundary_{days_ago}.pdf",
        }

    def test_exactly_180_days_yields_no_issue(self):
        record = self._open_suspend_record("TEST180", 180)
        self.assertLessEqual(
            record["announcement_date"], record["effective_date"]
        )
        issues = validate([record])
        self.assertEqual(issues, [])

    def test_181_days_yields_exactly_one_issue_naming_the_fund(self):
        record = self._open_suspend_record("TEST181", 181)
        self.assertLessEqual(
            record["announcement_date"], record["effective_date"]
        )
        issues = validate([record])
        self.assertEqual(len(issues), 1)
        self.assertIn("TEST181", issues[0])

    # Note on the 180-day-and-23-hours case named in the plan: validate()
    # parses effective_date with the date-only format "%Y-%m-%d", so a
    # record cannot carry a sub-day component through that field -- any
    # record built at "180 days" old is, at parse time, exactly midnight
    # of that date. The underlying comparison is
    # `(datetime.now() - eff).days > 180`, and `timedelta.days` truncates
    # toward zero rather than rounding. The two tests above already pin
    # this contract directly: the 180-day-old record (whose wall-clock age
    # is 180 days plus a few hours, because `eff` loses the time-of-day it
    # was constructed with once round-tripped through the date-only
    # format) still yields 0 issues, while a record aged one whole day
    # further yields 1 -- i.e. elapsed time strictly greater than 180
    # *whole* days is required to cross the threshold, matching the
    # truncating (not rounding) semantics of `.days`.


class TestEmptyInput(PostprocessDBTestCase):
    """Empty-input shapes: build_limit_events([]), validate([]), and
    postprocess() against a database with zero subscription_restrictions
    rows must not raise and must not silently wipe a downstream table."""

    def test_build_limit_events_empty_list(self):
        self.assertEqual(build_limit_events([]), [])

    def test_validate_empty_list(self):
        self.assertEqual(validate([]), [])

    def test_postprocess_empty_subscription_restrictions_leaves_limit_events(self):
        sentinel_rows = [
            {
                "ticker": "999999",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "max_amount": 0.0,
                "reason": "sentinel-1",
                "source_announcement_ids": "[]",
            }
        ]
        self._seed_limit_events(sentinel_rows)
        before = self._read_limit_events()

        stats = postprocess(self.db_path)

        self.assertEqual(stats["intervals"], 0)
        after = self._read_limit_events()
        self.assertEqual(before, after)


class TestValidateHolidayResumeStaleness(PostprocessDBTestCase):
    """CR-02 regression: validate()'s staleness check must not treat a
    holiday resume as closing a long-term suspension -- build_limit_events()
    doesn't, and the two must agree or the validation gate can wave through
    a suspension it should have caught as stale."""

    def test_holiday_resume_does_not_close_a_stale_long_term_suspension(self):
        now = datetime.now()
        eff = now - timedelta(days=400)
        ann = eff - timedelta(days=1)
        holiday_resume_date = eff + timedelta(days=5)
        records = [
            {
                "fund_code": "161129",
                "announcement_date": ann.strftime("%Y-%m-%d"),
                "effective_date": eff.strftime("%Y-%m-%d"),
                "action": "suspend",
                "restriction_type": "full_suspension",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "161129",
                "announcement_date": holiday_resume_date.strftime("%Y-%m-%d"),
                "effective_date": holiday_resume_date.strftime("%Y-%m-%d"),
                "action": "resume",
                "restriction_type": "holiday_suspension",
                "source_file": "b.pdf",
            },
        ]

        # build_limit_events() must still treat this suspension as open
        # (holiday resumes never close a long-term suspension).
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["end_date"])

        # validate() must agree and flag it as stale rather than letting a
        # holiday resume silently close it.
        issues = validate(records)
        self.assertTrue(
            any("161129" in i and "无对应resume" in i for i in issues),
            f"expected a staleness finding for 161129, got: {issues}",
        )


class TestAdjustRuleIsIntentionalNoOp(PostprocessDBTestCase):
    """WR-04: 'adjust_rule' is a legal subscription_restrictions.action
    value, but is intentionally a no-op at every stage of the pipeline --
    it represents a rule change to an existing restriction, not a new
    suspend/restrict state. This pins that behavior so a future change
    that silently starts (or silently stops) handling it is caught."""

    def test_fix_resume_type_does_not_treat_adjust_rule_as_a_restriction_start(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-01",
                "action": "adjust_rule",
                "restriction_type": "amount_limit",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-01-05",
                "action": "resume",
                "restriction_type": None,
                "source_file": "b.pdf",
            },
        ]
        fixed = fix_resume_type(records)
        # The resume's restriction_type must remain unset: adjust_rule is
        # not a suspend/restrict/invalidate, so it must not seed last_type.
        self.assertIsNone(fixed[1]["restriction_type"])

    def test_build_limit_events_produces_no_interval_for_adjust_rule(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-01",
                "end_date": None,
                "action": "adjust_rule",
                "restriction_type": "amount_limit",
                "limit_amount": 500000,
                "reason": None,
                "source_file": "a.pdf",
            }
        ]
        self.assertEqual(build_limit_events(records), [])

    def test_validate_does_not_flag_adjust_rule_as_an_unresolved_restriction(self):
        records = [
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-01",
                "effective_date": "2022-01-01",
                "action": "adjust_rule",
                "restriction_type": "amount_limit",
                "source_file": "a.pdf",
            }
        ]
        issues = validate(records)
        self.assertFalse(
            any("无对应resume" in i for i in issues),
            f"adjust_rule was flagged as an unresolved restriction: {issues}",
        )


class TestMalformedEffectiveDateFlagged(PostprocessDBTestCase):
    """WR-03 regression: an unparseable effective_date on an open
    restriction must be surfaced as its own validation issue, not silently
    swallowed (which would disable the staleness check for that record)."""

    def test_unparseable_effective_date_on_open_restriction_is_flagged(self):
        records = [
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-01",
                "effective_date": "not-a-date",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "source_file": "a.pdf",
            }
        ]
        issues = validate(records)
        self.assertTrue(
            any(
                "160105" in i and "not-a-date" in i and "无法解析" in i
                for i in issues
            ),
            f"expected a malformed-effective_date finding, got: {issues}",
        )


class TestPostprocessRawStat(PostprocessDBTestCase):
    """WR-02 regression: stats["raw"] must reflect the pre-dedup record
    count, not the post-dedup count records is reassigned to."""

    def test_raw_stat_reflects_pre_dedup_count_when_duplicates_removed(self):
        self._seed_subscription_restrictions([
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-05",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 1000000,
                "source_file": "a.pdf",
            },
            {
                # Same (fund_code, effective_date, action) key as above ->
                # dedup_records() collapses these two into one.
                "fund_code": "160105",
                "announcement_date": "2022-01-10",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 1000000,
                "source_file": "a_dup.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-18",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ])

        stats = postprocess(self.db_path)

        self.assertEqual(stats["raw"], 3)
        self.assertEqual(stats["deduped"], 2)
        self.assertNotEqual(
            stats["raw"],
            stats["deduped"],
            "raw and deduped stats collapsed to the same (post-dedup) count",
        )


class TestValidateForwardNearestPairing(PostprocessDBTestCase):
    """WR-01 regression: validate()'s open-restriction pairing must mirror
    build_limit_events()'s forward-nearest semantics, not a LIFO stack --
    two stacked restrict records closed by the same later resume must both
    be recognised as closed, matching build_limit_events()."""

    def test_two_stacked_restricts_closed_by_same_later_resume_are_both_recognised_closed(self):
        now = datetime.now()
        first_eff = now - timedelta(days=400)
        second_eff = first_eff + timedelta(days=10)
        resume_eff = second_eff + timedelta(days=5)
        records = [
            {
                "fund_code": "160105",
                "announcement_date": (first_eff - timedelta(days=1)).strftime("%Y-%m-%d"),
                "effective_date": first_eff.strftime("%Y-%m-%d"),
                "action": "restrict",
                "restriction_type": "amount_limit",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": (second_eff - timedelta(days=1)).strftime("%Y-%m-%d"),
                "effective_date": second_eff.strftime("%Y-%m-%d"),
                "action": "restrict",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": resume_eff.strftime("%Y-%m-%d"),
                "effective_date": resume_eff.strftime("%Y-%m-%d"),
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "c.pdf",
            },
        ]

        # build_limit_events() closes both restrictions off the single
        # later resume.
        events = build_limit_events(records)
        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertIsNotNone(ev["end_date"])

        # validate() must agree: no unresolved-restriction finding.
        issues = validate(records)
        self.assertFalse(
            any("无对应resume" in i for i in issues),
            f"expected no unresolved-restriction finding, got: {issues}",
        )


class TestExplicitEndDatePrecedence(PostprocessDBTestCase):
    """CR-03 regression: a restrict/suspend record that already carries its
    own explicit end_date from the announcement must keep it, even when an
    unrelated later resume exists further down that fund's timeline."""

    def test_explicit_end_date_is_not_overwritten_by_unrelated_later_resume(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-01",
                "end_date": "2022-03-01",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 500000,
                "reason": "第一次限购公告自带结束日期",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-06-01",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_date"], "2022-01-01")
        self.assertEqual(
            events[0]["end_date"],
            "2022-03-01",
            "the announcement's own explicit end_date was overwritten by "
            "an unrelated later resume",
        )


class TestZeroIntervalGuard(PostprocessDBTestCase):
    """CR-01 regression: non-empty subscription_restrictions that derive
    zero limit_events intervals must block the write rather than silently
    swapping in an empty table and wiping every fund's previously-computed
    backtest data."""

    def test_records_with_zero_derived_intervals_block_write_and_leave_limit_events_untouched(self):
        sentinel_rows = [
            {
                "ticker": "999999",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "max_amount": 0.0,
                "reason": "sentinel-1",
                "source_announcement_ids": "[]",
            },
        ]
        self._seed_limit_events(sentinel_rows)
        before = self._read_limit_events()

        # A single holiday resume with no other record for that fund:
        # build_limit_events() derives zero intervals from it (holiday
        # resumes never open a synthetic interval by themselves), yet the
        # record set itself is non-empty.
        self._seed_subscription_restrictions([
            {
                "fund_code": "888888",
                "announcement_date": "2022-01-30",
                "effective_date": "2022-01-31",
                "action": "resume",
                "restriction_type": "holiday_suspension",
                "source_file": "holiday.pdf",
            }
        ])

        with self.assertRaises(ValidationBlockedError) as ctx:
            postprocess(self.db_path)
        self.assertTrue(
            any("0 个 limit_events" in issue for issue in ctx.exception.issues),
            f"expected a zero-intervals issue, got: {ctx.exception.issues}",
        )

        after = self._read_limit_events()
        self.assertEqual(
            before,
            after,
            "a record set deriving zero intervals wiped the previously "
            "written limit_events table",
        )


class TestUnknownRestrictionType(PostprocessDBTestCase):
    """D-06 scenario 5: an unrecognised non-empty restriction_type must fail
    loudly (build_limit_events raises, validate() flags it), while None/empty
    (the "unspecified" case 32 production records rely on after
    fix_resume_type() runs) remain tolerated exactly as before."""

    def test_known_restriction_types_constant_matches_check_constraint(self):
        # Mirrors the subscription_restrictions CHECK constraint in
        # src/data/downloader.py -- see the constant's own comment.
        self.assertEqual(
            sorted(KNOWN_RESTRICTION_TYPES),
            [
                "amount_limit",
                "application_invalid",
                "full_suspension",
                "holiday_suspension",
                "pre_holiday_suspension",
                "rule_change",
            ],
        )

    def test_build_limit_events_raises_on_unknown_restriction_type(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "brand_new_type",
                "limit_amount": None,
                "reason": "future restriction type",
                "source_file": "x.pdf",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            build_limit_events(records)
        self.assertIn("brand_new_type", str(ctx.exception))

    def test_validate_returns_finding_for_unknown_restriction_type(self):
        records = [
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-10",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": "brand_new_type",
                "source_file": "x.pdf",
            }
        ]
        issues = validate(records)
        self.assertTrue(
            any("brand_new_type" in i and "160105" in i for i in issues),
            f"expected an issue naming brand_new_type and 160105, got: {issues}",
        )

    def test_validate_none_restriction_type_produces_no_unknown_type_finding(self):
        records = [
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-10",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "restriction_type": None,
                "source_file": "x.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-18",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": None,
                "source_file": "y.pdf",
            },
        ]
        issues = validate(records)
        self.assertFalse(
            any("未知" in i for i in issues),
            f"expected no unknown-type finding, got: {issues}",
        )

    def test_build_limit_events_tolerates_none_restriction_type(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": None,
                "limit_amount": None,
                "reason": None,
                "source_file": "x.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": None,
                "source_file": "y.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_date"], "2022-01-14")
        self.assertEqual(events[0]["end_date"], "2022-01-18")

    def test_build_limit_events_tolerates_empty_string_restriction_type(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "",
                "limit_amount": None,
                "reason": None,
                "source_file": "x.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": "",
                "source_file": "y.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_date"], "2022-01-14")
        self.assertEqual(events[0]["end_date"], "2022-01-18")

    def test_all_known_restriction_types_accepted(self):
        for rtype in sorted(KNOWN_RESTRICTION_TYPES):
            records = [
                {
                    "fund_code": "160105",
                    "effective_date": "2022-01-14",
                    "end_date": None,
                    "action": "restrict",
                    "restriction_type": rtype,
                    "limit_amount": 1000000 if rtype == "amount_limit" else None,
                    "reason": None,
                    "source_file": "x.pdf",
                }
            ]
            try:
                build_limit_events(records)
            except ValueError as e:
                self.fail(f"known restriction_type {rtype!r} raised unexpectedly: {e}")


class TestIntervalOrdering(PostprocessDBTestCase):
    """Inverted-interval clamp: a suspend/restrict paired with a non-holiday
    resume on the same effective_date must never produce a backwards
    interval, and build_limit_events() must be deterministic."""

    def test_suspend_and_non_holiday_resume_same_day_clamps_to_single_day(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-03-01",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 500000,
                "reason": None,
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-03-01",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2022-03-01")
        self.assertEqual(ev["end_date"], "2022-03-01")
        for e in events:
            if e["end_date"] is not None:
                self.assertGreaterEqual(
                    e["end_date"], e["start_date"],
                    f"interval runs backwards: {e}",
                )

    def test_build_limit_events_twice_on_same_input_yields_identical_output(self):
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 1000000,
                "reason": "r1",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ]
        first = build_limit_events(records)
        second = build_limit_events(records)
        self.assertEqual(first, second)

    def test_records_sharing_effective_date_preserve_id_order_after_load(self):
        self._seed_subscription_restrictions([
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-01",
                "effective_date": "2022-03-01",
                "action": "suspend",
                "restriction_type": "full_suspension",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-01",
                "effective_date": "2022-03-01",
                "action": "resume",
                "restriction_type": "full_suspension",
                "source_file": "b.pdf",
            },
        ])
        records = load_records(self.db_path)
        self.assertEqual(records[0]["action"], "suspend")
        self.assertEqual(records[1]["action"], "resume")


class TestBuildLimitEventsRegression(PostprocessDBTestCase):
    """D-06 scenario matrix, pinning the two commit 89830c8 state-machine
    defects (which together inflated backtest PnL ~7x) plus the surrounding
    happy-path/edge cases so neither can regress undetected again."""

    def test_normal_suspend_resume_pairing(self):
        """Scenario 1, happy-path anchor: ordinary restrict->resume pairing
        must be unaffected by anything else changed in this phase."""
        records = [
            {
                "fund_code": "160105",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "amount_limit",
                "limit_amount": 1000000,
                "reason": "保护持有人",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "160105",
                "effective_date": "2022-01-19",
                "action": "resume",
                "restriction_type": "amount_limit",
                "source_file": "b.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2022-01-14")
        self.assertEqual(ev["end_date"], "2022-01-18")
        self.assertEqual(ev["max_amount"], 1000000)

    def test_holiday_resume_mid_suspension_does_not_close_it(self):
        """Scenario 2, regression test for commit 89830c8 defect 1: a
        holiday resume in the middle of a long-term suspension must not
        terminate it. Before the fix this produced an interval ending
        2022-02-06, making the fund look purchasable for four months it
        was actually shut -- the core of the ~7x PnL inflation the commit
        fixed."""
        records = [
            {
                "fund_code": "161129",
                "effective_date": "2022-01-10",
                "end_date": None,
                "action": "suspend",
                "restriction_type": "full_suspension",
                "limit_amount": None,
                "reason": "主动暂停",
                "source_file": "a.pdf",
            },
            {
                "fund_code": "161129",
                "effective_date": "2022-02-07",
                "action": "resume",
                "restriction_type": "holiday_suspension",
                "source_file": "b.pdf",
            },
            {
                "fund_code": "161129",
                "effective_date": "2022-06-01",
                "action": "resume",
                "restriction_type": "full_suspension",
                "source_file": "c.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2022-01-10")
        self.assertEqual(ev["end_date"], "2022-05-31")
        self.assertNotEqual(
            ev["end_date"],
            "2022-02-06",
            "89830c8 regression: holiday resume closed the suspension early",
        )

    def test_missing_prior_suspend_yields_synthetic_interval(self):
        """Scenario 3, regression test for commit 89830c8 defect 2: a fund
        whose first non-holiday event is a resume must get a synthetic
        interval starting 2000-01-01, not be silently dropped as an orphan
        resume."""
        records = [
            {
                "fund_code": "161129",
                "effective_date": "2022-03-15",
                "action": "resume",
                "restriction_type": "full_suspension",
                "source_file": "a.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2000-01-01")
        self.assertEqual(ev["end_date"], "2022-03-14")
        self.assertEqual(ev["max_amount"], 0.0)
        self.assertIn("synthetic", ev["reason"])

    def test_synthetic_interval_survives_leading_holiday_resume(self):
        """Scenario 3b: the two commit 89830c8 fixes must compose. A
        leading holiday resume must not be mistaken for the "first event"
        that decides whether a synthetic interval is needed."""
        records = [
            {
                "fund_code": "161129",
                "effective_date": "2022-01-31",
                "action": "resume",
                "restriction_type": "holiday_suspension",
                "source_file": "z.pdf",
            },
            {
                "fund_code": "161129",
                "effective_date": "2022-03-15",
                "action": "resume",
                "restriction_type": "full_suspension",
                "source_file": "a.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2000-01-01")
        self.assertEqual(ev["end_date"], "2022-03-14")

    def test_unmatched_open_ended_suspend_round_trips_as_null(self):
        """Scenario 4: a suspend with no matching resume anywhere in the
        stream must produce an open interval (NULL end_date), never be
        silently dropped, and that NULL must survive a real write/read
        cycle against the temp database with the generated open-ended
        flag set. This also guards the generated-column definition that
        plan 04-03 rebuilds when it introduces the staging table."""
        records = [
            {
                "fund_code": "168102",
                "effective_date": "2022-12-20",
                "end_date": None,
                "action": "suspend",
                "restriction_type": "full_suspension",
                "limit_amount": None,
                "reason": "主动暂停",
                "source_file": "d.pdf",
            },
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIsNone(ev["end_date"])
        self.assertEqual(ev["max_amount"], 0.0)

        write_limit_events(self.db_path, events)
        rows = self._read_limit_events()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # id, ticker, start_date, end_date, max_amount, reason, source_announcement_ids, is_open_ended
        self.assertIsNone(row[3])
        self.assertEqual(row[7], 1)


class TestAtomicSwap(PostprocessDBTestCase):
    """T-04-06/07/08/11: write_limit_events() stages every row into
    limit_events_new inside one transaction and only replaces the live
    table after the final insert succeeds. A forced mid-write failure
    (a real NOT NULL constraint violation, no mocking library, per D-07)
    must leave the previously-written limit_events rows byte-identical,
    leave no staging-table residue, re-raise, and not wedge the database
    against the next run."""

    @staticmethod
    def _two_seed_rows():
        return [
            {
                "ticker": "160105",
                "start_date": "2022-01-01",
                "end_date": "2022-01-05",
                "max_amount": 0.0,
                "reason": "seed-1",
                "source_announcement_ids": "[]",
            },
            {
                "ticker": "160216",
                "start_date": "2022-02-01",
                "end_date": None,
                "max_amount": 500000.0,
                "reason": "seed-2",
                "source_announcement_ids": "[]",
            },
        ]

    @staticmethod
    def _mid_write_failure_events():
        """First entry is a well-formed interval; second sets start_date to
        None, which the NOT NULL constraint on that column rejects at
        insert time -- the real constraint violation that forces the
        mid-write failure, per D-07 (no mocking library)."""
        return [
            {
                "ticker": "888888",
                "start_date": "2023-01-01",
                "end_date": "2023-01-05",
                "max_amount": 100000.0,
                "reason": "valid",
                "source_announcement_ids": "[]",
            },
            {
                "ticker": "999999",
                "start_date": None,
                "end_date": None,
                "max_amount": 0.0,
                "reason": "invalid - null start_date",
                "source_announcement_ids": "[]",
            },
        ]

    def test_mid_write_failure_leaves_previous_rows_intact_and_reraises(self):
        self._seed_limit_events(self._two_seed_rows())
        before = self._read_limit_events()
        self.assertEqual(len(before), 2)

        with self.assertRaises(sqlite3.IntegrityError):
            write_limit_events(self.db_path, self._mid_write_failure_events())

        after = self._read_limit_events()
        self.assertEqual(
            len(after),
            2,
            "a crashed write destroyed the last known-good limit_events dataset",
        )
        self.assertEqual(
            [r[1] for r in before],
            [r[1] for r in after],
            "a crashed write altered the ticker values of the previously-written rows",
        )
        self.assertEqual(
            before,
            after,
            "a crashed write altered the previously-written rows",
        )

    def test_mid_write_failure_leaves_no_staging_table_residue(self):
        self._seed_limit_events(self._two_seed_rows())

        with self.assertRaises(sqlite3.IntegrityError):
            write_limit_events(self.db_path, self._mid_write_failure_events())

        tables = self._table_names()
        self.assertIn("limit_events", tables)
        self.assertNotIn(
            "limit_events_new",
            tables,
            "staging table lingered after a failed write and could collide "
            "with, or silently seed, the next run",
        )

    def test_valid_write_after_failed_write_succeeds_and_replaces(self):
        self._seed_limit_events(self._two_seed_rows())

        with self.assertRaises(sqlite3.IntegrityError):
            write_limit_events(self.db_path, self._mid_write_failure_events())

        good_events = [
            {
                "ticker": "160105",
                "start_date": "2024-01-01",
                "end_date": "2024-01-05",
                "max_amount": 200000.0,
                "reason": "recovered",
                "source_announcement_ids": "[]",
            },
        ]
        write_limit_events(self.db_path, good_events)

        rows = self._read_limit_events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "160105")
        self.assertEqual(rows[0][5], "recovered")

    def test_successful_write_against_fresh_database_creates_indexes(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE limit_events")
        conn.commit()
        conn.close()
        self.assertNotIn("limit_events", self._table_names())

        write_limit_events(
            self.db_path,
            [
                {
                    "ticker": "160105",
                    "start_date": "2022-01-01",
                    "end_date": None,
                    "max_amount": 0.0,
                    "reason": "fresh",
                    "source_announcement_ids": "[]",
                }
            ],
        )

        self.assertIn("limit_events", self._table_names())
        conn = sqlite3.connect(self.db_path)
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='limit_events'"
            ).fetchall()
        }
        conn.close()
        self.assertIn("idx_limit_events_ticker", indexes)
        self.assertIn("idx_limit_events_is_open_ended", indexes)

    def test_two_successive_successful_writes_hold_exactly_second_calls_rows(self):
        write_limit_events(
            self.db_path,
            [
                {
                    "ticker": "A",
                    "start_date": "2022-01-01",
                    "end_date": "2022-01-02",
                    "max_amount": 100.0,
                    "reason": "first",
                    "source_announcement_ids": "[]",
                }
            ],
        )
        write_limit_events(
            self.db_path,
            [
                {
                    "ticker": "B",
                    "start_date": "2023-01-01",
                    "end_date": None,
                    "max_amount": 0.0,
                    "reason": "second",
                    "source_announcement_ids": "[]",
                }
            ],
        )
        rows = self._read_limit_events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "B")


if __name__ == "__main__":
    unittest.main()
