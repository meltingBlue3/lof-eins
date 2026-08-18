"""
Post-processing: convert subscription_restrictions event stream to limit_events intervals.

Pipeline:
1. Load raw records from subscription_restrictions table
2. Deduplicate (annual arrangement vs single announcement overlap)
3. Fix resume records missing restriction_type
4. Build backtest intervals (suspend/restrict → resume pairing)
5. Write to limit_events table

Usage:
    >>> from src.data.postprocess import postprocess
    >>> stats = postprocess("data/real_all_lof/config/fund_status.db")
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


# The six values permitted by the subscription_restrictions.restriction_type
# CHECK constraint in src/data/downloader.py. Keep the two definitions in
# step -- if the database constraint is ever widened, this constant must be
# updated in the same change, or build_limit_events()/validate() will start
# rejecting legitimate new restriction types.
KNOWN_RESTRICTION_TYPES = frozenset(
    {
        "amount_limit",
        "full_suspension",
        "holiday_suspension",
        "pre_holiday_suspension",
        "application_invalid",
        "rule_change",
    }
)


class ValidationBlockedError(RuntimeError):
    """Raised by postprocess() when validate() reports one or more issues.

    Carries the full issue list so callers (e.g. the CLI) can surface every
    finding to the operator. limit_events is never written when this is
    raised.
    """

    def __init__(self, issues: List[str]):
        self.issues: List[str] = issues
        super().__init__(f"校验未通过，已阻止写入 limit_events: {len(issues)} 个问题")


def load_records(db_path: str | Path) -> List[dict]:
    """Load all records from subscription_restrictions table."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM subscription_restrictions ORDER BY id").fetchall()
    conn.close()
    records = []
    for row in rows:
        r = dict(row)
        # Parse affected_business from JSON string
        ab = r.get("affected_business", "[]")
        if isinstance(ab, str):
            try:
                r["affected_business"] = json.loads(ab)
            except (json.JSONDecodeError, TypeError):
                r["affected_business"] = []
        records.append(r)
    return records


def dedup_records(records: List[dict]) -> List[dict]:
    """
    Deduplicate by (fund_code, effective_date, action).
    Prefer single announcements over annual arrangements (more specific).
    Among same type, prefer latest announcement_date.
    """
    groups = defaultdict(list)
    for r in records:
        key = (r["fund_code"], r["effective_date"], r["action"])
        groups[key].append(r)

    deduped = []
    dup_count = 0
    for key, group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        dup_count += len(group) - 1

        def is_annual(r):
            src = r.get("source_file", "")
            return ("年" in src and "安排" in src) or ("年" in src and "节假日" in src)

        single = [r for r in group if not is_annual(r)]
        annual = [r for r in group if is_annual(r)]

        if single:
            best = max(single, key=lambda r: r.get("announcement_date", ""))
            deduped.append(best)
        else:
            best = max(annual, key=lambda r: r.get("announcement_date", ""))
            deduped.append(best)

    print(f"去重: {len(records)} → {len(deduped)} (移除 {dup_count} 条重复)")
    return deduped


def fix_resume_type(records: List[dict]) -> List[dict]:
    """
    Fill missing restriction_type on resume records
    by inheriting from the nearest preceding suspend/restrict.

    Note (WR-04): 'adjust_rule' is a legal value of the
    subscription_restrictions.action CHECK constraint, but it deliberately
    does not update last_type here (nor does build_limit_events() or
    validate() match on it elsewhere) -- an adjust_rule record represents a
    change to an existing restriction's rules, not a new suspend/restrict
    state, so it intentionally never produces a limit_events interval and
    is never referenced in source_announcement_ids. See
    tests.test_postprocess.TestAdjustRuleIsIntentionalNoOp.
    """
    fixed = 0
    by_fund = defaultdict(list)
    for r in records:
        by_fund[r["fund_code"]].append(r)

    for fund, fund_records in by_fund.items():
        fund_records.sort(key=lambda r: r["effective_date"])
        last_type = None
        for r in fund_records:
            if r["action"] in ("suspend", "restrict", "invalidate"):
                last_type = r["restriction_type"]
            elif r["action"] == "resume" and not r.get("restriction_type"):
                if last_type:
                    r["restriction_type"] = last_type
                    fixed += 1

    print(f"修复 resume restriction_type: {fixed} 条")
    return records


def _is_holiday_resume(record: dict) -> bool:
    """Check if a resume record is holiday-related (should not terminate long-term suspends).

    Holiday resumes only lift the holiday pause; any pre-existing long-term
    suspension remains in effect, as stated in fund announcements:
    "本次恢复后仍受相关交易状态限制".
    """
    src = record.get("source_file", "")
    rtype = record.get("restriction_type", "")
    return (
        rtype in ("holiday_suspension", "application_invalid")
        or "节假日" in src
        or "境外" in src
    )


def build_limit_events(records: List[dict]) -> List[dict]:
    """
    Convert event stream to limit_events intervals for backtesting.

    For each fund, processes suspend/restrict events and pairs them with
    corresponding resume events to form [start, end] intervals.

    Returns list of dicts with: ticker, start_date, end_date, max_amount, reason.
    """
    by_fund = defaultdict(list)
    for r in records:
        by_fund[r["fund_code"]].append(r)

    intervals = []
    synthetic_count = 0
    for fund, fund_records in by_fund.items():
        fund_records.sort(key=lambda r: r["effective_date"])

        # Detect missing prior suspend: if the first non-holiday event is a
        # resume, the original suspension predates our data range.  Add a
        # synthetic suspend from the earliest possible date so the gap is
        # covered.  (e.g. 161129 was suspended since 2020-03 but our data
        # starts 2022-01.)
        first_non_holiday = None
        for rec in fund_records:
            if not _is_holiday_resume(rec):
                first_non_holiday = rec
                break
        if first_non_holiday and first_non_holiday["action"] == "resume":
            resume_date = first_non_holiday["effective_date"]
            try:
                end_dt = datetime.strptime(resume_date, "%Y-%m-%d") - timedelta(
                    days=1
                )
                synth_end = end_dt.strftime("%Y-%m-%d")
            except ValueError:
                synth_end = resume_date
            intervals.append(
                {
                    "ticker": fund,
                    "start_date": "2000-01-01",
                    "end_date": synth_end,
                    "max_amount": 0.0,
                    "reason": "synthetic - suspension predates data range",
                    "source_announcement_ids": "[]",
                }
            )
            synthetic_count += 1

        i = 0
        while i < len(fund_records):
            r = fund_records[i]

            # WR-04: 'adjust_rule' (a legal action value) intentionally
            # falls through this branch untouched -- it represents a rule
            # change to an existing restriction rather than a new
            # suspend/restrict state, so it produces no limit_events
            # interval. See fix_resume_type()'s docstring note and
            # tests.test_postprocess.TestAdjustRuleIsIntentionalNoOp.
            if r["action"] in ("suspend", "restrict", "invalidate"):
                start = r["effective_date"]
                end = r.get("end_date")
                limit = r.get("limit_amount")
                rtype = r.get("restriction_type", "")

                # Fail loud on an unrecognised non-empty restriction_type
                # (D-06 item 5) instead of silently falling through to the
                # default zero-amount branch below as though it were a
                # known suspension type. None/empty is the "unspecified"
                # case -- 32 production records carry it after
                # fix_resume_type() runs -- and must NOT be treated as
                # unknown.
                if rtype and rtype not in KNOWN_RESTRICTION_TYPES:
                    raise ValueError(
                        f"未知 restriction_type: {rtype!r} "
                        f"(fund_code={fund}, effective_date={r['effective_date']})"
                    )

                # Holiday/application_invalid are inherently single-day;
                # never pair them with a distant resume
                if rtype in ("holiday_suspension", "application_invalid"):
                    if not end:
                        end = start
                elif end:
                    # The announcement itself already stated an explicit
                    # end_date -- that is authoritative. Do NOT let a later,
                    # unrelated resume's date overwrite it (CR-03): the
                    # resume-lookahead below is only a fallback for records
                    # that did not carry their own end_date.
                    pass
                else:
                    # Look for matching resume (skip holiday resumes)
                    found_resume = False
                    for j in range(i + 1, len(fund_records)):
                        nxt = fund_records[j]
                        if nxt["action"] == "resume":
                            # Holiday resumes don't terminate long-term suspends
                            if _is_holiday_resume(nxt):
                                continue
                            try:
                                resume_date = datetime.strptime(
                                    nxt["effective_date"], "%Y-%m-%d"
                                )
                                end = (resume_date - timedelta(days=1)).strftime(
                                    "%Y-%m-%d"
                                )
                            except ValueError:
                                end = nxt["effective_date"]
                            found_resume = True
                            break

                    if not found_resume and not end:
                        end = None  # Open-ended → NULL in limit_events

                # Inverted-interval clamp: a non-holiday resume sharing the
                # suspend/restrict's effective_date computes end = start - 1
                # day above, which runs backwards. Clamp to a single-day
                # interval instead of emitting a corrupt range -- 7 such
                # backwards intervals exist in current production output.
                # The NULL open-ended case is left untouched.
                if end is not None and end < start:
                    end = start

                # Determine max_amount for limit_events
                if r["action"] == "suspend" or rtype in (
                    "full_suspension",
                    "holiday_suspension",
                    "pre_holiday_suspension",
                    "application_invalid",
                ):
                    max_amount = 0.0  # Cannot purchase at all
                elif limit is not None:
                    max_amount = limit  # Amount limit
                else:
                    max_amount = 0.0  # Default to suspended

                # Build reason string
                reason_parts = []
                if rtype:
                    reason_parts.append(rtype)
                if r.get("reason"):
                    reason_parts.append(r["reason"])
                reason = " - ".join(reason_parts) if reason_parts else None

                source_ids = json.dumps(
                    [r.get("source_file", "")], ensure_ascii=False
                )

                intervals.append(
                    {
                        "ticker": fund,
                        "start_date": start,
                        "end_date": end,
                        "max_amount": max_amount,
                        "reason": reason,
                        "source_announcement_ids": source_ids,
                    }
                )

            i += 1

    print(
        f"构建 limit_events: {len(by_fund)} 只基金, "
        f"{len(intervals)} 个限制区间 "
        f"(含 {synthetic_count} 个合成前置暂停)"
    )
    return intervals


def write_limit_events(db_path: str | Path, events: List[dict]):
    """Write intervals to limit_events table (replaces existing data).

    Stages every row into a scratch `limit_events_new` table inside a single
    explicit transaction, and only drops/replaces the live `limit_events`
    table once every insert has succeeded. A failure at any point rolls the
    whole transaction back -- including the staging table's own creation --
    so the previously-written `limit_events` table is left byte-identical
    and the exception is re-raised for the caller to see.
    """
    # isolation_level=None disables the driver's implicit-transaction
    # handling entirely, so an explicit BEGIN below is the only thing that
    # opens a transaction. This matters because the driver only opens an
    # implicit transaction ahead of data-manipulation statements, not
    # data-definition ones -- without this, the DROP/CREATE/ALTER statements
    # here would each commit immediately and defeat the whole design.
    conn = sqlite3.connect(db_path, isolation_level=None)
    cursor = conn.cursor()

    in_transaction = False
    try:
        cursor.execute("BEGIN IMMEDIATE")
        in_transaction = True

        # Clear any staging-table residue left by a hard process kill on a
        # previous run.
        cursor.execute("DROP TABLE IF EXISTS limit_events_new")
        cursor.execute("""
            CREATE TABLE limit_events_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                max_amount REAL NOT NULL,
                reason TEXT,
                source_announcement_ids TEXT DEFAULT '[]',
                is_open_ended INTEGER GENERATED ALWAYS AS (
                    CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                ) STORED
            )
        """)

        for ev in events:
            cursor.execute(
                """
                INSERT INTO limit_events_new
                (ticker, start_date, end_date, max_amount, reason, source_announcement_ids)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ev["ticker"],
                    ev["start_date"],
                    ev["end_date"],
                    ev["max_amount"],
                    ev["reason"],
                    ev.get("source_announcement_ids", "[]"),
                ),
            )

        # Every row is staged -- only now touch the live table.
        cursor.execute("DROP TABLE IF EXISTS limit_events")
        cursor.execute("ALTER TABLE limit_events_new RENAME TO limit_events")
        cursor.execute("""
            CREATE INDEX idx_limit_events_ticker
            ON limit_events(ticker)
        """)
        cursor.execute("""
            CREATE INDEX idx_limit_events_is_open_ended
            ON limit_events(is_open_ended)
        """)

        cursor.execute("COMMIT")
        in_transaction = False
    except Exception:
        if in_transaction:
            # Rolling back also drops limit_events_new, since it was
            # created inside this same transaction -- no separate cleanup
            # needed on this path.
            cursor.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    print(f"已写入 {len(events)} 条 limit_events")


def validate(records: List[dict]) -> List[str]:
    """Backtest readiness validation.

    Returns:
        The list of issue strings found (empty list when there are none).
    """
    issues = []
    by_fund = defaultdict(list)
    for r in records:
        by_fund[r["fund_code"]].append(r)

    for fund, fund_records in by_fund.items():
        fund_records.sort(key=lambda r: r["effective_date"])

        # Check: non-empty restriction_type outside the known allowlist
        # (mirrors the fail-loud check in build_limit_events()). This lets
        # postprocess() block a run with an actionable message before
        # build_limit_events()'s ValueError is ever reached. None/empty is
        # the "unspecified" case and is intentionally not flagged here.
        for r in fund_records:
            rtype = r.get("restriction_type")
            if rtype and rtype not in KNOWN_RESTRICTION_TYPES:
                issues.append(
                    f"  {fund} {r['effective_date']} {r['action']} "
                    f"未知的 restriction_type: {rtype}"
                )

        # Check: restrict/suspend should have resume (non-holiday). Only
        # 'restrict'/'suspend' are considered here -- 'adjust_rule' is
        # intentionally excluded (WR-04, same as build_limit_events() and
        # fix_resume_type()): it represents a rule change, not a new open
        # restriction awaiting a resume.
        #
        # Mirrors build_limit_events()'s actual pairing semantics (WR-01):
        # each restrict/suspend independently searches forward for the
        # nearest following non-holiday resume, rather than popping off a
        # LIFO stack. A LIFO stack disagrees with build_limit_events() when
        # two restrictions are open at once and a single later resume
        # legitimately closes both -- build_limit_events() closes both,
        # but a stack only pops one, leaving the other falsely flagged as
        # unresolved and blocking a legitimate run.
        open_restrictions = []
        for idx, r in enumerate(fund_records):
            if r["action"] not in ("restrict", "suspend"):
                continue
            rtype = r.get("restriction_type")
            if rtype in ("holiday_suspension", "application_invalid"):
                # Inherently single-day, same as build_limit_events() --
                # never left "open" waiting on a resume.
                continue
            found_resume = any(
                nxt["action"] == "resume" and not _is_holiday_resume(nxt)
                for nxt in fund_records[idx + 1 :]
            )
            if not found_resume:
                open_restrictions.append(r)

        for r in open_restrictions:
            try:
                eff = datetime.strptime(r["effective_date"], "%Y-%m-%d")
            except ValueError:
                # WR-03: a malformed effective_date must be surfaced as its
                # own issue, not silently disable the staleness check for
                # this record.
                issues.append(
                    f"  {fund} {r['effective_date']} {r['action']} "
                    f"{r.get('restriction_type')} effective_date 格式无法解析"
                )
                continue
            if (datetime.now() - eff).days > 180:
                issues.append(
                    f"  {fund} {r['effective_date']} {r['action']} "
                    f"{r.get('restriction_type')} 无对应resume（超180天）"
                )

        # Check: effective_date should not be before announcement_date
        for r in fund_records:
            if r.get("announcement_date") and r.get("effective_date"):
                if r["effective_date"] < r["announcement_date"]:
                    if "年" not in r.get("source_file", ""):
                        issues.append(
                            f"  {fund} effective_date({r['effective_date']}) "
                            f"< announcement_date({r['announcement_date']})"
                        )

    print(f"\n回测校验问题: {len(issues)} 个")
    for issue in issues[:20]:
        print(issue)
    if len(issues) > 20:
        print(f"  ... 还有 {len(issues) - 20} 个")

    return issues


def postprocess(db_path: str | Path) -> dict:
    """
    Full postprocessing pipeline:
    subscription_restrictions → dedup → fix → limit_events.

    Args:
        db_path: Path to fund_status.db.

    Returns:
        Stats dict.

    Raises:
        ValidationBlockedError: when validate() reports one or more issues.
            limit_events is not written in this case; the previously written
            table (if any) is left untouched.
    """
    db_path = Path(db_path)

    records = load_records(db_path)
    raw_count = len(records)
    print(f"加载 {raw_count} 条原始记录")

    if not records:
        print("无记录，跳过后处理")
        return {"raw": 0, "deduped": 0, "intervals": 0}

    records = dedup_records(records)
    records = fix_resume_type(records)

    issues = validate(records)
    if issues:
        raise ValidationBlockedError(issues)

    events = build_limit_events(records)
    if records and not events:
        raise ValidationBlockedError(
            [
                f"  {len(records)} 条原始记录，但构建出 0 个 limit_events 区间 "
                "-- 拒绝清空现有 limit_events，请人工确认后再处理"
            ]
        )
    write_limit_events(db_path, events)

    return {
        "raw": raw_count,
        "deduped": len(records),
        "intervals": len(events),
    }
