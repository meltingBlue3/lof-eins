"""
Phase C: extract state assertions from announcement text with the LLM.

阶段 C：用 LLM 从公告正文中抽取状态声明。

Two halves, kept separate on purpose (design principle 5, deterministic rebuild):

  run()      -- calls the model for each document and caches the raw tool arguments in
                `extractions`, keyed by (sha256, prompt_version, model). Re-running only
                fills what is missing or failed.
  rebuild()  -- a pure function of the cache: validates every assertion and rewrites
                `state_assertions` and the extraction anomalies from scratch.
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "prompts" / "extract_v2.md"
MAX_INPUT_CHARS = 60_000

CHANNELS = ("all", "exchange", "agency", "direct", "specific")
BUSINESSES = ("purchase", "fixed_invest", "convert_in", "redemption", "convert_out")
PURCHASE_SIDE = {"purchase", "fixed_invest", "convert_in"}
STATUSES = ("open", "limited", "closed")
LAYERS = ("baseline", "overlay")
KINDS = ("change", "restatement")
CURRENCIES = ("CNY", "USD")
ANOMALY_KINDS = ("evidence_fail", "date_out_of_range", "null_amount", "amount_range",
                 "unknown_share_code", "unrequested_fund", "schema_error")


def load_prompt(path: Path = PROMPT_PATH) -> Tuple[str, str]:
    """Return (prompt_version, system prompt text). The version lives in the first-line comment."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"<!--\s*prompt_version:\s*(\S+)\s*-->\s*", text)
    if not m:
        raise ValueError(f"{path} must start with <!-- prompt_version: ... -->")
    return m.group(1), text[m.end():]


ASSERTION_SCHEMA = {
    "type": "object",
    "properties": {
        "fund_code": {"type": "string", "description": "所属基金主代码，必须是输入给出的代码之一"},
        "share_codes": {"type": "array", "items": {"type": "string"}, "description": "适用的份额代码；全部份额填 [\"*\"]"},
        "channel": {"type": "string", "enum": list(CHANNELS)},
        "businesses": {"type": "array", "items": {"type": "string", "enum": list(BUSINESSES)}},
        "status": {"type": "string", "enum": list(STATUSES)},
        "amount": {"type": ["number", "null"], "description": "limited 时的单日单账户上限；单位见 currency"},
        "currency": {"type": "string", "enum": list(CURRENCIES)},
        "valid_from": {"type": "string", "description": "YYYY-MM-DD"},
        "valid_to": {"type": ["string", "null"], "description": "overlay 的最后一天（含）；baseline 为 null"},
        "layer": {"type": "string", "enum": list(LAYERS)},
        "kind": {"type": "string", "enum": list(KINDS)},
        "prior_status": {"type": ["string", "null"], "enum": list(STATUSES) + [None]},
        "evidence": {"type": "string", "description": "原样摘出的原文片段"},
    },
    "required": ["fund_code", "share_codes", "channel", "businesses", "status", "amount", "currency",
                 "valid_from", "valid_to", "layer", "kind", "prior_status", "evidence"],
}

TOOL = {
    "type": "function",
    "function": {
        "name": "report_assertions",
        "description": "报告从公告中抽取的申购状态声明",
        "parameters": {
            "type": "object",
            "properties": {
                "relevant": {"type": "boolean", "description": "公告是否含指定基金的申购状态信息"},
                "assertions": {"type": "array", "items": ASSERTION_SCHEMA},
            },
            "required": ["relevant", "assertions"],
        },
    },
}
TOOL_CHOICE = {"type": "function", "function": {"name": "report_assertions"}}


# ------------------------------------------------------------------------------ input

def render_tables(tables: List[dict], limit: int = 20_000) -> str:
    lines = []
    for tb in tables:
        for row in tb["rows"]:
            cells = [re.sub(r"\s+", " ", c).strip() for c in row]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)[:limit]


def input_hash(user_message: str) -> str:
    """Fingerprint of what the model was shown; a changed text cache changes it."""
    return hashlib.sha256(user_message.encode("utf-8")).hexdigest()[:16]


def render_input(codes: List[str], announce_date: str, title: str, text: str, tables: List[dict]) -> str:
    body = text.replace("\f", "\n")[:MAX_INPUT_CHARS]
    parts = [f"要抽取的基金代码：{'、'.join(codes)}", f"公告日期：{announce_date}", f"标题：{title}", "",
             "--- 正文 ---", body, "--- 正文结束 ---"]
    tab = render_tables(tables)
    if tab:
        parts += ["", "--- 表格（extract_tables，单元格用 | 分隔） ---", tab, "--- 表格结束 ---"]
    return "\n".join(parts)


# ------------------------------------------------------------------------------ schema check

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date(s: Any) -> bool:
    if not isinstance(s, str) or not _DATE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def schema_errors(payload: Any) -> List[str]:
    """Problems that justify asking the model again. Empty list = structurally valid."""
    if not isinstance(payload, dict):
        return ["output is not a JSON object"]
    errs = []
    if not isinstance(payload.get("relevant"), bool):
        errs.append("relevant must be true/false")
    items = payload.get("assertions")
    if not isinstance(items, list):
        return errs + ["assertions must be an array"]
    for i, a in enumerate(items):
        w = f"assertions[{i}]"
        if not isinstance(a, dict):
            errs.append(f"{w} is not an object")
            continue
        missing = [k for k in ASSERTION_SCHEMA["required"] if k not in a]
        if missing:
            errs.append(f"{w} missing {missing}")
            continue
        for key, allowed in (("channel", CHANNELS), ("status", STATUSES), ("layer", LAYERS),
                             ("kind", KINDS), ("currency", CURRENCIES)):
            if a[key] not in allowed:
                errs.append(f"{w}.{key}={a[key]!r} not in {list(allowed)}")
        if a["prior_status"] not in STATUSES + (None,):
            errs.append(f"{w}.prior_status={a['prior_status']!r}")
        if not (isinstance(a["businesses"], list) and a["businesses"] and all(b in BUSINESSES for b in a["businesses"])):
            errs.append(f"{w}.businesses must be a non-empty list of {list(BUSINESSES)}")
        if not (isinstance(a["share_codes"], list) and a["share_codes"] and all(isinstance(s, str) for s in a["share_codes"])):
            errs.append(f"{w}.share_codes must be a non-empty list of strings")
        if not _is_date(a["valid_from"]):
            errs.append(f"{w}.valid_from={a['valid_from']!r} is not YYYY-MM-DD")
        if a["layer"] == "overlay":
            if not _is_date(a["valid_to"]):
                errs.append(f"{w}: overlay needs valid_to (YYYY-MM-DD)")
            elif _is_date(a["valid_from"]) and a["valid_to"] < a["valid_from"]:
                errs.append(f"{w}: valid_to before valid_from")
        elif a["valid_to"] is not None:
            errs.append(f"{w}: baseline must have valid_to=null (use overlay if it ends)")
        if a["amount"] is not None and not isinstance(a["amount"], (int, float)):
            errs.append(f"{w}.amount must be a number or null")
        if not isinstance(a["evidence"], str) or not a["evidence"].strip():
            errs.append(f"{w}.evidence is empty")
    return errs


# ------------------------------------------------------------------------------ run (LLM, cached)

def _documents(conn: sqlite3.Connection, funds: Optional[Iterable[str]], until: Optional[str],
               rel_paths: Optional[Iterable[str]] = None) -> List[sqlite3.Row]:
    """Relevant documents with text, one row per sha256, with every fund folder holding a copy."""
    where, args = ["a.triage = 'relevant'", "t.is_empty = 0"], []
    if rel_paths:
        rel_paths = list(rel_paths)
        where.append(f"a.sha256 IN (SELECT sha256 FROM announcements WHERE rel_path IN ({','.join('?' * len(rel_paths))}))")
        args += rel_paths
    if funds:
        funds = list(funds)
        where.append(f"a.sha256 IN (SELECT sha256 FROM announcements WHERE fund_code IN ({','.join('?' * len(funds))}))")
        args += funds
    if until:
        where.append("a.announce_date <= ?")
        args.append(until)
    q = (f"SELECT a.sha256, MIN(a.announce_date) AS announce_date, MIN(a.title) AS title, "
         f"GROUP_CONCAT(DISTINCT a.fund_code) AS codes, t.text, t.tables "
         f"FROM announcements a JOIN pdf_texts t ON t.sha256 = a.sha256 WHERE {' AND '.join(where)} "
         f"GROUP BY a.sha256 ORDER BY announce_date")
    return conn.execute(q, args).fetchall()


def run(conn: sqlite3.Connection, chat: Callable, model: str, funds: Optional[Iterable[str]] = None,
        until: Optional[str] = None, limit: Optional[int] = None, workers: int = 8,
        rel_paths: Optional[Iterable[str]] = None, prompt_path: Path = PROMPT_PATH,
        log: Callable[[str], None] = print) -> dict:
    """
    Extract every pending document. `chat(messages, tools=..., tool_choice=...)` returns an object
    with `.tool_args`, `.finish_reason` and `.usage` (see ChatLLM). A structurally invalid answer is
    sent back once with the list of problems; still invalid -> schema_error. Exceptions -> api_error.
    Documents already extracted 'ok' from the same model input (requested codes, title, text and
    tables, see `input_hash`) are skipped, so a refreshed text cache re-extracts only what changed.
    """
    version, system = load_prompt(prompt_path)
    docs = _documents(conn, funds, until, rel_paths)
    done = {r["sha256"]: json.loads(r["raw_response"] or "{}")
            for r in conn.execute("SELECT sha256, raw_response FROM extractions WHERE prompt_version = ? "
                                  "AND model = ? AND status = 'ok'", (version, model))}
    todo, changed = [], 0
    for d in docs:
        codes = sorted(d["codes"].split(","))
        user = render_input(codes, d["announce_date"], d["title"], d["text"], json.loads(d["tables"]))
        prev = done.get(d["sha256"])
        if prev is None or prev.get("requested_codes") != codes or prev.get("input_sha") != input_hash(user):
            todo.append((d, codes, user))
            changed += prev is not None
    if limit is not None:
        todo = todo[:limit]
    log(f"extract {version} with {model}: {len(todo)} to do ({changed} with changed input), "
        f"{len(docs) - len(todo)} cached")

    def one(item):
        d, codes, user = item
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        attempts, errors, usage, finish = 0, [], {"prompt_tokens": 0, "completion_tokens": 0}, None
        try:
            for attempts in (1, 2):
                res = chat(messages, tools=[TOOL], tool_choice=TOOL_CHOICE)
                for k in usage:
                    usage[k] += (res.usage or {}).get(k, 0)
                finish = res.finish_reason
                errs = schema_errors(res.tool_args)
                if not errs:
                    return d["sha256"], "ok", {"requested_codes": codes, "input_sha": input_hash(user),
                                               "tool_args": res.tool_args, "attempts": attempts, "errors": errors,
                                               "finish_reason": finish, "usage": usage}, None
                errors.append(errs[:20])
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(res.tool_args, ensure_ascii=False)[:20_000]},
                    {"role": "user", "content": "上一次的输出有以下问题，请修正后重新调用 report_assertions，输出完整结果：\n- "
                                                + "\n- ".join(errs[:20])},
                ]
            return d["sha256"], "schema_error", {"requested_codes": codes, "input_sha": input_hash(user),
                                                 "tool_args": res.tool_args,
                                                 "attempts": attempts, "errors": errors, "finish_reason": finish,
                                                 "usage": usage}, "; ".join(errors[-1])
        except Exception as e:  # noqa: BLE001 - recorded and retried next run
            return d["sha256"], "api_error", {"requested_codes": codes, "attempts": attempts, "usage": usage}, \
                f"{type(e).__name__}: {e}"

    counts = {"ok": 0, "schema_error": 0, "api_error": 0, "prompt_tokens": 0, "completion_tokens": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (sha, status, payload, err) in enumerate(pool.map(one, todo), 1):
            counts[status] += 1
            counts["prompt_tokens"] += payload["usage"]["prompt_tokens"]
            counts["completion_tokens"] += payload["usage"]["completion_tokens"]
            with conn:
                conn.execute(
                    "INSERT INTO extractions (sha256, prompt_version, model, raw_response, status, error) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(sha256, prompt_version, model) DO UPDATE SET "
                    "raw_response = excluded.raw_response, status = excluded.status, error = excluded.error, "
                    "created_at = CURRENT_TIMESTAMP",
                    (sha, version, model, json.dumps(payload, ensure_ascii=False), status, err))
            if i % 25 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)}  ok={counts['ok']} schema={counts['schema_error']} api={counts['api_error']}")
    return counts


# ------------------------------------------------------------------------------ validate + rebuild (pure)

_ELLIPSIS = re.compile(r"……|…|\.{3,}|。。。")


def normalize(s: str) -> str:
    """
    Full-width -> half-width, drop whitespace and the ' | ' cell separators of the rendered
    tables: the form used to compare quotes with the text.
    """
    return re.sub(r"[\s|“”\"'‘’「」『』]+", "", unicodedata.normalize("NFKC", s or ""))


def _loose_pattern(frag: str) -> "re.Pattern":
    """
    Like `frag`, but tolerating up to 3 stray digits between two non-digit characters.
    pdfplumber sometimes drops the page number into the flow ("恢复申1购"); digits next to
    digits are left strict so amounts and dates cannot drift (100 never matches 1000).
    """
    parts = []
    for i, ch in enumerate(frag):
        if i and not ch.isdigit() and not frag[i - 1].isdigit():
            parts.append(r"\d{0,3}")
        parts.append(re.escape(ch))
    return re.compile("".join(parts))


def _verbatim(frag: str, haystack: str) -> bool:
    return frag in haystack or bool(_loose_pattern(frag).search(haystack))


MIN_PIECE = 6
MAX_PIECES = 3


def _split_verbatim(frag: str, haystack: str) -> bool:
    """The model glued two or three verbatim pieces without '……': cover the quote greedily with long pieces."""
    i, pieces = 0, 0
    while i < len(frag):
        lo, hi = i, len(frag)  # longest j with frag[i:j] in haystack (substring-closed, so binary search works)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if frag[i:mid] in haystack:
                lo = mid
            else:
                hi = mid - 1
        if lo - i < MIN_PIECE:
            return False
        pieces += 1
        i = lo
    return pieces <= MAX_PIECES


_ASCII_ALNUM = re.compile(r"[0-9A-Za-z]")


def normalize_spaced(s: str) -> str:
    """Like normalize(), but whitespace collapses to one space: keeps displaced digit runs apart ("2 2022 3 7")."""
    s = re.sub(r"[|“”\"'‘’「」『』]+", "", unicodedata.normalize("NFKC", s or ""))
    return re.sub(r"\s+", " ", s)


def _contains_runs(runs: List[str], window: List[str]) -> bool:
    """
    The quote's digits, concatenated, equal the concatenation of a contiguous stretch of whole
    digit runs in the window. Garbled layers may glue a date into one run ("20221124") or split
    it ("2022 11 24"); either way a run is never cut, so 100 cannot match inside 1000.
    """
    target = "".join(runs)
    if not target:
        return True
    for i in range(len(window)):
        acc = ""
        for run in window[i:]:
            acc += run
            if len(acc) >= len(target):
                break
        if acc == target:
            return True
    return False


def _displaced_digits(frag: str, spaced: str) -> bool:
    """
    Garbled text layer: pdfplumber printed the digits (and Latin letters) of a line after it,
    e.g. "本基金自 年 月 日起暂停……\n2 2022 3 7". Accept when the quote minus ASCII letters and
    digits appears in the text minus them, and the quote's digit runs (whole numbers, in order)
    appear among the digit runs that follow the match -- so 100 can never stand in for 1000.
    """
    skel_frag = _ASCII_ALNUM.sub("", frag)
    if len(skel_frag) < MIN_PIECE:
        return False
    keep = [i for i, ch in enumerate(spaced) if not (_ASCII_ALNUM.match(ch) or ch == " ")]
    skel_hay = "".join(spaced[i] for i in keep)
    runs = re.findall(r"\d+", frag)
    start = skel_hay.find(skel_frag)
    while start >= 0:
        lo = keep[start]
        hi = keep[min(start + len(skel_frag), len(keep) - 1)]
        window = re.findall(r"\d+", spaced[lo: hi + 4 * len("".join(runs)) + 60])
        if _contains_runs(runs, window):
            return True
        start = skel_hay.find(skel_frag, start + 1)
    return False


def evidence_level(evidence: str, haystack: str, spaced: Optional[str] = None) -> int:
    """
    0 = fails; 1 = every '……'-separated fragment is verbatim (after normalize);
    2 = verbatim only after tolerating a missing '……', or digits displaced by a garbled text
        layer (that check needs `spaced`, the normalize_spaced() view of the same text).
    """
    frags = [normalize(f) for f in _ELLIPSIS.split(evidence or "")]
    frags = [f for f in frags if f]
    if not frags:
        return 0
    if all(_verbatim(f, haystack) for f in frags):
        return 1
    if all(_verbatim(f, haystack) or _split_verbatim(f, haystack)
           or (spaced is not None and _displaced_digits(f, spaced)) for f in frags):
        return 2
    return 0


def evidence_ok(evidence: str, haystack: str) -> bool:
    return evidence_level(evidence, haystack) > 0


def haystack_of(text: str, tables: List[dict]) -> str:
    cells = "".join("".join(row) for tb in tables for row in tb["rows"])
    return normalize(text) + "\u0000" + normalize(cells)


def spaced_haystack_of(text: str, tables: List[dict]) -> str:
    cells = " ".join(" ".join(row) for tb in tables for row in tb["rows"])
    return normalize_spaced(text) + "\u0000" + normalize_spaced(cells)


def check(a: dict, ctx: dict) -> Tuple[int, List[Tuple[str, str]]]:
    """Validate one structurally valid assertion. Returns (evidence level 0/1/2, [(anomaly kind, detail)])."""
    out = []
    ok = evidence_level(a["evidence"], ctx["haystack"], ctx.get("spaced"))
    if not ok:
        out.append(("evidence_fail", a["evidence"][:200]))
    if a["kind"] == "change":
        # annual holiday schedules announce overlays up to a year ahead
        ahead = 400 if a["layer"] == "overlay" else 90
        lo, hi = ctx["observed_on"] - timedelta(days=30), ctx["observed_on"] + timedelta(days=ahead)
        if not lo <= date.fromisoformat(a["valid_from"]) <= hi:
            out.append(("date_out_of_range", f"change valid_from {a['valid_from']} vs announced {ctx['observed_on']}"))
    if a["status"] == "limited":
        if a["amount"] is None:
            out.append(("null_amount", "limited without amount"))
        elif not 1 <= a["amount"] <= 1e9:
            out.append(("amount_range", f"amount {a['amount']}"))
    if a["fund_code"] not in ctx["codes"]:
        out.append(("unrequested_fund", f"fund_code {a['fund_code']} not in {ctx['codes']}"))
    unknown = [s for s in a["share_codes"] if s != "*" and normalize(s) not in ctx["haystack"]]
    if unknown:
        out.append(("unknown_share_code", f"{unknown} not found in text"))
    return ok, out





def rebuild(conn: sqlite3.Connection, prompt_version: str, model: str) -> dict:
    """Rewrite state_assertions and extraction anomalies from the cached extractions."""
    counts = {"documents": 0, "assertions": 0, "evidence_ok": 0, "evidence_relaxed": 0, "anomalies": 0,
              "schema_error_docs": 0}
    with conn:
        conn.execute("DELETE FROM state_assertions")
        conn.execute(f"DELETE FROM anomalies WHERE kind IN ({','.join('?' * len(ANOMALY_KINDS))})", ANOMALY_KINDS)
        rows = conn.execute(
            "SELECT e.id, e.sha256, e.status, e.raw_response, t.text, t.tables, "
            "(SELECT MIN(announce_date) FROM announcements a WHERE a.sha256 = e.sha256) AS observed_on "
            "FROM extractions e JOIN pdf_texts t ON t.sha256 = e.sha256 "
            "WHERE e.prompt_version = ? AND e.model = ? AND e.status IN ('ok', 'schema_error')",
            (prompt_version, model)).fetchall()
        for r in rows:
            payload = json.loads(r["raw_response"])
            codes = payload["requested_codes"]
            if r["status"] == "schema_error":
                counts["schema_error_docs"] += 1
                for c in codes:
                    conn.execute("INSERT INTO anomalies (fund_code, kind, detail, sha256) VALUES (?, 'schema_error', ?, ?)",
                                 (c, json.dumps(payload.get("errors", [])[-1:], ensure_ascii=False)[:500], r["sha256"]))
                continue
            counts["documents"] += 1
            ctx = {"codes": codes, "observed_on": date.fromisoformat(r["observed_on"]),
                   "haystack": haystack_of(r["text"], json.loads(r["tables"])),
                   "spaced": spaced_haystack_of(r["text"], json.loads(r["tables"]))}
            for a in payload["tool_args"]["assertions"]:
                ok, issues = check(a, ctx)
                cur = conn.execute(
                    "INSERT INTO state_assertions (extraction_id, sha256, fund_code, share_codes, channel, businesses, "
                    "status, amount, currency, valid_from, valid_to, layer, kind, observed_on, prior_status, evidence, "
                    "evidence_ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["id"], r["sha256"], a["fund_code"], json.dumps(a["share_codes"]), a["channel"],
                     json.dumps(a["businesses"]), a["status"], a["amount"], a["currency"], a["valid_from"],
                     a["valid_to"], a["layer"], a["kind"], r["observed_on"], a["prior_status"], a["evidence"], ok))
                counts["assertions"] += 1
                counts["evidence_ok"] += int(ok > 0)
                counts["evidence_relaxed"] += int(ok == 2)
                for kind, detail in issues:
                    counts["anomalies"] += 1
                    conn.execute(
                        "INSERT INTO anomalies (fund_code, date_from, date_to, kind, detail, assertion_ids, sha256) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (a["fund_code"], a["valid_from"], a["valid_to"], kind, detail, json.dumps([cur.lastrowid]),
                         r["sha256"]))
    return counts
