"""
Unit tests for PDF text extraction module.

PDF 文本提取模块的单元测试。

Tests cover:
测试覆盖：
- Real PDF extraction  # 真实 PDF 提取
- Error handling for non-existent files  # 不存在文件的错误处理
- Return structure validation  # 返回结构验证
- Page marker verification  # 页面标记验证
- Chinese text preservation  # 中文文本保留
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root to path for imports  # 添加项目根目录到路径以便导入
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.pdf_extractor import extract_pdf_text, PDFExtractionError


class TestPDFExtractor(unittest.TestCase):
    """Test cases for PDF text extraction functionality.
    PDF 文本提取功能的测试用例。
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures - find a real PDF if available.
        设置测试夹具 - 如果可用则查找真实 PDF。
        """
        cls.test_pdf_path = None
        cls.data_dir = project_root / "data" / "real_all_lof" / "announcements"

        # Try to find a real PDF in the announcements directory  # 尝试在公告目录中查找真实 PDF
        if cls.data_dir.exists():
            pdf_files = list(cls.data_dir.rglob("*.pdf"))
            if pdf_files:
                cls.test_pdf_path = pdf_files[0]
                print(f"\nFound test PDF: {cls.test_pdf_path}")

    def test_extract_real_pdf(self):
        """Test extraction from a real PDF file.
        测试从真实 PDF 文件提取。
        """
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Verify success  # 验证成功
        self.assertTrue(
            result["success"],
            f"Extraction should succeed but got error: {result.get('error')}",
        )

        # Verify text was extracted  # 验证文本已提取
        self.assertIsNotNone(result["text"])
        self.assertIsInstance(result["text"], str)
        # PDF should have some text content (may be empty for image-based PDFs)  # PDF 应有一些文本内容（图像 PDF 可能为空）
        # We just verify the extraction completed without error  # 我们只验证提取完成且无错误

        # Verify page count  # 验证页数
        self.assertIsInstance(result["pages"], int)
        self.assertGreater(result["pages"], 0, "PDF should have at least one page")

        # Verify no error  # 验证无错误
        self.assertIsNone(result["error"])

    def test_extract_nonexistent_file(self):
        """Test error handling for non-existent file.
        测试不存在文件的错误处理。
        """
        fake_path = "/path/that/does/not/exist/fake_announcement.pdf"
        result = extract_pdf_text(fake_path)

        # Should return failure, not raise  # 应返回失败，而不是抛出
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
        self.assertIn("not found", result["error"].lower())

        # Text should be empty  # 文本应为空
        self.assertEqual(result["text"], "")
        self.assertEqual(result["pages"], 0)

    def test_extract_returns_dict_structure(self):
        """Verify return dictionary has correct structure.
        验证返回字典具有正确的结构。
        """
        # Use a non-existent file to get a quick result  # 使用不存在的文件快速获取结果
        result = extract_pdf_text("/fake/path.pdf")

        # Check all required keys exist  # 检查所有必需的键存在
        self.assertIn("success", result)
        self.assertIn("text", result)
        self.assertIn("pages", result)
        self.assertIn("error", result)

        # Check types  # 检查类型
        self.assertIsInstance(result["success"], bool)
        self.assertIsInstance(result["text"], str)
        self.assertIsInstance(result["pages"], int)
        # error can be str or None  # error 可以是 str 或 None
        self.assertTrue(
            result["error"] is None or isinstance(result["error"], str),
            "error should be None or str",
        )

    def test_page_markers_present(self):
        """Verify page markers are included in multi-page PDFs.
        验证多页 PDF 中包含页面标记。
        """
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Skip if extraction failed
        if not result["success"]:
            self.skipTest(f"PDF extraction failed: {result['error']}")

        # Check page markers in multi-page PDFs  # 检查多页 PDF 中的页面标记
        if result["pages"] > 1:
            self.assertIn("--- Page 1 ---", result["text"])
            self.assertIn("--- Page", result["text"])

    def test_chinese_text_preserved(self):
        """Verify Chinese characters are preserved in extraction.
        验证提取中保留中文字符。
        """
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Skip if extraction failed
        if not result["success"]:
            self.skipTest(f"PDF extraction failed: {result['error']}")

        # Check if any Chinese characters are present  # 检查是否有任何中文字符
        # Chinese Unicode range: \u4e00-\u9fff
        text = result["text"]
        has_chinese = any("\u4e00" <= char <= "\u9fff" for char in text)

        # This is informational - Chinese PDFs should have Chinese text  # 这是信息性的 - 中文 PDF 应有中文文本
        # but some PDFs might be English-only or have no extractable text  # 但某些 PDF 可能仅含英文或无可提取文本
        if text and not has_chinese:
            print(f"\nNote: PDF {self.test_pdf_path.name} has no Chinese text")
            print(f"First 200 chars: {text[:200]}")

    def test_extract_directory_path(self):
        """Test error handling when path is a directory.
        测试路径为目录时的错误处理。
        """
        if not self.data_dir.exists():
            self.skipTest("Announcements directory does not exist")

        result = extract_pdf_text(self.data_dir)

        # Should fail gracefully  # 应优雅失败
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
        self.assertIn("not a file", result["error"].lower())

    def test_pdf_extraction_error_exception(self):
        """Verify PDFExtractionError exception can be raised.
        验证 PDFExtractionError 异常可以被抛出。
        """
        # Test that the exception class exists and can be used  # 测试异常类存在且可用
        exc = PDFExtractionError("Test error message")
        self.assertEqual(str(exc), "Test error message")

        # Verify it can be raised and caught  # 验证它可以被抛出和捕获
        with self.assertRaises(PDFExtractionError):
            raise PDFExtractionError("Test raise")


class TestPDFExtractionEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions.
    测试边缘情况和边界条件。
    """

    def test_empty_path(self):
        """Test handling of empty path string.
        测试空路径字符串的处理。
        """
        result = extract_pdf_text("")
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])

    def test_path_with_unicode(self):
        """Test handling of paths with Unicode characters.
        测试包含 Unicode 字符的路径的处理。
        """
        # This tests the path handling, not necessarily extraction  # 这测试路径处理，不一定是提取
        # Most systems won't have this file, so it tests error handling  # 大多数系统不会有此文件，因此测试错误处理
        unicode_path = "/tmp/公告测试_中文路径.pdf"
        result = extract_pdf_text(unicode_path)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    # Configure logging to see warnings during tests  # 配置日志以在测试期间查看警告
    import logging

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run tests  # 运行测试
    unittest.main(verbosity=2)
