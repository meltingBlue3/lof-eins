"""
Backtest PnL attribution: tie each round trip in a trade log back to the
subscription state on its buy day.

回测利润归因：把成交记录里的每一笔往返交易对应到买入日的申购状态。
"""

import pandas as pd

SHARE_TOLERANCE = 1e-6


def round_trips(trades: pd.DataFrame) -> pd.DataFrame:
    """Pair each buy with the sell that closes it.

    The engine buys at most once per ticker per day and sells a lot in full
    once it settles, so the k-th sell of a ticker closes its k-th buy. Pairs
    whose share counts differ are dropped rather than mis-attributed; buys
    still open at the end of the log have no sell and are dropped too.

    Args:
        trades: trade_logs.csv as written by run_backtest.py (date, action,
            ticker, shares, amount, net_amount, ...).

    Returns:
        DataFrame with ticker, buy_date, sell_date, invested, pnl.
    """
    t = trades.copy()
    t["ticker"] = t["ticker"].astype(str)
    t["date"] = pd.to_datetime(t["date"])
    buys = t[t["action"] == "buy"].copy()
    sells = t[t["action"] == "sell"].copy()
    buys["k"] = buys.groupby("ticker").cumcount()
    sells["k"] = sells.groupby("ticker").cumcount()
    m = buys.merge(sells, on=["ticker", "k"], suffixes=("_b", "_s"))
    m = m[(m["shares_b"] - m["shares_s"]).abs() <= SHARE_TOLERANCE * m["shares_b"].abs().clip(lower=1)]
    return pd.DataFrame(
        {
            "ticker": m["ticker"].to_numpy(),
            "buy_date": m["date_b"].to_numpy(),
            "sell_date": m["date_s"].to_numpy(),
            "invested": m["amount_b"].to_numpy(),
            "pnl": (m["net_amount_s"] - m["amount_b"]).to_numpy(),
        }
    )


BUY_COLUMNS = ("sub_status", "status_source", "stated_limit", "fee", "premium_rate", "decision_premium",
               "fee_source", "sell_days")


def fee_band(trips: pd.DataFrame) -> pd.Series:
    """Nominal subscription fee rate of each trip, in bands.

    fee / amount is r for the legacy formula and r / (1 + r) for the prospectus one; the
    edges sit between the two readings of 1.0% and of 1.5%, so either lands in its band.
    """
    rate = trips["fee"] / trips["invested"]
    bands = pd.cut(rate, [-1, 1e-9, 0.0095, 0.0147, 1], labels=["0%", "0~1%", "1%~1.5%", "≥1.5%"])
    return bands.astype(str)


def trips_with_status(trades: pd.DataFrame) -> pd.DataFrame:
    """round_trips() plus the buy day's columns (status, fee, premiums, sell day), when the log has them.

    往返交易，附上买入日的申购状态、申购费、溢价和可卖日。
    """
    trips = round_trips(trades)
    cols = [c for c in BUY_COLUMNS if c in trades.columns]
    if not cols or trips.empty:
        return trips
    buys = trades[trades["action"] == "buy"].copy()
    buys["ticker"] = buys["ticker"].astype(str)
    buys["buy_date"] = pd.to_datetime(buys["date"])
    buys = buys.drop_duplicates(["ticker", "buy_date"])[["ticker", "buy_date", *cols]]
    return trips.merge(buys, on=["ticker", "buy_date"], how="left")


def pnl_by(trips: pd.DataFrame, column: str) -> pd.DataFrame:
    """Round trips and PnL grouped by a buy-day column, most profitable first."""
    if trips.empty or column not in trips:
        return pd.DataFrame(columns=[column, "trips", "invested", "pnl"])
    g = trips.groupby(column, dropna=False).agg(trips=("pnl", "size"), invested=("invested", "sum"),
                                                pnl=("pnl", "sum"))
    return g.sort_values("pnl", ascending=False).reset_index()
