#!/usr/bin/env python
"""
Download LOF fund announcement PDFs from Eastmoney.

Usage:
    python scripts/download_announcements.py
    python scripts/download_announcements.py --ticker 163417
    python scripts/download_announcements.py --ticker 163417 --start 2024-01-01 --end 2024-12-31
    python scripts/download_announcements.py --data-dir ./data/custom
    python scripts/download_announcements.py --delay 2.0
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.announcement_downloader import AnnouncementDownloader


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download LOF fund announcements from Eastmoney",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/download_announcements.py
    python scripts/download_announcements.py --ticker 163417
    python scripts/download_announcements.py --ticker 163417 --start 2024-01-01 --end 2024-12-31
    python scripts/download_announcements.py --data-dir ./data/custom
    python scripts/download_announcements.py --delay 2.0
        """,
    )

    parser.add_argument(
        "--ticker",
        help="Specific fund ticker to download (e.g., 163417)",
    )
    parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD). If omitted, use backtest start.",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD). If omitted, use backtest end.",
    )
    parser.add_argument(
        "--data-dir",
        default="./data/real_all_lof",
        help="Root data directory (default: ./data/real_all_lof)",
    )
    parser.add_argument(
        "--type",
        type=int,
        default=0,
        help="Announcement type: 0=all, 5=periodic reports",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="Announcements per page (default: 50)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)",
    )

    args = parser.parse_args()

    downloader = AnnouncementDownloader(
        data_dir=args.data_dir,
        announcement_type=args.type,
        page_size=args.page_size,
        delay=args.delay,
    )

    try:
        if args.ticker:
            downloader.download_fund_announcements(
                ticker=args.ticker,
                start_date=args.start,
                end_date=args.end,
            )
        else:
            downloader.download_all_lof_announcements()
    except Exception as exc:
        print(f"[ERROR] Announcement download failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
