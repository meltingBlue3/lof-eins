#!/usr/bin/env python3
"""
CLI tool for parsing fund announcement PDFs using Kimi K2.5.

解析基金申购限制公告PDF，使用Kimi K2.5提取结构化数据，
并生成回测用的limit_events。

Usage:
    # Dry run - list files to process
    python scripts/parse_announcements.py --dry-run

    # Process all pending PDFs
    python scripts/parse_announcements.py

    # Process with custom concurrency
    python scripts/parse_announcements.py --concurrency 100

    # Process single file
    python scripts/parse_announcements.py --file 160105/2022-01-14_xxx.pdf

    # Retry failed files
    python scripts/parse_announcements.py --retry-failed

    # Reset and reprocess everything
    python scripts/parse_announcements.py --reset

    # Only run postprocessing (skip PDF parsing)
    python scripts/parse_announcements.py --postprocess-only

    # Custom data directory
    python scripts/parse_announcements.py --data-dir ./data/custom

Environment Variables:
    KIMI_API_KEY: API key for Kimi (Moonshot) platform. Required.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.data.announcement_processor import AnnouncementProcessor
from src.data.postprocess import postprocess


def main():
    parser = argparse.ArgumentParser(
        description="解析基金申购限制公告PDF（Kimi K2.5）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="仅列出待处理文件")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--file", type=str, default="", help="只处理指定文件（相对路径）")
    parser.add_argument("--retry-failed", action="store_true", help="重试之前失败的文件")
    parser.add_argument("--concurrency", type=int, default=50, help="并发数（默认50）")
    parser.add_argument("--reset", action="store_true", help="清除进度，从头开始")
    parser.add_argument(
        "--postprocess-only", action="store_true",
        help="跳过PDF解析，仅执行后处理（subscription_restrictions → limit_events）"
    )
    parser.add_argument(
        "--no-postprocess", action="store_true",
        help="跳过后处理步骤（仅解析PDF，不生成limit_events）"
    )
    parser.add_argument(
        "--data-dir", default="data/real_all_lof",
        help="数据根目录（默认 data/real_all_lof）"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")

    data_dir = Path(args.data_dir)
    db_path = data_dir / "config" / "fund_status.db"
    announcements_dir = data_dir / "announcements"

    if not db_path.exists():
        print(f"错误：数据库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    if not args.postprocess_only and not announcements_dir.exists():
        print(f"错误：公告目录不存在: {announcements_dir}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Parse PDFs
    if not args.postprocess_only:
        processor = AnnouncementProcessor(
            db_path=db_path,
            announcements_dir=announcements_dir,
        )
        stats = asyncio.run(
            processor.run(
                concurrency=args.concurrency,
                limit=args.limit,
                file=args.file,
                retry_failed=args.retry_failed,
                reset=args.reset,
                dry_run=args.dry_run,
            )
        )

        if args.dry_run:
            return

    # Step 2: Postprocess → limit_events
    if not args.no_postprocess:
        print("\n" + "=" * 60)
        print("后处理: subscription_restrictions → limit_events")
        print("=" * 60)
        postprocess(db_path)


if __name__ == "__main__":
    main()
