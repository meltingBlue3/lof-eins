#!/usr/bin/env python
"""
Download LOF daily bars and unit NAV from AKShare into the DataLoader layout.

从 AKShare 下载 LOF 日线和单位净值，写成 DataLoader 读取的目录结构。不需要账号。

Which funds / 下载哪些基金:
- default: the LOFs trading today (Sina's list plus Eastmoney's board; delisted funds are on neither)
  默认：当前在交易的 LOF（新浪列表并上东方财富板块；已退市的不在其中）
- --tickers-from DIR: the funds in DIR/market, e.g. to rebuild an existing universe from scratch
  --tickers-from DIR：沿用某个数据目录 market/ 下的基金，用于重建已有样本
- --tickers 161226,160216: just these
  --tickers：只下载这几只

Daily bars come from Sina by default (volume in shares; about 15 minutes for 400 funds). With
--source eastmoney they come from Eastmoney, which refuses an IP for minutes to over an hour after
a burst of requests: requests are then paced (--pause seconds apart, slower after each refusal)
and a refusal is waited out. Funds already on disk are skipped, so an interrupted run continues
where it stopped; --refresh fetches them again. Neither source has a row on a day without trades.
日线默认来自新浪（成交量单位为份，约 400 只基金 15 分钟）。--source eastmoney 改用东方财富，
它在短时间请求过多后会封 IP 几分钟到一小时以上，此时请求之间有间隔（被封后放慢），被封时自动等待。
已下载的基金会跳过，中断后重跑即可续传；--refresh 重新下载。两个来源在无成交的日子都没有记录。

Usage:
    python scripts/download_lof.py --start 2021-01-01 --end 2024-12-31
    python scripts/download_lof.py --tickers-from data/real_all_lof --output data/real_all_lof/_staging
    python scripts/download_lof.py --tickers 161226,160216 --output data/try --source eastmoney
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.downloader import RealDataDownloader  # noqa: E402

DEFAULT_START_DATE = "2021-01-01"
DEFAULT_END_DATE = "2024-12-31"
DEFAULT_OUTPUT_ROOT = "./data/real_all_lof"


def main():
    parser = argparse.ArgumentParser(
        description="Download LOF daily bars and unit NAV from AKShare",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[1],
    )
    parser.add_argument("--start", "-s", default=DEFAULT_START_DATE,
                        help=f"Start date (YYYY-MM-DD), default: {DEFAULT_START_DATE}")
    parser.add_argument("--end", "-e", default=DEFAULT_END_DATE,
                        help=f"End date (YYYY-MM-DD), default: {DEFAULT_END_DATE}")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_ROOT,
                        help=f"Output directory, default: {DEFAULT_OUTPUT_ROOT}")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--tickers", help="Comma-separated fund codes")
    which.add_argument("--tickers-from", metavar="DIR", help="Use the funds in DIR/market/*.parquet")
    parser.add_argument("--source", choices=["sina", "eastmoney"], default="sina",
                        help="Daily bars from Eastmoney (fund_lof_hist_em) or Sina (fund_etf_hist_sina)")
    parser.add_argument("--refresh", action="store_true", help="Fetch funds whose files already exist again")
    parser.add_argument("--pause", type=float, default=5.0,
                        help="Minimum seconds between quote requests (grows after a refusal), default: 5")
    args = parser.parse_args()

    codes = None
    if args.tickers:
        codes = [c.strip() for c in args.tickers.split(",") if c.strip()]
    elif args.tickers_from:
        market = Path(args.tickers_from) / "market"
        codes = sorted(p.stem for p in market.glob("*.parquet"))
        if not codes:
            sys.exit(f"[ERROR] no parquet files in {market}")

    print("=" * 60)
    print("LOF 数据下载器（AKShare）")
    print(f"  时间范围: {args.start} ~ {args.end}")
    print(f"  输出目录: {args.output}")
    print(f"  基金: {'当前 LOF 板块全部' if codes is None else f'{len(codes)} 只'}")
    print("=" * 60)

    RealDataDownloader(output_dir=args.output, source=args.source, pause=args.pause).download(
        args.start, args.end, codes=codes, refresh=args.refresh)


if __name__ == "__main__":
    main()
