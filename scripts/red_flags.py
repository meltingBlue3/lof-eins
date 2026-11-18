#!/usr/bin/env python
"""
Scan every fund for market red flags and summarise a timeline's coverage.

扫描所有基金的市场红旗，并汇总时间线的状态覆盖情况。

A red flag is a run of >= --min-days trading days where the timeline says
purchase is open (or limited to >= --permissive-amount yuan) while the premium
stays above --min-premium and the fund traded. Such runs usually mean a missed
restriction. See docs/redesign-subscription-state.md §7.4.

Usage:
    python scripts/red_flags.py
    python scripts/red_flags.py --candidate legacy --start 2022-01-01 --out docs/eval/legacy-red-flags.md
"""

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import DataLoader  # noqa: E402
from src.evaluation.candidates import CANDIDATES, load_fund  # noqa: E402
from src.evaluation.gold import expand_daily, load_gold  # noqa: E402
from src.evaluation.red_flags import find_red_flags  # noqa: E402

STATUS_ORDER = ("open", "limited", "closed", "unknown")


def rel(path: str) -> str:
    """Show paths relative to the project root so reports carry no local user paths."""
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=str(PROJECT_ROOT / "data" / "real_all_lof"))
    p.add_argument("--candidate", default="legacy", choices=sorted(CANDIDATES))
    p.add_argument("--start", help="ignore days before this date (YYYY-MM-DD)")
    p.add_argument("--min-premium", type=float, default=0.05)
    p.add_argument("--min-days", type=int, default=3)
    p.add_argument("--permissive-amount", type=float, default=100_000)
    p.add_argument("--gold", default=str(PROJECT_ROOT / "data" / "gold" / "timeline.csv"),
                   help="gold file used to annotate flags on gold funds ('' to skip)")
    p.add_argument("--max-rows", type=int, default=60)
    p.add_argument("--out")
    args = p.parse_args()

    loader = DataLoader(args.data_dir)
    gold = load_gold(args.gold) if args.gold and Path(args.gold).exists() else None
    gold_funds = set(gold["fund_code"]) if gold is not None else set()

    flags = []
    coverage = Counter()
    coverage_by_year = defaultdict(Counter)
    funds = loader.list_available_tickers()
    for fund in funds:
        frame, tl = load_fund(loader, fund, args.candidate)
        if args.start:
            frame, tl = frame.loc[args.start:], tl.loc[args.start:]
        coverage.update(tl["status"])
        for year, grp in tl.groupby(tl.index.year):
            coverage_by_year[year].update(grp["status"])
        g = expand_daily(gold, fund, frame.index) if fund in gold_funds else None
        for run in find_red_flags(frame, tl, args.min_premium, args.min_days, args.permissive_amount):
            run["fund"] = fund
            if g is not None:
                sl = g.loc[run["start"]:run["end"], "status"]
                run["gold"] = ", ".join(f"{k} {v}" for k, v in sl.value_counts().items()) or "unlabeled"
            flags.append(run)

    flags.sort(key=lambda r: (-r["days"], -r["mean_premium"]))
    flagged_funds = {r["fund"] for r in flags}
    flagged_days = sum(r["days"] for r in flags)

    out = []
    out.append(f"# 市场红旗与覆盖率：`{args.candidate}`\n")
    out.append(f"- 生成日期：{date.today():%Y-%m-%d}；数据目录：`{rel(args.data_dir)}`"
               + (f"；起始：{args.start}" if args.start else ""))
    out.append(f"- 红旗规则：状态为开放（或限额 ≥ {args.permissive_amount:,.0f} 元），溢价率 > {args.min_premium:.0%}，"
               f"成交量 > 0，连续 ≥ {args.min_days} 个交易日\n")
    out.append("## 汇总\n")
    out.append(f"- 扫描基金：{len(funds)} 只；有红旗：{len(flagged_funds)} 只；红旗区间 {len(flags)} 段，共 {flagged_days} 个基金日")
    total = sum(coverage.values())
    out.append("- 状态覆盖（基金日）：" + "；".join(
        f"{s} {coverage.get(s, 0):,}（{100 * coverage.get(s, 0) / total:.1f}%）" for s in STATUS_ORDER if total))
    out.append("\n| 年份 | " + " | ".join(STATUS_ORDER) + " |")
    out.append("|---|" + "---:|" * len(STATUS_ORDER))
    for year in sorted(coverage_by_year):
        c = coverage_by_year[year]
        out.append(f"| {year} | " + " | ".join(f"{c.get(s, 0):,}" for s in STATUS_ORDER) + " |")

    out.append(f"\n## 红旗区间（按天数排序，前 {args.max_rows} 段）\n")
    out.append("`金标` 一列只对金标基金有值：显示该区间内金标各状态的天数。\n")
    out.append("| 基金 | 起 | 止 | 交易日 | 平均溢价 | 最高溢价 | 候选状态 | 金标 |")
    out.append("|---|---|---|---:|---:|---:|---|---|")
    for r in flags[: args.max_rows]:
        out.append(
            f"| {r['fund']} | {r['start']} | {r['end']} | {r['days']} | {r['mean_premium']:.1%} | "
            f"{r['max_premium']:.1%} | {', '.join(r['statuses'])} | {r.get('gold', '')} |"
        )
    if len(flags) > args.max_rows:
        out.append(f"\n……另有 {len(flags) - args.max_rows} 段")

    report = "\n".join(out) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
