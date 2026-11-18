"""
Assertion-level check of an extraction run against the gold set.

声明级核对：金标的每一行都应该能在它引用的那份 PDF 的抽取结果里找到对应声明。

For each gold row we look at the assertions extracted from the PDF it cites, restricted
to the target path (the fund's exchange code or "*", channel all/agency/exchange,
business purchase, CNY), and grade the best one:

  full      status (and amount) agree, and so do the dates -- an assertion with an end date
            (overlay) is compared on [valid_from, valid_to] whatever the gold layer, a baseline
            change on valid_from, and a restatement skips dates because gold baselines are
            clipped to the labeling window
  state     status agrees and the intervals overlap, but a date differs
  prior     not stated directly, but implied by the next change's prior_status: the change
            right after the gold interval says the state before it was the gold status
            (phase D resolves such days as `inferred_prior`)
  missing   no target-path assertion with that status
  skipped   not gradable: the source is another fund's notice (cross-cited exchange calendar)
            or the PDF was not extracted
"""

import bisect
import sqlite3
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

import pandas as pd

AMOUNT_TOLERANCE = 0.5
GRADES = ("full", "state", "prior", "missing", "skipped")


def on_target(a: sqlite3.Row, fund: str) -> bool:
    """The target path (§7.1); one definition, shared with the timeline builder."""
    from src.pipeline.timeline import matches_target

    return matches_target(a, fund)


def _same_state(a, g) -> bool:
    if a["status"] != g["status"]:
        return False
    if g["status"] == "limited":
        return a["amount"] is not None and abs(a["amount"] - float(g["amount"])) <= AMOUNT_TOLERANCE
    return True


class Calendar:
    """Trading-day snapping, so that a calendar date and the trading day it lands on compare equal."""

    def __init__(self, trading_days: Optional[Sequence[str]] = None):
        self.days = sorted(trading_days) if trading_days else None

    def start(self, d: str) -> str:
        """First trading day on or after d."""
        if not self.days:
            return d
        i = bisect.bisect_left(self.days, d)
        return self.days[i] if i < len(self.days) else d

    def end(self, d: str) -> str:
        """Last trading day on or before d. Past the calendar's last day d is returned as is: the
        trading day it lands on is unknown, and snapping to the last known day would compare a
        2025 notice against 2024-12-31."""
        if not self.days or d > self.days[-1]:
            return d
        i = bisect.bisect_right(self.days, d)
        return self.days[i - 1] if i else d


def _same_dates(a, g, cal: Calendar) -> bool:
    if a["valid_to"] is not None:
        return (cal.start(a["valid_from"]) == cal.start(g["valid_from"])
                and cal.end(a["valid_to"]) == cal.end(g["valid_to"]))
    if g["layer"] == "overlay":
        return False
    return a["kind"] == "restatement" or cal.start(a["valid_from"]) == cal.start(g["valid_from"])


def _overlaps(a, g) -> bool:
    """Same shape (bounded vs open-ended) and overlapping: a holiday overlay inside a long gold baseline does not count."""
    if (a["valid_to"] is None) != (g["layer"] == "baseline"):
        return False
    if a["kind"] == "restatement" and a["valid_to"] is None:
        end = a["observed_on"]
    else:
        end = a["valid_to"] or "9999-12-31"
    return a["valid_from"] <= g["valid_to"] and end >= g["valid_from"]


def _implies_prior(a, g, cal: Calendar) -> bool:
    if g["layer"] != "baseline" or a["prior_status"] != g["status"]:
        return False
    after = (date.fromisoformat(g["valid_to"]) + timedelta(days=1)).isoformat()
    return cal.start(a["valid_from"]) == cal.start(after)


def contradictions(conn: sqlite3.Connection, gold: pd.DataFrame, trading_days: Sequence[str]) -> Dict:
    """
    Precision check: does a target-path assertion (with passing evidence) disagree with the gold
    on the days it speaks about?

    - overlays: every trading day they cover, against the resolved gold (overlays included)
    - baseline changes: their first trading day, against the gold *baseline* (a holiday that
      happens to fall on that day is not a contradiction)
    - restatements: the last trading day before the announcement, against the gold baseline --
      "由 X 调整为 Y" restates X, which held until the change the same notice makes

    `gold` is the parsed gold (load_gold). Returns counts and the disagreeing assertions.
    """
    from src.evaluation.gold import expand_daily

    cal = Calendar(trading_days)
    days = pd.DatetimeIndex(pd.to_datetime(list(trading_days)))
    funds = gold["fund_code"].unique()
    daily = {f: expand_daily(gold, f, days) for f in funds}
    base_only = gold[gold["layer"] == "baseline"]
    baseline = {f: expand_daily(base_only, f, days) for f in funds}
    counts = {"checked": 0, "agree": 0, "disagree": 0, "unlabeled": 0}
    bad = []
    for a in conn.execute("SELECT * FROM state_assertions WHERE evidence_ok > 0"):
        f = a["fund_code"]
        if f not in daily or not on_target(a, f):
            continue
        if a["layer"] == "overlay":
            probe = [d for d in trading_days if a["valid_from"] <= d <= a["valid_to"]]
            g = daily[f]
        elif a["kind"] == "change":
            probe = [cal.start(a["valid_from"])]
            g = baseline[f]
        else:
            before = (date.fromisoformat(a["observed_on"]) - timedelta(days=1)).isoformat()
            probe = [cal.end(before)]
            g = baseline[f]
        probe = [d for d in probe if pd.Timestamp(d) in g.index]
        if not probe:
            counts["unlabeled"] += 1
            continue
        counts["checked"] += 1
        wrong = []
        for d in probe:
            row = g.loc[pd.Timestamp(d)]
            same = row["status"] == a["status"]
            if same and a["status"] == "limited":
                same = a["amount"] is not None and abs(a["amount"] - row["amount"]) <= AMOUNT_TOLERANCE
            if not same:
                amt = f" {row['amount']:,.0f}" if row["status"] == "limited" else ""
                wrong.append(f"{d}: gold {row['status']}{amt}")
        if wrong:
            counts["disagree"] += 1
            bad.append({"assertion": dict(a), "wrong": wrong})
        else:
            counts["agree"] += 1
    return {"counts": counts, "disagreements": bad}


def grade_gold(conn: sqlite3.Connection, gold_raw: pd.DataFrame, prompt_version: str, model: str,
               trading_days: Optional[Sequence[str]] = None) -> List[Dict]:
    """
    Grade every gold row (raw CSV rows, strings) against `state_assertions`, which must have been
    rebuilt from (prompt_version, model). Returns one dict per row with `grade`, `reason` and `best`.
    """
    cal = Calendar(trading_days)
    sha_of = {r["rel_path"]: r["sha256"] for r in conn.execute("SELECT rel_path, sha256 FROM announcements")}
    extracted = {r["sha256"] for r in conn.execute(
        "SELECT sha256 FROM extractions WHERE status = 'ok' AND prompt_version = ? AND model = ?",
        (prompt_version, model))}
    by_sha: Dict[str, list] = {}
    for a in conn.execute("SELECT * FROM state_assertions"):
        by_sha.setdefault(a["sha256"], []).append(a)

    out = []
    for g in gold_raw.to_dict("records"):
        row = dict(g)
        folder = g["source_pdf"].split("/", 1)[0]
        sha = sha_of.get(g["source_pdf"])
        if folder != g["fund_code"]:
            row.update(grade="skipped", reason="cross-cited", best=None)
        elif sha is None or sha not in extracted:
            row.update(grade="skipped", reason="not extracted", best=None)
        else:
            cands = [a for a in by_sha.get(sha, []) if on_target(a, g["fund_code"])]
            full = [a for a in cands if _same_state(a, g) and _same_dates(a, g, cal)]
            state = [a for a in cands if _same_state(a, g) and _overlaps(a, g)]
            prior = [a for a in cands if _implies_prior(a, g, cal)]
            if full:
                row.update(grade="full", reason="", best=dict(full[0]))
            elif state:
                row.update(grade="state", reason="date differs", best=dict(state[0]))
            elif prior:
                row.update(grade="prior", reason="implied by the next change", best=dict(prior[0]))
            else:
                row.update(grade="missing", reason=f"{len(cands)} target-path assertions",
                           best=dict(cands[0]) if cands else None)
        out.append(row)
    return out
