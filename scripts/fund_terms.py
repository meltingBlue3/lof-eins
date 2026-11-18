#!/usr/bin/env python
"""
Phase F: per-fund trading terms (subscription fee tiers, confirmation days, NAV lag).

阶段 F：抓取并解析各基金的交易条款（申购费率、确认天数、净值滞后）。

Usage:
    python scripts/fund_terms.py fetch                 # cache missing Eastmoney fee pages (public, ~0.8s/page)
    python scripts/fund_terms.py build                 # parse cached pages -> config/fund_terms.csv
    python scripts/fund_terms.py report --out docs/eval/fund-terms.md

`build` never touches the network: rerun it after changing the parser. The backtest reads
config/fund_terms.csv when it exists (see src/data/loader.py).
"""

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.data import fund_terms  # noqa: E402

DATA = PROJECT_ROOT / "data" / "real_all_lof"
CONFIG = DATA / "config"


def tickers():
    return sorted(p.stem for p in (DATA / "market").glob("*.parquet"))


def cmd_fetch(args):
    failed = fund_terms.fetch_pages(tickers(), CONFIG / fund_terms.PAGES_DIR, refresh=args.refresh, pause=args.pause)
    print(f"failed: {failed}" if failed else "all pages cached")


def cmd_build(args):
    df = fund_terms.build_terms(tickers(), CONFIG / fund_terms.PAGES_DIR)
    df.to_csv(CONFIG / fund_terms.TERMS_FILE, index=False)
    bad = df[df["error"] != ""]
    print(f"{len(df)} funds -> {CONFIG / fund_terms.TERMS_FILE}; {len(bad)} with errors")
    for r in bad.itertuples():
        print(f"  {r.ticker}: {r.error}")


def pct(x):
    return "–" if pd.isna(x) else f"{x:.2%}"


def cmd_report(args):
    df = pd.read_csv(CONFIG / fund_terms.TERMS_FILE, dtype={"ticker": str}, keep_default_na=False)
    ok = df[df["error"] == ""].copy()
    ok["sub_fee_rate_1"] = pd.to_numeric(ok["sub_fee_rate_1"], errors="coerce")
    fetched = sorted(set(ok["fetched_at"]) - {""})
    out = ["# 基金交易条款（阶段 F）\n",
           f"- 生成日期：{date.today():%Y-%m-%d}；对应 [重构方案](../redesign-subscription-state.md) §8.4",
           f"- 来源：天天基金\"基金费率\"页（转录自招募说明书），抓取日期 {', '.join(fetched) or '–'}，"
           "反映的是抓取当天的条款",
           f"- 基金 {len(df)} 只，采用 {len(ok)} 只；其余在回测里沿用默认条款（1.5%、T+2 卖出、净值滞后 1 天）\n",
           "推导规则：场内申购份额在确认日登记，下一个交易日可以卖出，所以可卖日 = 买入确认日 + 1。"
           "境外基金和 FOF（确认日 T+2 及以上，或类型含 QDII/海外/FOF）在 T 日 15:00 前只能看到 T-2 的净值，"
           "境内基金能看到 T-1。页面上没有确认日的基金（天天基金不代销）按类型推定：境外和 FOF T+3，其余 T+2。\n",
           "## 首档申购费率（单笔小于首档上限时适用；回测单笔不超过 10 万元）\n",
           "| 首档费率 | 基金数 |", "|---|---:|"]
    for rate, n in ok["sub_fee_rate_1"].value_counts(dropna=False).sort_index().items():
        out.append(f"| {pct(rate)} | {n} |")
    out += ["\n## 可卖日与净值滞后\n", "| 可卖日 | 净值滞后 | 基金数 |", "|---|---|---:|"]
    for (s, lag), n in ok.groupby(["sell_days", "nav_lag"]).size().items():
        out.append(f"| T+{s} | {lag} 天 | {n} |")
    if len(df) > len(ok):
        out += ["\n## 未采用的条款（沿用默认条款）\n",
                "C 类份额不收申购费，0% 是对的；其他份额的费率表全是 0% 时，多半是页面上的占位"
                "（封闭运作或不开放申购的基金也是这样），不采用。\n",
                "| 基金 | 名称 | 原因 |", "|---|---|---|"]
        out += [f"| {r.ticker} | {r.name} | {r.error} |" for r in df[df["error"] != ""].itertuples()]
    conn = sqlite3.connect(f"file:{(CONFIG / 'subscription_state.db').as_posix()}?mode=ro", uri=True)
    notices = fund_terms.fee_change_notices(conn, args.start, args.end)
    conn.close()
    out += [f"\n## 回测区间内调整过申购费率的基金（{args.start} ~ {args.end}，按公告标题）\n",
            "这些基金在公告日之前的费率可能和上表不同，回测按抓取当天的费率计算。\n"]
    if notices.empty:
        out.append("没有找到。")
    else:
        out += ["| 基金 | 公告日 | 标题 |", "|---|---|---|"]
        out += [f"| {r.fund_code} | {r.announce_date} | {r.title} |" for r in notices.itertuples()]
    text = "\n".join(out) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"report -> {args.out}")
    else:
        print(text)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--refresh", action="store_true", help="refetch pages already cached")
    f.add_argument("--pause", type=float, default=0.8, help="seconds between requests")
    sub.add_parser("build")
    r = sub.add_parser("report")
    r.add_argument("--out")
    r.add_argument("--start", default="2022-01-01")
    r.add_argument("--end", default="2024-12-31")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    {"fetch": cmd_fetch, "build": cmd_build, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
