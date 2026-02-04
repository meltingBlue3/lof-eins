"""
LOF Backtest Runner with YAML Configuration Support.

Usage:
    python run_backtest.py                          # Use default config (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # Use custom config file
"""

import argparse
import logging
from pathlib import Path
from typing import List, Union

import yaml

from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy, DataLoader


DEFAULT_CONFIG_PATH = Path("configs/backtest.yaml")
DEFAULT_DATA_DIR = "./data/mock"


def setup_logging() -> None:
    """Configure logging to file and console."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("backtest_execution.log", mode='w', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def load_runtime_config(config_path: Path) -> dict:
    """Load runtime configuration from YAML (data_dir, tickers, etc.)."""
    if not config_path.exists():
        return {}
    
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    
    return data


def resolve_tickers(
    tickers_config: Union[str, List[str], None],
    data_loader: DataLoader
) -> List[str]:
    """Resolve ticker configuration to a list of ticker codes.
    
    Args:
        tickers_config: Either "all", a list of tickers, or None.
        data_loader: DataLoader instance for auto-discovery.
        
    Returns:
        List of ticker codes to run backtest on.
    """
    # Default tickers if not specified
    default_tickers = ['161005', '162411', '161725', '501018', '160216']
    
    if tickers_config is None:
        return default_tickers
    
    # Handle "all" - auto-discover from data directory
    if isinstance(tickers_config, str) and tickers_config.lower() == 'all':
        available = data_loader.list_available_tickers()
        if not available:
            print("[WARN] No tickers found in data directory, using defaults")
            return default_tickers
        print(f"[INFO] Auto-discovered {len(available)} tickers from data directory")
        return available
    
    # Handle explicit list
    if isinstance(tickers_config, list):
        return [str(t) for t in tickers_config]
    
    # Fallback
    return default_tickers


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LOF backtest with YAML configuration.")
    parser.add_argument(
        '--config', '-c',
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to YAML config file (default: {DEFAULT_CONFIG_PATH})"
    )
    args = parser.parse_args()

    setup_logging()

    print("=" * 60)
    print("开始回测...")
    print("=" * 60)

    # Load configuration
    config_path: Path = args.config
    if config_path.exists():
        print(f"[INFO] Loading config from: {config_path}")
        config = BacktestConfig.from_yaml(config_path)
        runtime_config = load_runtime_config(config_path)
    else:
        print(f"[WARN] Config file not found: {config_path}, using defaults")
        config = BacktestConfig()
        runtime_config = {}

    # Get data directory from config
    data_dir = runtime_config.get('data_dir', DEFAULT_DATA_DIR)
    print(f"[INFO] Data directory: {data_dir}")
    
    # Initialize data loader with configured directory
    try:
        data_loader = DataLoader(data_dir=data_dir)
    except FileNotFoundError as e:
        print(f"[ERROR] Data directory error: {e}")
        print(f"[ERROR] Please ensure data exists at: {data_dir}")
        return
    
    # Resolve tickers (support "all" for auto-discovery)
    tickers_config = runtime_config.get('tickers')
    tickers = resolve_tickers(tickers_config, data_loader)

    # Print loaded configuration
    print(f"[INFO] Configuration:")
    print(f"       initial_cash: {config.initial_cash:,.2f}")
    print(f"       buy_threshold: {config.buy_threshold:.2%}")
    print(f"       liquidity_ratio: {config.liquidity_ratio:.2%}")
    print(f"       risk_mode: {config.risk_mode}")
    print(f"       tickers: {len(tickers)} funds")
    if len(tickers) <= 10:
        print(f"       ticker list: {tickers}")
    else:
        print(f"       ticker list: {tickers[:5]} ... (and {len(tickers) - 5} more)")

    # Initialize engine
    engine = BacktestEngine(
        config=config,
        strategy=SimpleLOFStrategy(),
        data_loader=data_loader
    )

    # Run backtest
    print("\n--- 多标的回测 (统一资金池 + 溢价率排序买入) ---")
    result = engine.run(tickers=tickers)
    print(result)

    # Display trade logs
    if not result.trade_logs.empty:
        print("\n--- 交易日志 (前 20 条) ---")
        print(result.trade_logs.head(20).to_string())
        
        print("\n--- 各标的交易统计 ---")
        trade_summary = result.trade_logs.groupby(['ticker', 'action']).size().unstack(fill_value=0)
        print(trade_summary)


if __name__ == "__main__":
    main()
