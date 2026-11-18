"""
Candidate timelines: the subscription-state data being evaluated.

候选时间线：被评估的限购数据。

- ``v2``: the redesigned pipeline's ``daily_status`` table (phase D) in
  ``subscription_state.db``. ``unknown`` days, and limits without an amount, have no
  cap, so the comparison counts them as ``cand_unknown``.

The ``legacy`` candidate (the old ``limit_events`` data) was removed in phase G with the
rest of the old pipeline; its reports (docs/eval/legacy-*.md) were produced at commit
17a5bfd.
"""

import sqlite3
from functools import lru_cache
from typing import Callable, Dict, Tuple

import numpy as np
import pandas as pd

from src.data.loader import DataLoader


def status_from_cap(cap: pd.Series) -> pd.DataFrame:
    """Convert a daily purchase cap (yuan) into a daily timeline.

    inf -> open, <= 0 -> closed, anything else -> limited with that amount.
    """
    cap = cap.astype(float)
    status = np.where(np.isinf(cap), "open", np.where(cap <= 0, "closed", "limited"))
    amount = np.where(status == "limited", cap, np.nan)
    return pd.DataFrame({"status": status, "amount": amount}, index=cap.index)


@lru_cache(maxsize=1)
def _v2_connection(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)


def v2_timeline(fund_code: str, bundle_df: pd.DataFrame, db_path: str = "") -> pd.DataFrame:
    """The v2 candidate: daily_status for one fund, on the bundle's trading days."""
    from src.pipeline.db import DEFAULT_DB

    conn = _v2_connection(db_path or str(DEFAULT_DB))
    rows = conn.execute("SELECT date, status, amount, source FROM daily_status WHERE fund_code = ?",
                        (fund_code,)).fetchall()
    tl = pd.DataFrame(rows, columns=["date", "status", "amount", "source"])
    tl.index = pd.to_datetime(tl.pop("date"))
    tl = tl.reindex(bundle_df.index)
    tl["status"] = tl["status"].fillna("unknown")
    tl["source"] = tl["source"].fillna("default")
    tl["amount"] = tl["amount"].astype(float)
    return tl


CANDIDATES: Dict[str, Callable[[str, pd.DataFrame], pd.DataFrame]] = {
    "v2": v2_timeline,
}


def load_fund(loader: DataLoader, fund_code: str, candidate: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load one fund's market frame and the named candidate's daily timeline.

    Returns:
        (frame, timeline): frame is DataLoader's bundle (close, nav, volume,
        premium_rate, ...), indexed by the trading days that have both price
        and NAV; timeline is indexed the same way.
    """
    if candidate not in CANDIDATES:
        raise ValueError(f"unknown candidate {candidate!r}; choose from {sorted(CANDIDATES)}")
    frame = loader.load_bundle(fund_code).df
    return frame, CANDIDATES[candidate](fund_code, frame)
