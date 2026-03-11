"""
Integration tests for the announcement processor module.

公告处理模块的集成测试。

These tests verify the end-to-end functionality of the AnnouncementProcessor
class, including PDF processing, database storage, and batch operations.
这些测试验证 AnnouncementProcessor 类的端到端功能，包括 PDF 处理、数据库存储和批量操作。

Note: These tests use mocking to avoid requiring real PDF files or a running
Ollama instance. They verify the orchestration logic without external dependencies.
注意：这些测试使用模拟来避免需要真实的 PDF 文件或运行中的 Ollama 实例。
它们在没有外部依赖的情况下验证编排逻辑。
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
    """Test suite for AnnouncementProcessor class.
    AnnouncementProcessor 类的测试套件。
    """

    def setUp(self):
        """
        Set up test fixtures before each test.
        在每个测试前设置测试夹具。

        Creates:
        - Temporary directory for test files  # 测试文件的临时目录
        - Mock SQLite database with announcement_parses table  # 带有 announcement_parses 表的模拟 SQLite 数据库
        - Mock announcements directory structure  # 模拟公告目录结构
        - Mock PDF files (empty files)  # 模拟 PDF 文件（空文件）
        - Mock LLM client  # 模拟 LLM 客户端
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
        """Clean up temporary directory after each test.
        每个测试后清理临时目录。
        """
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
        """Create mock database with announcement_parses table.
        创建带有 announcement_parses 表的模拟数据库。
        """
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
        """Helper to get database entries.
        获取数据库条目的辅助函数。
        """
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
        # Force garbage collection to release file lock on Windows  # 强制垃圾回收以在 Windows 上释放文件锁
        import gc

        gc.collect()
        return entries

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_success(self, mock_extract):
        """
        Test successful PDF processing with mocked extraction and parsing.
        测试使用模拟提取和解析的成功 PDF 处理。

        Verifies:
        - PDF extraction is called  # PDF 提取被调用
        - LLM parsing is called with extracted text  # 使用提取的文本调用 LLM 解析
        - Database entry is created with correct fields  # 使用正确的字段创建数据库条目
        - Result indicates success  # 结果表示成功
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "测试公告内容：限购金额100元，从2024-01-15开始",
            "pages": 1,
            "error": None,
        }

        self.mock_llm_client.parse_announcement.return_value = [
            {
                "ticker": "161005",
                "limit_amount": 100.0,
                "start_date": "2024-01-15",
                "end_date": "2024-03-01",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.95,
            }
        ]

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

        # Verify parse_announcement was called with ticker kwarg
        self.mock_llm_client.parse_announcement.assert_called_once_with(
            "测试公告内容：限购金额100元，从2024-01-15开始", ticker="161005"
        )

        # Verify database entry
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        entry = entries[0]
        self.assertEqual(entry[1], "161005")  # ticker
        self.assertEqual(entry[2], "2024-01-15")  # announcement_date
        self.assertEqual(entry[3], "2024-01-15_限购公告.pdf")  # pdf_filename

        # Verify parse_result JSON (now stored as array)
        parse_result = json.loads(entry[4])
        self.assertIsInstance(parse_result, list)
        self.assertEqual(len(parse_result), 1)
        self.assertEqual(parse_result[0]["limit_amount"], 100.0)
        self.assertEqual(parse_result[0]["announcement_type"], "complete")

        # Verify parse_type and confidence
        self.assertEqual(entry[5], "complete")  # parse_type
        self.assertEqual(entry[6], 0.95)  # confidence

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_extraction_failure(self, mock_extract):
        """
        Test handling of PDF extraction failure.
        测试 PDF 提取失败的处理。

        Verifies:
        - Extraction failure is detected  # 提取失败被检测到
        - No database entry is created  # 不创建数据库条目
        - Error message is returned  # 返回错误消息
        - Result indicates failure but no exception raised  # 结果表示失败但不抛出异常
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
        测试非限购公告的处理。

        Verifies:
        - Non-limit announcements are detected  # 非限购公告被检测到
        - Still stored in database for audit trail  # 仍然存储在数据库中以供审计跟踪
        - is_limit_announcement flag is False  # is_limit_announcement 标志为 False
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "基金季度报告：本季度基金净值增长5%",
            "pages": 5,
            "error": None,
        }

        self.mock_llm_client.parse_announcement.return_value = [
            {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.85,
            }
        ]

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
        self.assertIsInstance(parse_result, list)
        self.assertFalse(parse_result[0]["is_purchase_limit_announcement"])

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_ticker_batch(self, mock_extract):
        """
        Test batch processing of all PDFs for a ticker.
        测试单个标的的所有 PDF 批量处理。

        Verifies:
        - All PDFs are processed  # 所有 PDF 都被处理
        - Statistics are accurate  # 统计信息准确
        - Individual failures don't stop batch  # 单个失败不会停止批量处理
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
        self.mock_llm_client.parse_announcement.return_value = [
            {
                "ticker": "161005",
                "limit_amount": 100.0,
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.90,
            }
        ]

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

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_process_pdf_multi_record(self, mock_extract):
        """Test processing PDF that yields multiple records.
        测试产生多条记录的 PDF 处理。
        """
        mock_extract.return_value = {
            "success": True,
            "text": "multi date text",
            "pages": 1,
            "error": None,
        }
        self.mock_llm_client.parse_announcement.return_value = [
            {
                "ticker": "161005",
                "limit_amount": 100.0,
                "start_date": "2024-04-18",
                "end_date": "2024-04-18",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.90,
            },
            {
                "ticker": "161005",
                "limit_amount": 100.0,
                "start_date": "2024-07-01",
                "end_date": "2024-07-01",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.85,
            },
        ]
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)
        self.assertTrue(result["success"])
        self.assertTrue(result["is_limit_announcement"])
        # Verify DB stores the array
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)  # Still one row per PDF
        parse_result = json.loads(entries[0][4])
        self.assertIsInstance(parse_result, list)
        self.assertEqual(len(parse_result), 2)
        # Confidence should be minimum
        self.assertEqual(entries[0][6], 0.85)

    def test_date_extraction_from_filename(self):
        """
        Test date parsing from various filename formats.
        测试从各种文件名格式解析日期。

        Verifies:
        - Standard format: YYYY-MM-DD_title.pdf  # 标准格式
        - Correct date extraction  # 正确的日期提取
        - Error handling for invalid formats  # 无效格式的错误处理
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
        测试解析结果以有效的 JSON 格式存储。

        Verifies:
        - parse_result is valid JSON  # parse_result 是有效的 JSON
        - All required fields are present  # 所有必需字段都存在
        - parse_type and confidence are extracted correctly  # parse_type 和 confidence 正确提取
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "测试内容",
            "pages": 1,
            "error": None,
        }

        parse_result = [
            {
                "ticker": "161005",
                "limit_amount": 500.0,
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.92,
            }
        ]

        self.mock_llm_client.parse_announcement.return_value = parse_result

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        self.processor.process_pdf("161005", pdf_path)

        # Verify database entry
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        entry = entries[0]

        # Verify JSON is valid and contains array of records
        stored_result = json.loads(entry[4])
        self.assertIsInstance(stored_result, list)
        self.assertEqual(len(stored_result), 1)
        self.assertEqual(stored_result[0]["ticker"], "161005")
        self.assertEqual(stored_result[0]["limit_amount"], 500.0)
        self.assertEqual(stored_result[0]["start_date"], "2024-01-01")
        self.assertEqual(stored_result[0]["end_date"], "2024-06-30")
        self.assertEqual(stored_result[0]["announcement_type"], "complete")
        self.assertTrue(stored_result[0]["is_purchase_limit_announcement"])
        self.assertEqual(stored_result[0]["confidence"], 0.92)

        # Verify parse_type and confidence columns
        self.assertEqual(entry[5], "complete")  # parse_type
        self.assertEqual(entry[6], 0.92)  # confidence

    @patch("src.data.announcement_processor.extract_pdf_text")
    def test_error_handling_continues_processing(self, mock_extract):
        """
        Test that individual PDF failures don't stop batch processing.
        测试单个 PDF 失败不会停止批量处理。

        Verifies:
        - Exception during processing is caught  # 处理期间的异常被捕获
        - Batch continues with remaining PDFs  # 批量处理继续处理剩余的 PDF
        - Error is logged and included in stats  # 错误被记录并包含在统计中
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

        self.mock_llm_client.parse_announcement.return_value = [
            {
                "is_purchase_limit_announcement": True,
                "confidence": 0.90,
            }
        ]

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
        测试 _ticker_has_parses 方法。

        Verifies:
        - Returns False when ticker has no entries  # 当标的没有条目时返回 False
        - Returns True after processing PDFs  # 处理 PDF 后返回 True
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
        测试处理不存在目录的标的。

        Verifies:
        - Graceful handling of missing directory  # 优雅处理缺失的目录
        - Appropriate error in result  # 结果中有适当的错误
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
        测试包含错误字段的 LLM 解析结果的处理。

        Verifies:
        - Results with error fields are still stored  # 包含错误字段的结果仍然被存储
        - Error information is preserved in database  # 错误信息保留在数据库中
        """
        # Setup mocks
        mock_extract.return_value = {
            "success": True,
            "text": "some text",
            "pages": 1,
            "error": None,
        }

        # LLM returns result with error (now as list)
        self.mock_llm_client.parse_announcement.return_value = [
            {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": "Connection error: Cannot connect to Ollama",
            }
        ]

        # Execute
        pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
        result = self.processor.process_pdf("161005", pdf_path)

        # Verify result stored despite error
        self.assertTrue(result["stored"])
        self.assertIn("LLM parsing failed", result["error"])

        # Verify database entry contains error (stored as JSON array)
        entries = self._get_db_entries("161005")
        self.assertEqual(len(entries), 1)

        parse_result = json.loads(entries[0][4])
        self.assertIsInstance(parse_result, list)
        self.assertIn("error", parse_result[0])
        self.assertIn("Cannot connect to Ollama", parse_result[0]["error"])


class TestCleanExtractedText(unittest.TestCase):
    """Unit tests for AnnouncementProcessor._clean_extracted_text static method.
    AnnouncementProcessor._clean_extracted_text 静态方法的单元测试。
    """

    def test_clean_html_tags(self):
        """HTML and XML tags are removed while text content is preserved.
        HTML 和 XML 标签被移除，同时保留文本内容。
        """
        text = '<p>本基金将于2024年限购</p><br/><div>每日限额</div><a href="http://fund.com">点击</a>'
        result = AnnouncementProcessor._clean_extracted_text(text)
        # All tags removed
        self.assertNotIn("<p>", result)
        self.assertNotIn("</p>", result)
        self.assertNotIn("<br/>", result)
        self.assertNotIn("<div>", result)
        self.assertNotIn("</div>", result)
        self.assertNotIn("<a", result)
        self.assertNotIn("</a>", result)
        # Text content preserved
        self.assertIn("本基金将于2024年限购", result)
        self.assertIn("每日限额", result)
        self.assertIn("点击", result)

    def test_clean_urls(self):
        """HTTP, HTTPS, and bare www. URLs are removed.
        HTTP、HTTPS 和裸 www. URL 被移除。
        """
        text = "请访问 https://www.example.com/path?q=1 或 http://fund.com 及 www.bare-url.com 获取信息"
        result = AnnouncementProcessor._clean_extracted_text(text)
        self.assertNotIn("https://", result)
        self.assertNotIn("http://", result)
        self.assertNotIn("www.example.com", result)
        self.assertNotIn("www.bare-url.com", result)
        # Surrounding words preserved
        self.assertIn("请访问", result)
        self.assertIn("获取信息", result)

    def test_clean_email_addresses(self):
        """Email addresses are removed from text.
        电子邮件地址从文本中被移除。
        """
        text = "联系方式：contact@fund.com 或 service@example.org 咨询"
        result = AnnouncementProcessor._clean_extracted_text(text)
        self.assertNotIn("contact@fund.com", result)
        self.assertNotIn("service@example.org", result)
        self.assertIn("联系方式", result)
        self.assertIn("咨询", result)

    def test_clean_excessive_whitespace(self):
        """3+ consecutive newlines are collapsed to 2, multiple spaces to single space.
        3 个或更多连续换行符折叠为 2 个，多个空格折叠为单个空格。
        """
        text = "第一段\n\n\n\n\n第二段\n\n第三段  有  多余  空格"
        result = AnnouncementProcessor._clean_extracted_text(text)
        # 5 newlines collapsed to 2
        self.assertNotIn("\n\n\n", result)
        self.assertIn("\n\n", result)
        # Multiple spaces collapsed
        self.assertNotIn("  ", result)
        # Content preserved
        self.assertIn("第一段", result)
        self.assertIn("第二段", result)
        self.assertIn("第三段", result)
        self.assertIn("有", result)
        self.assertIn("多余", result)
        self.assertIn("空格", result)

    def test_preserve_page_markers(self):
        """Page markers (--- Page N ---) are fully preserved through cleaning.
        页面标记（--- Page N ---）在清理过程中完全保留。
        """
        text = "--- Page 1 ---\n本基金公告内容\n--- Page 2 ---\n继续内容"
        result = AnnouncementProcessor._clean_extracted_text(text)
        self.assertIn("--- Page 1 ---", result)
        self.assertIn("--- Page 2 ---", result)
        self.assertIn("本基金公告内容", result)
        self.assertIn("继续内容", result)

    def test_clean_real_world_sample(self):
        """Realistic Chinese announcement snippet with mixed HTML, URLs, and content.
        真实的中文公告片段，包含混合的 HTML、URL 和内容。
        """
        text = (
            "<p>关于161005基金限购的公告</p>\n"
            "发布日期：2024年1月15日\n"
            "https://www.csindex.com.cn/announcement/2024/01/fund.pdf\n\n\n"
            "<div>根据市场情况，本基金自2024年1月15日起</div>\n"
            "每日限购金额为<b>100万元</b>\n"
            "请联系 investor@fund.com 咨询\n\n\n\n"
            "www.fundinfo.com.cn 查询详情"
        )
        result = AnnouncementProcessor._clean_extracted_text(text)
        # HTML removed
        self.assertNotIn("<p>", result)
        self.assertNotIn("<div>", result)
        self.assertNotIn("<b>", result)
        # URLs removed
        self.assertNotIn("https://", result)
        self.assertNotIn("www.csindex", result)
        self.assertNotIn("www.fundinfo", result)
        # Email removed
        self.assertNotIn("investor@fund.com", result)
        # Excessive newlines collapsed
        self.assertNotIn("\n\n\n", result)
        # Meaningful content preserved
        self.assertIn("161005", result)
        self.assertIn("2024年1月15日", result)
        self.assertIn("100万元", result)
        self.assertIn("每日限购金额为", result)

    def test_clean_empty_and_whitespace(self):
        """Empty string returns empty string; whitespace-only returns empty string.
        空字符串返回空字符串；仅包含空白字符的返回空字符串。
        """
        self.assertEqual(AnnouncementProcessor._clean_extracted_text(""), "")
        self.assertEqual(AnnouncementProcessor._clean_extracted_text("   "), "")
        self.assertEqual(AnnouncementProcessor._clean_extracted_text("\n\n\n"), "")
        self.assertEqual(AnnouncementProcessor._clean_extracted_text("   \n  \n  "), "")

    def test_clean_already_clean_text(self):
        """Clean Chinese text passes through unchanged (idempotent for clean input).
        干净的中文文本通过时保持不变（对干净输入是幂等的）。
        """
        text = "本基金将于2024年1月15日起实施限购\n每日限购金额为100万元\n请投资者注意"
        result = AnnouncementProcessor._clean_extracted_text(text)
        self.assertEqual(result, text)

        # Running twice gives same result (idempotent)
        result2 = AnnouncementProcessor._clean_extracted_text(result)
        self.assertEqual(result, result2)


class TestConvenienceFunctions(unittest.TestCase):
    """Test suite for convenience functions.
    便捷函数的测试套件。
    """

    def setUp(self):
        """Set up test fixtures.
        设置测试夹具。
        """
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
        """Clean up temporary directory.
        清理临时目录。
        """
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
        测试 process_pdf 便捷函数。

        Verifies:
        - Function creates AnnouncementProcessor instance  # 函数创建 AnnouncementProcessor 实例
        - Calls process_pdf method  # 调用 process_pdf 方法
        - Returns result  # 返回结果
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
        测试 process_ticker 便捷函数。

        Verifies:
        - Function creates AnnouncementProcessor instance  # 函数创建 AnnouncementProcessor 实例
        - Calls process_ticker method  # 调用 process_ticker 方法
        - Returns statistics  # 返回统计信息
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
