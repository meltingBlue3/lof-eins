#!/usr/bin/env python
"""
Phase D: build daily_status from state_assertions, and report on its coverage.

阶段 D：由状态声明物化每日状态（daily_status），并输出覆盖率报告。

Usage:
    python scripts/build_timeline.py build
    python scripts/build_timeline.py report --out docs/eval/timeline-report.md
    python scripts/eval_timeline.py --candidate v2 --out docs/eval/v2-timeline.md     # against gold

`build` covers every fund with a market file, over the A-share trading days those files
contain. It never calls a model: rerun it after `extract_v2.py rebuild`.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.pipeline import db, timeline  # noqa: E402

MARKET = PROJECT_ROOT / "data" / "real_all_lof" / "market"
GOLD = PROJECT_ROOT / "data" / "gold" / "timeline.csv"


def cmd_build(conn, args):
    days = timeline.trading_calendar(args.market)
    funds = [p.stem for p in Path(args.market).glob("*.parquet")]
    print(f"calendar {days[0]} ~ {days[-1]} ({len(days)} days), {len(funds)} funds")
    print("build:", timeline.build(conn, funds, days))


def cmd_report(conn, args):
    start = args.start
    rows = pd.read_sql_query("SELECT fund_code, date, status, amount, source FROM daily_status WHERE date >= ?",
                             conn, params=(start,))
    gold_funds = sorted(pd.read_csv(GOLD, dtype=str)["fund_code"].unique())
    n = len(rows)
    out = [f"# 每日状态覆盖率报告（v2，阶段 D）\n",
           f"- 生成日期：{date.today():%Y-%m-%d}；对应 [重构方案](../redesign-subscription-state.md) §7.2、§7.5",
           f"- 范围：{rows['date'].min()} ~ {rows['date'].max()}，{rows['fund_code'].nunique()} 只基金，{n:,} 个基金日"
           f"（公告语料从 2022 年开始，所以从 {start} 起统计）\n"]

    out += ["## 状态与来源\n", "| 状态 | 基金日 | 占比 |", "|---|---:|---:|"]
    for s, c in rows["status"].value_counts().items():
        out.append(f"| {s} | {c:,} | {100 * c / n:.1f}% |")
    lim = rows[rows["status"] == "limited"]
    out.append(f"\n`limited` 中金额不明的 {lim['amount'].isna().sum():,} 天。\n")
    out += ["| 来源 | 基金日 | 占比 |", "|---|---:|---:|"]
    for s, c in rows["source"].value_counts().items():
        out.append(f"| {s} | {c:,} | {100 * c / n:.1f}% |")

    per = rows.groupby("fund_code")["status"].value_counts().unstack(fill_value=0)
    per["days"] = per.sum(axis=1)
    unknown_share = per.get("unknown", 0) / per["days"]
    out += ["\n## 基金分布\n",
            f"- 整个区间都是 unknown 的基金 {int((unknown_share == 1).sum())} 只；"
            f"unknown 占一半以上的 {int((unknown_share > 0.5).sum())} 只；完全没有 unknown 的 {int((unknown_share == 0).sum())} 只。",
            "- unknown 的日子没有任何目标路径上的声明可依。回测按 `unknown_policy` 处理（§8.1），保守边界当作不能申购。"]

    out += ["\n## 金标基金\n", "| 基金 | open | limited | closed | unknown | 来自 overlay | 来自推断 |", "|---|---:|---:|---:|---:|---:|---:|"]
    src = rows.groupby("fund_code")["source"].value_counts().unstack(fill_value=0)
    for f in gold_funds:
        if f not in per.index:
            continue
        p, s = per.loc[f], src.loc[f]
        out.append(f"| {f} | {p.get('open', 0)} | {p.get('limited', 0)} | {p.get('closed', 0)} | {p.get('unknown', 0)} | "
                   f"{s.get('overlay', 0)} | {s.get('inferred_prior', 0)} |")

    an = conn.execute(f"SELECT kind, COUNT(*) n, COUNT(DISTINCT fund_code) f FROM anomalies WHERE kind IN "
                      f"({','.join('?' * len(timeline.ANOMALY_KINDS))}) GROUP BY kind ORDER BY n DESC",
                      timeline.ANOMALY_KINDS).fetchall()
    out += ["\n## 时间线异常\n",
            "冲突一律按更严格的状态物化，并写入 `anomalies`，等人裁决。各类型的含义见 `src/pipeline/timeline.py` 模块说明。\n",
            "| 类型 | 条数 | 基金数 |", "|---|---:|---:|"]
    out += [f"| {r['kind']} | {r['n']} | {r['f']} |" for r in an]
    for kind in ("conflict_same_day", "conflict_leapfrog", "conflict_restatement", "overlay_overridden", "investor_scope",
                 "ignored_resume"):
        ex = conn.execute("SELECT fund_code, date_from, date_to, detail FROM anomalies WHERE kind = ? "
                          "ORDER BY fund_code IN (%s) DESC, fund_code, date_from LIMIT ?" % ",".join("?" * len(gold_funds)),
                          (kind, *gold_funds, args.examples)).fetchall()
        if ex:
            out.append(f"\n`{kind}` 示例（金标基金在前）：\n")
            out += [f"- {r['fund_code']} {r['date_from']}~{r['date_to']}：{r['detail']}" for r in ex]

    report = "\n".join(out) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["build", "report"])
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    p.add_argument("--market", default=str(MARKET))
    p.add_argument("--start", default="2022-01-01", help="report: first day counted")
    p.add_argument("--examples", type=int, default=8)
    p.add_argument("--out")
    args = p.parse_args()
    conn = db.connect(args.db)
    {"build": cmd_build, "report": cmd_report}[args.step](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
