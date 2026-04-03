"""
Tests for the announcement processor module (Kimi K2.5 async version).

Tests cover:
- PDF discovery (filtering by title rules)
- Record storage to subscription_restrictions table
- Progress tracking and resume
- Postprocessing: dedup, fix resume type, build limit_events
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data.announcement_processor import AnnouncementProcessor
from src.data.postprocess import (
    dedup_records,
    fix_resume_type,
    build_limit_events,
    write_limit_events,
)


class TestPDFDiscovery(unittest.TestCase):
    """Test find_pdfs() filtering logic."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.db_path = self.test_dir / "fund_status.db"
        self.db_path.touch()
        self.ann_dir = self.test_dir / "announcements"

        # Create test PDFs
        ticker_dir = self.ann_dir / "160105"
        ticker_dir.mkdir(parents=True)
        # Should match: title contains 申购, no 优惠
        (ticker_dir / "2022-01-14_限制大额申购公告.pdf").touch()
        (ticker_dir / "2022-01-19_恢复大额申购公告.pdf").touch()
        # Should NOT match: contains 优惠
        (ticker_dir / "2022-02-01_申购费率优惠公告.pdf").touch()
        # Should NOT match: no 申购
        (ticker_dir / "2022-03-01_分红公告.pdf").touch()
        # Should NOT match: wrong filename pattern
        (ticker_dir / "readme.pdf").touch()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_find_pdfs_filters_correctly(self):
        processor = AnnouncementProcessor(self.db_path, self.ann_dir)
        pdfs = processor.find_pdfs()
        self.assertEqual(len(pdfs), 2)
        names = [Path(p).name for p in pdfs]
        self.assertIn("2022-01-14_限制大额申购公告.pdf", names)
        self.assertIn("2022-01-19_恢复大额申购公告.pdf", names)

    def test_find_pdfs_excludes_youhui(self):
        processor = AnnouncementProcessor(self.db_path, self.ann_dir)
        pdfs = processor.find_pdfs()
        names = [Path(p).name for p in pdfs]
        self.assertNotIn("2022-02-01_申购费率优惠公告.pdf", names)

    def test_find_pdfs_multi_ticker(self):
        # Add another ticker
        ticker2 = self.ann_dir / "160125"
        ticker2.mkdir()
        (ticker2 / "2022-04-12_暂停申购公告.pdf").touch()

        processor = AnnouncementProcessor(self.db_path, self.ann_dir)
        pdfs = processor.find_pdfs()
        self.assertEqual(len(pdfs), 3)
        # Check ticker prefix in paths
        tickers = {Path(p).parts[0] for p in pdfs}
        self.assertEqual(tickers, {"160105", "160125"})


class TestRecordStorage(unittest.TestCase):
    """Test _save_records() writes to subscription_restrictions table."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fund_status.db"
        self.ann_dir = Path(self.temp_dir.name) / "announcements"
        self.ann_dir.mkdir()
        self.processor = AnnouncementProcessor(self.db_path, self.ann_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_single_record(self):
        records = [
            {
                "fund_code": "160105",
                "fund_name": "南方积极配置",
                "announcement_date": "2022-01-14",
                "effective_date": "2022-01-14",
                "end_date": None,
                "action": "restrict",
                "restriction_type": "amount_limit",
                "scope": "large_only",
                "limit_amount": 1000000.0,
                "affected_business": ["purchase", "fixed_invest"],
                "reason": "保护基金份额持有人的利益",
                "source_file": "160105/2022-01-14_限制大额申购.pdf",
                "fund_company": "南方基金",
            }
        ]
        self.processor._save_records(records)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM subscription_restrictions").fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        row = dict(rows[0])
        self.assertEqual(row["fund_code"], "160105")
        self.assertEqual(row["action"], "restrict")
        self.assertEqual(row["limit_amount"], 1000000.0)
        self.assertEqual(row["scope"], "large_only")
        # affected_business stored as JSON string
        ab = json.loads(row["affected_business"])
        self.assertEqual(ab, ["purchase", "fixed_invest"])

    def test_save_multiple_records(self):
        records = [
            {
                "fund_code": "165513",
                "announcement_date": "2022-12-30",
                "effective_date": "2023-01-03",
                "end_date": "2023-01-03",
                "action": "restrict",
                "restriction_type": "holiday_suspension",
                "source_file": "165513/2022-12-30_年度安排.pdf",
            },
            {
                "fund_code": "165513",
                "announcement_date": "2022-12-30",
                "effective_date": "2023-12-25",
                "end_date": "2023-12-25",
                "action": "restrict",
                "restriction_type": "holiday_suspension",
                "source_file": "165513/2022-12-30_年度安排.pdf",
            },
        ]
        self.processor._save_records(records)

        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM subscription_restrictions"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_clear_restrictions(self):
        # Insert then clear
        self.processor._save_records([
            {
                "fund_code": "160105",
                "announcement_date": "2022-01-14",
                "effective_date": "2022-01-14",
                "action": "restrict",
                "source_file": "test.pdf",
            }
        ])
        self.processor._clear_restrictions()

        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM subscription_restrictions"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)


class TestDedup(unittest.TestCase):
    """Test dedup_records from postprocess module."""

    def test_no_duplicates(self):
        records = [
            {"fund_code": "A", "effective_date": "2022-01-01", "action": "restrict",
             "announcement_date": "2022-01-01", "source_file": "A/test.pdf"},
            {"fund_code": "A", "effective_date": "2022-02-01", "action": "resume",
             "announcement_date": "2022-02-01", "source_file": "A/test2.pdf"},
        ]
        result = dedup_records(records)
        self.assertEqual(len(result), 2)

    def test_prefer_single_over_annual(self):
        records = [
            # Annual arrangement
            {"fund_code": "A", "effective_date": "2023-01-03", "action": "restrict",
             "announcement_date": "2022-12-30",
             "source_file": "A/2022-12-30_2023年节假日安排.pdf"},
            # Single announcement (more specific)
            {"fund_code": "A", "effective_date": "2023-01-03", "action": "restrict",
             "announcement_date": "2023-01-02",
             "source_file": "A/2023-01-02_暂停申购.pdf"},
        ]
        result = dedup_records(records)
        self.assertEqual(len(result), 1)
        self.assertIn("暂停申购", result[0]["source_file"])

    def test_prefer_latest_announcement_date(self):
        records = [
            {"fund_code": "A", "effective_date": "2023-01-03", "action": "restrict",
             "announcement_date": "2023-01-01", "source_file": "A/old.pdf"},
            {"fund_code": "A", "effective_date": "2023-01-03", "action": "restrict",
             "announcement_date": "2023-01-02", "source_file": "A/new.pdf"},
        ]
        result = dedup_records(records)
        self.assertEqual(len(result), 1)
        self.assertIn("new.pdf", result[0]["source_file"])


class TestFixResumeType(unittest.TestCase):
    """Test fix_resume_type from postprocess module."""

    def test_inherits_from_preceding_restrict(self):
        records = [
            {"fund_code": "A", "effective_date": "2022-01-14", "action": "restrict",
             "restriction_type": "amount_limit"},
            {"fund_code": "A", "effective_date": "2022-01-19", "action": "resume",
             "restriction_type": None},
        ]
        fix_resume_type(records)
        self.assertEqual(records[1]["restriction_type"], "amount_limit")

    def test_inherits_from_suspend(self):
        records = [
            {"fund_code": "A", "effective_date": "2022-12-20", "action": "suspend",
             "restriction_type": "full_suspension"},
            {"fund_code": "A", "effective_date": "2023-03-01", "action": "resume",
             "restriction_type": None},
        ]
        fix_resume_type(records)
        self.assertEqual(records[1]["restriction_type"], "full_suspension")

    def test_does_not_overwrite_existing(self):
        records = [
            {"fund_code": "A", "effective_date": "2022-01-14", "action": "restrict",
             "restriction_type": "amount_limit"},
            {"fund_code": "A", "effective_date": "2022-01-19", "action": "resume",
             "restriction_type": "full_suspension"},
        ]
        fix_resume_type(records)
        # Should not change already-filled type
        self.assertEqual(records[1]["restriction_type"], "full_suspension")

    def test_separate_funds(self):
        records = [
            {"fund_code": "A", "effective_date": "2022-01-14", "action": "restrict",
             "restriction_type": "amount_limit"},
            {"fund_code": "B", "effective_date": "2022-01-19", "action": "resume",
             "restriction_type": None},
        ]
        fix_resume_type(records)
        # Fund B has no preceding restrict, should remain None
        self.assertIsNone(records[1]["restriction_type"])


class TestBuildLimitEvents(unittest.TestCase):
    """Test build_limit_events from postprocess module."""

    def test_restrict_with_resume(self):
        records = [
            {"fund_code": "160105", "effective_date": "2022-01-14", "end_date": None,
             "action": "restrict", "restriction_type": "amount_limit",
             "limit_amount": 1000000, "reason": "保护持有人", "source_file": "a.pdf"},
            {"fund_code": "160105", "effective_date": "2022-01-19",
             "action": "resume", "restriction_type": "amount_limit",
             "source_file": "b.pdf"},
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["ticker"], "160105")
        self.assertEqual(ev["start_date"], "2022-01-14")
        self.assertEqual(ev["end_date"], "2022-01-18")  # resume - 1 day
        self.assertEqual(ev["max_amount"], 1000000)

    def test_holiday_suspension_defaults_to_one_day(self):
        records = [
            {"fund_code": "160216", "effective_date": "2026-01-19", "end_date": None,
             "action": "restrict", "restriction_type": "holiday_suspension",
             "limit_amount": None, "reason": "MLK day", "source_file": "c.pdf"},
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2026-01-19")
        self.assertEqual(ev["end_date"], "2026-01-19")  # Same day
        self.assertEqual(ev["max_amount"], 0.0)  # Cannot purchase

    def test_suspend_full_suspension(self):
        records = [
            {"fund_code": "168102", "effective_date": "2022-12-20", "end_date": None,
             "action": "suspend", "restriction_type": "full_suspension",
             "limit_amount": None, "reason": "主动暂停", "source_file": "d.pdf"},
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["start_date"], "2022-12-20")
        self.assertIsNone(ev["end_date"])  # Open-ended
        self.assertEqual(ev["max_amount"], 0.0)

    def test_explicit_end_date_used(self):
        records = [
            {"fund_code": "160125", "effective_date": "2022-04-15",
             "end_date": "2022-04-18",
             "action": "restrict", "restriction_type": "holiday_suspension",
             "limit_amount": None, "reason": "耶稣受难日", "source_file": "e.pdf"},
        ]
        events = build_limit_events(records)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["end_date"], "2022-04-18")


class TestWriteLimitEvents(unittest.TestCase):
    """Test writing limit_events to database."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fund_status.db"
        conn = sqlite3.connect(self.db_path)
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
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_and_read(self):
        events = [
            {
                "ticker": "160105",
                "start_date": "2022-01-14",
                "end_date": "2022-01-18",
                "max_amount": 1000000.0,
                "reason": "amount_limit",
                "source_announcement_ids": '["a.pdf"]',
            },
            {
                "ticker": "160216",
                "start_date": "2026-01-19",
                "end_date": "2026-01-19",
                "max_amount": 0.0,
                "reason": "holiday_suspension - MLK day",
            },
        ]
        write_limit_events(self.db_path, events)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT * FROM limit_events ORDER BY id").fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        # First event: amount limit with end date
        self.assertEqual(rows[0][1], "160105")
        self.assertEqual(rows[0][4], 1000000.0)
        self.assertEqual(rows[0][7], 0)  # is_open_ended = 0
        # Second event: holiday suspension
        self.assertEqual(rows[1][1], "160216")
        self.assertEqual(rows[1][4], 0.0)

    def test_write_replaces_existing(self):
        # Write first batch
        write_limit_events(self.db_path, [
            {"ticker": "A", "start_date": "2022-01-01", "end_date": "2022-01-02",
             "max_amount": 100, "reason": "old"},
        ])
        # Write second batch (should replace)
        write_limit_events(self.db_path, [
            {"ticker": "B", "start_date": "2023-01-01", "end_date": None,
             "max_amount": 0, "reason": "new"},
        ])

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT ticker FROM limit_events").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "B")

    def test_open_ended_limit(self):
        write_limit_events(self.db_path, [
            {"ticker": "168102", "start_date": "2022-12-20", "end_date": None,
             "max_amount": 0, "reason": "full_suspension"},
        ])

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT end_date, is_open_ended FROM limit_events").fetchone()
        conn.close()
        self.assertIsNone(row[0])  # end_date is NULL
        self.assertEqual(row[1], 1)  # is_open_ended = 1


if __name__ == "__main__":
    unittest.main()
