"""
Integration tests for the announcement processor module.

These tests verify the end-to-end functionality of the AnnouncementProcessor
class, including PDF processing, database storage, and batch operations.

Note: These tests use mocking to avoid requiring real PDF files or a running
Ollama instance. They verify the orchestration logic without external dependencies.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.data.announcement_processor import (
    AnnouncementProcessor,
    process_pdf,
    process_ticker,
)


class TestAnnouncementProcessor(unittest.TestCase):
    """Test suite for AnnouncementProcessor class."""

    def setUp(self):
        """
        Set up test fixtures before each test.

        Creates:
        - Temporary directory for test files
        - Mock SQLite database with announcement_parses table
        - Mock announcements directory structure
        - Mock PDF files (empty files)
        - Mock LLM client
        """
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

        # Create mock database
        self.db_path = self.test_dir / "fund_status.db"
        self._create_mock_database()

        # Create mock announcements directory
        self.announcements_dir = self.test_dir / "announcements"
        self.ticker_dir = self.announcements_dir / "161005"
        self.ticker_dir.mkdir(parents=True)

        # Create mock PDF files
        (self.ticker_dir / "2024-01-15_限购公告.pdf").touch()
        (self.ticker_dir / "2024-02-01_恢复公告.pdf").touch()
        (self.ticker_dir / "2024-03-15_修改公告.pdf").touch()

        # Create mock LLM client
        self.mock_llm_client = MagicMock()

        # Initialize processor with mock LLM
        self.processor = AnnouncementProcessor(
            db_path=self.db_path,
            announcements_dir=self.announcements_dir,
            llm_client=self.mock_llm_client,
        )

    def tearDown(self):
        """Clean up temporary directory after each test."""
        import gc
        import time

        # Force garbage collection to close any lingering DB connections
        gc.collect()

        # On Windows, brief sleep helps release file locks
        time.sleep(0.1)

        try:
            self.temp_dir.cleanup()
        except PermissionError:
            # If cleanup fails due to file lock, try again after a delay
            time.sleep(0.5)
            gc.collect()
            try:
                self.temp_dir.cleanup()
            except PermissionError:
                # Final fallback: ignore cleanup errors
                pass

    def _create_mock_database(self):
        """Create mock database with announcement_parses table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_parse ON announcement_parses (ticker, announcement_date, pdf_filename)"
        )
        conn.commit()
        conn.close()

    def _get_db_entries(self, ticker: str = None) -> list:
        """Helper to get database entries."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if ticker:
            cursor.execute(
                "SELECT * FROM announcement_parses WHERE ticker = ? ORDER BY announcement_date",
                (ticker,),
            )
        else:
            cursor.execute(
                "SELECT * FROM announcement_parses ORDER BY ticker, announcement_date"
            )
        entries = cursor.fetchall()
        conn.close()
        # Force garbage collection to release file lock on Windows
        import gc

        gc.collect()
        return entries

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_success(self, mock_extract):
        """
        Test successful PDF processing with mocked extraction and parsing.

        Verifies:
        - PDF extraction is called
        - LLM parsing is called with extracted text
        - Database entry is created with correct fields
        - Result indicates success
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "测试公告内容：限购金额100元，从2024-01-15开始",
            "pages": 1,
            "error": None,
        }

        self.mock_llm_client.parse_announcement.return_value = {
            "ticker": "161005",
            "limit_amount": 100.0,
            "start_date": "2024-01-15",
            "end_date": "2024-03-01",
            "announcement_type": "complete",
            "is_purchase_limit_announcement": True,
            "confidence": 0.95,
        }

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)

        # Verify
        self.assertTrue(result["success"])
        self.assertTrue(result["extracted"])
        self.assertTrue(result["parsed"])
        self.assertTrue(result["stored"])
        self.assertTrue(result["is_limit_announcement"])
        self.assertIsNone(result["error"])

        # Verify database entry
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        entry = entries[0]
        self.assertEqual(entry[1], "161005")  # ticker
        self.assertEqual(entry[2], "2024-01-15")  # announcement_date
        self.assertEqual(entry[3], "2024-01-15_限购公告.pdf")  # pdf_filename

        # Verify parse_result JSON
        parse_result = json.loads(entry[4])
        self.assertEqual(parse_result["limit_amount"], 100.0)
        self.assertEqual(parse_result["announcement_type"], "complete")

        # Verify parse_type and confidence
        self.assertEqual(entry[5], "complete")  # parse_type
        self.assertEqual(entry[6], 0.95)  # confidence

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_extraction_failure(self, mock_extract):
        """
        Test handling of PDF extraction failure.

        Verifies:
        - Extraction failure is detected
        - No database entry is created
        - Error message is returned
        - Result indicates failure but no exception raised
        """
        # Setup mock to simulate extraction failure
        mock_extract.return_value = {
            "success": False,
            "text": "",
            "pages": 0,
            "error": "PDF file not found",
        }

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)

        # Verify
        self.assertFalse(result["success"])
        self.assertFalse(result["extracted"])
        self.assertFalse(result["stored"])
        self.assertIn("extraction failed", result["error"].lower())

        # Verify no database entry created
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 0)

        # Verify LLM client was NOT called
        self.mock_llm_client.parse_announcement.assert_not_called()

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_not_limit_announcement(self, mock_extract):
        """
        Test handling of non-limit announcements.

        Verifies:
        - Non-limit announcements are detected
        - Still stored in database for audit trail
        - is_limit_announcement flag is False
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "基金季度报告：本季度基金净值增长5%",
            "pages": 5,
            "error": None,
        }

        self.mock_llm_client.parse_announcement.return_value = {
            "ticker": None,
            "limit_amount": None,
            "start_date": None,
            "end_date": None,
            "announcement_type": None,
            "is_purchase_limit_announcement": False,
            "confidence": 0.85,
        }

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_季度报告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)

        # Verify
        self.assertTrue(result["success"])
        self.assertTrue(result["stored"])
        self.assertFalse(result["is_limit_announcement"])

        # Verify database entry exists (for audit trail)
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        parse_result = json.loads(entries[0][4])
        self.assertFalse(parse_result["is_purchase_limit_announcement"])

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_ticker_batch(self, mock_extract):
        """
        Test batch processing of all PDFs for a ticker.

        Verifies:
        - All PDFs are processed
        - Statistics are accurate
        - Individual failures don't stop batch
        """

        # Setup mock to succeed for first PDF, fail for second, succeed for third
        def side_effect(pdf_path):
            if "限购" in str(pdf_path):
                return {
                    "success": True,
                    "text": "限购公告",
                    "pages": 1,
                    "error": None,
                }
            elif "恢复" in str(pdf_path):
                return {
                    "success": False,
                    "text": "",
                    "pages": 0,
                    "error": "Corrupt PDF",
                }
            else:
                return {
                    "success": True,
                    "text": "修改公告",
                    "pages": 1,
                    "error": None,
                }

        mock_extract.side_effect = side_effect

        # Setup LLM mock
        self.mock_llm_client.parse_announcement.return_value = {
            "ticker": "161005",
            "limit_amount": 100.0,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "announcement_type": "complete",
            "is_purchase_limit_announcement": True,
            "confidence": 0.90,
        }

        # Execute
        result = self.processor.process_ticker("161005")

        # Verify statistics
        self.assertEqual(result["ticker"], "161005")
        self.assertEqual(result["total"], 3)  # Three PDF files
        self.assertEqual(result["extracted"], 2)  # Two succeeded
        self.assertEqual(result["failed"], 1)  # One failed (恢复公告)
        self.assertEqual(result["stored"], 2)  # Two stored

        # Verify database has 2 entries
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 2)

    def test_date_extraction_from_filename(self):
        """
        Test date parsing from various filename formats.

        Verifies:
        - Standard format: YYYY-MM-DD_title.pdf
        - Correct date extraction
        - Error handling for invalid formats
        """
        # Test valid formats
        test_cases = [
            ("2024-01-15_限购公告.pdf", "2024-01-15"),
            ("2024-12-31_年末公告.pdf", "2024-12-31"),
            ("2023-06-01_测试.pdf", "2023-06-01"),
        ]

        for filename, expected_date in test_cases:
            with self.subTest(filename=filename):
                result = self.processor._parse_date_from_filename(filename)
                self.assertEqual(result, expected_date)

        # Test invalid format
        with self.assertRaises(ValueError):
            self.processor._parse_date_from_filename("invalid_filename.pdf")

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_database_insertion_format(self, mock_extract):
        """
        Test that parse results are stored as valid JSON with correct format.

        Verifies:
        - parse_result is valid JSON
        - All required fields are present
        - parse_type and confidence are extracted correctly
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "测试内容",
            "pages": 1,
            "error": None,
        }

        parse_result = {
            "ticker": "161005",
            "limit_amount": 500.0,
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
            "announcement_type": "complete",
            "is_purchase_limit_announcement": True,
            "confidence": 0.92,
        }

        self.mock_llm_client.parse_announcement.return_value = parse_result

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        self.processor.process_pdf("161005", pdf_path)

        # Verify database entry
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        entry = entries[0]

        # Verify JSON is valid and contains all fields
        stored_result = json.loads(entry[4])
        self.assertEqual(stored_result["ticker"], "161005")
        self.assertEqual(stored_result["limit_amount"], 500.0)
        self.assertEqual(stored_result["start_date"], "2024-01-01")
        self.assertEqual(stored_result["end_date"], "2024-06-30")
        self.assertEqual(stored_result["announcement_type"], "complete")
        self.assertTrue(stored_result["is_purchase_limit_announcement"])
        self.assertEqual(stored_result["confidence"], 0.92)

        # Verify parse_type and confidence columns
        self.assertEqual(entry[5], "complete")  # parse_type
        self.assertEqual(entry[6], 0.92)  # confidence

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_error_handling_continues_processing(self, mock_extract):
        """
        Test that individual PDF failures don't stop batch processing.

        Verifies:
        - Exception during processing is caught
        - Batch continues with remaining PDFs
        - Error is logged and included in stats
        """

        # Setup mock to raise exception for one PDF
        def side_effect(pdf_path):
            if "失败" in str(pdf_path):
                raise Exception("Simulated processing error")
            return {
                "success": True,
                "text": "正常公告",
                "pages": 1,
                "error": None,
            }

        mock_extract.side_effect = side_effect

        # Create additional PDF that will fail
        (self.ticker_dir / "2024-04-01_失败公告.pdf").touch()

        self.mock_llm_client.parse_announcement.return_value = {
            "is_purchase_limit_announcement": True,
            "confidence": 0.90,
        }

        # Execute
        result = self.processor.process_ticker("161005")

        # Verify batch completed despite one failure
        self.assertEqual(result["total"], 4)  # Four PDFs total
        self.assertEqual(result["failed"], 1)  # One failed
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("失败公告.pdf", result["errors"][0])

    def test_ticker_has_parses(self):
        """
        Test _ticker_has_parses method.

        Verifies:
        - Returns False when ticker has no entries
        - Returns True after processing PDFs
        """
        # Initially should have no parses
        self.assertFalse(self.processor._ticker_has_parses("161005"))

        # Add a parse entry manually
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO announcement_parses 
            (ticker, announcement_date, pdf_filename, parse_result, processed)
            VALUES (?, ?, ?, ?, 1)
            """,
            ("161005", "2024-01-15", "test.pdf", "{}"),
        )
        conn.commit()
        conn.close()

        # Now should have parses
        self.assertTrue(self.processor._ticker_has_parses("161005"))

    def test_process_ticker_no_directory(self):
        """
        Test processing ticker with non-existent directory.

        Verifies:
        - Graceful handling of missing directory
        - Appropriate error in result
        """
        result = self.processor.process_ticker("999999")

        self.assertEqual(result["ticker"], "999999")
        self.assertEqual(result["total"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("not found", result["errors"][0].lower())

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_parse_result_with_error_field(self, mock_extract):
        """
        Test handling of LLM parse results that contain an error field.

        Verifies:
        - Results with error fields are still stored
        - Error information is preserved in database
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "some text",
            "pages": 1,
            "error": None,
        }

        # LLM returns result with error
        self.mock_llm_client.parse_announcement.return_value = {
            "ticker": None,
            "limit_amount": None,
            "start_date": None,
            "end_date": None,
            "announcement_type": None,
            "is_purchase_limit_announcement": False,
            "confidence": 0.0,
            "error": "Connection error: Cannot connect to Ollama",
        }

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)

        # Verify result stored despite error
        self.assertTrue(result["stored"])
        self.assertIn("LLM parsing failed", result["error"])

        # Verify database entry contains error
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        parse_result = json.loads(entries[0][4])
        self.assertIn("error", parse_result)
        self.assertIn("Cannot connect to Ollama", parse_result["error"])


class TestConvenienceFunctions(unittest.TestCase):
    """Test suite for convenience functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

        # Create mock database
        self.db_path = self.test_dir / "fund_status.db"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE announcement_parses (
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
            """
        )
        conn.commit()
        conn.close()

        # Create announcements directory
        self.announcements_dir = self.test_dir / "announcements"
        self.ticker_dir = self.announcements_dir / "161005"
        self.ticker_dir.mkdir(parents=True)
        (self.ticker_dir / "2024-01-15_公告.pdf").touch()

    def tearDown(self):
        """Clean up temporary directory."""
        import gc
        import time

        # Force garbage collection to close any lingering DB connections
        gc.collect()

        # On Windows, brief sleep helps release file locks
        time.sleep(0.1)

        try:
            self.temp_dir.cleanup()
        except PermissionError:
            # If cleanup fails due to file lock, try again after a delay
            time.sleep(0.5)
            gc.collect()
            try:
                self.temp_dir.cleanup()
            except PermissionError:
                # Final fallback: ignore cleanup errors
                pass

    @patch("src.data.announcement_processor.AnnouncementProcessor")
    def test_process_pdf_convenience(self, mock_processor_class):
        """
        Test process_pdf convenience function.

        Verifies:
        - Function creates AnnouncementProcessor instance
        - Calls process_pdf method
        - Returns result
        """
        # Setup mock
        mock_processor = MagicMock()
        mock_processor.process_pdf.return_value = {"success": True}
        mock_processor_class.return_value = mock_processor

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_公告.pdf"
        result = process_pdf(
            pdf_path=pdf_path,
            ticker="161005",
            db_path=self.db_path,
        )

        # Verify
        self.assertTrue(result["success"])
        mock_processor_class.assert_called_once()
        mock_processor.process_pdf.assert_called_once_with("161005", pdf_path)

    @patch("src.data.announcement_processor.AnnouncementProcessor")
    def test_process_ticker_convenience(self, mock_processor_class):
        """
        Test process_ticker convenience function.

        Verifies:
        - Function creates AnnouncementProcessor instance
        - Calls process_ticker method
        - Returns statistics
        """
        # Setup mock
        mock_processor = MagicMock()
        mock_processor.process_ticker.return_value = {
            "ticker": "161005",
            "total": 1,
            "stored": 1,
        }
        mock_processor_class.return_value = mock_processor

        # Execute
        result = process_ticker(
            ticker="161005",
            db_path=self.db_path,
            announcements_dir=self.announcements_dir,
        )

        # Verify
        self.assertEqual(result["ticker"], "161005")
        mock_processor_class.assert_called_once()
        mock_processor.process_ticker.assert_called_once_with("161005")


if __name__ == "__main__":
    unittest.main()
