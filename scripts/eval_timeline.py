#!/usr/bin/env python
"""
Score a subscription-state timeline against the gold set.

对照金标集给限购时间线打分。

Usage:
    python scripts/eval_timeline.py
    python scripts/eval_timeline.py --candidate legacy --out docs/eval/legacy-baseline.md \
        --trades output/20260413_154550/trade_logs.csv
    python scripts/eval_timeline.py --min-confidence high

Output: a Markdown report (stdout, and --out if given) with per-fund day counts
per category (agree / too_permissive / too_strict / cand_unknown), the same on
arbitrage-relevant days (premium above --threshold), the mismatch runs, and --
with --trades -- the backtest PnL of round trips bought on each category of day.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.data.loader import DataLoader  # noqa: E402
from src.evaluation.attribution import round_trips  # noqa: E402
from src.evaluation.candidates import CANDIDATES, load_fund  # noqa: E402
from src.evaluation.compare import (  # noqa: E402
    AGREE,
    CAND_UNKNOWN,
    CATEGORIES,
    TOO_PERMISSIVE,
    TOO_STRICT,
    classify,
    mismatch_kinds,
    summarize,
)
from src.evaluation.gold import CONFIDENCES, expand_daily, load_gold  # noqa: E402


def fmt_state(status, amount) -> str:
    if status == "limited":
        return f"limited {amount:,.0f}"
    return str(status)


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "–"


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
    p.add_argument("--gold", default=str(PROJECT_ROOT / "data" / "gold" / "timeline.csv"))
    p.add_argument("--candidate", default="legacy", choices=sorted(CANDIDATES))
    p.add_argument("--threshold", type=float, default=0.017, help="premium above which a day is arbitrage-relevant")
    p.add_argument("--min-confidence", default="low", choices=CONFIDENCES,
                   help="ignore gold days labeled below this confidence")
    p.add_argument("--trades", help="trade_logs.csv from a backtest run, for PnL attribution")
    p.add_argument("--out", help="also write the report to this Markdown file")
    args = p.parse_args()

    gold = load_gold(args.gold)
    keep = CONFIDENCES[: CONFIDENCES.index(args.min_confidence) + 1]
    loader = DataLoader(args.data_dir)
    trips = round_trips(pd.read_csv(args.trades, dtype={"ticker": str})) if args.trades else None

    per_fund = []
    kinds_by_fund = {}
    pnl_rows = []
    for fund in sorted(gold["fund_code"].unique()):
        frame, cand = load_fund(loader, fund, args.candidate)
        g = expand_daily(gold, fund, frame.index)
        g = g[g["confidence"].isin(keep)]
        classified = classify(g, cand)
        s = summarize(classified, premium=frame["premium_rate"], threshold=args.threshold)
        s["fund"] = fund
        s["window"] = (
            f"{classified.index.min():%Y-%m-%d} ~ {classified.index.max():%Y-%m-%d}" if len(classified) else "–"
        )
        per_fund.append(s)
        kinds_by_fund[fund] = mismatch_kinds(classified)
        if trips is not None:
            t = trips[trips["ticker"] == fund].copy()
            t["category"] = t["buy_date"].map(classified["category"]).fillna("unlabeled")
            for cat, grp in t.groupby("category"):
                pnl_rows.append({"fund": fund, "category": cat, "trips": len(grp), "pnl": grp["pnl"].sum()})

    total = {k: sum(s[k] for s in per_fund) for k in per_fund[0] if k not in ("fund", "window")}

    out = []
    out.append(f"# 限购时间线评估：`{args.candidate}`\n")
    out.append(f"- 生成日期：{date.today():%Y-%m-%d}")
    out.append(f"- 数据目录：`{rel(args.data_dir)}`；金标：`{rel(args.gold)}`")
    out.append(f"- 金标置信度：{', '.join(keep)}；相关日 = 溢价率 > {args.threshold:.1%}")
    out.append("- 分类：`agree` 一致；`too_permissive` 候选比金标宽松（回测会买到实际买不到的）；"
               "`too_strict` 候选比金标严格；`cand_unknown` 候选无答案\n")

    out.append("## 汇总\n")
    out.append("| 基金 | 评估区间 | 评估日 | 一致 | 过松 | 过严 | 相关日 | 相关日过松 | 相关日过严 |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in per_fund + [dict(total, fund="**合计**", window="")]:
        out.append(
            f"| {s['fund']} | {s['window']} | {s['days']} | {pct(s[AGREE], s['days'])} | {s[TOO_PERMISSIVE]} | "
            f"{s[TOO_STRICT]} | {s['relevant_days']} | {s['relevant_' + TOO_PERMISSIVE]} | "
            f"{s['relevant_' + TOO_STRICT]} |"
        )
    if total[CAND_UNKNOWN]:
        out.append(f"\n候选无答案的日子：{total[CAND_UNKNOWN]}")

    if trips is not None:
        out.append(f"\n## 回测利润归因（`{rel(args.trades)}`）\n")
        out.append("按买入日所属分类汇总往返交易的盈亏。`unlabeled` 表示买入日不在金标覆盖范围内。"
                   "盈亏是绝对金额，受资金复利路径影响：早期的虚假盈利会放大后续每笔交易的规模。\n")
        out.append("| 基金 | 分类 | 往返笔数 | 盈亏（元） |")
        out.append("|---|---|---:|---:|")
        order = {c: i for i, c in enumerate(CATEGORIES + ("unlabeled",))}
        for r in sorted(pnl_rows, key=lambda r: (r["fund"], order.get(r["category"], 99))):
            out.append(f"| {r['fund']} | {r['category']} | {r['trips']} | {r['pnl']:,.0f} |")
        by_cat = {}
        for r in pnl_rows:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["pnl"]
        out.append("")
        out.append("合计：" + "；".join(f"{c} {v:,.0f}" for c, v in sorted(by_cat.items(), key=lambda kv: order.get(kv[0], 99))))

    out.append("\n## 不一致类型\n")
    out.append("同一种\"金标值 vs 候选值\"的组合合并计数；中间被一致的日子（比如双方都对的节假日暂停）隔开也算在一起。\n")
    for fund, kinds in kinds_by_fund.items():
        if not kinds:
            out.append(f"### {fund}\n\n全部一致。\n")
            continue
        out.append(f"### {fund}\n")
        out.append("| 分类 | 金标 | 候选 | 交易日 | 首日 | 末日 |")
        out.append("|---|---|---|---:|---|---|")
        for k in kinds:
            out.append(
                f"| {k['category']} | {fmt_state(k['gold_status'], k['gold_amount'])} | "
                f"{fmt_state(k['cand_status'], k['cand_amount'])} | {k['days']} | {k['first']} | {k['last']} |"
            )
        out.append("")

    report = "\n".join(out) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
