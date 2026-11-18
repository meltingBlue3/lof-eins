"""
Phase D: resolve state assertions into one purchase status per fund per trading day.

阶段 D：把状态声明解析成"每只基金、每个交易日"的申购状态（表 daily_status）。

Only the target path is materialised -- the fund's exchange code (or "*"), channel
exchange / agency / all, business purchase, CNY, evidence passing (§7.1). For each day:

1. overlay: the latest-announced overlay covering the day (ties: the stricter one).
   An `open` overlay is read by what it does, not taken literally:
   - window -- a periodic-open fund's opening period (the same notice closes the fund
     again from the next trading day): the fund is open, but a baseline limit still holds;
   - cancel -- "新增港股通交易日照常开放" and the like: only undoes a scheduled closure,
     so the day falls back to the baseline.
2. baseline: the last baseline event on or before the day. Events are changes and
   restatements; a restatement ("根据相关公告，本基金自 X 日起暂停申购") is an implied
   change at its valid_from, ranked below an explicit change of the same day.
3. before the first event: an explicit prior state (`inferred_prior`); else, for a fund that
   announces temporary suspensions, `inferred_open`; else unknown (see `_pre_history`).

Rules for patterns the full extraction showed (redesign §7.2):

- institution-only notices ("机构投资者" without "个人投资者") are not on the target path;
- a resumption right after an overlay of the same notice ("X 日暂停……X+1 日起恢复") returns
  to the pre-holiday baseline: an `open` change there is ignored, and a prior_status equal to
  that overlay's status describes the overlay, not the baseline, so it is dropped;
- `limited` without an amount inherits the amount in force before it ("仍然限制，具体见相关公告").

Genuine conflicts are resolved to the stricter state and written to `anomalies`:
same-day changes of the same specificity that disagree, an earlier-announced change
leapfrogged by a later-announced one with an earlier effective date, a restatement
contradicted by a change announced before it, and an overlay overridden by a baseline
change announced after it. Everything here is a pure function of `state_assertions`.
"""

import bisect
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

TARGET_CHANNELS = ("exchange", "agency", "all")
SPECIFICITY = {"all": 0, "agency": 1, "exchange": 2}   # ties on one day: the more specific channel wins
RANK = {"closed": 0, "limited": 1, "open": 2}
LONG_INFERENCE_DAYS = 365
INFERRED_OPEN_DAYS = 190      # QDII and 港股通 funds announce a closure every month or two; bridges a quiet half-year
INFERRED_OPEN_BACK_DAYS = 30  # the corpus starts 2022-01; the first holiday notices come a week or two later
ANOMALY_KINDS = ("investor_scope", "ignored_resume", "conflict_same_day", "conflict_leapfrog",
                 "conflict_restatement", "overlay_overridden", "long_inferred_prior")

DAILY_STATUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_status (
  fund_code      TEXT NOT NULL,
  date           DATE NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('open','limited','closed','unknown')),
  amount         REAL,
  source         TEXT NOT NULL CHECK (source IN ('overlay','change','restatement','inferred_prior',
                                                'inferred_open','default')),
  assertion_ids  TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (fund_code, date)
);
"""


# ------------------------------------------------------------------------------ values

@dataclass(frozen=True)
class State:
    status: str                      # open / limited / closed / unknown
    amount: Optional[float] = None   # limited only; None = amount not stated


UNKNOWN = State("unknown")


def stricter(a: State, b: State) -> State:
    """The state allowing less purchase. A limit with a known amount beats one without."""
    if a.status != b.status:
        return a if RANK[a.status] < RANK[b.status] else b
    if a.status == "limited":
        if a.amount is None:
            return b
        if b.amount is None:
            return a
        return a if a.amount <= b.amount else b
    return a


def same_state(a: State, b: State) -> bool:
    if a.status != b.status:
        return False
    return a.status != "limited" or a.amount is None or b.amount is None or abs(a.amount - b.amount) <= 0.5


@dataclass(frozen=True)
class Assertion:
    id: int
    sha256: str
    fund_code: str
    status: str
    amount: Optional[float]
    valid_from: str
    valid_to: Optional[str]
    layer: str
    kind: str
    observed_on: str
    prior_status: Optional[str]
    channel: str
    evidence: str

    @property
    def state(self) -> State:
        return State(self.status, self.amount if self.status == "limited" else None)

    @classmethod
    def from_row(cls, r) -> "Assertion":
        return cls(r["id"], r["sha256"], r["fund_code"], r["status"], r["amount"], r["valid_from"], r["valid_to"],
                   r["layer"], r["kind"], r["observed_on"], r["prior_status"], r["channel"], r["evidence"])


def matches_target(a, fund_code: str) -> bool:
    """§7.1: the path the arbitrage trade takes. `a` is a state_assertions row or an Assertion-like mapping."""
    shares = json.loads(a["share_codes"])
    return (a["fund_code"] == fund_code and a["channel"] in TARGET_CHANNELS
            and "purchase" in json.loads(a["businesses"]) and a["currency"] == "CNY"
            and (fund_code in shares or "*" in shares))


def institution_only(evidence: str) -> bool:
    """The quote limits institutional investors only -- not the individual account the arbitrage uses."""
    text = evidence.replace("非个人投资者", "机构投资者")
    return "机构投资者" in text and not any(k in text for k in ("个人投资者", "包括个人", "所有投资者", "全部投资者"))


class Calendar:
    def __init__(self, days: Sequence[str]):
        self.days = sorted(days)

    def between(self, lo: str, hi: str) -> List[str]:
        """Trading days d with lo <= d <= hi."""
        return self.days[bisect.bisect_left(self.days, lo):bisect.bisect_right(self.days, hi)]

    def adjacent(self, end: str, start: str) -> bool:
        """No trading day strictly between end and start (end < start). Past the calendar: at most 4 calendar days."""
        if end >= start:
            return False
        if not self.days or end >= self.days[-1]:
            return (date.fromisoformat(start) - date.fromisoformat(end)).days <= 4
        return bisect.bisect_left(self.days, start) == bisect.bisect_right(self.days, end)


# ------------------------------------------------------------------------------ one fund

@dataclass
class Day:
    status: str
    amount: Optional[float]
    source: str
    assertion_ids: List[int]


@dataclass
class FundTimeline:
    days: Dict[str, Day]
    anomalies: List[dict] = field(default_factory=list)


def _event_key(e: Assertion):
    return (e.valid_from, 0 if e.kind == "restatement" else 1, e.observed_on, SPECIFICITY[e.channel], e.id)


def _pre_history(events: List[Assertion], prior_of: Dict[int, Optional[str]],
                 overlays: List[Tuple[Assertion, str]], by_doc: Dict[str, List[Assertion]],
                 unverified: Sequence[Assertion] = ()):
    """
    The baseline before the first baseline event, strongest evidence first:

    1. an explicit prior state -- the first change's prior_status, or the prior of a periodic-open
       fund's first opening window ("每三年开放一次": closed before it). A limited prior takes the
       amount the same notice restates, if any;
    2. `inferred_open`: the fund announced temporary suspensions ("暂停申购……恢复申购"), so purchase
       was otherwise possible -- from INFERRED_OPEN_BACK_DAYS before the first such notice to
       INFERRED_OPEN_DAYS after the last, and never past a baseline claim whose evidence failed
       (something changed there that could not be verified). Whether a limit applied is not known,
       so the source is kept apart for the backtest's conservative bound;
    3. unknown.
    """
    v0 = events[0].valid_from if events else None
    anchors = []
    first_change = next((e for e in events if e.kind == "change"), None)
    if first_change and first_change.valid_from == v0 and prior_of.get(first_change.id):
        anchors.append((v0, prior_of[first_change.id], first_change))
    for o, role in overlays:
        if role == "window" and o.prior_status and (v0 is None or o.valid_from < v0):
            anchors.append((o.valid_from, o.prior_status, o))
    if anchors:
        _, status, a = min(anchors, key=lambda x: x[0])
        amount = None
        if status == "limited":
            restated = [r for r in by_doc[a.sha256] if r.kind == "restatement" and r.status == "limited" and r.amount]
            amount = restated[0].amount if restated else None
        state = State(status, amount)
        return lambda d: (state, "inferred_prior", [a.id])

    evidence = sorted({o.observed_on for o, role in overlays if role != "window"})
    if not evidence:
        return lambda d: (UNKNOWN, "default", [])
    lo = (date.fromisoformat(evidence[0]) - timedelta(days=INFERRED_OPEN_BACK_DAYS)).isoformat()
    hi = (date.fromisoformat(evidence[-1]) + timedelta(days=INFERRED_OPEN_DAYS)).isoformat()
    blocked = min((u.valid_from for u in unverified if u.layer == "baseline"), default="9999-12-31")
    return lambda d: ((State("open"), "inferred_open", []) if lo <= d <= hi and d < blocked
                      else (UNKNOWN, "default", []))


def resolve_fund(fund: str, assertions: Iterable[Assertion], cal: Calendar,
                 unverified: Iterable[Assertion] = ()) -> FundTimeline:
    """
    Resolve one fund's target-path assertions (matches_target, evidence passing) over `cal`.
    `unverified` are its target-path assertions whose evidence failed: never materialised, they
    only stop `inferred_open` (see _pre_history).
    """
    anomalies: Dict[tuple, dict] = {}

    def flag(kind: str, ids: Sequence[int], day: Optional[str], detail: str):
        key = (kind, tuple(sorted(set(ids))))
        a = anomalies.setdefault(key, {"fund_code": fund, "kind": kind, "assertion_ids": sorted(set(ids)),
                                       "date_from": day, "date_to": day, "detail": detail})
        if day is not None:
            a["date_from"] = min(filter(None, [a["date_from"], day]))
            a["date_to"] = max(filter(None, [a["date_to"], day]))

    kept: List[Assertion] = []
    for a in assertions:
        if institution_only(a.evidence):   # any status: "取消机构投资者限额" must not open the fund for everyone
            flag("investor_scope", [a.id], a.valid_from, f"institution-only {a.status} {a.amount}: {a.evidence[:80]}")
        else:
            kept.append(a)
    by_doc: Dict[str, List[Assertion]] = defaultdict(list)
    for a in kept:
        by_doc[a.sha256].append(a)

    # overlays and their role
    overlays: List[Tuple[Assertion, str]] = []
    for o in (a for a in kept if a.layer == "overlay"):
        role = "state"
        if o.status == "open":
            closes = any(s.layer == "baseline" and s.kind == "change" and s.status == "closed"
                         and cal.adjacent(o.valid_to, s.valid_from) for s in by_doc[o.sha256])
            role = "window" if closes else "cancel"
        overlays.append((o, role))

    # baseline events, with holiday resumptions removed and their prior dropped
    events: List[Assertion] = []
    prior_of: Dict[int, Optional[str]] = {}
    for c in (a for a in kept if a.layer == "baseline"):
        prior = c.prior_status
        if c.kind == "change":
            before = [o for o in by_doc[c.sha256] if o.layer == "overlay" and o.status in ("closed", "limited")
                      and cal.adjacent(o.valid_to, c.valid_from)]
            if before:
                if prior in {o.status for o in before}:
                    prior = None
                if c.status == "open" and prior is None:
                    flag("ignored_resume", [c.id] + [o.id for o in before], c.valid_from,
                         "resumption right after a closure of the same notice: back to the pre-holiday baseline")
                    continue
        prior_of[c.id] = prior
        events.append(c)
    events.sort(key=_event_key)
    starts = [e.valid_from for e in events]

    # value per event: limited without an amount inherits the amount in force. Conflicts are judged on
    # what each notice says (`raw`): an unstated amount never disagrees.
    raw = [e.state for e in events]
    resolved: List[State] = []
    for s in raw:
        if s.status == "limited" and s.amount is None and resolved and resolved[-1].status == "limited":
            s = State("limited", resolved[-1].amount)
        resolved.append(s)
    changes = [(i, e) for i, e in enumerate(events) if e.kind == "change"]
    restatements = [(i, e) for i, e in enumerate(events) if e.kind == "restatement"]
    pre_history = _pre_history(events, prior_of, overlays, by_doc, list(unverified))

    def baseline(d: str) -> Tuple[State, str, List[int]]:
        k = bisect.bisect_right(starts, d) - 1
        if k < 0:
            return pre_history(d)
        e, state = events[k], resolved[k]
        ids = [e.id]
        # same day, same specificity, announced together, disagreeing
        same = [i for i, x in enumerate(events) if x.valid_from == e.valid_from and x.kind == e.kind
                and x.observed_on == e.observed_on and SPECIFICITY[x.channel] == SPECIFICITY[e.channel]
                and not same_state(raw[i], raw[k])]
        if same:
            for i in same:
                state = stricter(state, resolved[i])
            flag("conflict_same_day", [e.id] + [events[i].id for i in same], d,
                 "changes effective the same day disagree; the stricter is used")
            ids += [events[i].id for i in same]
        if e.kind == "change":
            # leapfrog: announced after e, effective before it, different state
            for i, f in changes:
                if f.valid_from < e.valid_from and f.observed_on > e.observed_on and not same_state(raw[i], raw[k]):
                    state = stricter(state, resolved[i])
                    ids.append(f.id)
                    flag("conflict_leapfrog", [e.id, f.id], d,
                         f"{e.observed_on} notice effective {e.valid_from} vs later {f.observed_on} notice effective "
                         f"{f.valid_from}; the stricter is used")
            # restatement written after e, claiming its state held through e's start, and stricter than e
            for i, r in restatements:
                if (r.valid_from <= e.valid_from and r.valid_from <= d <= r.observed_on and r.sha256 != e.sha256
                        and e.observed_on < r.observed_on and not same_state(raw[i], raw[k])
                        and stricter(raw[i], state) == raw[i]):
                    state = raw[i]
                    ids.append(r.id)
                    flag("conflict_restatement", [e.id, r.id], d,
                         f"restatement of {r.observed_on} says {r.status} since {r.valid_from}; the stricter is used")
        return state, ("change" if e.kind == "change" else "restatement"), ids

    by_day: Dict[str, List[Tuple[Assertion, str]]] = defaultdict(list)
    for o, role in overlays:
        for d in cal.between(o.valid_from, o.valid_to):
            by_day[d].append((o, role))

    def overlay_rank(item):
        o, role = item
        strict = {"state": RANK[o.status], "window": 2, "cancel": 3}[role]
        return (o.observed_on, -strict, -(o.amount or 0))

    out: Dict[str, Day] = {}
    for d in cal.days:
        base, source, ids = baseline(d)
        cover = by_day.get(d)
        if cover:
            o, role = max(cover, key=overlay_rank)
            if role == "cancel":
                state = base
            else:
                if role == "window":
                    state = base if base.status in ("limited", "open") else State("open")
                elif o.status == "limited" and o.amount is None and base.status == "limited":
                    state = base      # "暂停大额申购" without an amount: the limit in force
                else:
                    state = o.state
                source = "overlay"
                # a baseline change announced after the overlay still applies when it is stricter
                k = bisect.bisect_right(starts, d) - 1
                if k >= 0 and events[k].kind == "change" and events[k].observed_on > o.observed_on:
                    later = stricter(state, base)
                    if later != state:
                        flag("overlay_overridden", [o.id, events[k].id], d,
                             f"overlay of {o.observed_on} vs stricter change announced {events[k].observed_on}")
                        state, source = later, "change"
                ids = [o.id] + ids
        else:
            state = base
        out[d] = Day(state.status, state.amount if state.status == "limited" else None, source, ids)

    inferred = [d for d, x in out.items() if x.source == "inferred_prior"]
    if inferred:
        span = (date.fromisoformat(inferred[-1]) - date.fromisoformat(inferred[0])).days
        if span > LONG_INFERENCE_DAYS:
            ids = out[inferred[0]].assertion_ids
            flag("long_inferred_prior", ids, inferred[0],
                 f"{out[inferred[0]].status} inferred back {span} days from assertion {ids}")
            flag("long_inferred_prior", ids, inferred[-1], "")
    return FundTimeline(out, list(anomalies.values()))


# ------------------------------------------------------------------------------ all funds

def trading_calendar(market_dir: Union[str, Path]) -> List[str]:
    """A-share trading days: every date with a bar in any fund's market file."""
    import pandas as pd

    days = set()
    for p in Path(market_dir).glob("*.parquet"):
        days.update(pd.read_parquet(p, columns=["date"])["date"].astype(str).str[:10])
    return sorted(days)


def target_assertions(conn: sqlite3.Connection) -> Tuple[Dict[str, List[Assertion]], Dict[str, List[Assertion]]]:
    """Target-path assertions per fund: (evidence passing, evidence failing)."""
    ok: Dict[str, List[Assertion]] = defaultdict(list)
    failed: Dict[str, List[Assertion]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM state_assertions"):
        if matches_target(r, r["fund_code"]):
            (ok if r["evidence_ok"] > 0 else failed)[r["fund_code"]].append(Assertion.from_row(r))
    return ok, failed


def build(conn: sqlite3.Connection, funds: Iterable[str], days: Sequence[str]) -> dict:
    """Rewrite daily_status and the timeline anomalies for `funds` over `days`."""
    conn.execute("DROP TABLE IF EXISTS daily_status")   # rebuilt whole, so its schema can change
    conn.executescript(DAILY_STATUS_SCHEMA)
    cal = Calendar(days)
    by_fund, unverified = target_assertions(conn)
    counts = {"funds": 0, "days": 0, "anomalies": 0}
    status_days: Dict[str, int] = defaultdict(int)
    with conn:
        conn.execute("DELETE FROM daily_status")
        conn.execute(f"DELETE FROM anomalies WHERE kind IN ({','.join('?' * len(ANOMALY_KINDS))})", ANOMALY_KINDS)
        for fund in sorted(set(funds)):
            tl = resolve_fund(fund, by_fund.get(fund, []), cal, unverified.get(fund, []))
            conn.executemany(
                "INSERT INTO daily_status (fund_code, date, status, amount, source, assertion_ids) VALUES (?, ?, ?, ?, ?, ?)",
                [(fund, d, x.status, x.amount, x.source, json.dumps(x.assertion_ids)) for d, x in tl.days.items()])
            conn.executemany(
                "INSERT INTO anomalies (fund_code, date_from, date_to, kind, detail, assertion_ids) VALUES (?, ?, ?, ?, ?, ?)",
                [(a["fund_code"], a["date_from"], a["date_to"], a["kind"], a["detail"], json.dumps(a["assertion_ids"]))
                 for a in tl.anomalies])
            counts["funds"] += 1
            counts["days"] += len(tl.days)
            counts["anomalies"] += len(tl.anomalies)
            for x in tl.days.values():
                status_days[x.status] += 1
    counts.update({f"days_{k}": v for k, v in sorted(status_days.items())})
    return counts
