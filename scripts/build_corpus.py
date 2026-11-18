#!/usr/bin/env python
"""
Phase B: build the announcement corpus in subscription_state.db.

阶段 B：登记公告、分诊、缓存正文，并输出覆盖报告。

Usage:
    python scripts/build_corpus.py register      # scan PDFs, record sha256
    python scripts/build_corpus.py triage        # title rules
    python scripts/build_corpus.py texts         # pdfplumber text cache for relevant + unsure
    python scripts/build_corpus.py texts --refresh   # also redo texts cached by an older extractor
    python scripts/build_corpus.py llm-triage    # LLM decides the remaining unsure (uses LOF_LLM_* env)
    python scripts/build_corpus.py report --out docs/eval/corpus-report.md
    python scripts/build_corpus.py all           # register, triage, texts, report

All steps are idempotent: re-running only does the missing work.
"""

import argparse
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import db, registry, texts, triage  # noqa: E402

ANN_ROOT = PROJECT_ROOT / "data" / "real_all_lof" / "announcements"
GOLD = PROJECT_ROOT / "data" / "gold" / "timeline.csv"


def cmd_register(conn, args):
    r = registry.register(conn, args.root)
    print("register:", {k: v for k, v in r.items() if k != "unparsed"}, "unparsed:", len(r["unparsed"]))
    for p in r["unparsed"][:20]:
        print("  unparsed name:", p)


def cmd_triage(conn, args):
    print("triage rules:", triage.apply_rules(conn, overwrite_llm=args.overwrite_llm))


def cmd_texts(conn, args):
    print("texts:", texts.build_cache(conn, args.root, workers=args.workers, refresh=args.refresh))


def cmd_llm_triage(conn, args):
    from src.pipeline.llm import ChatLLM, LLMConfig

    cfg = LLMConfig.from_env()
    llm = ChatLLM(cfg)
    print(f"llm triage with {cfg.model} at {cfg.base_url}")
    print("llm triage:", triage.llm_triage(conn, llm.chat, cfg.model, limit=args.limit, workers=args.workers))


def gold_recall(conn):
    """Gold-cited PDFs (high/medium confidence) and how they were triaged."""
    rows = list(csv.DictReader(open(GOLD, encoding="utf-8")))
    cited = sorted({r["source_pdf"] for r in rows if r["confidence"] != "low"})
    tri = {r["rel_path"]: (r["triage"], r["triage_by"]) for r in conn.execute(
        "SELECT rel_path, triage, triage_by FROM announcements")}
    missing = [p for p in cited if tri.get(p, (None,))[0] != "relevant"]
    return cited, missing, tri


def cmd_report(conn, args):
    out = [f"# 公告清单与正文覆盖报告\n",
           f"- 生成日期：{date.today():%Y-%m-%d}；数据库：`data/real_all_lof/config/subscription_state.db`",
           f"- 对应 [重构方案](../redesign-subscription-state.md) 阶段 B（§5 表 1~3、§6.1、§6.2）\n"]
    n, n_sha, n_fund = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT sha256), COUNT(DISTINCT fund_code) FROM announcements").fetchone()
    out += ["## 登记\n", f"- PDF 文件 {n:,} 个，涉及 {n_fund} 只基金；不同内容（sha256）{n_sha:,} 份。"
            "同一份家族公告会被复制到多只基金的目录下，所以文件数远多于内容数。\n"]

    out += ["## 分诊\n", "| 结果 | 依据 | 文件 | 不同内容 |", "|---|---|---:|---:|"]
    for r in conn.execute("SELECT triage, triage_by, COUNT(*) n, COUNT(DISTINCT sha256) s FROM announcements "
                          "GROUP BY triage, triage_by ORDER BY triage, n DESC"):
        out.append(f"| {r['triage']} | `{r['triage_by']}` | {r['n']:,} | {r['s']:,} |")
    unsure = conn.execute("SELECT DISTINCT title FROM announcements WHERE triage = 'unsure' ORDER BY title").fetchall()
    if unsure:
        out.append(f"\n仍为 unsure 的标题（{len(unsure)} 个，等待 LLM 分诊）：\n")
        out += [f"- {r['title']}" for r in unsure]

    cited, missing, tri = gold_recall(conn)
    out += ["\n## 召回验收（金标引用的 PDF）\n",
            f"- 金标中 high / medium 置信度的行一共引用了 {len(cited)} 份 PDF，其中 {len(cited) - len(missing)} 份被分为 relevant"
            f"（召回率 {100 * (len(cited) - len(missing)) / len(cited):.1f}%）。",
            "- low 置信度的行（169201、162207）引用的是费率优惠公告，只用来证明基金在售，不计入召回。"]
    by_rule = Counter(tri[p][1] for p in cited if p in tri)
    out.append("- 按分诊依据：" + "；".join(f"`{k}` {v}" for k, v in by_rule.most_common()))
    for p in missing:
        out.append(f"- **未召回**：`{p}`（{tri.get(p)}）")

    out += ["\n## 正文缓存\n"]
    wanted = "SELECT DISTINCT sha256 FROM announcements WHERE triage IN ('relevant','unsure')"
    want = conn.execute(f"SELECT COUNT(*) FROM ({wanted})").fetchone()[0]
    have = conn.execute(
        f"SELECT COUNT(*), SUM(is_empty = 1 AND n_pages IS NOT NULL), SUM(n_pages IS NULL), "
        f"SUM(error LIKE 'truncated%'), SUM(n_pages), SUM(LENGTH(text)) FROM pdf_texts WHERE sha256 IN ({wanted})"
    ).fetchone()
    extra = conn.execute(f"SELECT COUNT(*) FROM pdf_texts WHERE sha256 NOT IN ({wanted})").fetchone()[0]
    out.append(f"- relevant + unsure 共 {want:,} 份不同内容，已缓存 {have[0]:,} 份；"
               f"共 {have[4] or 0:,} 页、{have[5] or 0:,} 个字符。"
               + (f"另有 {extra} 份是分诊前缓存、后来被判为 irrelevant 的。" if extra else ""))
    out.append(f"- 提取器：`{texts.EXTRACTOR}`；无文字层（疑似扫描件）{have[1] or 0} 份，打不开 {have[2] or 0} 份，"
               f"超过 {texts.MAX_PAGES} 页被截断 {have[3] or 0} 份。")
    bad = conn.execute(
        "SELECT t.sha256, t.n_pages, t.is_empty, t.error, MIN(a.rel_path) rel, COUNT(a.id) copies, MIN(a.triage) tri "
        "FROM pdf_texts t JOIN announcements a ON a.sha256 = t.sha256 "
        "WHERE (t.is_empty = 1 OR t.error IS NOT NULL) AND a.triage IN ('relevant','unsure') "
        "GROUP BY t.sha256 ORDER BY rel").fetchall()
    if bad:
        out += ["\n需要人工处理或 OCR 的文件（扫描件不会被静默跳过）：\n",
                "| 文件 | 分诊 | 页数 | 副本 | 问题 |", "|---|---|---:|---:|---|"]
        for r in bad:
            problem = r["error"] or "无文字层"
            out.append(f"| `{r['rel']}` | {r['tri']} | {r['n_pages'] if r['n_pages'] is not None else '–'} | "
                       f"{r['copies']} | {problem} |")

    llm = conn.execute("SELECT model, status, COUNT(*) n FROM extractions WHERE prompt_version = ? "
                       "GROUP BY model, status", (triage.TRIAGE_PROMPT_VERSION,)).fetchall()
    if llm:
        out += ["\n## LLM 分诊调用\n", "| 模型 | 状态 | 份数 |", "|---|---|---:|"]
        out += [f"| `{r['model']}` | {r['status']} | {r['n']} |" for r in llm]

    report = "\n".join(out) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["register", "triage", "texts", "llm-triage", "report", "all"])
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    p.add_argument("--root", default=str(ANN_ROOT))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, help="llm-triage: only this many documents")
    p.add_argument("--overwrite-llm", action="store_true", help="triage: also overwrite earlier LLM decisions")
    p.add_argument("--refresh", action="store_true", help="texts: also redo texts cached by an older extractor version")
    p.add_argument("--out", help="report: also write Markdown here")
    args = p.parse_args()

    conn = db.connect(args.db)
    steps = {"register": cmd_register, "triage": cmd_triage, "texts": cmd_texts,
             "llm-triage": cmd_llm_triage, "report": cmd_report}
    for name in (["register", "triage", "texts", "report"] if args.step == "all" else [args.step]):
        steps[name](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
