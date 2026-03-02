#!/usr/bin/env python
"""
Real Data Downloader for ALL LOFs.

Downloads data from JoinQuant, chunks requests to avoid timeouts,
and structures it for the DataLoader.

Usage:
    python scripts/download_lof.py                           # Use defaults
    python scripts/download_lof.py --start 2024-01-01        # Custom start date
    python scripts/download_lof.py --output ./data/custom    # Custom output dir

Configuration:
    Create a .env file in project root with:
        JQ_USERNAME=your_username
        JQ_PASSWORD=your_password
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    print("[WARN] python-dotenv not installed, using system environment variables only")

from src.data.downloader import RealDataDownloader


# ---------------------------------------------------------
# 默认配置
# ---------------------------------------------------------
DEFAULT_START_DATE = "2024-10-27"
DEFAULT_END_DATE = "2024-12-26"
DEFAULT_OUTPUT_ROOT = "./data/real_all_lof"
DEFAULT_BATCH_SIZE = 50


def main():
    parser = argparse.ArgumentParser(
        description="Download LOF data from JoinQuant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/download_lof.py
    python scripts/download_lof.py --start 2024-01-01 --end 2024-06-30
    python scripts/download_lof.py --output ./data/my_lof_data

Environment Variables (or .env file):
    JQ_USERNAME    JoinQuant account username
    JQ_PASSWORD    JoinQuant account password
        """,
    )
    parser.add_argument(
        "--start",
        "-s",
        default=DEFAULT_START_DATE,
        help=f"Start date (YYYY-MM-DD), default: {DEFAULT_START_DATE}",
    )
    parser.add_argument(
        "--end",
        "-e",
        default=DEFAULT_END_DATE,
        help=f"End date (YYYY-MM-DD), default: {DEFAULT_END_DATE}",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output directory, default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Batch size for API calls, default: {DEFAULT_BATCH_SIZE}",
    )

    args = parser.parse_args()

    # 从环境变量获取账号密码
    username = os.environ.get("JQ_USERNAME")
    password = os.environ.get("JQ_PASSWORD")

    if not username or not password:
        print("[ERROR] 未设置 JQ_USERNAME 和 JQ_PASSWORD 环境变量")
        print("[INFO] 请创建 .env 文件或设置环境变量:")
        print("       JQ_USERNAME=your_username")
        print("       JQ_PASSWORD=your_password")
        sys.exit(1)

    print("=" * 60)
    print("LOF 数据下载器")
    print("=" * 60)
    print(f"  时间范围: {args.start} ~ {args.end}")
    print(f"  输出目录: {args.output}")
    print(f"  批处理大小: {args.batch_size}")
    print("=" * 60)

    downloader = RealDataDownloader(
        output_dir=args.output,
        batch_size=args.batch_size,
    )

    if downloader.authenticate(username, password):
        downloader.download(args.start, args.end)


if __name__ == "__main__":
    main()
