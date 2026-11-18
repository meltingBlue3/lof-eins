"""
Triage: decide which announcements are worth extracting.

分诊：决定哪些公告值得抽取。先按标题规则分类，剩下的 unsure 交给 LLM 看标题和正文开头。

Rule order matters -- the first matching rule wins:
  1. document types that never carry purchase state (periodic reports, prospectus...)  -> irrelevant
  2. a single sales agency's business being suspended/terminated                         -> irrelevant
  3. purchase-state words (暂停/恢复/大额/限额/休市/节假日/开放期...)                    -> relevant
  4. sales, fee and service notices                                                       -> irrelevant
  5. everything else                                                                      -> unsure

Unlike the legacy filter, a title does not need to contain 申购: 暂停赎回 notices, trading-day
schedules and open-period notices all carry restatements of the purchase state.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

RELEVANT, IRRELEVANT, UNSURE = "relevant", "irrelevant", "unsure"

# Words that make a title state-bearing even if it also names a document type.
_STATE_GUARD = re.compile(r"暂停|恢复|大额|限额|开放期|封闭期|休市|节假日|非港股通")
# A fee/promotion title without any hard state word.
_FEE_ONLY = re.compile(r"^(?!.*(大额|限额|开放(?!式).{0,30}?(申购|赎回)|休市|节假日|非港股通|开放期|封闭期)).*(费率|优惠活动)")

RULES: List[Tuple[str, str, re.Pattern, Optional[re.Pattern]]] = [
    # (name, label, pattern, unless) -- `unless` vetoes the rule
    ("doc_type", IRRELEVANT,
     re.compile(r"季度报告|年度报告|中期报告|半年度报告|招募说明书|产品资料概要|托管协议|收益分配|分红"
                r"|基金经理|高级管理人员|董事|监事|会计师事务所|上市交易公告书|份额发售|发售公告|关联交易|审计|基金合同生效"),
     _STATE_GUARD),
    ("single_agency", IRRELEVANT,
     re.compile(r"(暂停|终止|恢复)[^，。]{0,40}?(销售有限公司|销售股份有限公司|证券股份有限公司|证券有限责任公司|期货有限公司"
                r"|银行股份有限公司|销售机构|财富|基金销售)[^，。]{0,30}?(办理|销售|代销|合作|业务)"
                r"|销售机构暂停办理|代销机构办理"),
     re.compile(r"大额")),
    ("state", RELEVANT,
     re.compile(r"暂停|恢复(?!原?.{0,6}费率)|大额|限额|限制.{0,20}申购|申购上限|规模上限|休市|节假日|假期|非港股通|港股通交易日"
                r"|交易日安排|开放日|开放期|封闭期|开放(?!式).{0,30}?(申购|赎回)|延长.{0,6}开放|申赎"
                r"|调整.{0,40}申购(?!.{0,4}费)|申购.{0,12}限制|无效处理|不予确认"),
     # fee promotions that merely mention 申购 fall through to sales_fee, unless they also carry a hard state word
     _FEE_ONLY),
    ("sales_fee", IRRELEVANT,
     re.compile(r"费率|优惠|销售机构|销售有限公司|代销|代理销售|直销|新增|增加|开通|终止.{0,30}(合作|销售|代销|代理|办理)"
                r"|网上交易|销售服务|流动性服务|做市"
                r"|起点金额|最低.{0,6}金额|转托管|电子直销|定投业务"),
     None),
]


@dataclass(frozen=True)
class Decision:
    label: str
    rule: str  # name of the rule that fired, or "default"


def triage_title(title: str) -> Decision:
    """Classify an announcement by its title alone."""
    for name, label, pattern, unless in RULES:
        if pattern.search(title) and not (unless is not None and unless.search(title)):
            return Decision(label, name)
    return Decision(UNSURE, "default")


def apply_rules(conn: sqlite3.Connection, overwrite_llm: bool = False) -> dict:
    """
    Write rule decisions to `announcements.triage`.

    Rows already decided by the LLM keep their decision unless overwrite_llm is set,
    except when the rules now say relevant/irrelevant with certainty.
    """
    counts = {RELEVANT: 0, IRRELEVANT: 0, UNSURE: 0, "kept_llm": 0}
    rows = conn.execute("SELECT id, title, triage, triage_by FROM announcements").fetchall()
    with conn:
        for r in rows:
            d = triage_title(r["title"])
            if d.label == UNSURE and (r["triage_by"] or "").startswith("llm:") and not overwrite_llm:
                counts["kept_llm"] += 1
                continue
            counts[d.label] += 1
            conn.execute("UPDATE announcements SET triage = ?, triage_by = ? WHERE id = ?",
                         (d.label, f"rule:{d.rule}", r["id"]))
    return counts


# ---------------------------------------------------------------- LLM fallback

TRIAGE_PROMPT_VERSION = "triage-v1"
HEAD_CHARS = 800

TRIAGE_SYSTEM = (
    "你是基金公告分诊员。判断一份公告是否包含某只或某几只基金的【申购业务状态】信息，"
    "包括：暂停或恢复申购、暂停或恢复赎回（这类公告常顺带说明申购是否暂停）、大额申购限额、"
    "开放期或封闭期安排、节假日或非港股通交易日暂停安排、基金规模上限、因清算或转型终止申购等。"
    "只涉及费率优惠、销售机构增减、某一家销售机构暂停代销、定期报告、人事变动、分红的公告判为不相关。"
    "拿不准时判为相关。"
)

TRIAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_triage",
        "description": "报告分诊结果",
        "parameters": {
            "type": "object",
            "properties": {
                "relevant": {"type": "boolean", "description": "是否包含申购业务状态信息"},
                "reason": {"type": "string", "description": "一句话理由"},
            },
            "required": ["relevant", "reason"],
        },
    },
}


def triage_messages(title: str, head: str) -> list:
    return [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user", "content": f"标题：{title}\n\n正文开头：\n{head[:HEAD_CHARS]}"},
    ]


def llm_triage(conn: sqlite3.Connection, chat: Callable, model: str, limit: Optional[int] = None,
               workers: int = 4, log: Callable[[str], None] = print) -> dict:
    """
    Classify `unsure` announcements with the LLM, caching raw output in `extractions`.

    `chat(messages, tools, tool_choice)` must return an object with `.tool_args` (dict or None)
    and `.raw` (JSON-serialisable). Documents are deduplicated by sha256; every row sharing
    the content gets the same decision. Rows whose text is missing stay unsure.
    """
    from concurrent.futures import ThreadPoolExecutor

    todo = conn.execute(
        "SELECT a.sha256, MIN(a.title) AS title, t.text, t.is_empty FROM announcements a "
        "LEFT JOIN pdf_texts t ON t.sha256 = a.sha256 WHERE a.triage = 'unsure' GROUP BY a.sha256"
    ).fetchall()
    cached = {r["sha256"]: r for r in conn.execute(
        "SELECT sha256, raw_response, status FROM extractions WHERE prompt_version = ? AND model = ?",
        (TRIAGE_PROMPT_VERSION, model))}
    todo = [r for r in todo if r["text"] is not None and not r["is_empty"]]
    if limit is not None:
        todo = todo[:limit]

    def run(row):
        if row["sha256"] in cached and cached[row["sha256"]]["status"] == "ok":
            return row["sha256"], json.loads(cached[row["sha256"]]["raw_response"]), None, True
        try:
            res = chat(triage_messages(row["title"], row["text"]), tools=[TRIAGE_TOOL],
                       tool_choice={"type": "function", "function": {"name": "report_triage"}})
            return row["sha256"], {"tool_args": res.tool_args, "raw": res.raw}, None, False
        except Exception as e:  # recorded as api_error, retried on the next run
            return row["sha256"], None, f"{type(e).__name__}: {e}", False

    counts = {RELEVANT: 0, IRRELEVANT: 0, "schema_error": 0, "api_error": 0, "cached": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (sha, payload, err, was_cached) in enumerate(pool.map(run, todo), 1):
            counts["cached"] += was_cached
            args = (payload or {}).get("tool_args")
            ok = isinstance(args, dict) and isinstance(args.get("relevant"), bool)
            status = "api_error" if err else ("ok" if ok else "schema_error")
            with conn:
                if not was_cached:
                    conn.execute(
                        "INSERT INTO extractions (sha256, prompt_version, model, raw_response, status, error) "
                        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(sha256, prompt_version, model) DO UPDATE SET "
                        "raw_response = excluded.raw_response, status = excluded.status, error = excluded.error, "
                        "created_at = CURRENT_TIMESTAMP",
                        (sha, TRIAGE_PROMPT_VERSION, model, json.dumps(payload, ensure_ascii=False) if payload else None,
                         status, err))
                if status == "ok":
                    label = RELEVANT if args["relevant"] else IRRELEVANT
                    counts[label] += 1
                    conn.execute("UPDATE announcements SET triage = ?, triage_by = ? WHERE sha256 = ? AND triage = 'unsure'",
                                 (label, f"llm:{model}@{TRIAGE_PROMPT_VERSION}", sha))
                else:
                    counts[status] += 1
            if i % 50 == 0:
                log(f"  llm triage {i}/{len(todo)}")
    return counts
