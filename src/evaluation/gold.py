"""
Gold (hand-verified) subscription-state timelines: loading, validation and
expansion to one row per trading day.

金标（人工核对）申购状态时间线：加载、校验、展开为逐日序列。

File format and labeling rules: data/gold/README.md.
"""

from pathlib import Path
from typing import List, Union

import numpy as np
import pandas as pd

GOLD_COLUMNS = [
    "fund_code", "layer", "status", "amount", "valid_from", "valid_to",
    "confidence", "source_pdf", "evidence", "note",
]
STATUSES = ("open", "limited", "closed")
LAYERS = ("baseline", "overlay")
CONFIDENCES = ("high", "medium", "low")


class GoldValidationError(ValueError):
    """Raised by load_gold() when the file breaks the format rules.

    Carries every problem found, not just the first, so a labeler can fix the
    file in one pass.
    """

    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__(f"gold file has {len(problems)} problem(s):\n" + "\n".join(problems))


def validate_gold(raw: pd.DataFrame) -> List[str]:
    """Check a raw gold frame (all columns as strings) against the format rules.

    Returns:
        Human-readable problems, each prefixed with the CSV line number
        (header is line 1). Empty when the frame is valid.
    """
    missing = [c for c in GOLD_COLUMNS if c not in raw.columns]
    if missing:
        return [f"missing columns: {missing}"]

    problems: List[str] = []
    parsed = []  # (fund, layer, from, to, line) for the overlap check
    for i, r in enumerate(raw.itertuples(index=False)):
        line = i + 2
        where = f"line {line} ({r.fund_code} {r.valid_from})"
        if r.layer not in LAYERS:
            problems.append(f"{where}: layer must be one of {LAYERS}, got {r.layer!r}")
        if r.status not in STATUSES:
            problems.append(f"{where}: status must be one of {STATUSES}, got {r.status!r}")
        if r.confidence not in CONFIDENCES:
            problems.append(f"{where}: confidence must be one of {CONFIDENCES}, got {r.confidence!r}")
        if not str(r.source_pdf).strip():
            problems.append(f"{where}: source_pdf is required")
        if r.layer == "baseline" and not str(r.evidence).strip():
            problems.append(f"{where}: baseline rows need an evidence quote")

        amount = str(r.amount).strip()
        if r.status == "limited":
            try:
                if float(amount) <= 0:
                    raise ValueError
            except ValueError:
                problems.append(f"{where}: limited rows need a positive amount, got {amount!r}")
        elif r.status in STATUSES and amount:
            problems.append(f"{where}: amount must be empty unless status is limited")

        try:
            start = pd.Timestamp(r.valid_from)
            end = pd.Timestamp(r.valid_to)
        except (ValueError, TypeError):
            problems.append(f"{where}: valid_from/valid_to must be YYYY-MM-DD dates")
            continue
        if pd.isna(start) or pd.isna(end):
            problems.append(f"{where}: valid_from/valid_to are both required")
            continue
        if end < start:
            problems.append(f"{where}: valid_to {r.valid_to} is before valid_from")
            continue
        parsed.append((r.fund_code, r.layer, start, end, line))

    baselines = sorted((p for p in parsed if p[1] == "baseline"), key=lambda p: (p[0], p[2]))
    for prev, cur in zip(baselines, baselines[1:]):
        if prev[0] == cur[0] and cur[2] <= prev[3]:
            problems.append(
                f"line {cur[4]} ({cur[0]}): baseline {cur[2].date()} overlaps the baseline on line {prev[4]} "
                f"ending {prev[3].date()}"
            )
    return problems


def load_gold(path: Union[str, Path]) -> pd.DataFrame:
    """Read, validate and type a gold timeline CSV.

    Raises:
        GoldValidationError: if validate_gold() reports any problem.
    """
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    problems = validate_gold(raw)
    if problems:
        raise GoldValidationError(problems)
    gold = raw.copy()
    # validate_gold() guarantees amount is either empty or a positive number
    gold["amount"] = pd.to_numeric(gold["amount"], errors="coerce")
    gold["valid_from"] = pd.to_datetime(gold["valid_from"])
    gold["valid_to"] = pd.to_datetime(gold["valid_to"])
    return gold


def expand_daily(gold: pd.DataFrame, fund_code: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Expand one fund's gold rows to a daily timeline over ``days``.

    Overlays win over the baseline on the days they cover. Days not covered by
    any baseline row are unlabeled and are left out of the result.

    Returns:
        DataFrame indexed by the covered days, columns status, amount, layer,
        confidence.
    """
    rows = gold[gold["fund_code"] == fund_code]
    out = pd.DataFrame(
        {"status": None, "amount": np.nan, "layer": None, "confidence": None},
        index=days,
    )
    for layer in LAYERS:  # baselines first, then overlays on top
        for r in rows[rows["layer"] == layer].itertuples(index=False):
            mask = (days >= r.valid_from) & (days <= r.valid_to)
            if layer == "overlay":
                mask &= out["layer"].notna().to_numpy()  # overlays never label uncovered days
            out.loc[mask, ["status", "amount", "layer", "confidence"]] = [
                r.status, r.amount, layer, r.confidence,
            ]
    out = out[out["layer"].notna()].copy()
    out["amount"] = out["amount"].astype(float)
    return out
