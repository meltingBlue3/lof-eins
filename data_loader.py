"""
DataLoader for LOF Fund Arbitrage Backtesting System.

Reads market data, NAV, limit events, and fees from disk and provides
unified data access for backtesting.
"""

import sqlite3
from pathlib import Path
from typing import Optional, Dict

import pandas as pd
import numpy as np


class DataLoader:
    """Loads and aligns LOF fund data from multiple sources.
    
    Attributes:
        data_dir: Root directory containing mock data.
        _fees_cache: Cached fee configuration DataFrame.
    """
    
    def __init__(self, data_dir: str = './data/mock'):
        """Initialize DataLoader with data directory.
        
        Args:
            data_dir: Path to directory containing mock data.
        """
        self.data_dir = Path(data_dir)
        self._fees_cache: Optional[pd.DataFrame] = None
        
        # Validate directory structure
        required_dirs = ['market', 'nav', 'config']
        for dir_name in required_dirs:
            dir_path = self.data_dir / dir_name
            if not dir_path.exists():
                raise FileNotFoundError(f"Required directory not found: {dir_path}")
    
    def load_bundle(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Load and merge all data for a single ticker.
        
        Args:
            ticker: Fund ticker symbol (e.g., '161005').
            start_date: Optional start date filter (format: 'YYYY-MM-DD').
            end_date: Optional end date filter (format: 'YYYY-MM-DD').
            
        Returns:
            DataFrame indexed by date with columns:
            open, high, low, close, volume, nav, premium_rate, daily_limit
            Fee configuration is attached as DataFrame.attrs.
            
        Raises:
            FileNotFoundError: If market or NAV data files don't exist.
        """
        # Load market data
        market_path = self.data_dir / 'market' / f'{ticker}.parquet'
        if not market_path.exists():
            raise FileNotFoundError(f"Market data not found: {market_path}")
        df_market = pd.read_parquet(market_path)
        
        # Load NAV data
        nav_path = self.data_dir / 'nav' / f'{ticker}.parquet'
        if not nav_path.exists():
            raise FileNotFoundError(f"NAV data not found: {nav_path}")
        df_nav = pd.read_parquet(nav_path)
        
        # Set date as index for both DataFrames
        df_market = df_market.set_index('date')
        df_nav = df_nav.set_index('date')
        
        # Merge market and NAV data on date index
        df = pd.merge(
            df_market[['open', 'high', 'low', 'close', 'volume']],
            df_nav[['nav']],
            left_index=True,
            right_index=True,
            how='inner'
        )
        
        # Calculate premium rate
        df['premium_rate'] = (df['close'] - df['nav']) / df['nav']
        
        # Load and resample limit events to daily series
        daily_limits = self._resample_limits_to_daily(ticker, df.index)
        df['daily_limit'] = daily_limits
        
        # Apply forward fill to handle any NaN values
        df = df.ffill()
        
        # Apply date filtering if specified
        if start_date is not None or end_date is not None:
            df = df.loc[start_date:end_date]
        
        # Attach fee configuration as DataFrame attributes
        fees = self.load_fees(ticker)
        df.attrs.update(fees)
        
        return df
    
    def load_fees(self, ticker: str) -> Dict[str, float]:
        """Load fee configuration for a specific ticker.
        
        Args:
            ticker: Fund ticker symbol.
            
        Returns:
            Dictionary containing fee configuration:
            {
                'fee_rate_tier_1': float,
                'fee_limit_1': float,
                'fee_rate_tier_2': float,
                'fee_limit_2': float,
                'fee_fixed': float,
                'redeem_fee_7d': float
            }
            
        Raises:
            ValueError: If ticker not found in fee configuration.
        """
        # Load and cache fees CSV on first call
        if self._fees_cache is None:
            fees_path = self.data_dir / 'config' / 'fees.csv'
            if not fees_path.exists():
                raise FileNotFoundError(f"Fee configuration not found: {fees_path}")
            self._fees_cache = pd.read_csv(fees_path)
            # Convert ticker column to string for consistent comparison
            self._fees_cache['ticker'] = self._fees_cache['ticker'].astype(str)
        
        # Filter for the specific ticker
        ticker_fees = self._fees_cache[self._fees_cache['ticker'] == str(ticker)]
        
        if ticker_fees.empty:
            raise ValueError(f"Ticker '{ticker}' not found in fee configuration")
        
        # Convert to dictionary (first row only)
        fee_dict = ticker_fees.iloc[0].to_dict()
        # Remove ticker from dict as it's not a fee parameter
        fee_dict.pop('ticker', None)
        
        return fee_dict
    
    def _resample_limits_to_daily(
        self,
        ticker: str,
        date_index: pd.DatetimeIndex
    ) -> pd.Series:
        """Resample limit events to daily time series.
        
        For each date in the index:
        - If date falls within a limit event period, returns the max_amount
        - Otherwise, returns float('inf') indicating no limit
        
        Args:
            ticker: Fund ticker symbol.
            date_index: DatetimeIndex for which to generate daily limits.
            
        Returns:
            Series indexed by date with daily_limit values.
        """
        # Initialize all dates with no limit (infinity)
        daily_limits = pd.Series(
            float('inf'),
            index=date_index,
            name='daily_limit'
        )
        
        # Load limit events from SQLite
        db_path = self.data_dir / 'config' / 'fund_status.db'
        if not db_path.exists():
            # No limit events database, return all unlimited
            return daily_limits
        
        conn = sqlite3.connect(db_path)
        
        # Query limit events for this ticker
        query = """
            SELECT start_date, end_date, max_amount
            FROM limit_events
            WHERE ticker = ?
        """
        
        try:
            df_limits = pd.read_sql(query, conn, params=(ticker,))
        finally:
            conn.close()
        
        # If no limit events found, return all unlimited
        if df_limits.empty:
            return daily_limits
        
        # Convert date columns to datetime
        df_limits['start_date'] = pd.to_datetime(df_limits['start_date'])
        df_limits['end_date'] = pd.to_datetime(df_limits['end_date'])
        
        # For each limit event, set daily_limit for dates in range
        for _, event in df_limits.iterrows():
            start = event['start_date']
            end = event['end_date']
            max_amount = event['max_amount']
            
            # Create mask for dates within this limit period
            mask = (date_index >= start) & (date_index <= end)
            daily_limits.loc[mask] = max_amount
        
        return daily_limits
