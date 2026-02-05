"""
Real Data Downloader for LOF funds from JoinQuant.

Downloads market data, NAV, and generates config files compatible with DataLoader.
Handles batch processing to avoid API rate limits.
"""

import os
import time
import math
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

# JoinQuant SDK - optional dependency
try:
    import jqdatasdk as jq
    from jqdatasdk import finance

    JQ_AVAILABLE = True
except ImportError:
    JQ_AVAILABLE = False


class RealDataDownloader:
    """Downloads real LOF data from JoinQuant API.

    Creates data in the standard directory structure expected by DataLoader:
    - market/{ticker}.parquet
    - nav/{ticker}.parquet
    - config/fees.csv
    - config/fund_status.db

    Attributes:
        output_dir: Root directory for downloaded data.
        batch_size: Number of funds to process per API batch.
    """

    def __init__(self, output_dir: str = "./data/real_all_lof", batch_size: int = 50):
        """Initialize downloader.

        Args:
            output_dir: Root directory for output data.
            batch_size: Number of funds per batch (default 50 to avoid API limits).
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

        Args:
            username: JoinQuant account username.
            password: JoinQuant account password.

        Returns:
            True if authentication successful, False otherwise.
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

        Returns:
            True if authentication successful, False otherwise.
        """
        username = os.environ.get("JQ_USERNAME")
        password = os.environ.get("JQ_PASSWORD")

        if not username or not password:
            print("[ERROR] JQ_USERNAME and JQ_PASSWORD environment variables not set")
            return False

        return self.authenticate(username, password)

    def _setup_directories(self) -> None:
        """Create standard directory structure."""
        for d in [self.market_dir, self.nav_dir, self.config_dir]:
            d.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory structure ready: {self.output_dir}")

    def fetch_all_lof_codes(self, reference_date: str) -> List[str]:
        """Fetch all LOF fund codes from JoinQuant.

        Args:
            reference_date: Reference date for fund list (YYYY-MM-DD).

        Returns:
            List of fund codes (e.g., ['160105.XSHE', '161005.XSHE']).
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
        """Fetch market OHLCV data for a batch of codes."""
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
            # Handle different JQ versions ('time' vs 'date')
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
        """Fetch NAV data for a batch of codes."""
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

            # Normalize NAV column name
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
            print(f"    [WARN] NAV data batch error: {e}")
            return pd.DataFrame()

    def _process_and_save(
        self, codes: List[str], price_df: pd.DataFrame, nav_df: pd.DataFrame
    ) -> List[str]:
        """Process and save data for a batch of funds.

        Returns:
            List of successfully processed ticker codes (pure, without exchange suffix).
        """
        processed_tickers = []

        for code in codes:
            ticker_pure = code.split(".")[0]

            # Process market data
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

            # Process NAV data
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

    def _generate_fee_config(self, tickers: List[str]) -> None:
        """Generate or update fee configuration file."""
        csv_path = self.config_dir / "fees.csv"

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

        if csv_path.exists():
            old_df = pd.read_csv(csv_path, dtype={"ticker": str})
            combined = pd.concat([old_df, new_df])
            combined = combined.drop_duplicates(subset=["ticker"], keep="last")
            combined.to_csv(csv_path, index=False)
        else:
            new_df.to_csv(csv_path, index=False)

    def _generate_limit_db(self) -> None:
        """Create empty limit events database with enhanced schema.

        Includes is_open_ended computed column, source_announcement_ids for audit trail,
        and proper indexes for query performance.
        """
        db_path = self.config_dir / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create limit_events table with enhanced schema
        # - is_open_ended: computed column identifying open-ended limits (end_date IS NULL)
        # - source_announcement_ids: JSON array of announcement IDs that contributed to this event
        # - reason: human-readable context for why the limit exists
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

        # Create index on is_open_ended for efficient queries of open-ended limits
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)

        # Create index on ticker for efficient lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_events_ticker
            ON limit_events(ticker)
        """)

        conn.commit()
        conn.close()

    def _create_announcement_parses_table(self) -> None:
        """Create announcement_parses table for storing LLM extraction results.

        This table stores raw LLM extraction results from PDF announcements,
        supporting the PDF announcement processing pipeline.
        """
        db_path = self.config_dir / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create announcement_parses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcement_parses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                announcement_date DATE NOT NULL,
                pdf_filename TEXT NOT NULL,
                parse_result TEXT,
                parse_type TEXT,
                confidence REAL,
                processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_ticker
            ON announcement_parses(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_processed
            ON announcement_parses(processed)
        """)

        conn.commit()
        conn.close()

    def _create_limit_event_log_table(self) -> None:
        """Create limit_event_log table for audit trail of timeline changes.

        This table provides an audit trail for debugging timeline changes
        in the purchase limit processing pipeline.
        """
        db_path = self.config_dir / "fund_status.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create limit_event_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                operation TEXT NOT NULL,
                old_start DATE,
                old_end DATE,
                new_start DATE,
                new_end DATE,
                triggered_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_ticker
            ON limit_event_log(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_created_at
            ON limit_event_log(created_at)
        """)

        conn.commit()
        conn.close()

    def download(
        self, start_date: str, end_date: str, codes: Optional[List[str]] = None
    ) -> Tuple[int, List[str]]:
        """Download LOF data for specified date range.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            codes: Optional list of fund codes. If None, downloads all LOFs.

        Returns:
            Tuple of (total_processed_count, list_of_processed_tickers).
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        self._setup_directories()

        # Get fund list if not provided
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

        # Batch processing
        for i in range(0, total_funds, self.batch_size):
            batch_codes = codes[i : i + self.batch_size]
            current_batch = (i // self.batch_size) + 1

            print(
                f"\n[Batch {current_batch}/{total_batches}] Processing {len(batch_codes)} funds..."
            )

            # Download data
            price_df = self._get_market_data(batch_codes, start_date, end_date)
            nav_df = self._get_nav_data(batch_codes, start_date, end_date)

            # Save data
            processed = self._process_and_save(batch_codes, price_df, nav_df)
            all_processed_tickers.extend(processed)

            print(f"    -> Saved {len(processed)} funds")

            # Rate limiting
            time.sleep(0.5)

        # Generate config files
        print(
            f"\n>>> All batches complete. Total processed: {len(all_processed_tickers)} funds."
        )
        if all_processed_tickers:
            print(">>> Updating configuration files...")
            self._generate_fee_config(all_processed_tickers)
            self._generate_limit_db()
            self._create_announcement_parses_table()
            self._create_limit_event_log_table()
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

    Args:
        username: JoinQuant username.
        password: JoinQuant password.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        output_dir: Output directory path.
        batch_size: Batch size for API calls.

    Returns:
        Tuple of (total_processed_count, list_of_processed_tickers).
    """
    downloader = RealDataDownloader(output_dir=output_dir, batch_size=batch_size)

    if not downloader.authenticate(username, password):
        return 0, []

    return downloader.download(start_date, end_date)
