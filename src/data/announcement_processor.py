"""
Announcement processor module for orchestrating PDF extraction, LLM parsing, and database storage.

This module provides the orchestration layer that combines:
1. PDF text extraction (pdf_extractor)
2. LLM parsing of limit information (llm_client)
3. Database storage of parse results (SQLite)

Usage:
    >>> from src.data.announcement_processor import AnnouncementProcessor
    >>> processor = AnnouncementProcessor(
    ...     db_path="data/real_all_lof/config/fund_status.db",
    ...     announcements_dir="data/real_all_lof/announcements"
    ... )
    >>> result = processor.process_pdf("161005", Path("path/to/announcement.pdf"))
    >>> print(result)
    {'success': True, 'stored': True, 'parse_result': {...}}

    >>> # Process all PDFs for a ticker
    >>> stats = processor.process_ticker("161005")
    >>> print(f"Processed {stats['total']} PDFs, {stats['stored']} stored")
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger(__name__)


class AnnouncementProcessor:
    """
    Orchestrates the end-to-end processing of fund announcement PDFs.

    This class combines PDF text extraction, LLM-based parsing, and database
    storage to provide a complete pipeline from raw PDF to structured data.

    Attributes:
        db_path: Path to the SQLite database file
        announcements_dir: Base directory containing ticker subdirectories with PDFs
        llm_client: LLMClient instance for parsing announcements
        logger: Logger instance for this class

    Example:
        >>> processor = AnnouncementProcessor(
        ...     db_path="data/config/fund_status.db",
        ...     announcements_dir="data/announcements"
        ... )
        >>> result = processor.process_ticker("161005")
        >>> print(f"Total PDFs: {result['total']}")
    """

    def __init__(
        self,
        db_path: Path | str,
        announcements_dir: Path | str,
        llm_client: Optional[LLMClient] = None,
    ):
        """
        Initialize the announcement processor.

        Args:
            db_path: Path to the SQLite database file (fund_status.db)
            announcements_dir: Base directory containing ticker subdirectories with PDFs
            llm_client: Optional LLMClient instance. If None, creates default client.
        """
        self.db_path = Path(db_path)
        self.announcements_dir = Path(announcements_dir)
        self.llm_client = llm_client or LLMClient()
        self.logger = logging.getLogger(__name__)

    def process_pdf(self, ticker: str, pdf_path: Path) -> dict:
        """
        Process a single PDF file: extract text, parse with LLM, and store result.

        This is the core method that orchestrates the full pipeline for a single
        PDF file. It handles extraction errors, parsing failures, and database
        storage, returning a detailed result dictionary.

        Args:
            ticker: Fund ticker code (e.g., "161005")
            pdf_path: Path to the PDF file

        Returns:
            Dictionary with processing results:
            - success (bool): Whether processing completed without errors
            - extracted (bool): Whether text extraction succeeded
            - parsed (bool): Whether LLM parsing succeeded
            - stored (bool): Whether result was stored in database
            - is_limit_announcement (bool): Whether this is a purchase limit announcement
            - parse_result (dict | None): The parsed result from LLM (if successful)
            - error (str | None): Error message if something failed

        Example:
            >>> result = processor.process_pdf("161005", Path("announcements/161005/2024-01-01_公告.pdf"))
            >>> if result['success']:
            ...     print(f"Limit amount: {result['parse_result']['limit_amount']}")
        """
        pdf_path = Path(pdf_path)
        self.logger.info(f"Processing PDF for {ticker}: {pdf_path.name}")

        result = {
            "success": False,
            "extracted": False,
            "parsed": False,
            "stored": False,
            "is_limit_announcement": False,
            "parse_result": None,
            "error": None,
        }

        # Step 1: Extract text from PDF
        extraction_result = extract_pdf_text(pdf_path)

        if not extraction_result["success"]:
            error_msg = f"Text extraction failed: {extraction_result.get('error', 'Unknown error')}"
            self.logger.warning(f"{error_msg} - File: {pdf_path}")
            result["error"] = error_msg
            return result

        result["extracted"] = True
        extracted_text = extraction_result["text"]
        self.logger.debug(
            f"Extracted {len(extracted_text)} characters from {pdf_path.name}"
        )

        # Step 2: Parse with LLM
        parse_result = self.llm_client.parse_announcement(extracted_text)

        if parse_result.get("error"):
            error_msg = f"LLM parsing failed: {parse_result['error']}"
            self.logger.warning(f"{error_msg} - File: {pdf_path}")
            result["error"] = error_msg
            # Still store the error result for audit trail
            result["parse_result"] = parse_result
        else:
            result["parsed"] = True
            result["parse_result"] = parse_result
            result["is_limit_announcement"] = parse_result.get(
                "is_purchase_limit_announcement", False
            )
            self.logger.info(
                f"Parsed announcement: type={parse_result.get('announcement_type')}, "
                f"is_limit={result['is_limit_announcement']}"
            )

        # Step 3: Parse date from filename
        try:
            announcement_date = self._parse_date_from_filename(pdf_path.name)
        except ValueError as e:
            error_msg = f"Failed to parse date from filename: {e}"
            self.logger.warning(f"{error_msg} - File: {pdf_path}")
            result["error"] = error_msg
            return result

        # Step 4: Store in database (even for non-limit announcements - audit trail)
        try:
            self._save_parse_result(
                ticker=ticker,
                announcement_date=announcement_date,
                pdf_filename=pdf_path.name,
                parse_result=result["parse_result"],
            )
            result["stored"] = True
            result["success"] = True
            self.logger.info(f"Successfully stored parse result for {pdf_path.name}")
        except Exception as e:
            error_msg = f"Database storage failed: {str(e)}"
            self.logger.error(f"{error_msg} - File: {pdf_path}")
            result["error"] = error_msg

        return result

    def process_ticker(self, ticker: str) -> dict:
        """
        Process all PDF announcements for a specific ticker.

        Finds all PDF files in the ticker's subdirectory, processes each one,
        and returns comprehensive statistics about the batch operation.

        Args:
            ticker: Fund ticker code (e.g., "161005")

        Returns:
            Dictionary with batch processing statistics:
            - ticker (str): The ticker code
            - total (int): Total number of PDFs found
            - extracted (int): Number of PDFs successfully extracted
            - parsed (int): Number of PDFs successfully parsed
            - stored (int): Number of results stored in database
            - limit_announcements (int): Number of purchase limit announcements
            - skipped (int): Number of non-limit announcements
            - failed (int): Number of failures
            - errors (list): List of error messages for failed PDFs

        Example:
            >>> stats = processor.process_ticker("161005")
            >>> print(f"Processed {stats['total']} PDFs, {stats['stored']} stored, "
            ...       f"{stats['failed']} failed")
        """
        self.logger.info(f"Starting batch processing for ticker: {ticker}")

        ticker_dir = self.announcements_dir / ticker

        if not ticker_dir.exists():
            self.logger.warning(f"Ticker directory not found: {ticker_dir}")
            return {
                "ticker": ticker,
                "total": 0,
                "extracted": 0,
                "parsed": 0,
                "stored": 0,
                "limit_announcements": 0,
                "skipped": 0,
                "failed": 0,
                "errors": [f"Ticker directory not found: {ticker_dir}"],
            }

        # Find all PDF files
        pdf_files = sorted(ticker_dir.glob("*.pdf"))
        total = len(pdf_files)

        self.logger.info(f"Found {total} PDF files for {ticker}")

        stats = {
            "ticker": ticker,
            "total": total,
            "extracted": 0,
            "parsed": 0,
            "stored": 0,
            "limit_announcements": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        # Process each PDF
        for i, pdf_path in enumerate(pdf_files, 1):
            self.logger.info(f"[{i}/{total}] Processing: {pdf_path.name}")

            try:
                result = self.process_pdf(ticker, pdf_path)

                if result["extracted"]:
                    stats["extracted"] += 1
                if result["parsed"]:
                    stats["parsed"] += 1
                if result["stored"]:
                    stats["stored"] += 1

                if result["is_limit_announcement"]:
                    stats["limit_announcements"] += 1
                elif result["parsed"] and not result.get("error"):
                    # Successfully parsed but not a limit announcement
                    stats["skipped"] += 1

                if result.get("error"):
                    stats["failed"] += 1
                    stats["errors"].append(f"{pdf_path.name}: {result['error']}")

            except Exception as e:
                self.logger.error(f"Unexpected error processing {pdf_path.name}: {e}")
                stats["failed"] += 1
                stats["errors"].append(f"{pdf_path.name}: {str(e)}")

        self.logger.info(
            f"Batch processing complete for {ticker}: "
            f"{stats['stored']}/{stats['total']} stored, "
            f"{stats['failed']} failed"
        )

        return stats

    def _save_parse_result(
        self,
        ticker: str,
        announcement_date: str,
        pdf_filename: str,
        parse_result: dict,
    ) -> None:
        """
        Save parse result to the announcement_parses table.

        Args:
            ticker: Fund ticker code
            announcement_date: Date string in YYYY-MM-DD format
            pdf_filename: Name of the PDF file
            parse_result: Dictionary with parsed information from LLM

        Raises:
            sqlite3.Error: If database operation fails
        """
        # Convert parse_result dict to JSON string
        parse_result_json = json.dumps(parse_result, ensure_ascii=False)

        # Extract fields from parse_result
        parse_type = parse_result.get("announcement_type") if parse_result else None
        confidence = parse_result.get("confidence") if parse_result else None

        # Ensure confidence is a valid float
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = None

        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Use INSERT OR REPLACE to handle re-processing
            # This allows running the processor multiple times on the same PDFs
            cursor.execute(
                """
                INSERT OR REPLACE INTO announcement_parses 
                (ticker, announcement_date, pdf_filename, parse_result, parse_type, confidence, processed)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    ticker,
                    announcement_date,
                    pdf_filename,
                    parse_result_json,
                    parse_type,
                    confidence,
                ),
            )

            conn.commit()
            self.logger.debug(f"Stored parse result for {pdf_filename}")
        finally:
            if conn:
                conn.close()

    def _parse_date_from_filename(self, filename: str) -> str:
        """
        Extract date from PDF filename.

        Expected format: YYYY-MM-DD_{title}.pdf
        Example: 2024-01-15_限购公告.pdf

        Args:
            filename: PDF filename

        Returns:
            Date string in YYYY-MM-DD format

        Raises:
            ValueError: If date cannot be parsed from filename
        """
        # Remove .pdf extension
        if filename.endswith(".pdf"):
            filename = filename[:-4]

        # Try to extract date from start of filename
        # Format: YYYY-MM-DD_
        parts = filename.split("_", 1)

        if not parts:
            raise ValueError(f"Cannot parse date from filename: {filename}")

        date_part = parts[0]

        # Validate date format
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
            return date_part
        except ValueError:
            raise ValueError(
                f"Invalid date format in filename: {date_part}. Expected YYYY-MM-DD"
            )

    def _ticker_has_parses(self, ticker: str) -> bool:
        """
        Check if a ticker already has parse results in the database.

        Args:
            ticker: Fund ticker code

        Returns:
            True if ticker has at least one parse result, False otherwise
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM announcement_parses WHERE ticker = ?",
                (ticker,),
            )
            count = cursor.fetchone()[0]
            return count > 0
        finally:
            if conn:
                conn.close()


def process_pdf(
    pdf_path: Path | str,
    ticker: str,
    db_path: Path | str,
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """
    Convenience function to process a single PDF file.

    This is a standalone function for simple use cases where you don't need
    to create an AnnouncementProcessor instance.

    Args:
        pdf_path: Path to the PDF file
        ticker: Fund ticker code
        db_path: Path to the SQLite database
        llm_client: Optional LLMClient instance

    Returns:
        Dictionary with processing results (see AnnouncementProcessor.process_pdf)

    Example:
        >>> result = process_pdf(
        ...     pdf_path="announcements/161005/2024-01-01_公告.pdf",
        ...     ticker="161005",
        ...     db_path="data/fund_status.db"
        ... )
        >>> print(f"Success: {result['success']}")
    """
    pdf_path = Path(pdf_path)
    db_path = Path(db_path)

    # Derive announcements_dir from pdf_path and ticker
    announcements_dir = pdf_path.parent.parent

    processor = AnnouncementProcessor(
        db_path=db_path,
        announcements_dir=announcements_dir,
        llm_client=llm_client,
    )

    return processor.process_pdf(ticker, pdf_path)


def process_ticker(
    ticker: str,
    db_path: Path | str,
    announcements_dir: Path | str,
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """
    Convenience function to process all PDFs for a ticker.

    This is a standalone function for simple use cases where you don't need
    to create an AnnouncementProcessor instance.

    Args:
        ticker: Fund ticker code
        db_path: Path to the SQLite database
        announcements_dir: Base directory containing ticker subdirectories
        llm_client: Optional LLMClient instance

    Returns:
        Dictionary with batch processing statistics

    Example:
        >>> stats = process_ticker(
        ...     ticker="161005",
        ...     db_path="data/fund_status.db",
        ...     announcements_dir="data/announcements"
        ... )
        >>> print(f"Processed {stats['total']} PDFs")
    """
    processor = AnnouncementProcessor(
        db_path=db_path,
        announcements_dir=announcements_dir,
        llm_client=llm_client,
    )

    return processor.process_ticker(ticker)
