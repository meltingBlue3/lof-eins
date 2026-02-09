---
name: Backtest verification optimization
overview: Enhance the backtest runner and engine to output richer, exportable data for manual verification -- including decision context in trade logs, daily account snapshots, and CSV export.
todos:
  - id: enrich-trades
    content: Add premium_rate, daily_limit, constraint caps (limit/liquid/cash), cash_before/after to trade records in BacktestEngine._execute_buy and _execute_sell
    status: completed
  - id: daily-snapshots
    content: Add daily per-ticker position snapshots (settled/pending/total shares, price, value) to BacktestResult in BacktestEngine.run()
    status: completed
  - id: csv-export
    content: Add CSV export of trade_logs, daily_perf, daily_snapshots, and summary.txt to a timestamped output directory
    status: completed
  - id: cli-args
    content: Add --output-dir, --start-date, --end-date, --no-export CLI arguments to run_backtest.py
    status: completed
  - id: console-output
    content: "Improve console output: show all trades, per-ticker PnL summary, date range, output dir path"
    status: completed
isProject: false
---

# Optimize Backtest Script for Manual Data Verification

## Problem Analysis

Current `run_backtest.py` has several gaps that hinder manual verification:

- **Trade logs lack decision context**: no `premium_rate`, `daily_limit`, or constraint breakdown -- hard to understand *why* a trade happened or *why* the amount was capped
- **No daily account snapshot**: can't verify that cash, settled positions, and T+2 pending shares evolve correctly day-by-day
- **No export**: all output is console-only; no CSV files for spreadsheet verification
- **Truncated output**: only shows first 20 trade logs, no date filtering

## Changes Overview

### 1. Enrich trade records in engine ([src/engine/backtest.py](src/engine/backtest.py))

Add the following fields to each trade record dict:

**For BUY trades** (in `_execute_buy` and the buy loop in `run`):

- `premium_rate` -- the premium rate that triggered the buy signal
- `daily_limit` -- the limit cap at the time
- `limit_cap`, `liquid_cap`, `cash_cap` -- the three constraint values, so we can see which was binding
- `effective_cap` -- `min(limit_cap, liquid_cap, cash_cap)` (the actual binding constraint)
- `cash_before` -- account cash before trade
- `cash_after` -- account cash after trade

**For SELL trades** (in `_execute_sell`):

- `premium_rate` -- premium rate at sell time (for context)
- `cash_before`, `cash_after`

This is achieved by passing `premium_rate` from the call site and recording `account.cash` before/after execution.

### 2. Add daily account snapshot to `BacktestResult` ([src/engine/backtest.py](src/engine/backtest.py))

In the main `run()` loop, after recording daily performance, also record a per-ticker snapshot:

```python
# For each ticker, record: settled_shares, pending_shares, last_price
```

Store this as a new `daily_snapshots: pd.DataFrame` field on `BacktestResult`, with columns:
`date, ticker, settled_shares, pending_shares, total_shares, last_price, position_value`

This lets the user verify T+2 settlement is working correctly for each ticker on each day.

### 3. Export results to CSV ([run_backtest.py](run_backtest.py))

Add an `--output-dir` CLI argument (default: `output/`). After the backtest completes, export:


| File                  | Content                                   |
| --------------------- | ----------------------------------------- |
| `trade_logs.csv`      | Full enriched trade log                   |
| `daily_perf.csv`      | Daily total_assets, cash, positions_value |
| `daily_snapshots.csv` | Per-ticker daily position snapshots       |
| `summary.txt`         | The same text summary printed to console  |


Use timestamped subdirectory (e.g., `output/20260209_143000/`) to avoid overwriting previous runs.

### 4. Add CLI enhancements ([run_backtest.py](run_backtest.py))

- `--output-dir` / `-o`: Output directory for CSV export (default: `output/`)
- `--start-date` / `-s`: Start date filter (YYYY-MM-DD)
- `--end-date` / `-e`: End date filter (YYYY-MM-DD)
- `--no-export`: Skip CSV export (console-only mode)

### 5. Improve console output ([run_backtest.py](run_backtest.py))

- Show **all** trade logs (not just 20) in console, or a configurable number
- Add per-ticker performance summary: buy count, sell count, total invested, total returned, PnL
- Print the output directory path at the end for easy access
- Show date range of the backtest data

## Files to Modify

- **[src/engine/backtest.py](src/engine/backtest.py)** -- enrich trade records, add daily_snapshots to `BacktestResult`
- **[run_backtest.py](run_backtest.py)** -- CSV export, CLI args, improved console output

