"""
Database schema validation tests for LOF Fund Arbitrage Backtesting System.

Tests verify that all three tables (limit_events, announcement_parses, limit_event_log)
have correct schema including:
- Proper columns with correct types
- Nullable vs non-nullable fields
- Generated columns (is_open_ended)
- Indexes exist
- Default values
"""

import sys
import os
import unittest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDatabaseSchema(unittest.TestCase):
    """Test suite for database schema validation."""

    def setUp(self):
        """Set up temporary SQLite database."""
        self.temp_dir = tempfile.mkdtemp(prefix="lof_schema_test_")
        self.db_path = Path(self.temp_dir) / "test_fund_status.db"
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()

        # Create schema matching generators.py
        self._create_full_schema()

    def tearDown(self):
        """Clean up temporary database."""
        self.conn.close()
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_full_schema(self):
        """Create the full database schema as defined in generators.py."""
        # limit_events table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_events (
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

        # Indexes for limit_events
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)

        # announcement_parses table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcement_parses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                announcement_date DATE NOT NULL,
                pdf_filename TEXT NOT NULL,
                parse_result TEXT,
                parse_type TEXT,
                confidence REAL,
                processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for announcement_parses
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_ticker
            ON announcement_parses(ticker)
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_processed
            ON announcement_parses(processed)
        """)

        # limit_event_log table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                operation TEXT NOT NULL,
                old_start DATE,
                old_end DATE,
                new_start DATE,
                new_end DATE,
                triggered_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for limit_event_log
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_ticker
            ON limit_event_log(ticker)
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_created_at
            ON limit_event_log(created_at)
        """)

        self.conn.commit()

    def _get_table_info(self, table_name: str) -> list:
        """Get PRAGMA table_info results for a table."""
        self.cursor.execute(f"PRAGMA table_info({table_name})")
        return self.cursor.fetchall()

    def _get_indexes(self, table_name: str) -> list:
        """Get indexes for a table."""
        self.cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table_name,),
        )
        return self.cursor.fetchall()

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists (including generated columns)."""
        # Check regular columns via PRAGMA
        self.cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in self.cursor.fetchall()]
        if column_name in columns:
            return True

        # Check generated columns by trying to query
        try:
            self.cursor.execute(f"SELECT {column_name} FROM {table_name} LIMIT 0")
            return True
        except sqlite3.OperationalError:
            return False

    # =========================================================================
    # limit_events Schema Tests
    # =========================================================================

    def test_limit_events_table_exists(self):
        """Test that limit_events table exists."""
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='limit_events'"
        )
        result = self.cursor.fetchone()
        self.assertIsNotNone(result, "limit_events table should exist")
        self.assertEqual(result[0], "limit_events")

    def test_limit_events_required_columns(self):
        """Test that limit_events has all required columns."""
        required_columns = [
            "id",
            "ticker",
            "start_date",
            "end_date",
            "max_amount",
            "reason",
            "source_announcement_ids",
            "is_open_ended",
        ]

        for col in required_columns:
            self.assertTrue(
                self._column_exists("limit_events", col),
                f"Column '{col}' should exist in limit_events",
            )

    def test_limit_events_id_column_properties(self):
        """Test id column: INTEGER PRIMARY KEY AUTOINCREMENT."""
        info = self._get_table_info("limit_events")
        id_col = [row for row in info if row[1] == "id"][0]

        # cid, name, type, notnull, dflt_value, pk
        self.assertEqual(id_col[2], "INTEGER", "id should be INTEGER")
        self.assertEqual(id_col[3], 0, "id should be nullable (SQLite convention)")
        self.assertEqual(id_col[5], 1, "id should be primary key")

    def test_limit_events_ticker_not_null(self):
        """Test ticker column: TEXT NOT NULL."""
        info = self._get_table_info("limit_events")
        ticker_col = [row for row in info if row[1] == "ticker"][0]

        self.assertEqual(ticker_col[2], "TEXT", "ticker should be TEXT")
        self.assertEqual(ticker_col[3], 1, "ticker should be NOT NULL")

    def test_limit_events_start_date_not_null(self):
        """Test start_date column: DATE NOT NULL."""
        info = self._get_table_info("limit_events")
        start_col = [row for row in info if row[1] == "start_date"][0]

        self.assertEqual(start_col[2], "DATE", "start_date should be DATE")
        self.assertEqual(start_col[3], 1, "start_date should be NOT NULL")

    def test_limit_events_end_date_nullable(self):
        """Test end_date column: DATE (nullable for open-ended limits)."""
        info = self._get_table_info("limit_events")
        end_col = [row for row in info if row[1] == "end_date"][0]

        self.assertEqual(end_col[2], "DATE", "end_date should be DATE")
        self.assertEqual(end_col[3], 0, "end_date should be nullable")

    def test_limit_events_max_amount_not_null(self):
        """Test max_amount column: REAL NOT NULL."""
        info = self._get_table_info("limit_events")
        max_col = [row for row in info if row[1] == "max_amount"][0]

        self.assertEqual(max_col[2], "REAL", "max_amount should be REAL")
        self.assertEqual(max_col[3], 1, "max_amount should be NOT NULL")
        # Check NOT NULL in CREATE TABLE statement
        self.cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='limit_events'"
        )
        create_sql = self.cursor.fetchone()[0]
        self.assertIn(
            "max_amount REAL NOT NULL", create_sql, "max_amount should be REAL NOT NULL"
        )

    def test_limit_events_reason_nullable(self):
        """Test reason column: TEXT (nullable)."""
        info = self._get_table_info("limit_events")
        reason_col = [row for row in info if row[1] == "reason"][0]

        self.assertEqual(reason_col[2], "TEXT", "reason should be TEXT")
        self.assertEqual(reason_col[3], 0, "reason should be nullable")

    def test_limit_events_source_announcement_ids(self):
        """Test source_announcement_ids column: TEXT DEFAULT '[]'."""
        info = self._get_table_info("limit_events")
        source_col = [row for row in info if row[1] == "source_announcement_ids"][0]

        self.assertEqual(
            source_col[2], "TEXT", "source_announcement_ids should be TEXT"
        )
        self.assertEqual(
            source_col[4], "'[]'", "source_announcement_ids should DEFAULT '[]'"
        )

    def test_limit_events_is_open_ended_generated(self):
        """Test is_open_ended column: GENERATED ALWAYS AS (CASE WHEN end_date IS NULL THEN 1 ELSE 0 END)."""
        # Verify column exists (won't show in table_info)
        self.assertTrue(
            self._column_exists("limit_events", "is_open_ended"),
            "is_open_ended column should exist",
        )

        # Verify it's a generated column by checking CREATE TABLE
        self.cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='limit_events'"
        )
        create_sql = self.cursor.fetchone()[0]

        self.assertIn(
            "GENERATED ALWAYS AS", create_sql, "is_open_ended should be generated"
        )
        self.assertIn("is_open_ended", create_sql, "is_open_ended should be in schema")

    def test_limit_events_is_open_ended_computation(self):
        """Test that is_open_ended correctly computes based on end_date."""
        # Insert test data
        self.cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount)
            VALUES (?, ?, ?, ?)""",
            ("TEST1", "2024-01-01", None, 100.0),
        )
        open_ended_id = self.cursor.lastrowid

        self.cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount)
            VALUES (?, ?, ?, ?)""",
            ("TEST2", "2024-01-01", "2024-02-01", 100.0),
        )
        closed_id = self.cursor.lastrowid

        self.conn.commit()

        # Verify computed values
        self.cursor.execute(
            "SELECT is_open_ended FROM limit_events WHERE id=?", (open_ended_id,)
        )
        self.assertEqual(
            self.cursor.fetchone()[0], 1, "NULL end_date should give is_open_ended=1"
        )

        self.cursor.execute(
            "SELECT is_open_ended FROM limit_events WHERE id=?", (closed_id,)
        )
        self.assertEqual(
            self.cursor.fetchone()[0],
            0,
            "Non-NULL end_date should give is_open_ended=0",
        )

    def test_limit_events_indexes_exist(self):
        """Test that required indexes exist on limit_events."""
        indexes = self._get_indexes("limit_events")
        index_names = [idx[0] for idx in indexes]

        self.assertIn(
            "idx_limit_events_is_open_ended",
            index_names,
            "Index on is_open_ended should exist",
        )

    def test_limit_events_insert_null_end_date(self):
        """Test inserting NULL end_date succeeds."""
        self.cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, end_date, max_amount)
            VALUES (?, ?, ?, ?)""",
            ("NULL_TEST", "2024-01-01", None, 100.0),
        )
        self.conn.commit()

        self.cursor.execute(
            "SELECT COUNT(*) FROM limit_events WHERE ticker=?", ("NULL_TEST",)
        )
        self.assertEqual(
            self.cursor.fetchone()[0], 1, "Insert with NULL end_date should succeed"
        )

    def test_limit_events_insert_without_end_date(self):
        """Test inserting without specifying end_date uses NULL."""
        self.cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, max_amount)
            VALUES (?, ?, ?)""",
            ("NO_END_TEST", "2024-01-01", 100.0),
        )
        self.conn.commit()

        self.cursor.execute(
            "SELECT end_date, is_open_ended FROM limit_events WHERE ticker=?",
            ("NO_END_TEST",),
        )
        row = self.cursor.fetchone()
        self.assertIsNone(row[0], "end_date should be NULL when not specified")
        self.assertEqual(row[1], 1, "is_open_ended should be 1 when end_date is NULL")

    def test_limit_events_insert_without_source_ids(self):
        """Test that source_announcement_ids defaults to '[]'."""
        self.cursor.execute(
            """INSERT INTO limit_events (ticker, start_date, max_amount)
            VALUES (?, ?, ?)""",
            ("NO_SOURCE_TEST", "2024-01-01", 100.0),
        )
        self.conn.commit()

        self.cursor.execute(
            "SELECT source_announcement_ids FROM limit_events WHERE ticker=?",
            ("NO_SOURCE_TEST",),
        )
        self.assertEqual(
            self.cursor.fetchone()[0],
            "[]",
            "source_announcement_ids should default to '[]'",
        )

    def test_limit_events_insert_null_ticker_fails(self):
        """Test inserting NULL ticker fails due to NOT NULL constraint."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO limit_events (ticker, start_date, max_amount)
                VALUES (?, ?, ?)""",
                (None, "2024-01-01", 100.0),
            )

    def test_limit_events_insert_null_start_fails(self):
        """Test inserting NULL start_date fails due to NOT NULL constraint."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO limit_events (ticker, start_date, max_amount)
                VALUES (?, ?, ?)""",
                ("TEST", None, 100.0),
            )

    # =========================================================================
    # announcement_parses Schema Tests
    # =========================================================================

    def test_announcement_parses_table_exists(self):
        """Test that announcement_parses table exists."""
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='announcement_parses'"
        )
        result = self.cursor.fetchone()
        self.assertIsNotNone(result, "announcement_parses table should exist")

    def test_announcement_parses_required_columns(self):
        """Test that announcement_parses has all required columns."""
        required_columns = [
            "id",
            "ticker",
            "announcement_date",
            "pdf_filename",
            "parse_result",
            "parse_type",
            "confidence",
            "processed",
            "created_at",
        ]

        info = self._get_table_info("announcement_parses")
        column_names = [row[1] for row in info]

        for col in required_columns:
            self.assertIn(
                col, column_names, f"Column '{col}' should exist in announcement_parses"
            )

    def test_announcement_parses_id_column(self):
        """Test id column in announcement_parses."""
        info = self._get_table_info("announcement_parses")
        id_col = [row for row in info if row[1] == "id"][0]

        self.assertEqual(id_col[2], "INTEGER", "id should be INTEGER")
        self.assertEqual(id_col[5], 1, "id should be primary key")

    def test_announcement_parses_ticker_not_null(self):
        """Test ticker column: TEXT NOT NULL."""
        info = self._get_table_info("announcement_parses")
        ticker_col = [row for row in info if row[1] == "ticker"][0]

        self.assertEqual(ticker_col[2], "TEXT", "ticker should be TEXT")
        self.assertEqual(ticker_col[3], 1, "ticker should be NOT NULL")

    def test_announcement_parses_announcement_date_not_null(self):
        """Test announcement_date column: DATE NOT NULL."""
        info = self._get_table_info("announcement_parses")
        date_col = [row for row in info if row[1] == "announcement_date"][0]

        self.assertEqual(date_col[2], "DATE", "announcement_date should be DATE")
        self.assertEqual(date_col[3], 1, "announcement_date should be NOT NULL")

    def test_announcement_parses_pdf_filename_not_null(self):
        """Test pdf_filename column: TEXT NOT NULL."""
        info = self._get_table_info("announcement_parses")
        pdf_col = [row for row in info if row[1] == "pdf_filename"][0]

        self.assertEqual(pdf_col[2], "TEXT", "pdf_filename should be TEXT")
        self.assertEqual(pdf_col[3], 1, "pdf_filename should be NOT NULL")

    def test_announcement_parses_parse_result_nullable(self):
        """Test parse_result column: TEXT (nullable for storing LLM output)."""
        info = self._get_table_info("announcement_parses")
        result_col = [row for row in info if row[1] == "parse_result"][0]

        self.assertEqual(result_col[2], "TEXT", "parse_result should be TEXT")
        self.assertEqual(result_col[3], 0, "parse_result should be nullable")

    def test_announcement_parses_parse_type_nullable(self):
        """Test parse_type column: TEXT (nullable)."""
        info = self._get_table_info("announcement_parses")
        type_col = [row for row in info if row[1] == "parse_type"][0]

        self.assertEqual(type_col[2], "TEXT", "parse_type should be TEXT")
        self.assertEqual(type_col[3], 0, "parse_type should be nullable")

    def test_announcement_parses_confidence_nullable(self):
        """Test confidence column: REAL (nullable for LLM confidence score)."""
        info = self._get_table_info("announcement_parses")
        conf_col = [row for row in info if row[1] == "confidence"][0]

        self.assertEqual(conf_col[2], "REAL", "confidence should be REAL")
        self.assertEqual(conf_col[3], 0, "confidence should be nullable")

    def test_announcement_parses_processed_default(self):
        """Test processed column: INTEGER DEFAULT 0."""
        info = self._get_table_info("announcement_parses")
        proc_col = [row for row in info if row[1] == "processed"][0]

        self.assertEqual(proc_col[2], "INTEGER", "processed should be INTEGER")
        self.assertEqual(proc_col[4], "0", "processed should DEFAULT 0")

    def test_announcement_parses_created_at_default(self):
        """Test created_at column: TIMESTAMP DEFAULT CURRENT_TIMESTAMP."""
        info = self._get_table_info("announcement_parses")
        created_col = [row for row in info if row[1] == "created_at"][0]

        # SQLite stores TIMESTAMP as TEXT/NUMERIC
        self.assertIn(
            created_col[2],
            ["TIMESTAMP", "TEXT", "NUMERIC"],
            "created_at should be TIMESTAMP type",
        )
        self.assertEqual(
            created_col[4],
            "CURRENT_TIMESTAMP",
            "created_at should DEFAULT CURRENT_TIMESTAMP",
        )

    def test_announcement_parses_indexes_exist(self):
        """Test that required indexes exist on announcement_parses."""
        indexes = self._get_indexes("announcement_parses")
        index_names = [idx[0] for idx in indexes]

        self.assertIn(
            "idx_announcement_parses_ticker",
            index_names,
            "Index on ticker should exist",
        )
        self.assertIn(
            "idx_announcement_parses_processed",
            index_names,
            "Index on processed should exist",
        )

    def test_announcement_parses_insert_minimal(self):
        """Test inserting minimal required fields succeeds."""
        before = datetime.now()

        self.cursor.execute(
            """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename)
            VALUES (?, ?, ?)""",
            ("TEST", "2024-01-01", "test.pdf"),
        )
        self.conn.commit()

        self.cursor.execute(
            """SELECT processed, created_at FROM announcement_parses WHERE ticker=?""",
            ("TEST",),
        )
        row = self.cursor.fetchone()

        self.assertEqual(row[0], 0, "processed should default to 0")
        self.assertIsNotNone(row[1], "created_at should be auto-populated")

    def test_announcement_parses_insert_null_required_fails(self):
        """Test inserting NULL into required fields fails."""
        # Test NULL ticker
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename)
                VALUES (?, ?, ?)""",
                (None, "2024-01-01", "test.pdf"),
            )

        # Test NULL announcement_date
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename)
                VALUES (?, ?, ?)""",
                ("TEST", None, "test.pdf"),
            )

        # Test NULL pdf_filename
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename)
                VALUES (?, ?, ?)""",
                ("TEST", "2024-01-01", None),
            )

    def test_announcement_parses_json_storage(self):
        """Test that parse_result can store JSON text."""
        json_data = '{"limit": 100, "start_date": "2024-01-01", "end_date": null}'

        self.cursor.execute(
            """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename, parse_result)
            VALUES (?, ?, ?, ?)""",
            ("JSON_TEST", "2024-01-01", "test.pdf", json_data),
        )
        self.conn.commit()

        self.cursor.execute(
            "SELECT parse_result FROM announcement_parses WHERE ticker=?",
            ("JSON_TEST",),
        )
        result = self.cursor.fetchone()[0]
        self.assertEqual(result, json_data, "JSON data should be stored correctly")

    # =========================================================================
    # limit_event_log Schema Tests
    # =========================================================================

    def test_limit_event_log_table_exists(self):
        """Test that limit_event_log table exists."""
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='limit_event_log'"
        )
        result = self.cursor.fetchone()
        self.assertIsNotNone(result, "limit_event_log table should exist")

    def test_limit_event_log_required_columns(self):
        """Test that limit_event_log has all required columns."""
        required_columns = [
            "id",
            "ticker",
            "operation",
            "old_start",
            "old_end",
            "new_start",
            "new_end",
            "triggered_by",
            "created_at",
        ]

        info = self._get_table_info("limit_event_log")
        column_names = [row[1] for row in info]

        for col in required_columns:
            self.assertIn(
                col, column_names, f"Column '{col}' should exist in limit_event_log"
            )

    def test_limit_event_log_id_column(self):
        """Test id column in limit_event_log."""
        info = self._get_table_info("limit_event_log")
        id_col = [row for row in info if row[1] == "id"][0]

        self.assertEqual(id_col[2], "INTEGER", "id should be INTEGER")
        self.assertEqual(id_col[5], 1, "id should be primary key")

    def test_limit_event_log_ticker_not_null(self):
        """Test ticker column: TEXT NOT NULL."""
        info = self._get_table_info("limit_event_log")
        ticker_col = [row for row in info if row[1] == "ticker"][0]

        self.assertEqual(ticker_col[2], "TEXT", "ticker should be TEXT")
        self.assertEqual(ticker_col[3], 1, "ticker should be NOT NULL")

    def test_limit_event_log_operation_not_null(self):
        """Test operation column: TEXT NOT NULL."""
        info = self._get_table_info("limit_event_log")
        op_col = [row for row in info if row[1] == "operation"][0]

        self.assertEqual(op_col[2], "TEXT", "operation should be TEXT")
        self.assertEqual(op_col[3], 1, "operation should be NOT NULL")

    def test_limit_event_log_date_columns_nullable(self):
        """Test that old/new date columns are nullable."""
        nullable_date_cols = ["old_start", "old_end", "new_start", "new_end"]
        info = self._get_table_info("limit_event_log")

        for col_name in nullable_date_cols:
            col = [row for row in info if row[1] == col_name][0]
            self.assertEqual(col[2], "DATE", f"{col_name} should be DATE")
            self.assertEqual(col[3], 0, f"{col_name} should be nullable")

    def test_limit_event_log_triggered_by_nullable(self):
        """Test triggered_by column: TEXT (nullable)."""
        info = self._get_table_info("limit_event_log")
        trig_col = [row for row in info if row[1] == "triggered_by"][0]

        self.assertEqual(trig_col[2], "TEXT", "triggered_by should be TEXT")
        self.assertEqual(trig_col[3], 0, "triggered_by should be nullable")

    def test_limit_event_log_created_at_default(self):
        """Test created_at column: TIMESTAMP DEFAULT CURRENT_TIMESTAMP."""
        info = self._get_table_info("limit_event_log")
        created_col = [row for row in info if row[1] == "created_at"][0]

        self.assertEqual(
            created_col[4],
            "CURRENT_TIMESTAMP",
            "created_at should DEFAULT CURRENT_TIMESTAMP",
        )

    def test_limit_event_log_indexes_exist(self):
        """Test that required indexes exist on limit_event_log."""
        indexes = self._get_indexes("limit_event_log")
        index_names = [idx[0] for idx in indexes]

        self.assertIn(
            "idx_limit_event_log_ticker", index_names, "Index on ticker should exist"
        )
        self.assertIn(
            "idx_limit_event_log_created_at",
            index_names,
            "Index on created_at should exist",
        )

    def test_limit_event_log_insert_minimal(self):
        """Test inserting minimal required fields succeeds."""
        self.cursor.execute(
            """INSERT INTO limit_event_log (ticker, operation)
            VALUES (?, ?)""",
            ("TEST", "INSERT"),
        )
        self.conn.commit()

        self.cursor.execute(
            """SELECT old_start, old_end, new_start, new_end, triggered_by, created_at
            FROM limit_event_log WHERE ticker=?""",
            ("TEST",),
        )
        row = self.cursor.fetchone()

        self.assertIsNone(row[0], "old_start should be NULL")
        self.assertIsNone(row[1], "old_end should be NULL")
        self.assertIsNone(row[2], "new_start should be NULL")
        self.assertIsNone(row[3], "new_end should be NULL")
        self.assertIsNone(row[4], "triggered_by should be NULL")
        self.assertIsNotNone(row[5], "created_at should be auto-populated")

    def test_limit_event_log_insert_full(self):
        """Test inserting full audit record with all dates."""
        self.cursor.execute(
            """INSERT INTO limit_event_log 
            (ticker, operation, old_start, old_end, new_start, new_end, triggered_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "TEST",
                "UPDATE",
                "2024-01-01",
                "2024-01-31",
                "2024-01-01",
                None,
                "manual",
            ),
        )
        self.conn.commit()

        self.cursor.execute(
            """SELECT * FROM limit_event_log WHERE ticker=?""", ("TEST",)
        )
        row = self.cursor.fetchone()

        self.assertEqual(row[1], "TEST", "ticker should be stored")
        self.assertEqual(row[2], "UPDATE", "operation should be stored")
        self.assertEqual(row[3], "2024-01-01", "old_start should be stored")
        self.assertEqual(row[4], "2024-01-31", "old_end should be stored")
        self.assertEqual(row[5], "2024-01-01", "new_start should be stored")
        self.assertIsNone(row[6], "new_end should be NULL (open-ended)")
        self.assertEqual(row[7], "manual", "triggered_by should be stored")

    def test_limit_event_log_insert_null_required_fails(self):
        """Test inserting NULL into required fields fails."""
        # Test NULL ticker
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO limit_event_log (ticker, operation)
                VALUES (?, ?)""",
                (None, "INSERT"),
            )

        # Test NULL operation
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                """INSERT INTO limit_event_log (ticker, operation)
                VALUES (?, ?)""",
                ("TEST", None),
            )

    # =========================================================================
    # Cross-Table Integrity Tests
    # =========================================================================

    def test_all_tables_exist(self):
        """Test that all three required tables exist."""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in self.cursor.fetchall()]

        required_tables = ["limit_events", "announcement_parses", "limit_event_log"]
        for table in required_tables:
            self.assertIn(table, tables, f"Table '{table}' should exist")

    def test_all_indexes_exist(self):
        """Test that all required indexes exist across all tables."""
        self.cursor.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index'"
        )
        indexes = self.cursor.fetchall()

        expected_indexes = [
            ("idx_limit_events_is_open_ended", "limit_events"),
            ("idx_announcement_parses_ticker", "announcement_parses"),
            ("idx_announcement_parses_processed", "announcement_parses"),
            ("idx_limit_event_log_ticker", "limit_event_log"),
            ("idx_limit_event_log_created_at", "limit_event_log"),
        ]

        for idx_name, table_name in expected_indexes:
            self.assertIn(
                (idx_name, table_name),
                indexes,
                f"Index '{idx_name}' on '{table_name}' should exist",
            )


class TestDatabaseSchemaIntegration(unittest.TestCase):
    """Integration tests using actual database creation patterns."""

    def test_schema_matches_generator_pattern(self):
        """Verify schema matches the pattern used in FundStatusGenerator."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "fund_status.db"

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Create schema exactly as FundStatusGenerator does
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS limit_events (
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

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
                ON limit_events(is_open_ended)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS announcement_parses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    announcement_date DATE NOT NULL,
                    pdf_filename TEXT NOT NULL,
                    parse_result TEXT,
                    parse_type TEXT,
                    confidence REAL,
                    processed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_announcement_parses_ticker
                ON announcement_parses(ticker)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_announcement_parses_processed
                ON announcement_parses(processed)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS limit_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    old_start DATE,
                    old_end DATE,
                    new_start DATE,
                    new_end DATE,
                    triggered_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_limit_event_log_ticker
                ON limit_event_log(ticker)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_limit_event_log_created_at
                ON limit_event_log(created_at)
            """)

            conn.commit()

            # Verify tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            self.assertIn("limit_events", tables)
            self.assertIn("announcement_parses", tables)
            self.assertIn("limit_event_log", tables)

            # Test insertion
            cursor.execute(
                """INSERT INTO limit_events (ticker, start_date, end_date, max_amount)
                VALUES (?, ?, ?, ?)""",
                ("TEST", "2024-01-01", None, 100.0),
            )

            cursor.execute(
                """INSERT INTO announcement_parses (ticker, announcement_date, pdf_filename, parse_result)
                VALUES (?, ?, ?, ?)""",
                ("TEST", "2024-01-01", "test.pdf", '{"limit": 100}'),
            )

            cursor.execute(
                """INSERT INTO limit_event_log (ticker, operation, old_start, new_start)
                VALUES (?, ?, ?, ?)""",
                ("TEST", "INSERT", None, "2024-01-01"),
            )

            conn.commit()

            # Verify data
            cursor.execute(
                "SELECT is_open_ended FROM limit_events WHERE ticker=?", ("TEST",)
            )
            self.assertEqual(cursor.fetchone()[0], 1)

            conn.close()

        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


def run_tests():
    """Run all tests and print results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchema))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchemaIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
