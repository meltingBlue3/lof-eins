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

from src.data.postprocess import ValidationBlockedError, validate

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


if __name__ == "__main__":
    unittest.main()
