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

            if r["action"] in ("suspend", "restrict", "invalidate"):
                start = r["effective_date"]
                end = r.get("end_date")
                limit = r.get("limit_amount")
                rtype = r.get("restriction_type", "")

                # Holiday/application_invalid are inherently single-day;
                # never pair them with a distant resume
                if rtype in ("holiday_suspension", "application_invalid"):
                    if not end:
                        end = start
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
    """Write intervals to limit_events table (replaces existing data)."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Recreate limit_events table with current schema
    cursor.execute("DROP TABLE IF EXISTS limit_events")
    cursor.execute("""
        CREATE TABLE limit_events (
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
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_limit_events_ticker
        ON limit_events(ticker)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
        ON limit_events(is_open_ended)
    """)

    for ev in events:
        cursor.execute(
            """
            INSERT INTO limit_events
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

    conn.commit()
    conn.close()
    print(f"已写入 {len(events)} 条 limit_events")


def validate(records: List[dict]):
    """Backtest readiness validation."""
    issues = []
    by_fund = defaultdict(list)
    for r in records:
        by_fund[r["fund_code"]].append(r)

    for fund, fund_records in by_fund.items():
        fund_records.sort(key=lambda r: r["effective_date"])

        # Check: restrict/suspend should have resume (non-holiday)
        open_restrictions = []
        for r in fund_records:
            if r["action"] in ("restrict", "suspend"):
                if r.get("restriction_type") not in ("holiday_suspension",):
                    open_restrictions.append(r)
            elif r["action"] == "resume":
                if open_restrictions:
                    open_restrictions.pop()

        for r in open_restrictions:
            try:
                eff = datetime.strptime(r["effective_date"], "%Y-%m-%d")
                if (datetime.now() - eff).days > 180:
                    issues.append(
                        f"  {fund} {r['effective_date']} {r['action']} "
                        f"{r.get('restriction_type')} 无对应resume（超180天）"
                    )
            except ValueError:
                pass

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


def postprocess(db_path: str | Path) -> dict:
    """
    Full postprocessing pipeline:
    subscription_restrictions → dedup → fix → limit_events.

    Args:
        db_path: Path to fund_status.db.

    Returns:
        Stats dict.
    """
    db_path = Path(db_path)

    records = load_records(db_path)
    print(f"加载 {len(records)} 条原始记录")

    if not records:
        print("无记录，跳过后处理")
        return {"raw": 0, "deduped": 0, "intervals": 0}

    records = dedup_records(records)
    records = fix_resume_type(records)

    validate(records)

    events = build_limit_events(records)
    write_limit_events(db_path, events)

    return {
        "raw": len(records),
        "deduped": len(records),
        "intervals": len(events),
    }
