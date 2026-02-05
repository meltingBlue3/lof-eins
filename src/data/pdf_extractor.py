"""
PDF text extraction module for Chinese LOF fund announcements.

Uses pdfplumber for superior Chinese text support compared to PyPDF2.
Handles multi-page PDFs with page markers and graceful error handling.
"""

import logging
import sys
from pathlib import Path
from typing import Union

import pdfplumber

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    """Raised when PDF extraction fails."""

    pass


def _clean_text(text: str) -> str:
    """
    Clean and normalize extracted text.

    - Normalize whitespace (multiple spaces -> single)
    - Preserve Chinese punctuation
    - Remove excessive newlines but keep paragraph structure

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Replace multiple spaces with single space
    import re

    text = re.sub(r" +", " ", text)

    # Replace 3+ newlines with 2 newlines (preserve paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split("\n")]

    # Rejoin non-empty lines
    text = "\n".join(line for line in lines if line)

    return text.strip()


def extract_pdf_text(pdf_path: Union[Path, str]) -> dict:
    """
    Extract text from a PDF file using pdfplumber.

    pdfplumber is chosen over PyPDF2 for superior Chinese text handling
    and better support for financial documents with tables.

    Args:
        pdf_path: Path to the PDF file (Path object or string)

    Returns:
        Dict with keys:
        - success (bool): Whether extraction succeeded
        - text (str): Extracted and cleaned text
        - pages (int): Number of pages processed
        - error (str | None): Error message if failed, None if succeeded
    """
    pdf_path = Path(pdf_path)

    logger.info(f"Attempting to extract text from PDF: {pdf_path}")

    result = {"success": False, "text": "", "pages": 0, "error": None}

    try:
        # Check if file exists
        if not pdf_path.exists():
            error_msg = f"PDF file not found: {pdf_path}"
            logger.warning(error_msg)
            result["error"] = error_msg
            return result

        # Check if it's a file
        if not pdf_path.is_file():
            error_msg = f"Path is not a file: {pdf_path}"
            logger.warning(error_msg)
            result["error"] = error_msg
            return result

        # Open and extract text using pdfplumber
        all_pages_text = []
        page_count = 0

        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

            for i, page in enumerate(pdf.pages, 1):
                # Extract text from page
                page_text = page.extract_text()

                if page_text:
                    all_pages_text.append(page_text)
                    # Add page marker between pages
                    if i < page_count:
                        all_pages_text.append(f"\n--- Page {i} ---\n")

        # Combine all pages
        raw_text = "\n".join(all_pages_text)

        # Clean the text
        cleaned_text = _clean_text(raw_text)

        result["success"] = True
        result["text"] = cleaned_text
        result["pages"] = page_count

        logger.info(f"Successfully extracted text from {page_count} pages: {pdf_path}")

    except pdfplumber.exceptions.PDFException as e:
        error_msg = f"PDF parsing error: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    except PermissionError as e:
        error_msg = f"Permission denied reading PDF: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    except Exception as e:
        error_msg = f"Unexpected error extracting PDF: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    return result


if __name__ == "__main__":
    # CLI mode for testing
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract text from PDF files using pdfplumber"
    )
    parser.add_argument("pdf_path", help="Path to the PDF file to extract text from")
    parser.add_argument(
        "-o", "--output", help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Extract text
    result = extract_pdf_text(args.pdf_path)

    if result["success"]:
        output = f"""Successfully extracted text from {result["pages"]} pages.

--- EXTRACTED TEXT ---

{result["text"]}
"""
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Text saved to: {args.output}")
        else:
            print(output)
    else:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
