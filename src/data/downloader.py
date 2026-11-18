"""
Real Data Downloader for LOF funds from JoinQuant.

LOF 基金实盘数据下载器（来自聚宽数据源）。

Downloads market data, NAV, and generates config files compatible with DataLoader.
下载行情数据、净值数据，并生成与 DataLoader 兼容的配置文件。

Handles batch processing to avoid API rate limits.
支持批量处理以避免 API 频率限制。
"""

import os
import time
import math
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

# JoinQuant SDK - optional dependency  # 聚宽 SDK - 可选依赖
try:
    import jqdatasdk as jq
    from jqdatasdk import finance

    JQ_AVAILABLE = True
except ImportError:
    JQ_AVAILABLE = False


class RealDataDownloader:
    """Downloads real LOF data from JoinQuant API.
    从聚宽 API 下载 LOF 实盘数据。

    Creates data in the standard directory structure expected by DataLoader:
    在 DataLoader 期望的标准目录结构中创建数据：
    - market/{ticker}.parquet
    - nav/{ticker}.parquet
    - config/ (created empty; subscription_state.db and fund_terms.csv come from
      scripts/build_corpus.py ... build_timeline.py and scripts/fund_terms.py)

    Attributes:
        output_dir: Root directory for downloaded data.  # 下载数据的根目录
        batch_size: Number of funds to process per API batch.  # 每个 API 批次处理的基金数量
    """

    def __init__(self, output_dir: str = "./data/real_all_lof", batch_size: int = 50):
        """Initialize downloader.
        初始化下载器。

        Args:
            output_dir: Root directory for output data.  # 输出数据的根目录
            batch_size: Number of funds per batch (default 50 to avoid API limits).  # 每批次基金数量（默认 50 以避免 API 限制）
        """
        if not JQ_AVAILABLE:
            raise ImportError(
                "jqdatasdk is required for RealDataDownloader. "
                "Install with: pip install jqdatasdk"
            )

        self.output_dir = Path(output_dir)
        self.batch_size = batch_size
        self.market_dir = self.output_dir / "market"
        self.nav_dir = self.output_dir / "nav"
        self.config_dir = self.output_dir / "config"
        self._authenticated = False

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate with JoinQuant API.
        使用聚宽 API 进行身份验证。

        Args:
            username: JoinQuant account username.  # 聚宽账户用户名
            password: JoinQuant account password.  # 聚宽账户密码

        Returns:
            True if authentication successful, False otherwise.  # 认证成功返回 True，否则返回 False
        """
        try:
            jq.auth(username, password)
            count = jq.get_query_count()
            print(
                f"[OK] JoinQuant login successful | Quota: {count['spare']}/{count['total']}"
            )
            self._authenticated = True
            return True
        except Exception as e:
            print(f"[ERROR] Login failed: {e}")
            return False

    def authenticate_from_env(self) -> bool:
        """Authenticate using environment variables JQ_USERNAME and JQ_PASSWORD.
        使用环境变量 JQ_USERNAME 和 JQ_PASSWORD 进行身份验证。

        Returns:
            True if authentication successful, False otherwise.  # 认证成功返回 True，否则返回 False
        """
        username = os.environ.get("JQ_USERNAME")
        password = os.environ.get("JQ_PASSWORD")

        if not username or not password:
            print("[ERROR] JQ_USERNAME and JQ_PASSWORD environment variables not set")
            return False

        return self.authenticate(username, password)

    def _setup_directories(self) -> None:
        """Create standard directory structure.
        创建标准目录结构。
        """
        for d in [self.market_dir, self.nav_dir, self.config_dir]:
            d.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory structure ready: {self.output_dir}")

    def fetch_all_lof_codes(self, reference_date: str) -> List[str]:
        """Fetch all LOF fund codes from JoinQuant.
        从聚宽获取所有 LOF 基金代码。

        Args:
            reference_date: Reference date for fund list (YYYY-MM-DD).  # 基金列表的参考日期（YYYY-MM-DD）

        Returns:
            List of fund codes (e.g., ['160105.XSHE', '161005.XSHE']).  # 基金代码列表
        """
        print(
            f"\n>>> Fetching all LOF fund codes (reference date: {reference_date})..."
        )
        try:
            df = jq.get_all_securities(types=["lof"], date=reference_date)
            codes = df.index.tolist()
            print(f"    [OK] Found {len(codes)} LOF funds")
            return codes
        except Exception as e:
            print(f"[ERROR] Failed to fetch LOF list: {e}")
            return []

    def _get_market_data(
        self, codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Fetch market OHLCV data for a batch of codes.
        获取一批代码的行情 OHLCV 数据。
        """
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
            # Handle different JQ versions ('time' vs 'date')  # 处理不同聚宽版本（'time' vs 'date'）
            if "time" in df.columns:
                df["date"] = df["time"].dt.date
                df = df.drop(columns=["time"])

            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            print(f"    [WARN] Market data batch error: {e}")
            return pd.DataFrame()

    def _get_nav_data(
        self, codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Fetch NAV data for a batch of codes via akshare.
        通过 akshare 获取一批代码的净值数据。
        """
        try:
            import akshare as ak
        except ImportError:
            print("    [ERROR] akshare is required for NAV download: pip install akshare")
            return pd.DataFrame()

        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date)
        frames = []

        for code in codes:
            ticker_pure = code.split(".")[0]
            try:
                df = ak.fund_open_fund_info_em(symbol=ticker_pure, indicator="单位净值走势")
                if df.empty:
                    continue
                # Columns: 净值日期, 单位净值, 日增长率
                df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})
                df["date"] = pd.to_datetime(df["date"])
                df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
                df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
                df["code"] = code
                frames.append(df[["date", "code", "nav"]])
            except Exception as e:
                print(f"    [WARN] NAV for {ticker_pure}: {e}")

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _process_and_save(
        self, codes: List[str], price_df: pd.DataFrame, nav_df: pd.DataFrame
    ) -> List[str]:
        """Process and save data for a batch of funds.
        处理并保存一批基金的数据。

        Returns:
            List of successfully processed ticker codes (pure, without exchange suffix).  # 成功处理的标的代码列表（不含交易所后缀）
        """
        processed_tickers = []

        for code in codes:
            ticker_pure = code.split(".")[0]

            # Process market data  # 处理行情数据
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

                    save_path = self.market_dir / f"{ticker_pure}.parquet"
                    df_m[final_cols].to_parquet(save_path, index=False)

            # Process NAV data  # 处理净值数据
            if not nav_df.empty:
                df_n = nav_df[nav_df["code"] == code].copy()
                if not df_n.empty:
                    df_n["ticker"] = ticker_pure
                    df_n = df_n.sort_values("date")
                    df_n = df_n.drop_duplicates(subset=["date"], keep="last")

                    nav_cols = ["date", "ticker", "nav"]
                    save_path = self.nav_dir / f"{ticker_pure}.parquet"
                    df_n[nav_cols].to_parquet(save_path, index=False)

                    processed_tickers.append(ticker_pure)

        return list(set(processed_tickers))

    def download(
        self, start_date: str, end_date: str, codes: Optional[List[str]] = None
    ) -> Tuple[int, List[str]]:
        """Download LOF data for specified date range.
        下载指定日期范围的 LOF 数据。

        Args:
            start_date: Start date (YYYY-MM-DD).  # 开始日期（YYYY-MM-DD）
            end_date: End date (YYYY-MM-DD).  # 结束日期（YYYY-MM-DD）
            codes: Optional list of fund codes. If None, downloads all LOFs.  # 可选的基金代码列表。如果为 None，下载所有 LOF

        Returns:
            Tuple of (total_processed_count, list_of_processed_tickers).  # (总处理数量, 已处理的标的列表) 元组
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        self._setup_directories()

        # Get fund list if not provided  # 如果未提供则获取基金列表
        if codes is None:
            codes = self.fetch_all_lof_codes(end_date)

        if not codes:
            return 0, []

        total_funds = len(codes)
        total_batches = math.ceil(total_funds / self.batch_size)

        print(
            f"\n>>> Starting download: {total_funds} funds in {total_batches} batches..."
        )

        all_processed_tickers = []

        # Batch processing  # 批量处理
        for i in range(0, total_funds, self.batch_size):
            batch_codes = codes[i : i + self.batch_size]
            current_batch = (i // self.batch_size) + 1

            print(
                f"\n[Batch {current_batch}/{total_batches}] Processing {len(batch_codes)} funds..."
            )

            # Download data  # 下载数据
            price_df = self._get_market_data(batch_codes, start_date, end_date)
            nav_df = self._get_nav_data(batch_codes, start_date, end_date)

            # Save data  # 保存数据
            processed = self._process_and_save(batch_codes, price_df, nav_df)
            all_processed_tickers.extend(processed)

            print(f"    -> Saved {len(processed)} funds")

            # Rate limiting  # 频率限制
            time.sleep(0.5)

        print(
            f"\n>>> All batches complete. Total processed: {len(all_processed_tickers)} funds."
        )
        if all_processed_tickers:
            print(f"\n[SUCCESS] Download complete! Data path: {self.output_dir}")
        else:
            print("\n[WARN] No valid data downloaded.")

        return len(all_processed_tickers), all_processed_tickers


def download_all_lof(
    username: str,
    password: str,
    start_date: str,
    end_date: str,
    output_dir: str = "./data/real_all_lof",
    batch_size: int = 50,
) -> Tuple[int, List[str]]:
    """Convenience function to download all LOF data.
    下载所有 LOF 数据的便捷函数。

    Args:
        username: JoinQuant username.  # 聚宽用户名
        password: JoinQuant password.  # 聚宽密码
        start_date: Start date (YYYY-MM-DD).  # 开始日期（YYYY-MM-DD）
        end_date: End date (YYYY-MM-DD).  # 结束日期（YYYY-MM-DD）
        output_dir: Output directory path.  # 输出目录路径
        batch_size: Batch size for API calls.  # API 调用的批次大小

    Returns:
        Tuple of (total_processed_count, list_of_processed_tickers).  # (总处理数量, 已处理的标的列表) 元组
    """
    downloader = RealDataDownloader(output_dir=output_dir, batch_size=batch_size)

    if not downloader.authenticate(username, password):
        return 0, []

    return downloader.download(start_date, end_date)
