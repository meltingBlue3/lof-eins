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
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    print("[WARN] python-dotenv not installed, using system environment variables only")

import jqdatasdk as jq
from jqdatasdk import finance


# ---------------------------------------------------------
# 默认配置
# ---------------------------------------------------------
DEFAULT_START_DATE = "2024-10-27"
DEFAULT_END_DATE = "2024-12-26"
DEFAULT_OUTPUT_ROOT = "./data/real_all_lof"
DEFAULT_BATCH_SIZE = 50


class RealDataDownloader:
    """Downloads real LOF data from JoinQuant API."""

    def __init__(
        self, username: str, password: str, output_dir: str, batch_size: int = 50
    ):
        self.username = username
        self.password = password
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.market_dir = os.path.join(output_dir, "market")
        self.nav_dir = os.path.join(output_dir, "nav")
        self.config_dir = os.path.join(output_dir, "config")

    def authenticate(self) -> bool:
        """Authenticate with JoinQuant API."""
        try:
            jq.auth(self.username, self.password)
            count = jq.get_query_count()
            print(
                f"[OK] JoinQuant 登录成功 | 剩余额度: {count['spare']}/{count['total']}"
            )
            return True
        except Exception as e:
            print(f"[ERROR] 登录失败: {e}")
            return False

    def setup_directories(self) -> None:
        """创建标准目录结构"""
        for d in [self.market_dir, self.nav_dir, self.config_dir]:
            os.makedirs(d, exist_ok=True)
        print(f"[OK] 目录结构已准备: {self.output_dir}")

    def fetch_all_lof_list(self, date: str) -> list:
        """获取全市场 LOF 列表"""
        print(f"\n>>> 正在获取全市场 LOF 基金列表 (基准日期: {date})...")
        try:
            df = jq.get_all_securities(types=["lof"], date=date)
            print(f"    原始数量: {len(df)}")
            codes = df.index.tolist()
            print(f"    [OK] 成功获取 {len(codes)} 只 LOF 基金代码")
            return codes
        except Exception as e:
            print(f"[ERROR] 获取 LOF 列表失败: {e}")
            return []

    def get_market_data(
        self, codes: list, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取行情数据 (OHLCV)"""
        try:
            df = jq.get_price(
                codes,
                start_date=start_date,
                end_date=end_date,
                frequency="daily",
                fields=["open", "close", "high", "low", "volume"],
                skip_paused=False,
                fq="none",
            )
            if df.empty:
                return pd.DataFrame()

            df = df.reset_index()
            if "time" in df.columns:
                df["date"] = df["time"].dt.date
                df = df.drop(columns=["time"])

            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            print(f"    [WARN] 本批次行情下载遇到部分错误: {e}")
            return pd.DataFrame()

    def get_nav_data(self, codes: list, start_date: str, end_date: str) -> pd.DataFrame:
        """获取净值数据 (NAV)"""
        pure_codes = [c.split(".")[0] for c in codes]
        pure_to_full = {c.split(".")[0]: c for c in codes}

        try:
            q = jq.query(finance.FUND_NET_VALUE).filter(
                finance.FUND_NET_VALUE.code.in_(pure_codes),
                finance.FUND_NET_VALUE.day >= start_date,
                finance.FUND_NET_VALUE.day <= end_date,
            )
            nav_df = finance.run_query(q)

            if nav_df.empty:
                return pd.DataFrame()

            if "unit_net_value" in nav_df.columns:
                nav_df["nav"] = nav_df["unit_net_value"]
            elif "net_value" in nav_df.columns:
                nav_df["nav"] = nav_df["net_value"]
            else:
                return pd.DataFrame()

            nav_df = nav_df.rename(columns={"day": "date"})
            nav_df["date"] = pd.to_datetime(nav_df["date"])
            nav_df["code"] = nav_df["code"].map(pure_to_full)
            nav_df = nav_df.dropna(subset=["code"])

            return nav_df[["date", "code", "nav"]]

        except Exception as e:
            print(f"    [WARN] 本批次 NAV 下载遇到部分错误: {e}")
            return pd.DataFrame()

    def process_and_save(
        self, codes: list, price_df: pd.DataFrame, nav_df: pd.DataFrame
    ) -> list:
        """拆分数据并保存"""
        processed_tickers = []

        for code in codes:
            ticker_pure = code.split(".")[0]

            # 处理 Market
            if not price_df.empty:
                df_m = price_df[price_df["code"] == code].copy()
                if not df_m.empty:
                    df_m["ticker"] = ticker_pure
                    df_m = df_m.sort_values("date")
                    df_m["volume_ma5"] = (
                        df_m["volume"].rolling(window=5).mean().fillna(df_m["volume"])
                    )

                    cols = [
                        "date",
                        "ticker",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "volume_ma5",
                    ]
                    final_cols = [c for c in cols if c in df_m.columns]

                    save_path = os.path.join(self.market_dir, f"{ticker_pure}.parquet")
                    df_m[final_cols].to_parquet(save_path, index=False)

            # 处理 NAV
            if not nav_df.empty:
                df_n = nav_df[nav_df["code"] == code].copy()
                if not df_n.empty:
                    df_n["ticker"] = ticker_pure
                    df_n = df_n.sort_values("date")
                    df_n = df_n.drop_duplicates(subset=["date"], keep="last")

                    nav_cols = ["date", "ticker", "nav"]
                    save_path = os.path.join(self.nav_dir, f"{ticker_pure}.parquet")
                    df_n[nav_cols].to_parquet(save_path, index=False)

                    processed_tickers.append(ticker_pure)

        return list(set(processed_tickers))

    def _generate_fee_config(self, tickers: list) -> None:
        """追加或生成费率文件"""
        csv_path = os.path.join(self.config_dir, "fees.csv")

        new_data = []
        for t in tickers:
            new_data.append(
                {
                    "ticker": t,
                    "fee_rate_tier_1": 0.015,
                    "fee_limit_1": 500000,
                    "fee_rate_tier_2": 0.010,
                    "fee_limit_2": 2000000,
                    "fee_fixed": 1000.0,
                    "redeem_fee_7d": 0.015,
                }
            )
        new_df = pd.DataFrame(new_data)

        if os.path.exists(csv_path):
            old_df = pd.read_csv(csv_path, dtype={"ticker": str})
            combined = pd.concat([old_df, new_df])
            combined = combined.drop_duplicates(subset=["ticker"], keep="last")
            combined.to_csv(csv_path, index=False)
        else:
            new_df.to_csv(csv_path, index=False)

    def _generate_limit_db(self) -> None:
        """创建限购事件数据库"""
        db_path = os.path.join(self.config_dir, "fund_status.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)

        conn.commit()
        conn.close()

    def run_all(self, start_date: str, end_date: str) -> None:
        """执行完整下载流程"""
        self.setup_directories()

        all_codes = self.fetch_all_lof_list(end_date)
        if not all_codes:
            return

        total_funds = len(all_codes)
        total_batches = math.ceil(total_funds / self.batch_size)

        print(
            f"\n>>> 开始批量下载: 共 {total_funds} 只基金, 分 {total_batches} 批处理..."
        )

        all_processed_tickers = []

        for i in range(0, total_funds, self.batch_size):
            batch_codes = all_codes[i : i + self.batch_size]
            current_batch = (i // self.batch_size) + 1

            print(
                f"\n[Batch {current_batch}/{total_batches}] 处理 {len(batch_codes)} 只基金 ({batch_codes[0]} ...)"
            )

            price_df = self.get_market_data(batch_codes, start_date, end_date)
            nav_df = self.get_nav_data(batch_codes, start_date, end_date)

            processed = self.process_and_save(batch_codes, price_df, nav_df)
            all_processed_tickers.extend(processed)

            print(f"    -> 本批次成功保存 {len(processed)} 只")

            time.sleep(0.5)

        print(f"\n>>> 所有批次完成. 共处理 {len(all_processed_tickers)} 只有效基金.")
        if all_processed_tickers:
            print(">>> 更新全局配置文件...")
            self._generate_fee_config(all_processed_tickers)
            self._generate_limit_db()
            print(f"\n[SUCCESS] 下载任务全部完成! 数据路径: {self.output_dir}")
        else:
            print("\n[WARN] 未下载到任何有效数据。")


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
        username=username,
        password=password,
        output_dir=args.output,
        batch_size=args.batch_size,
    )

    if downloader.authenticate():
        downloader.run_all(args.start, args.end)


if __name__ == "__main__":
    main()
