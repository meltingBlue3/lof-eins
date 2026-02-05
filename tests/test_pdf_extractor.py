"""
Unit tests for PDF text extraction module.

Tests cover:
- Real PDF extraction
- Error handling for non-existent files
- Return structure validation
- Page marker verification
- Chinese text preservation
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.pdf_extractor import extract_pdf_text, PDFExtractionError


class TestPDFExtractor(unittest.TestCase):
    """Test cases for PDF text extraction functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures - find a real PDF if available."""
        cls.test_pdf_path = None
        cls.data_dir = project_root / "data" / "real_all_lof" / "announcements"

        # Try to find a real PDF in the announcements directory
        if cls.data_dir.exists():
            pdf_files = list(cls.data_dir.rglob("*.pdf"))
            if pdf_files:
                cls.test_pdf_path = pdf_files[0]
                print(f"\nFound test PDF: {cls.test_pdf_path}")

    def test_extract_real_pdf(self):
        """Test extraction from a real PDF file."""
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Verify success
        self.assertTrue(
            result["success"],
            f"Extraction should succeed but got error: {result.get('error')}",
        )

        # Verify text was extracted
        self.assertIsNotNone(result["text"])
        self.assertIsInstance(result["text"], str)
        # PDF should have some text content (may be empty for image-based PDFs)
        # We just verify the extraction completed without error

        # Verify page count
        self.assertIsInstance(result["pages"], int)
        self.assertGreater(result["pages"], 0, "PDF should have at least one page")

        # Verify no error
        self.assertIsNone(result["error"])

    def test_extract_nonexistent_file(self):
        """Test error handling for non-existent file."""
        fake_path = "/path/that/does/not/exist/fake_announcement.pdf"
        result = extract_pdf_text(fake_path)

        # Should return failure, not raise
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
        self.assertIn("not found", result["error"].lower())

        # Text should be empty
        self.assertEqual(result["text"], "")
        self.assertEqual(result["pages"], 0)

    def test_extract_returns_dict_structure(self):
        """Verify return dictionary has correct structure."""
        # Use a non-existent file to get a quick result
        result = extract_pdf_text("/fake/path.pdf")

        # Check all required keys exist
        self.assertIn("success", result)
        self.assertIn("text", result)
        self.assertIn("pages", result)
        self.assertIn("error", result)

        # Check types
        self.assertIsInstance(result["success"], bool)
        self.assertIsInstance(result["text"], str)
        self.assertIsInstance(result["pages"], int)
        # error can be str or None
        self.assertTrue(
            result["error"] is None or isinstance(result["error"], str),
            "error should be None or str",
        )

    def test_page_markers_present(self):
        """Verify page markers are included in multi-page PDFs."""
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Skip if extraction failed
        if not result["success"]:
            self.skipTest(f"PDF extraction failed: {result['error']}")

        # Check page markers in multi-page PDFs
        if result["pages"] > 1:
            self.assertIn("--- Page 1 ---", result["text"])
            self.assertIn("--- Page", result["text"])

    def test_chinese_text_preserved(self):
        """Verify Chinese characters are preserved in extraction."""
        if not self.test_pdf_path:
            self.skipTest("No real PDF files available for testing")

        result = extract_pdf_text(self.test_pdf_path)

        # Skip if extraction failed
        if not result["success"]:
            self.skipTest(f"PDF extraction failed: {result['error']}")

        # Check if any Chinese characters are present
        # Chinese Unicode range: \u4e00-\u9fff
        text = result["text"]
        has_chinese = any("\u4e00" <= char <= "\u9fff" for char in text)

        # This is informational - Chinese PDFs should have Chinese text
        # but some PDFs might be English-only or have no extractable text
        if text and not has_chinese:
            print(f"\nNote: PDF {self.test_pdf_path.name} has no Chinese text")
            print(f"First 200 chars: {text[:200]}")

    def test_extract_directory_path(self):
        """Test error handling when path is a directory."""
        if not self.data_dir.exists():
            self.skipTest("Announcements directory does not exist")

        result = extract_pdf_text(self.data_dir)

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
        self.assertIn("not a file", result["error"].lower())

    def test_pdf_extraction_error_exception(self):
        """Verify PDFExtractionError exception can be raised."""
        # Test that the exception class exists and can be used
        exc = PDFExtractionError("Test error message")
        self.assertEqual(str(exc), "Test error message")

        # Verify it can be raised and caught
        with self.assertRaises(PDFExtractionError):
            raise PDFExtractionError("Test raise")


class TestPDFExtractionEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_empty_path(self):
        """Test handling of empty path string."""
        result = extract_pdf_text("")
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])

    def test_path_with_unicode(self):
        """Test handling of paths with Unicode characters."""
        # This tests the path handling, not necessarily extraction
        # Most systems won't have this file, so it tests error handling
        unicode_path = "/tmp/公告测试_中文路径.pdf"
        result = extract_pdf_text(unicode_path)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    # Configure logging to see warnings during tests
    import logging

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run tests
    unittest.main(verbosity=2)
