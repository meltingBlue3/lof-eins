"""
LOF Backtest Runner with YAML Configuration Support.

LOF 回测运行器，支持 YAML 配置。

Usage:
    python run_backtest.py                          # Use default config (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # Use custom config file
    python run_backtest.py -s 2024-01-15 -e 2024-02-15  # Date range filter
    python run_backtest.py -o results/              # Custom output directory
    python run_backtest.py --no-export              # Console-only, skip CSV export
    python run_backtest.py --bounds                 # Conservative and optimistic bounds (redesign §8.2)

用法：
    python run_backtest.py                          # 使用默认配置 (configs/backtest.yaml)
    python run_backtest.py --config my_config.yaml  # 使用自定义配置文件
    python run_backtest.py -s 2024-01-15 -e 2024-02-15  # 日期范围筛选
    python run_backtest.py -o results/              # 自定义输出目录
    python run_backtest.py --no-export              # 仅控制台输出，跳过 CSV 导出
    python run_backtest.py --bounds                 # 同时跑保守和乐观两个边界（重构方案 §8.2）
    python run_backtest.py --unknown-policy open --n-accounts 2
    python run_backtest.py --sensitivity            # Phase F ladder: fees, sell days, decision premium (§8.4)

With --bounds the run starts at the first announcement in the status database unless -s
is given: before that date every day is unknown, so both bounds would only measure the gap.
--bounds 时，除非指定 -s，回测从状态库里的第一份公告开始。

--sensitivity runs both bounds for each step of the phase F ladder (redesign §8.4): the
phase E assumptions, then each fund's own fees, its own sell day, and a decision premium on
the NAV visible at the cut-off; then a fee discount and higher buy thresholds.
--sensitivity 依次叠加阶段 F 的各项修正，每一步都跑两个边界。
"""

import argparse
import dataclasses
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import yaml

from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy, DataLoader
from src.engine.backtest import BacktestResult
from src.evaluation.attribution import fee_band, pnl_by, trips_with_status
from src.evaluation.red_flags import find_red_flags


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
    parser.add_argument("--unknown-policy", choices=["closed", "open"], help="override unknown_policy")
    parser.add_argument("--n-accounts", type=int, help="override n_accounts")
    parser.add_argument("--bounds", action="store_true",
                        help="run unknown_policy=closed and =open, and write a bounds report")
    parser.add_argument("--terms", choices=["auto", "fund", "default"], default="auto",
                        help="trading terms source (default: fund_terms.csv when built, else the old defaults)")
    parser.add_argument("--premium-basis", choices=["published", "same_day"], help="override premium_basis")
    parser.add_argument("--fees", choices=["fund", "default"], help="override fees")
    parser.add_argument("--settlement", choices=["fund", "t2"], help="override settlement")
    parser.add_argument("--fee-discount", type=float, help="override fee_discount")
    parser.add_argument("--sensitivity", action="store_true",
                        help="phase F ladder: both bounds for each correction, and a report")
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

    overrides = {k: v for k, v in (("unknown_policy", args.unknown_policy), ("n_accounts", args.n_accounts),
                                   ("premium_basis", args.premium_basis), ("fees", args.fees),
                                   ("settlement", args.settlement), ("fee_discount", args.fee_discount))
                 if v is not None}
    if overrides:
        config = dataclasses.replace(config, **overrides)

    # Initialize data loader with configured directory  # 使用配置的目录初始化数据加载器
    try:
        data_loader = DataLoader(data_dir=data_dir, terms=args.terms)
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

    if args.sensitivity:
        run_sensitivity(config, data_loader, tickers, start_date, end_date, args)
        return
    if args.bounds:
        run_bounds(config, data_loader, tickers, start_date, end_date, args)
        return

    # Print loaded configuration  # 打印已加载的配置
    print(f"[INFO] Configuration:")
    print(f"       initial_cash:    {config.initial_cash:,.2f}")
    print(f"       buy_threshold:   {config.buy_threshold:.2%}")
    print(f"       liquidity_ratio: {config.liquidity_ratio:.2%}")
    print(f"       risk_mode:       {config.risk_mode}")
    print(f"       status:          {'daily_status' if data_loader.has_status else 'none (all unknown)'} "
          f"(unknown_policy={config.unknown_policy}, "
          f"n_accounts={config.n_accounts})")
    print(f"       terms:           {data_loader.terms_mode} ({terms_line(config)})")
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


def corpus_start(data_loader: DataLoader) -> Optional[str]:
    """First announcement date in the status database: where daily_status stops being all unknown."""
    if not data_loader.has_status:
        return None
    conn = sqlite3.connect(f"file:{data_loader.status_db.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT MIN(announce_date) FROM announcements").fetchone()[0]
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def red_flag_days(data_loader: DataLoader, tickers: List[str]) -> set:
    """(ticker, day) pairs inside a red-flag run of the status data (redesign §7.4); policy-free."""
    days = set()
    for t in tickers:
        frame = data_loader.load_bundle(t).df
        tl = pd.DataFrame({"status": frame["sub_status"],
                           "amount": frame["daily_limit"].where(frame["sub_status"] == "limited")})
        for run in find_red_flags(frame, tl):
            days.update((t, d) for d in frame.loc[run["start"]:run["end"]].index)
    return days


BOUND_NAMES = {"closed": "保守（unknown_policy=closed）", "open": "乐观（unknown_policy=open）"}


def terms_line(cfg: BacktestConfig) -> str:
    """The phase F settings of a config, in words."""
    premium = {"published": "决策时可见的最新净值（T-1，境外 T-2）", "same_day": "T 日净值（前视）"}[cfg.premium_basis]
    fees = {"fund": "各基金自己的费率表（外扣法）", "default": "统一 1.5%"}[cfg.fees]
    sell = {"fund": "各基金自己的可卖日（QDII T+3）", "t2": "统一 T+2"}[cfg.settlement]
    discount = f"，申购费打 {cfg.fee_discount:.0%}" if cfg.fee_discount != 1 else ""
    return f"决策溢价用{premium}；申购费{fees}{discount}；卖出{sell}"


def bounds_report(results: Dict[str, BacktestResult], window: str, data_loader: DataLoader,
                  tickers: List[str]) -> str:
    """Markdown: both bounds side by side, PnL by buy-day status source, and the red-flag share."""
    trips = {k: trips_with_status(r.trade_logs) if not r.trade_logs.empty else pd.DataFrame()
             for k, r in results.items()}
    cfg = next(iter(results.values())).config
    out = [
        "# 回测双边界报告\n",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}；对应重构方案 §8.2",
        f"- 申购状态来源：`daily_status`；区间：{window}；基金：{len(tickers)} 只",
        f"- 参数：初始资金 {cfg.initial_cash:,.0f}，买入阈值 {cfg.buy_threshold:.2%}，流动性比例 {cfg.liquidity_ratio:.0%}，"
        f"账户数 {cfg.n_accounts}；单笔申购上限 100,000 元（引擎内置）",
        f"- 交易条款：{terms_line(cfg)}（条款来源 `{data_loader.terms_mode}`）",
        "- 保守边界只在有直接证据（change / restatement / overlay）证明可以申购的日子买入；unknown、金额不明的限额，"
        "以及只是推断出来的开放或限额（inferred_open、inferred_prior），一律当作不能申购。"
        "乐观边界把 unknown 和金额不明的限额当作不限购，推断出来的状态照用。\n",
        "## 结果\n",
        "| 指标 | " + " | ".join(BOUND_NAMES[k] for k in results) + " |",
        "|---|" + "---:|" * len(results),
    ]
    metrics = [("总收益率", lambda r: f"{r.total_return:.2%}"), ("年化收益率", lambda r: f"{r.annualized_return:.2%}"),
               ("最大回撤", lambda r: f"{r.max_drawdown:.2%}"), ("夏普比率", lambda r: f"{r.sharpe_ratio:.2f}"),
               ("买入笔数", lambda r: f"{r.num_buy_trades}")]
    for label, fn in metrics:
        out.append(f"| {label} | " + " | ".join(fn(r) for r in results.values()) + " |")
    out.append("| 往返盈亏合计（元） | " + " | ".join(
        f"{t['pnl'].sum():,.0f}" if len(t) else "0" for t in trips.values()) + " |")

    traded = sorted({x for t in trips.values() if len(t) for x in t["ticker"]})
    flagged = red_flag_days(data_loader, traded)
    out += ["\n## 按买入日的状态来源归因\n", "盈亏是绝对金额，受资金复利路径影响，只用来看方向和占比。\n"]
    for k, t in trips.items():
        out.append(f"### {BOUND_NAMES[k]}\n")
        if t.empty:
            out.append("没有成交。\n")
            continue
        total = t["pnl"].sum()
        out += ["| 状态来源 | 往返笔数 | 投入（元） | 盈亏（元） | 占比 |", "|---|---:|---:|---:|---:|"]
        for _, r in pnl_by(t, "status_source").iterrows():
            share = f"{r['pnl'] / total:.1%}" if total else "–"
            out.append(f"| {r['status_source']} | {r['trips']} | {r['invested']:,.0f} | {r['pnl']:,.0f} | {share} |")
        in_flag = t[[(a, pd.Timestamp(b)) in flagged for a, b in zip(t["ticker"], t["buy_date"])]]
        share = f"（占合计 {in_flag['pnl'].sum() / total:.1%}）" if total else ""
        out.append(f"\n买入日落在红旗区间内的往返 {len(in_flag)} 笔，盈亏 {in_flag['pnl'].sum():,.0f} 元{share}。")
        top = t.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        out.append("\n盈利最多的基金：" + "，".join(f"{i} {v:,.0f}" for i, v in top.head(8).items()) + "。\n")
    return "\n".join(out) + "\n"


def run_pair(config: BacktestConfig, data_loader: DataLoader, tickers: List[str], start: Optional[str],
             end_date: Optional[str]) -> Dict[str, BacktestResult]:
    """The same config under unknown_policy=closed and =open."""
    results: Dict[str, BacktestResult] = {}
    for policy in ("closed", "open"):
        cfg = dataclasses.replace(config, unknown_policy=policy)
        print(f"\n--- unknown_policy={policy} ---")
        engine = BacktestEngine(config=cfg, strategy=SimpleLOFStrategy(), data_loader=data_loader)
        results[policy] = engine.run(tickers=tickers, start_date=start, end_date=end_date)
        print(results[policy])
    return results


def export_pair(results: Dict[str, BacktestResult], run_dir: Path) -> None:
    for policy, r in results.items():
        sub = run_dir / policy
        sub.mkdir(parents=True, exist_ok=True)
        if not r.daily_perf.empty:
            r.daily_perf.to_csv(sub / "daily_perf.csv")
        if not r.trade_logs.empty:
            r.trade_logs.to_csv(sub / "trade_logs.csv", index=False)
        (sub / "summary.txt").write_text(str(r), encoding="utf-8")


def bounds_start(data_loader: DataLoader, start_date: Optional[str]) -> Optional[str]:
    start = start_date or corpus_start(data_loader)
    if start and not start_date:
        print(f"[INFO] starting at the first announcement in the status database, {start}")
    return start


def window_of(results: Dict[str, BacktestResult]) -> str:
    perf = results["closed"].daily_perf
    return f"{perf.index[0].date()} ~ {perf.index[-1].date()}" if not perf.empty else "–"


def run_bounds(config: BacktestConfig, data_loader: DataLoader, tickers: List[str], start_date: Optional[str],
               end_date: Optional[str], args) -> Dict[str, BacktestResult]:
    """Run the conservative and optimistic bounds; export both results and the report."""
    results = run_pair(config, data_loader, tickers, bounds_start(data_loader, start_date), end_date)
    report = bounds_report(results, window_of(results), data_loader, tickers)
    print(report)
    if not args.no_export:
        run_dir = args.output_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_bounds")
        export_pair(results, run_dir)
        (run_dir / "bounds_report.md").write_text(report, encoding="utf-8")
        print(f"\n[INFO] 结果已导出至: {run_dir.resolve()}")
    return results


def sensitivity_steps(config: BacktestConfig) -> List[tuple]:
    """(key, label, config): the phase F ladder, then variations of its last step."""
    base = dataclasses.replace(config, fees="default", settlement="t2", premium_basis="same_day", fee_discount=1.0)
    fees = dataclasses.replace(base, fees="fund")
    sell = dataclasses.replace(fees, settlement="fund")
    final = dataclasses.replace(sell, premium_basis="published")
    steps = [("e_baseline", "阶段 E 的假设（统一 1.5%、统一 T+2、T 日净值）", base),
             ("fund_fees", "＋各基金自己的申购费率", fees),
             ("fund_sell_days", "＋各基金自己的可卖日", sell),
             ("published_nav", "＋决策溢价改用可见净值（阶段 F 结果）", final),
             ("discount_10pct", "阶段 F 结果，申购费打 1 折", dataclasses.replace(final, fee_discount=0.1))]
    for th in (0.025, 0.04):
        steps.append((f"threshold_{th * 1000:.0f}", f"阶段 F 结果，买入阈值 {th:.1%}",
                      dataclasses.replace(final, buy_threshold=th)))
    return steps


def signal_overlap(data_loader: DataLoader, tickers: List[str], start: Optional[str], end: Optional[str],
                   threshold: float) -> Dict[str, int]:
    """Fund-days above the threshold on the same-day premium, on the published one, and on both."""
    same = published = both = days = 0
    for t in tickers:
        df = data_loader.load_bundle(t, start, end).df
        a, b = df["premium_rate"] > threshold, df["premium_published"] > threshold
        same, published, both, days = same + a.sum(), published + b.sum(), both + (a & b).sum(), days + len(df)
    return {"days": int(days), "same_day": int(same), "published": int(published), "both": int(both)}


def sensitivity_report(runs: List[tuple], window: str, data_loader: DataLoader, tickers: List[str],
                       overlap: Dict[str, int], final: Dict[str, BacktestResult]) -> str:
    cfg = runs[0][2]
    out = ["# 阶段 F：时序与成本的敏感性\n",
           f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}；对应重构方案 §8.4",
           f"- 申购状态来源：`daily_status`；交易条款来源：`{data_loader.terms_mode}`；区间：{window}；"
           f"基金：{len(tickers)} 只",
           f"- 参数：初始资金 {cfg.initial_cash:,.0f}，买入阈值 {cfg.buy_threshold:.2%}（另有说明的除外），"
           f"流动性比例 {cfg.liquidity_ratio:.0%}，账户数 {cfg.n_accounts}；单笔申购上限 100,000 元",
           "- 前四步每一步在上一步的基础上只改一项；后面几行在阶段 F 结果上只改一项。两个边界各跑一次。",
           "- 资金只有 1 万元，买入按溢价贪婪分配，所以总收益受复利路径影响很大：一项改动让某几笔交易做成或做不成，"
           "就能让总收益大幅变化。\"往返收益率\"是全部往返盈亏除以全部投入，不经过复利，更适合比较各步骤；"
           "\"前 10 笔占比\"是盈利最多的 10 笔往返占全部往返盈亏的比例，越高说明结果越依赖少数交易。"
           "\"剔除红旗\"去掉买入日落在红旗区间内的往返（§7.4：可能漏了限购，也可能只是流动性差）。\n",
           "## 逐步叠加\n"]
    flagged = red_flag_days(data_loader, tickers)
    for k in ("closed", "open"):
        out += [f"### {BOUND_NAMES[k]}\n",
                "| 步骤 | 总收益 | 年化 | 最大回撤 | 买入笔数 | 往返收益率 | 剔除红旗后 | 胜率 | 前 10 笔占比 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for _, label, _, res in runs:
            r = res[k]
            t = trips_with_status(r.trade_logs) if not r.trade_logs.empty else pd.DataFrame()
            if t.empty:
                trip_cells = ["–"] * 4
            else:
                total = t["pnl"].sum()
                top = t["pnl"].nlargest(10).sum()
                clean = t[[(a, pd.Timestamp(b)) not in flagged for a, b in zip(t["ticker"], t["buy_date"])]]
                trip_cells = [f"{total / t['invested'].sum():.3%}",
                              f"{clean['pnl'].sum() / clean['invested'].sum():.3%}" if len(clean) else "–",
                              f"{(t['pnl'] > 0).mean():.1%}",
                              f"{top / total:.0%}" if total > 0 else "–（合计亏损）"]
            out.append(f"| {label} | {r.total_return:.2%} | {r.annualized_return:.2%} | {r.max_drawdown:.2%} | "
                       f"{r.num_buy_trades} | " + " | ".join(trip_cells) + " |")
        out.append("")
    out += ["\n## 前视偏差：信号有多少是看了 T 日净值才有的\n",
            f"买入阈值 {cfg.buy_threshold:.2%}，区间内全部 {overlap['days']:,} 个基金日（不论申购状态）：\n",
            "| 口径 | 超过阈值的基金日 |", "|---|---:|",
            f"| T 日净值（前视） | {overlap['same_day']:,} |",
            f"| 决策时可见的净值 | {overlap['published']:,} |",
            f"| 两者都超过 | {overlap['both']:,} |"]
    if overlap["same_day"]:
        out.append(f"\n用 T 日净值算出的信号日里，只有 {overlap['both'] / overlap['same_day']:.1%} "
                   "在决策时就能看到。")
    out.append("\n## 阶段 F 结果按申购费率和可卖日分组\n")
    out.append("费率是基金自己的名义费率；0% 的都是 C 类份额。\n")
    for k, r in final.items():
        out.append(f"### {BOUND_NAMES[k]}\n")
        t = trips_with_status(r.trade_logs) if not r.trade_logs.empty else pd.DataFrame()
        if t.empty:
            out.append("没有成交。\n")
            continue
        t["fee_band"] = fee_band(t)
        t["sell_day"] = "T+" + t["sell_days"].astype(int).astype(str)
        for col, title in (("fee_band", "申购费率"), ("sell_day", "可卖日")):
            out += [f"| {title} | 往返笔数 | 投入（元） | 盈亏（元） |", "|---|---:|---:|---:|"]
            for _, row in pnl_by(t, col).iterrows():
                out.append(f"| {row[col]} | {row['trips']} | {row['invested']:,.0f} | {row['pnl']:,.0f} |")
            out.append("")
    out += ["\n## 阶段 F 结果的归因\n",
            bounds_report(final, window, data_loader, tickers).split("\n## 结果\n", 1)[1]]
    return "\n".join(out) + "\n"


def run_sensitivity(config: BacktestConfig, data_loader: DataLoader, tickers: List[str], start_date: Optional[str],
                    end_date: Optional[str], args) -> None:
    """Both bounds for every step of the phase F ladder; export each step and write the report."""
    start = bounds_start(data_loader, start_date)
    run_dir = args.output_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_sensitivity")
    runs = []
    for key, label, cfg in sensitivity_steps(config):
        print(f"\n=== {label} ===")
        res = run_pair(cfg, data_loader, tickers, start, end_date)
        runs.append((key, label, cfg, res))
        if not args.no_export:
            export_pair(res, run_dir / key)
    final = next(res for key, _, _, res in runs if key == "published_nav")
    overlap = signal_overlap(data_loader, tickers, start, end_date, config.buy_threshold)
    report = sensitivity_report(runs, window_of(final), data_loader, tickers, overlap, final)
    print(report)
    if not args.no_export:
        (run_dir / "sensitivity_report.md").write_text(report, encoding="utf-8")
        print(f"\n[INFO] 结果已导出至: {run_dir.resolve()}")


if __name__ == "__main__":
    main()
