---
name: Union dates forward fill
overview: Change date alignment in BacktestEngine from intersection to union, and add forward-fill price tracking to prevent position valuation errors when a fund has no data on a given trading day.
todos:
  - id: union-dates
    content: Change `_load_multi_data` from intersection to union and update docstring
    status: completed
  - id: ffill-prices
    content: Add `last_known_prices` dict in `run()` and use it in Step 4 daily performance recording
    status: completed
isProject: false
---

# Union Dates with Forward-Fill Price Tracking

## Problem

`_load_multi_data` uses **intersection** of trading days across all tickers. If one fund is suspended or has missing data, those days are dropped for all funds, shrinking the backtest window.

## Key Insight

The main loop (sell/buy phases) already has `if timestamp not in all_data[ticker].index: continue` guards, so buy/sell logic is safe. The **only critical gap** is in the daily performance recording (Step 4), where `Account.get_total_value(prices)` falls back to `0.0` for missing tickers, causing false asset drops.

## Changes

### 1. Change intersection to union in `_load_multi_data` ([src/engine/backtest.py](src/engine/backtest.py), lines 274-286)

Replace the intersection logic:

```python
common_dates = None
for df in all_data.values():
    if common_dates is None:
        common_dates = set(df.index)
    else:
        common_dates = common_dates.intersection(set(df.index))
aligned_dates = pd.DatetimeIndex(sorted(common_dates))
```

With union:

```python
all_dates: set = set()
for df in all_data.values():
    all_dates = all_dates.union(set(df.index))
aligned_dates = pd.DatetimeIndex(sorted(all_dates))
```

Update the docstring to reflect "union" instead of "intersection".

### 2. Add forward-fill price cache in `run()` ([src/engine/backtest.py](src/engine/backtest.py), lines 335-420)

Add a `last_known_prices: Dict[str, float]` dictionary **before** the main loop (after line 336). Then modify Step 4:

- For each ticker, if the current timestamp has data, update `last_known_prices[ticker]` with the current `close`.
- Pass `last_known_prices` (instead of the day-only `prices` dict) to `account.get_total_value()` and `account.get_positions_value()`.

This ensures that when fund A is suspended on day X but we hold shares of A, its last known close price is used for valuation rather than `0.0`.

**Before:**

```python
prices: Dict[str, float] = {}
for ticker in ticker_list:
    if ticker in all_data and timestamp in all_data[ticker].index:
        prices[ticker] = all_data[ticker].loc[timestamp, 'close']

daily_records.append({
    'date': timestamp,
    'total_assets': account.get_total_value(prices),
    ...
})
```

**After:**

```python
for ticker in ticker_list:
    if ticker in all_data and timestamp in all_data[ticker].index:
        last_known_prices[ticker] = all_data[ticker].loc[timestamp, 'close']

daily_records.append({
    'date': timestamp,
    'total_assets': account.get_total_value(last_known_prices),
    ...
})
```

### 3. No changes needed elsewhere

- **Sell phase** (lines 346-362): Already has `timestamp not in all_data[ticker].index: continue` -- suspended funds are skipped (correct: can't sell during suspension).
- **Buy phase** (lines 367-382): Same guard -- suspended funds won't appear as candidates (correct: can't subscribe during suspension).
- **Account class** ([src/engine/account.py](src/engine/account.py)): No changes needed. `get_total_value` and `get_positions_value` will receive complete price dicts via forward-fill.
- **T+2 settlement** (line 329): `trading_days` becomes the union calendar, which is actually more accurate for settlement date calculation since the market is still open even if one fund is suspended.

### Total diff

~15 lines changed in a single file (`backtest.py`), no new files.