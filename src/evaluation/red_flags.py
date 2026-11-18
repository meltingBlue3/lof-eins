"""
Market red flags: days a timeline says purchase is (nearly) unrestricted
while the premium stays high.

市场红旗：时间线认为申购基本不受限，溢价却持续偏高的日子。

A persistent premium on an open fund is unusual -- arbitrageurs would buy at
NAV and sell on exchange until it closed. So a run of such days usually means
the timeline missed a restriction. This is a data-quality tool, never a
trading rule: deciding tradability from the premium would bias a backtest.
"""

from typing import List

import numpy as np
import pandas as pd


def find_red_flags(
    frame: pd.DataFrame,
    timeline: pd.DataFrame,
    min_premium: float = 0.05,
    min_days: int = 3,
    permissive_amount: float = 100_000,
) -> List[dict]:
    """Find runs of permissive, high-premium, traded days.

    Args:
        frame: Market frame indexed by trading day with premium_rate and volume.
        timeline: Daily timeline (status, amount) for the same fund.
        min_premium: Premium above which a day counts as high.
        min_days: Minimum run length (consecutive trading days) to report.
        permissive_amount: A limited day counts as permissive when its amount
            is at least this many yuan.

    Returns:
        One dict per run: start, end, days, mean_premium, max_premium,
        statuses (the candidate statuses seen in the run).
    """
    tl = timeline.reindex(frame.index)
    permissive = (tl["status"] == "open") | (
        (tl["status"] == "limited") & (tl["amount"] >= permissive_amount)
    )
    flag = permissive & (frame["premium_rate"] > min_premium) & (frame["volume"] > 0)

    runs: List[dict] = []
    run_id = (flag != flag.shift()).cumsum()
    for _, idx in flag[flag].groupby(run_id[flag]).groups.items():
        if len(idx) < min_days:
            continue
        prem = frame.loc[idx, "premium_rate"]
        runs.append(
            {
                "start": idx[0].strftime("%Y-%m-%d"),
                "end": idx[-1].strftime("%Y-%m-%d"),
                "days": int(len(idx)),
                "mean_premium": float(np.mean(prem)),
                "max_premium": float(np.max(prem)),
                "statuses": sorted(set(tl.loc[idx, "status"])),
            }
        )
    return runs
