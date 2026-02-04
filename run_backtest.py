"""
LOF Backtest Runner with YAML Configuration Support.

Usage:
    python run_backtest.py                          # Use default config (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # Use custom config file
"""

import argparse
import logging
from pathlib import Path

import yaml

from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy, DataLoader


DEFAULT_CONFIG_PATH = Path("configs/backtest.yaml")


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


def load_tickers_from_yaml(config_path: Path) -> list[str]:
    """Load tickers list from YAML config file (outside BacktestConfig)."""
    if not config_path.exists():
        return ['161005', '162411', '161725', '501018', '160216']
    
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    
    return data.get('tickers', ['161005', '162411', '161725', '501018', '160216'])


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
        tickers = load_tickers_from_yaml(config_path)
    else:
        print(f"[WARN] Config file not found: {config_path}, using defaults")
        config = BacktestConfig()
        tickers = ['161005', '162411', '161725', '501018', '160216']

    # Print loaded configuration
    print(f"[INFO] Configuration:")
    print(f"       initial_cash: {config.initial_cash:,.2f}")
    print(f"       buy_threshold: {config.buy_threshold:.2%}")
    print(f"       liquidity_ratio: {config.liquidity_ratio:.2%}")
    print(f"       risk_mode: {config.risk_mode}")
    print(f"       tickers: {tickers}")

    # Initialize engine
    engine = BacktestEngine(
        config=config,
        strategy=SimpleLOFStrategy(),
        data_loader=DataLoader()
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
