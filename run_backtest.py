"""
LOF Backtest Runner with YAML Configuration Support.

LOF 回测运行器，支持 YAML 配置。

Usage:
    python run_backtest.py                          # Use default config (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # Use custom config file
    python run_backtest.py -s 2024-01-15 -e 2024-02-15  # Date range filter
    python run_backtest.py -o results/              # Custom output directory
    python run_backtest.py --no-export              # Console-only, skip CSV export

用法：
    python run_backtest.py                          # 使用默认配置 (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # 使用自定义配置文件
    python run_backtest.py -s 2024-01-15 -e 2024-02-15  # 日期范围筛选
    python run_backtest.py -o results/              # 自定义输出目录
    python run_backtest.py --no-export              # 仅控制台输出，跳过 CSV 导出
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd
import yaml

from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy, DataLoader
from src.engine.backtest import BacktestResult


DEFAULT_CONFIG_PATH = Path("configs/backtest.yaml")
DEFAULT_DATA_DIR = "./data/mock"
DEFAULT_OUTPUT_DIR = Path("output")


def setup_logging() -> None:
    """Configure logging to file and console.
    配置日志输出到文件和控制台。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("backtest_execution.log", mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_runtime_config(config_path: Path) -> dict:
    """Load runtime configuration from YAML (data_dir, tickers, etc.).
    从 YAML 加载运行时配置（数据目录、标的列表等）。
    """
    if not config_path.exists():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data


def resolve_tickers(
    tickers_config: Union[str, List[str], None], data_loader: DataLoader
) -> List[str]:
    """Resolve ticker configuration to a list of ticker codes.
    将标的配置解析为标的代码列表。

    Args:
        tickers_config: Either "all", a list of tickers, or None.  # "all"、标的列表或 None
        data_loader: DataLoader instance for auto-discovery.  # 用于自动发现的 DataLoader 实例

    Returns:
        List of ticker codes to run backtest on.  # 用于回测的标的代码列表
    """
    default_tickers = ["161005", "162411", "161725", "501018", "160216"]

    if tickers_config is None:
        return default_tickers

    if isinstance(tickers_config, str) and tickers_config.lower() == "all":
        available = data_loader.list_available_tickers()
        if not available:
            print("[WARN] No tickers found in data directory, using defaults")
            return default_tickers
        print(f"[INFO] Auto-discovered {len(available)} tickers from data directory")
        return available

    if isinstance(tickers_config, list):
        return [str(t) for t in tickers_config]

    return default_tickers


def export_results(
    result: BacktestResult,
    output_dir: Path,
) -> Path:
    """Export backtest results to CSV files in a timestamped subdirectory.
    将回测结果导出到带时间戳子目录的 CSV 文件中。

    Args:
        result: BacktestResult containing all data to export.  # 包含所有待导出数据的回测结果
        output_dir: Base output directory.  # 基础输出目录

    Returns:
        Path to the timestamped run directory.  # 带时间戳的运行目录路径
    """
    run_dir = output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    # Export daily performance  # 导出每日绩效数据
    if not result.daily_perf.empty:
        result.daily_perf.to_csv(run_dir / "daily_perf.csv")

    # Export trade logs  # 导出交易日志
    if not result.trade_logs.empty:
        result.trade_logs.to_csv(run_dir / "trade_logs.csv", index=False)

    # Export daily snapshots  # 导出每日快照
    if not result.daily_snapshots.empty:
        result.daily_snapshots.to_csv(run_dir / "daily_snapshots.csv", index=False)

    # Export summary text  # 导出摘要文本
    with open(run_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write(str(result))

    return run_dir


def print_ticker_summary(trade_logs: pd.DataFrame) -> None:
    """Print per-ticker performance summary from trade logs.
    打印各标的的绩效汇总。

    Shows buy/sell counts, total invested, total returned, and PnL per ticker.
    显示买入/卖出次数、总投资、总回报和各标的盈亏。
    """
    if trade_logs.empty:
        return

    print("\n--- 各标的交易统计 ---")

    tickers = sorted(trade_logs["ticker"].unique())

    rows = []
    for ticker in tickers:
        t = trade_logs[trade_logs["ticker"] == ticker]
        buys = t[t["action"] == "buy"]
        sells = t[t["action"] == "sell"]
        total_invested = buys["amount"].sum() if not buys.empty else 0.0
        total_fees = buys["fee"].sum() if not buys.empty else 0.0
        total_returned = sells["net_amount"].sum() if not sells.empty else 0.0
        sell_fees = sells["fee"].sum() if not sells.empty else 0.0
        pnl = total_returned - total_invested
        rows.append(
            {
                "ticker": ticker,
                "buys": len(buys),
                "sells": len(sells),
                "invested": total_invested,
                "buy_fees": total_fees,
                "returned": total_returned,
                "sell_fees": sell_fees,
                "PnL": pnl,
            }
        )

    summary_df = pd.DataFrame(rows)
    # Format for display  # 格式化显示
    fmt = summary_df.copy()
    for col in ["invested", "buy_fees", "returned", "sell_fees", "PnL"]:
        fmt[col] = fmt[col].map(lambda x: f"{x:,.2f}")
    print(fmt.to_string(index=False))

    # Grand total  # 总计
    total_pnl = sum(r["PnL"] for r in rows)
    total_invested = sum(r["invested"] for r in rows)
    total_returned = sum(r["returned"] for r in rows)
    print(f"\n  Total invested: {total_invested:>14,.2f} CNY")
    print(f"  Total returned: {total_returned:>14,.2f} CNY")
    print(f"  Total PnL:      {total_pnl:>14,.2f} CNY")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run LOF backtest with YAML configuration."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to YAML config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for CSV export (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--start-date",
        "-s",
        type=str,
        default=None,
        help="Start date filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date", "-e", type=str, default=None, help="End date filter (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        default=False,
        help="Skip CSV export (console-only mode)",
    )
    args = parser.parse_args()

    setup_logging()

    print("=" * 60)
    print("开始回测...")
    print("=" * 60)

    # Load configuration  # 加载配置
    config_path: Path = args.config
    if config_path.exists():
        print(f"[INFO] Loading config from: {config_path}")
        config = BacktestConfig.from_yaml(config_path)
        runtime_config = load_runtime_config(config_path)
    else:
        print(f"[WARN] Config file not found: {config_path}, using defaults")
        config = BacktestConfig()
        runtime_config = {}

    # Get data directory from config  # 从配置获取数据目录
    data_dir = runtime_config.get("data_dir", DEFAULT_DATA_DIR)
    print(f"[INFO] Data directory: {data_dir}")

    # Initialize data loader with configured directory  # 使用配置的目录初始化数据加载器
    try:
        data_loader = DataLoader(data_dir=data_dir)
    except FileNotFoundError as e:
        print(f"[ERROR] Data directory error: {e}")
        print(f"[ERROR] Please ensure data exists at: {data_dir}")
        return

    # Resolve tickers (support "all" for auto-discovery)  # 解析标的（支持 "all" 自动发现）
    tickers_config = runtime_config.get("tickers")
    tickers = resolve_tickers(tickers_config, data_loader)

    # Resolve date range: CLI args override config  # 解析日期范围：CLI 参数覆盖配置
    start_date: Optional[str] = args.start_date
    end_date: Optional[str] = args.end_date

    # Print loaded configuration  # 打印已加载的配置
    print(f"[INFO] Configuration:")
    print(f"       initial_cash:    {config.initial_cash:,.2f}")
    print(f"       buy_threshold:   {config.buy_threshold:.2%}")
    print(f"       liquidity_ratio: {config.liquidity_ratio:.2%}")
    print(f"       risk_mode:       {config.risk_mode}")
    print(f"       tickers:         {len(tickers)} funds")
    if len(tickers) <= 10:
        print(f"       ticker list:     {tickers}")
    else:
        print(
            f"       ticker list:     {tickers[:5]} ... (and {len(tickers) - 5} more)"
        )
    if start_date or end_date:
        print(f"       date range:      {start_date or '...'} ~ {end_date or '...'}")

    # Initialize engine  # 初始化引擎
    engine = BacktestEngine(
        config=config, strategy=SimpleLOFStrategy(), data_loader=data_loader
    )

    # Run backtest  # 运行回测
    print("\n--- 多标的回测 (统一资金池 + 溢价率排序买入) ---")
    result = engine.run(tickers=tickers, start_date=start_date, end_date=end_date)
    print(result)

    # Display date range from actual data  # 显示实际数据的日期范围
    if not result.daily_perf.empty:
        first_date = result.daily_perf.index[0]
        last_date = result.daily_perf.index[-1]
        n_days = len(result.daily_perf)
        print(
            f"[INFO] 数据日期范围: {first_date.date()} ~ {last_date.date()} ({n_days} 个交易日)"
        )

    # Display trade logs  # 显示交易日志
    if not result.trade_logs.empty:
        n_trades = len(result.trade_logs)
        print(f"\n--- 交易日志 (共 {n_trades} 条) ---")
        # Show all trades with key columns for readability  # 显示所有交易的关键列以提高可读性
        display_cols = [
            "date",
            "action",
            "ticker",
            "premium_rate",
            "shares",
            "price",
            "amount",
            "fee",
            "net_amount",
            "cash_after",
        ]
        # Only include columns that exist  # 仅包含存在的列
        display_cols = [c for c in display_cols if c in result.trade_logs.columns]
        df_display = result.trade_logs[display_cols].copy()
        # Format premium_rate as percentage for display  # 将溢价率格式化为百分比显示
        if "premium_rate" in df_display.columns:
            df_display["premium_rate"] = df_display["premium_rate"].map(
                lambda x: f"{x:.2%}" if pd.notna(x) else ""
            )
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", 200)
        pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
        print(df_display.to_string(index=False))
        pd.reset_option("display.max_rows")
        pd.reset_option("display.width")
        pd.reset_option("display.float_format")

        # Per-ticker summary  # 各标的汇总
        print_ticker_summary(result.trade_logs)

    # Export results to CSV  # 将结果导出为 CSV
    if not args.no_export:
        run_dir = export_results(result, args.output_dir)
        print(f"\n[INFO] 结果已导出至: {run_dir.resolve()}")
    else:
        print("\n[INFO] CSV 导出已跳过 (--no-export)")


if __name__ == "__main__":
    main()
