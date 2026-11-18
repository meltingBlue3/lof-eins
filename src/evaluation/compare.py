"""
Day-by-day comparison of a candidate timeline against gold.

候选时间线与金标的逐日对比。

Each shared day falls in one category:

- ``agree``: same status (and same amount when limited)
- ``too_permissive``: the candidate allows more purchase than gold -- the
  dangerous direction, because the backtest then trades days it could not
- ``too_strict``: the candidate allows less than gold
- ``cand_unknown``: the candidate has no answer for the day
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

AGREE = "agree"
TOO_PERMISSIVE = "too_permissive"
TOO_STRICT = "too_strict"
CAND_UNKNOWN = "cand_unknown"
CATEGORIES = (AGREE, TOO_PERMISSIVE, TOO_STRICT, CAND_UNKNOWN)

AMOUNT_TOLERANCE = 0.5  # yuan


def cap_of(status: pd.Series, amount: pd.Series) -> pd.Series:
    """Purchase cap implied by a status/amount pair: open=inf, closed=0, else amount."""
    cap = pd.Series(np.nan, index=status.index)
    cap[status == "open"] = np.inf
    cap[status == "closed"] = 0.0
    limited = status == "limited"
    cap[limited] = amount[limited]
    return cap


def classify(gold_daily: pd.DataFrame, cand_daily: pd.DataFrame) -> pd.DataFrame:
    """Categorise every day present in both timelines.

    Returns:
        DataFrame indexed by the shared days with gold_status, gold_amount,
        cand_status, cand_amount and category.
    """
    shared = gold_daily.index.intersection(cand_daily.index)
    g = gold_daily.loc[shared]
    c = cand_daily.loc[shared]
    g_cap = cap_of(g["status"], g["amount"])
    c_cap = cap_of(c["status"], c["amount"])

    category = np.where(
        c_cap.isna(), CAND_UNKNOWN,
        np.where(
            (g_cap == c_cap) | ((g_cap - c_cap).abs() <= AMOUNT_TOLERANCE), AGREE,
            np.where(c_cap > g_cap, TOO_PERMISSIVE, TOO_STRICT),
        ),
    )
    return pd.DataFrame(
        {
            "gold_status": g["status"].to_numpy(),
            "gold_amount": g["amount"].to_numpy(),
            "cand_status": c["status"].to_numpy(),
            "cand_amount": c["amount"].to_numpy(),
            "category": category,
        },
        index=shared,
    )


def summarize(
    classified: pd.DataFrame,
    premium: Optional[pd.Series] = None,
    threshold: float = 0.017,
) -> Dict[str, int]:
    """Count days per category, overall and on arbitrage-relevant days.

    A day is relevant when its premium exceeds ``threshold`` -- the days on
    which the strategy would actually try to buy.
    """
    counts = classified["category"].value_counts()
    out: Dict[str, int] = {"days": int(len(classified))}
    out.update({cat: int(counts.get(cat, 0)) for cat in CATEGORIES})
    if premium is not None:
        relevant = premium.reindex(classified.index) > threshold
        rel_counts = classified.loc[relevant, "category"].value_counts()
        out["relevant_days"] = int(relevant.sum())
        out.update({f"relevant_{cat}": int(rel_counts.get(cat, 0)) for cat in CATEGORIES})
    return out


def mismatch_kinds(classified: pd.DataFrame) -> List[dict]:
    """Collapse disagreeing days by (category, gold value, candidate value).

    Unlike mismatch_runs(), days of one kind are counted together even when
    agreeing days (e.g. holiday closures both sides got right) split them.

    Returns:
        One dict per kind with category, gold_status, gold_amount,
        cand_status, cand_amount, days, first, last; most days first.
    """
    bad = classified[classified["category"] != AGREE]
    if bad.empty:
        return []
    key_cols = ["category", "gold_status", "gold_amount", "cand_status", "cand_amount"]
    keyed = bad.assign(_day=bad.index).fillna({"gold_amount": -1, "cand_amount": -1})
    kinds = []
    for key, grp in keyed.groupby(key_cols, sort=False):
        d = dict(zip(key_cols, key))
        for col in ("gold_amount", "cand_amount"):
            d[col] = np.nan if d[col] == -1 else d[col]
        d.update(days=len(grp), first=grp["_day"].min().strftime("%Y-%m-%d"),
                 last=grp["_day"].max().strftime("%Y-%m-%d"))
        kinds.append(d)
    return sorted(kinds, key=lambda k: -k["days"])


def mismatch_runs(classified: pd.DataFrame) -> List[dict]:
    """Group consecutive disagreeing days with the same gold/candidate values.

    "Consecutive" follows the row order of the trading-day index, so a run
    spans weekends and holidays.
    """
    runs: List[dict] = []
    key_cols = ["category", "gold_status", "gold_amount", "cand_status", "cand_amount"]
    current = None
    for day, row in classified.iterrows():
        if row["category"] == AGREE:
            current = None
            continue
        key = tuple("nan" if isinstance(v, float) and np.isnan(v) else v for v in row[key_cols])
        if current is not None and current["_key"] == key:
            current["end"] = day.strftime("%Y-%m-%d")
            current["days"] += 1
            continue
        current = {
            "_key": key,
            "start": day.strftime("%Y-%m-%d"),
            "end": day.strftime("%Y-%m-%d"),
            "days": 1,
            **{c: row[c] for c in key_cols},
        }
        runs.append(current)
    for r in runs:
        del r["_key"]
    return runs
