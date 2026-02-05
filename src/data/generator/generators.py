"""
Core data generation logic for LOF mock data.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .config import MockConfig


class NAVGenerator:
    """Generates Net Asset Value (NAV) data using geometric Brownian motion."""

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str) -> pd.DataFrame:
        """Generate NAV time series for a given ticker.

        Args:
            ticker: Fund ticker symbol.

        Returns:
            DataFrame with columns: date, ticker, nav
        """
        dates = pd.bdate_range(
            start=self.config.start_date,
            end=self.config.end_date,
            freq="B",  # Business days only
        )

        n_days = len(dates)

        # Geometric Brownian Motion for NAV
        # dS = μ*S*dt + σ*S*dW
        np.random.seed(hash(ticker) % (2**32))  # Reproducible per ticker

        returns = np.random.normal(
            self.config.nav_drift, self.config.nav_volatility, n_days
        )

        nav_series = self.config.initial_nav * np.exp(np.cumsum(returns))

        df = pd.DataFrame({"date": dates, "ticker": ticker, "nav": nav_series})

        return df


class PriceGenerator:
    """Generates market price data (OHLCV) with premium rate spikes."""

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str, nav_df: pd.DataFrame) -> pd.DataFrame:
        """Generate market price data based on NAV with premium rates.

        Args:
            ticker: Fund ticker symbol.
            nav_df: DataFrame with NAV data.

        Returns:
            DataFrame with columns: date, ticker, open, high, low, close, volume
        """
        np.random.seed(hash(ticker + "_price") % (2**32))

        n_days = len(nav_df)
        premium_rates = np.zeros(n_days)

        # Generate premium rates with spike mechanism
        in_spike = False
        spike_decay = 0.0

        for i in range(n_days):
            if not in_spike:
                # Check for spike event
                if np.random.random() < self.config.spike_probability:
                    # Trigger premium spike
                    premium_rates[i] = np.random.uniform(0.10, 0.25)
                    in_spike = True
                    spike_decay = premium_rates[i]
                else:
                    # Normal premium fluctuation
                    premium_rates[i] = np.random.normal(
                        0.0, self.config.premium_volatility
                    )
            else:
                # Mean reversion after spike
                spike_decay *= np.random.uniform(0.85, 0.95)  # Decay factor
                noise = np.random.normal(0.0, self.config.premium_volatility * 0.5)
                premium_rates[i] = spike_decay + noise

                # Exit spike mode when premium drops low enough
                if premium_rates[i] < self.config.limit_release_threshold * 1.5:
                    in_spike = False

        # Calculate close prices based on NAV and premium
        close_prices = nav_df["nav"].values * (1 + premium_rates)

        # Generate OHLC based on close
        intraday_volatility = 0.01  # 1% intraday volatility

        open_prices = close_prices * (
            1 + np.random.normal(0, intraday_volatility, n_days)
        )
        high_prices = np.maximum(open_prices, close_prices) * (
            1 + np.abs(np.random.normal(0, intraday_volatility * 0.5, n_days))
        )
        low_prices = np.minimum(open_prices, close_prices) * (
            1 - np.abs(np.random.normal(0, intraday_volatility * 0.5, n_days))
        )

        # Generate volume (correlated with premium rate)
        # Higher premium -> higher volume
        base_volume = 1_000_000  # Base volume in shares
        volume_multiplier = (
            1 + np.abs(premium_rates) * 5
        )  # 5x volume increase at high premium
        volumes = np.random.lognormal(
            np.log(base_volume) + np.log(volume_multiplier), 0.5, n_days
        ).astype(int)

        df = pd.DataFrame(
            {
                "date": nav_df["date"],
                "ticker": ticker,
                "open": open_prices,
                "high": high_prices,
                "low": low_prices,
                "close": close_prices,
                "volume": volumes,
                "premium_rate": premium_rates,  # Keep for limit event generation
            }
        )

        return df


class FeeConfigGenerator:
    """Generates fee configuration CSV with tiered fee structure."""

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, output_path: Path) -> None:
        """Generate fee configuration CSV file.

        Args:
            output_path: Path to save fees.csv
        """
        fee_data = []

        for ticker in self.config.tickers:
            # Tiered fee structure (common for public funds in China)
            # Tier 1: < 500k CNY -> 1.5% fee rate
            # Tier 2: 500k - 2M CNY -> 1.0% fee rate
            # Tier 3: >= 2M CNY -> 1000 CNY fixed fee
            # Redemption fee (< 7 days): 1.5%

            fee_data.append(
                {
                    "ticker": ticker,
                    "fee_rate_tier_1": 0.015,  # 1.5%
                    "fee_limit_1": 500_000.0,  # 50万
                    "fee_rate_tier_2": 0.010,  # 1.0%
                    "fee_limit_2": 2_000_000.0,  # 200万
                    "fee_fixed": 1000.0,  # 固定1000元
                    "redeem_fee_7d": 0.015,  # 7天内赎回1.5%
                }
            )

        df = pd.DataFrame(fee_data)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")


class FundStatusGenerator:
    """Generates fund status events (purchase limits) based on premium rates."""

    def __init__(self, config: MockConfig):
        self.config = config

    def generate(self, ticker: str, price_df: pd.DataFrame, output_db: Path) -> int:
        """Generate fund status events and store in SQLite database.

        Args:
            ticker: Fund ticker symbol.
            price_df: DataFrame with price data including premium_rate column.
            output_db: Path to SQLite database file.

        Returns:
            Number of limit events generated for this ticker.
        """
        # Identify limit events based on premium rate
        limit_events = self._identify_limit_events(ticker, price_df)

        # Store in database
        conn = sqlite3.connect(output_db)
        cursor = conn.cursor()

        # Create table if not exists
        # Note: end_date is nullable to support open-ended limits (limits without known end date)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS limit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,  -- NULL indicates open-ended limit
                max_amount REAL DEFAULT 100.0,
                reason TEXT
            )
        """)

        # Create announcement_parses table for LLM extraction results
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

        # Create indexes for announcement_parses
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_ticker
            ON announcement_parses(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_announcement_parses_processed
            ON announcement_parses(processed)
        """)

        # Create limit_event_log table for audit trail of timeline changes
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

        # Create indexes for limit_event_log
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_ticker
            ON limit_event_log(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_limit_event_log_created_at
            ON limit_event_log(created_at)
        """)

        # Insert limit events
        for event in limit_events:
            cursor.execute(
                """
                INSERT INTO limit_events (ticker, start_date, end_date, max_amount, reason)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    event["ticker"],
                    event["start_date"],
                    event["end_date"],
                    event["max_amount"],
                    event["reason"],
                ),
            )

        conn.commit()
        conn.close()

        return len(limit_events)

    def _identify_limit_events(self, ticker: str, price_df: pd.DataFrame) -> List[Dict]:
        """Identify periods when purchase limits should be triggered.

        Logic:
        - If premium_rate > threshold for consecutive_days, trigger limit on T+1
        - Limit remains active until premium_rate < release_threshold
        - During limit: max_amount = limit_max_amount (very low)
        - During normal: max_amount = normal_max_amount (high or unlimited)

        Args:
            ticker: Fund ticker symbol.
            price_df: DataFrame with premium_rate data.

        Returns:
            List of limit event dictionaries.
        """
        events = []

        premium_rates = price_df["premium_rate"].values
        dates = price_df["date"].values

        in_limit = False
        high_premium_days = 0
        limit_start = None

        for i, (date, premium) in enumerate(zip(dates, premium_rates)):
            if not in_limit:
                # Check if premium exceeds trigger threshold
                if premium > self.config.limit_trigger_threshold:
                    high_premium_days += 1

                    # Trigger limit if consecutive days reached
                    if high_premium_days >= self.config.consecutive_days:
                        in_limit = True
                        # Limit starts on next trading day
                        if i + 1 < len(dates):
                            limit_start = pd.Timestamp(dates[i + 1]).strftime(
                                "%Y-%m-%d"
                            )
                        else:
                            limit_start = pd.Timestamp(date).strftime("%Y-%m-%d")
                        high_premium_days = 0
                else:
                    high_premium_days = 0
            else:
                # Check if premium falls below release threshold
                if premium < self.config.limit_release_threshold:
                    # End limit period
                    limit_end = pd.Timestamp(date).strftime("%Y-%m-%d")

                    events.append(
                        {
                            "ticker": ticker,
                            "start_date": limit_start,
                            "end_date": limit_end,
                            "max_amount": self.config.limit_max_amount,
                            "reason": f"High premium (>{self.config.limit_trigger_threshold * 100:.0f}%) for {self.config.consecutive_days} consecutive days",
                        }
                    )

                    in_limit = False
                    limit_start = None

        # Handle case where limit extends to end of data
        if in_limit and limit_start:
            events.append(
                {
                    "ticker": ticker,
                    "start_date": limit_start,
                    "end_date": pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
                    "max_amount": self.config.limit_max_amount,
                    "reason": f"High premium (>{self.config.limit_trigger_threshold * 100:.0f}%) for {self.config.consecutive_days} consecutive days",
                }
            )

        return events
