"""
Main entry point for LOF mock data generation.
"""

from pathlib import Path
from typing import Optional

from .config import MockConfig
from .generators import (
    NAVGenerator,
    PriceGenerator,
    FeeConfigGenerator,
    FundStatusGenerator
)


def generate_mock_data(config: Optional[MockConfig] = None) -> None:
    """Generate complete mock dataset for LOF fund backtesting.
    
    This function orchestrates the generation of:
    - NAV data (parquet files per ticker)
    - Market data (parquet files per ticker)
    - Fee configuration (CSV file)
    - Fund status events (SQLite database)
    
    Args:
        config: MockConfig instance. If None, uses default configuration.
    """
    if config is None:
        config = MockConfig()
    
    print("=" * 70)
    print("LOF Mock Data Generator")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  Tickers: {config.tickers}")
    print(f"  Date Range: {config.start_date} to {config.end_date}")
    print(f"  Initial NAV: {config.initial_nav}")
    print(f"  Limit Trigger Threshold: {config.limit_trigger_threshold*100:.1f}%")
    print(f"  Limit Release Threshold: {config.limit_release_threshold*100:.1f}%")
    print(f"  Consecutive Days: {config.consecutive_days}")
    print("=" * 70)
    
    # Create output directories
    base_dir = Path("data/mock")
    market_dir = base_dir / "market"
    nav_dir = base_dir / "nav"
    config_dir = base_dir / "config"
    
    market_dir.mkdir(parents=True, exist_ok=True)
    nav_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize generators
    nav_gen = NAVGenerator(config)
    price_gen = PriceGenerator(config)
    fee_gen = FeeConfigGenerator(config)
    status_gen = FundStatusGenerator(config)
    
    # Generate fee configuration (once for all tickers)
    print("\n[1/4] Generating fee configuration...")
    fee_csv_path = config_dir / "fees.csv"
    fee_gen.generate(fee_csv_path)
    print(f"  [OK] Generated: {fee_csv_path}")
    
    # Initialize database for fund status
    db_path = config_dir / "fund_status.db"
    
    total_limit_events = 0
    
    # Generate data for each ticker
    print(f"\n[2/4] Generating NAV and market data for {len(config.tickers)} tickers...")
    
    for i, ticker in enumerate(config.tickers, 1):
        print(f"  [{i}/{len(config.tickers)}] Processing {ticker}...")
        
        # Generate NAV
        nav_df = nav_gen.generate(ticker)
        nav_path = nav_dir / f"{ticker}.parquet"
        nav_df.to_parquet(nav_path, index=False)
        
        # Generate market prices
        price_df = price_gen.generate(ticker, nav_df)
        
        # Save market data (without premium_rate column)
        market_df = price_df[['date', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
        market_path = market_dir / f"{ticker}.parquet"
        market_df.to_parquet(market_path, index=False)
        
        print(f"      NAV: {nav_path}")
        print(f"      Market: {market_path}")
        
        # Generate fund status events
        num_events = status_gen.generate(ticker, price_df, db_path)
        total_limit_events += num_events
        
        if num_events > 0:
            print(f"      Limit Events: {num_events}")
    
    print(f"\n[3/4] Generating fund status database...")
    print(f"  [OK] Generated: {db_path}")
    print(f"    Total limit events across all tickers: {total_limit_events}")
    
    # Generate summary statistics
    print(f"\n[4/4] Summary Statistics")
    print("=" * 70)
    _print_summary_statistics(config, market_dir, nav_dir, total_limit_events)
    
    print("=" * 70)
    print("[SUCCESS] Mock data generation completed successfully!")
    print("=" * 70)


def _print_summary_statistics(
    config: MockConfig,
    market_dir: Path,
    nav_dir: Path,
    total_limit_events: int
) -> None:
    """Print summary statistics of generated data.
    
    Args:
        config: Configuration used for generation.
        market_dir: Directory containing market data files.
        nav_dir: Directory containing NAV data files.
        total_limit_events: Total number of limit events generated.
    """
    import pandas as pd
    
    print(f"  Total Tickers: {len(config.tickers)}")
    print(f"  Total Limit Events: {total_limit_events}")
    print(f"  Average Limit Events per Ticker: {total_limit_events / len(config.tickers):.2f}")
    
    # Sample one ticker for detailed stats
    sample_ticker = config.tickers[0]
    market_df = pd.read_parquet(market_dir / f"{sample_ticker}.parquet")
    nav_df = pd.read_parquet(nav_dir / f"{sample_ticker}.parquet")
    
    # Calculate premium rate for sample ticker
    merged = market_df.merge(nav_df[['date', 'nav']], on='date')
    merged['premium_rate'] = (merged['close'] - merged['nav']) / merged['nav']
    
    print(f"\n  Sample Ticker: {sample_ticker}")
    print(f"    Trading Days: {len(market_df)}")
    print(f"    NAV Range: {nav_df['nav'].min():.4f} - {nav_df['nav'].max():.4f}")
    print(f"    Price Range: {market_df['close'].min():.2f} - {market_df['close'].max():.2f}")
    print(f"    Premium Rate Stats:")
    print(f"      Mean: {merged['premium_rate'].mean()*100:.2f}%")
    print(f"      Std Dev: {merged['premium_rate'].std()*100:.2f}%")
    print(f"      Min: {merged['premium_rate'].min()*100:.2f}%")
    print(f"      Max: {merged['premium_rate'].max()*100:.2f}%")
    print(f"      Days > {config.limit_trigger_threshold*100:.0f}%: {(merged['premium_rate'] > config.limit_trigger_threshold).sum()}")
    
    print(f"\n  File Sizes:")
    market_size = sum(f.stat().st_size for f in market_dir.glob("*.parquet"))
    nav_size = sum(f.stat().st_size for f in nav_dir.glob("*.parquet"))
    print(f"    Market Data: {market_size / 1024:.2f} KB")
    print(f"    NAV Data: {nav_size / 1024:.2f} KB")


if __name__ == "__main__":
    # Example usage with custom configuration
    custom_config = MockConfig(
        tickers=['161005', '162411', '161725', '501018', '160216'],
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_nav=1.0,
        premium_volatility=0.05,
        limit_trigger_threshold=0.15,
        limit_release_threshold=0.05,
        consecutive_days=2,
        spike_probability=0.04
    )
    
    generate_mock_data(custom_config)
