#!/usr/bin/env python3
"""
CLI tool for parsing LOF fund announcement PDFs and extracting limit information.

This script provides a command-line interface for batch processing fund
announcement PDFs using the AnnouncementProcessor orchestration layer.

Usage:
    # Process single ticker
    python scripts/parse_announcements.py --ticker 161005

    # Process all tickers
    python scripts/parse_announcements.py --all

    # Custom data directory
    python scripts/parse_announcements.py --ticker 161005 --data-dir ./data/custom

    # Verbose output for debugging
    python scripts/parse_announcements.py --ticker 161005 --verbose

Directory Structure:
    The script expects the following directory structure:

    data_dir/
        config/
            fund_status.db      # SQLite database for storing parse results
        announcements/
            {ticker}/           # Ticker subdirectory
                YYYY-MM-DD_{title}.pdf   # PDF announcement files

Environment Variables:
    OLLAMA_URL: Base URL for Ollama API (default: http://localhost:11434)
    OLLAMA_MODEL: Model name to use (default: qwen2.5:7b)

Exit Codes:
    0: Success
    1: Configuration error (missing database, invalid paths)
    2: Processing error (all PDFs failed for ticker)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.announcement_processor import AnnouncementProcessor


def _discover_tickers(announcements_dir: Path) -> list:
    """
    Discover all tickers with PDF announcements.

    Scans the announcements directory and returns a sorted list of
    ticker codes (subdirectory names) that contain PDF files.

    Args:
        announcements_dir: Base directory containing ticker subdirectories

    Returns:
        Sorted list of ticker codes as strings
    """
    if not announcements_dir.exists():
        return []

    tickers = []
    for item in announcements_dir.iterdir():
        if item.is_dir():
            # Check if directory contains PDF files
            pdfs = list(item.glob("*.pdf"))
            if pdfs:
                tickers.append(item.name)

    return sorted(tickers)


def _print_result(result: dict, verbose: bool = False) -> None:
    """
    Pretty print processing statistics.

    Args:
        result: Statistics dictionary from process_ticker()
        verbose: If True, print detailed error information
    """
    ticker = result.get("ticker", "Unknown")
    total = result.get("total", 0)
    extracted = result.get("extracted", 0)
    parsed = result.get("parsed", 0)
    stored = result.get("stored", 0)
    limit_announcements = result.get("limit_announcements", 0)
    skipped = result.get("skipped", 0)
    failed = result.get("failed", 0)
    errors = result.get("errors", [])

    print(f"\n  Results for {ticker}:")
    print(f"    Total PDFs found:        {total}")
    print(f"    Successfully extracted:  {extracted}")
    print(f"    Successfully parsed:     {parsed}")
    print(f"    Stored in database:      {stored}")
    print(f"    Limit announcements:     {limit_announcements}")
    print(f"    Non-limit (skipped):     {skipped}")
    print(f"    Failed:                  {failed}")

    if verbose and errors:
        print(f"\n    Errors:")
        for error in errors[:10]:  # Show first 10 errors
            print(f"      - {error}")
        if len(errors) > 10:
            print(f"      ... and {len(errors) - 10} more errors")
    elif errors and not verbose:
        print(f"\n    Run with --verbose to see {len(errors)} error(s)")

    # Success rate
    if total > 0:
        success_rate = (stored / total) * 100
        print(f"\n    Success rate: {success_rate:.1f}%")


def main():
    """
    Main entry point for the CLI tool.

    Parses command-line arguments and orchestrates PDF processing.
    """
    parser = argparse.ArgumentParser(
        description="Parse LOF fund announcement PDFs and extract limit information",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single ticker
  python scripts/parse_announcements.py --ticker 161005
  
  # Process all tickers
  python scripts/parse_announcements.py --all
  
  # Custom data directory
  python scripts/parse_announcements.py --ticker 161005 --data-dir ./data/custom
  
  # Verbose output with detailed error information
  python scripts/parse_announcements.py --ticker 161005 --verbose

Environment Variables:
  OLLAMA_URL    - Ollama API URL (default: http://localhost:11434)
  OLLAMA_MODEL  - Model name (default: qwen2.5:7b)

Notes:
  - Ollama must be running for LLM parsing to work
  - Install Ollama from https://ollama.com
  - Pull model with: ollama pull qwen2.5:7b
        """,
    )

    parser.add_argument("--ticker", help="Process single ticker (e.g., 161005)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all tickers found in announcements directory",
    )
    parser.add_argument(
        "--data-dir",
        default="data/real_all_lof",
        help="Base data directory (default: data/real_all_lof)",
    )
    parser.add_argument(
        "--db-path",
        help="Override fund_status.db path (default: {data_dir}/config/fund_status.db)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output with detailed error information",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    # Resolve paths
    data_dir = Path(args.data_dir)
    db_path = args.db_path or data_dir / "config" / "fund_status.db"
    announcements_dir = data_dir / "announcements"

    # Validate paths
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        print(
            "Run the database setup first or specify correct --db-path", file=sys.stderr
        )
        sys.exit(1)

    if not announcements_dir.exists():
        print(
            f"Error: Announcements directory not found: {announcements_dir}",
            file=sys.stderr,
        )
        print(
            "Download announcements first or specify correct --data-dir",
            file=sys.stderr,
        )
        sys.exit(1)

    # Initialize processor
    try:
        processor = AnnouncementProcessor(db_path, announcements_dir)
    except Exception as e:
        print(f"Error: Failed to initialize processor: {e}", file=sys.stderr)
        sys.exit(1)

    # Process based on args
    exit_code = 0

    if args.ticker:
        print(f"Processing ticker: {args.ticker}")
        result = processor.process_ticker(args.ticker)
        _print_result(result, verbose=args.verbose)

        # Set exit code based on success
        if result["failed"] == result["total"] and result["total"] > 0:
            exit_code = 2
        elif result["failed"] > 0:
            exit_code = 0  # Partial success is still success

    elif args.all:
        tickers = _discover_tickers(announcements_dir)

        if not tickers:
            print("No tickers found in announcements directory")
            sys.exit(0)

        print(f"Found {len(tickers)} tickers to process")

        total_stats = {
            "tickers": 0,
            "pdfs": 0,
            "stored": 0,
            "failed": 0,
        }

        for i, ticker in enumerate(tickers, 1):
            print(f"\n[{i}/{len(tickers)}] Processing ticker: {ticker}")
            result = processor.process_ticker(ticker)
            _print_result(result, verbose=args.verbose)

            total_stats["tickers"] += 1
            total_stats["pdfs"] += result["total"]
            total_stats["stored"] += result["stored"]
            total_stats["failed"] += result["failed"]

        # Print summary
        print("\n" + "=" * 60)
        print("BATCH PROCESSING SUMMARY")
        print("=" * 60)
        print(f"Tickers processed: {total_stats['tickers']}")
        print(f"Total PDFs found:  {total_stats['pdfs']}")
        print(f"Total stored:      {total_stats['stored']}")
        print(f"Total failed:      {total_stats['failed']}")

        if total_stats["pdfs"] > 0:
            success_rate = (total_stats["stored"] / total_stats["pdfs"]) * 100
            print(f"Overall success rate: {success_rate:.1f}%")

        if total_stats["failed"] > 0:
            exit_code = 0  # Partial success

    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
