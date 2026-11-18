#!/usr/bin/env python
"""
Phase C: run the v2 extraction, rebuild state_assertions, and report on it.

阶段 C：运行 v2 抽取、重建状态声明表，并输出报告。

Usage:
    python scripts/extract_v2.py run --funds gold --until 2024-12-31        # LLM calls (LOF_LLM_* env)
    python scripts/extract_v2.py run --funds gold --limit 5                  # pilot
    python scripts/extract_v2.py rebuild
    python scripts/extract_v2.py report --out docs/eval/extract-v2-report.md

`run` only calls the model for documents not yet extracted with the current prompt version
and model; `rebuild` and `report` never call it.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.evaluation.assertions import GRADES, contradictions, grade_gold  # noqa: E402
from src.evaluation.gold import load_gold  # noqa: E402
from src.pipeline import db, extract  # noqa: E402

GOLD = PROJECT_ROOT / "data" / "gold" / "timeline.csv"


def gold_funds():
    return sorted(pd.read_csv(GOLD, dtype=str)["fund_code"].unique())


def trading_days():
    """A-share trading days seen in the market data of the gold funds."""
    from src.data.loader import DataLoader

    loader = DataLoader(str(PROJECT_ROOT / "data" / "real_all_lof"))
    days = set()
    for f in gold_funds():
        frame = loader.load_bundle(f).df
        days |= {d.strftime("%Y-%m-%d") for d in frame.index}
    return sorted(days)


def model_name(args):
    if args.model:
        return args.model
    from src.pipeline.llm import LLMConfig
    return LLMConfig.from_env().model


def cmd_run(conn, args):
    from src.pipeline.llm import ChatLLM, LLMConfig

    cfg = LLMConfig.from_env()
    llm = ChatLLM(cfg)
    funds = gold_funds() if args.funds == "gold" else (args.funds.split(",") if args.funds else None)
    files = [line.strip() for line in open(args.files, encoding="utf-8") if line.strip()] if args.files else None
    chat = (lambda *a, **k: llm.chat(*a, reasoning=args.reasoning, **k)) if args.reasoning else llm.chat
    counts = extract.run(conn, chat, cfg.model, funds=funds, until=args.until, limit=args.limit,
                         workers=args.workers, rel_paths=files)
    print("run:", counts, "| client usage:", llm.usage)


def cmd_rebuild(conn, args):
    version, _ = extract.load_prompt()
    print("rebuild:", extract.rebuild(conn, version, model_name(args)))


def fmt_assertion(a):
    if not a:
        return "–"
    amt = f" {a['amount']:,.0f}" if a["amount"] is not None else ""
    to = f"~{a['valid_to']}" if a["valid_to"] else ""
    return f"{a['layer']} {a['kind']} {a['status']}{amt} {a['valid_from']}{to} ({a['channel']})"


def coverage_section(conn, examples):
    """Which funds have any usable target-path assertion -- the rest will resolve to `unknown` in phase D."""
    from src.evaluation.assertions import on_target

    docs = Counter(r[0] for r in conn.execute(
        "SELECT fund_code FROM announcements WHERE triage = 'relevant'"))
    all_funds = {r[0] for r in conn.execute("SELECT DISTINCT fund_code FROM announcements")}
    hit, status = Counter(), Counter()
    for a in conn.execute("SELECT * FROM state_assertions WHERE evidence_ok > 0"):
        if on_target(a, a["fund_code"]):
            hit[a["fund_code"]] += 1
            status[(a["layer"], a["status"])] += 1
    by_year = conn.execute(
        "SELECT substr(a.announce_date, 1, 4) y, COUNT(DISTINCT a.sha256) n FROM announcements a "
        "WHERE a.triage = 'relevant' GROUP BY y ORDER BY y").fetchall()
    out = ["\n## 覆盖面\n",
           f"- 有公告目录的基金 {len(all_funds)} 只，其中有 relevant 公告的 {len(docs)} 只，"
           f"抽到至少一条目标路径声明（场内代码或 `*`、全部/场外/场内渠道、申购、人民币，且引用通过）的 **{len(hit)} 只**。",
           "- relevant 公告按年份（去重后）：" + "，".join(f"{r['y']} 年 {r['n']}" for r in by_year) + "。",
           "- 目标路径声明按层和状态：" + "，".join(f"{l} {s} {n}" for (l, s), n in status.most_common()) + "。"]
    empty = sorted((f for f in docs if f not in hit), key=lambda f: -docs[f])
    if empty:
        out.append(f"- 有 relevant 公告、但没有一条目标路径声明的基金 {len(empty)} 只（阶段 D 会把它们的日子判为 unknown），"
                   "按 relevant 公告数排序：" + "，".join(f"{f}（{docs[f]}）" for f in empty[: examples * 2]) + "。")
    return out


def cmd_report(conn, args):
    version, _ = extract.load_prompt()
    model = model_name(args)
    out = [f"# v2 抽取报告：`{version}` · `{model}`\n",
           f"- 生成日期：{date.today():%Y-%m-%d}；对应 [重构方案](../redesign-subscription-state.md) 阶段 C（§6.3、§6.4）",
           "- 数据：`data/real_all_lof/config/subscription_state.db` 中的 `extractions`、`state_assertions`、`anomalies`\n"]

    st = conn.execute("SELECT status, COUNT(*) n, SUM(json_extract(raw_response, '$.attempts') = 2) re "
                      "FROM extractions WHERE prompt_version = ? AND model = ? GROUP BY status", (version, model)).fetchall()
    usage = conn.execute("SELECT SUM(json_extract(raw_response, '$.usage.prompt_tokens')), "
                         "SUM(json_extract(raw_response, '$.usage.completion_tokens')) FROM extractions "
                         "WHERE prompt_version = ? AND model = ?", (version, model)).fetchone()
    out += ["## 调用\n", "| 状态 | 份数 | 其中重问过一次 |", "|---|---:|---:|"]
    out += [f"| {r['status']} | {r['n']} | {r['re'] or 0} |" for r in st]
    out.append(f"\n输入 {usage[0] or 0:,} token、输出 {usage[1] or 0:,} token"
               f"（按网关标价约 ${((usage[0] or 0) * 0.12 + (usage[1] or 0) * 0.42) / 1e6:.2f}）。")

    tot = conn.execute("SELECT COUNT(*), SUM(evidence_ok > 0), SUM(evidence_ok = 2) FROM state_assertions").fetchone()
    n, ok, relaxed = tot[0] or 0, tot[1] or 0, tot[2] or 0
    out += ["\n## 原文引用校验\n",
            (f"- 声明 {n:,} 条，引用通过 {ok:,} 条，**通过率 {100 * ok / n:.1f}%**（验收线 98%）。"
             f"其中 {ok - relaxed:,} 条是逐字子串（`evidence_ok=1`），{relaxed:,} 条放宽后才对上（`evidence_ok=2`："
             "模型把两三段原文拼在一起、漏了“……”，或者 PDF 文字层把日期数字挪到了下一行）。") if n else "- 尚无声明。"]
    by = conn.execute("SELECT layer, kind, status, COUNT(*) n, SUM(evidence_ok = 1) v, SUM(evidence_ok = 2) r "
                      "FROM state_assertions GROUP BY layer, kind, status ORDER BY n DESC").fetchall()
    if by:
        out += ["", "| 层 | 类型 | 状态 | 条数 | 逐字通过 | 放宽通过 |", "|---|---|---|---:|---:|---:|"]
        out += [f"| {r['layer']} | {r['kind']} | {r['status']} | {r['n']} | {r['v']} | {r['r']} |" for r in by]

    an = conn.execute("SELECT kind, COUNT(*) n FROM anomalies GROUP BY kind ORDER BY n DESC").fetchall()
    out += ["\n## 校验异常\n", "| 类型 | 条数 |", "|---|---:|"] + [f"| {r['kind']} | {r['n']} |" for r in an]
    for kind in ("evidence_fail", "date_out_of_range", "unknown_share_code", "null_amount", "schema_error"):
        ex = conn.execute("SELECT a.fund_code, a.detail, (SELECT MIN(rel_path) FROM announcements x WHERE x.sha256 = a.sha256) p "
                          "FROM anomalies a WHERE kind = ? LIMIT ?", (kind, args.examples)).fetchall()
        if ex:
            out.append(f"\n`{kind}` 示例：\n")
            out += [f"- {r['fund_code']} · `{r['p']}` · {r['detail']}" for r in ex]

    out += coverage_section(conn, args.examples)

    gold = pd.read_csv(GOLD, dtype=str, keep_default_na=False)
    days = trading_days()
    graded = grade_gold(conn, gold, version, model, days)
    out += ["\n## 对照金标（声明级）\n",
            "金标每一行，在它引用的 PDF 的抽取结果里找目标路径上的声明：`full` 状态、层、日期都对；`state` 状态对、日期不同；"
            "`prior` 公告没有直接说，但紧接着的那条变更用 `prior_status` 表明了之前的状态（阶段 D 按 inferred_prior 处理）；"
            "`missing` 没找到；`skipped` 引用的是别的基金的公告或该 PDF 未抽取。日期按交易日比较。medium 置信度的开放区间多半是从节假日公告推断的，"
            "公告本身并没有这句话，`missing` 属于预期。\n",
            "| 置信度 | 层 | " + " | ".join(GRADES) + " |", "|---|---|" + "---:|" * len(GRADES)]
    cnt = Counter((g["confidence"], g["layer"], g["grade"]) for g in graded)
    for conf in ("high", "medium", "low"):
        for layer in ("baseline", "overlay"):
            row = [cnt[(conf, layer, k)] for k in GRADES]
            if sum(row):
                out.append(f"| {conf} | {layer} | " + " | ".join(map(str, row)) + " |")
    hi = [g for g in graded if g["confidence"] == "high" and g["grade"] != "skipped"]
    if hi:
        full = sum(g["grade"] == "full" for g in hi)
        state = sum(g["grade"] in ("full", "state") for g in hi)
        recov = sum(g["grade"] in ("full", "state", "prior") for g in hi)
        out.append(f"\nhigh 置信度、可评的 {len(hi)} 行：完全一致 {full}（{100 * full / len(hi):.1f}%），"
                   f"状态一致 {state}（{100 * state / len(hi):.1f}%），"
                   f"算上 prior 可还原 {recov}（{100 * recov / len(hi):.1f}%）。")
    per_fund = defaultdict(Counter)
    for g in graded:
        if g["confidence"] == "high":
            per_fund[g["fund_code"]][g["grade"]] += 1
    out += ["\n| 基金 | " + " | ".join(GRADES) + " |", "|---|" + "---:|" * len(GRADES)]
    out += [f"| {f} | " + " | ".join(str(c[k]) for k in GRADES) + " |" for f, c in sorted(per_fund.items())]

    bad = [g for g in graded if g["confidence"] == "high" and g["grade"] in ("missing", "state")]
    if bad:
        out += [f"\n### high 置信度未完全一致的行（{len(bad)}）\n", "| 基金 | 金标 | 结果 | 抽取到的最接近声明 | 来源 |", "|---|---|---|---|---|"]
        for g in bad[: args.examples * 4]:
            gold_s = f"{g['layer']} {g['status']}{' ' + g['amount'] if g['amount'] else ''} {g['valid_from']}~{g['valid_to']}"
            out.append(f"| {g['fund_code']} | {gold_s} | {g['grade']} | {fmt_assertion(g['best'])} | "
                       f"`{g['source_pdf'].split('/', 1)[1][:60]}` |")

    prec = contradictions(conn, load_gold(str(GOLD)), days)
    c = prec["counts"]
    out += ["\n## 反向核对：声明是否与金标矛盾\n",
            "上一节查的是\"金标的事实有没有被抽到\"，这一节反过来查\"抽到的声明有没有说错\"。对金标基金上、引用通过的目标路径声明："
            "overlay 逐个交易日对照金标；baseline change 看生效首日的金标基线；restatement 看公告前一个交易日的金标基线。\n",
            f"- 可核对 {c['checked']} 条，一致 {c['agree']} 条（{100 * c['agree'] / max(c['checked'], 1):.1f}%），"
            f"矛盾 {c['disagree']} 条；另有 {c['unlabeled']} 条落在金标未覆盖的日子。"]
    if prec["disagreements"]:
        out += ["", "| 基金 | 声明 | 金标 | 原文引用 |", "|---|---|---|---|"]
        for b in prec["disagreements"][: args.examples * 3]:
            a = b["assertion"]
            out.append(f"| {a['fund_code']} | {fmt_assertion(a)}，公告 {a['observed_on']} | {'；'.join(b['wrong'][:2])} | "
                       f"{a['evidence'][:70]} |")

    report = "\n".join(out) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["run", "rebuild", "report"])
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    p.add_argument("--funds", help="'gold' or comma-separated fund codes (default: all relevant documents)")
    p.add_argument("--until", help="only documents announced on or before this date")
    p.add_argument("--limit", type=int)
    p.add_argument("--files", help="text file with one announcements-relative PDF path per line")
    p.add_argument("--reasoning", choices=["low", "medium", "high"], help="override LOF_LLM_REASONING for this run")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--model", help="model name for rebuild/report (default: LOF_LLM_MODEL)")
    p.add_argument("--examples", type=int, default=10)
    p.add_argument("--out")
    args = p.parse_args()
    conn = db.connect(args.db)
    {"run": cmd_run, "rebuild": cmd_rebuild, "report": cmd_report}[args.step](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
