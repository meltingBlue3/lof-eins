---
phase: 01-foundation
plan: 01
subsystem: data-loading
tags: [bugfix, null-handling, sqlite, pandas]

# Dependency tracking
dependencies:
  requires: []
  provides: ["NULL end_date handling", "Open-ended limit support"]
  affects: ["PDF processing", "Timeline integration"]

# Tech stack updates
tech-stack:
  added: []
  patterns: ["NULL-safe date comparisons", "Open-ended time ranges"]

# File tracking
key-files:
  created: []
  modified:
    - src/data/loader.py
    - src/data/downloader.py
    - src/data/generator/generators.py

# Decisions made in this plan
decisions:
  - id: NULL-for-open-ended
    description: "Use NULL (NaT) to represent open-ended limits that apply indefinitely from start_date"
    context: "Required for limits where end date is unknown or hasn't been set yet"

# Execution tracking
metrics:
  started: "2026-02-06"
  duration: "15 minutes"
  completed: "2026-02-06"

completed-tasks: 3
---

# Phase 1 Plan 1: Fix NULL end_date Handling Summary

## One-liner
Fixed critical bugs in NULL end_date handling to support open-ended purchase limits across all database modules.

## What Was Built

### Task 1: DataLoader NULL Handling
**File:** `src/data/loader.py`

Modified `_resample_limits_to_daily()` method to correctly handle NULL/NaT end_date values. The previous code used `(date_index >= start) & (date_index <= end)` which never evaluates to True when `end` is NaT, causing open-ended limits to be silently ignored.

**Fix:**
```python
# Handle open-ended limits (NULL/NaT end_date) - applies to all dates >= start_date
if pd.isna(end):
    mask = date_index >= start
else:
    mask = (date_index >= start) & (date_index <= end)
```

### Task 2: Downloader Schema Update
**File:** `src/data/downloader.py`

Updated `_generate_limit_db()` to create a schema with nullable end_date:

```sql
end_date DATE,  -- Removed NOT NULL constraint
```

This allows the download pipeline to correctly create limit event tables that support open-ended limits.

### Task 3: Generators Documentation
**File:** `src/data/generator/generators.py`

Verified generators.py already had the correct nullable schema. Added inline documentation:

```python
# Note: end_date is nullable to support open-ended limits (limits without known end date)
end_date DATE,  -- NULL indicates open-ended limit
```

## Technical Details

### The Bug
When `end_date` is `NaT` (pandas' Not-a-Time) or `NULL` (SQLite), the comparison `date_index <= end` fails because:
- Any comparison with NaT returns False in pandas
- Open-ended limits would never be applied to any dates
- This breaks the core requirement of supporting limits with unknown end dates

### The Solution
Use `pd.isna()` to detect NULL/NaT values and handle them as a special case:
- **NULL end_date:** Apply limit to all dates >= start_date (open-ended)
- **Non-NULL end_date:** Apply limit to dates within [start_date, end_date] range

## Decisions Made

### Decision: NULL for Open-ended Limits
- **Rationale:** NULL is the industry standard for representing unknown/unset values in SQL
- **Alternative considered:** Using a sentinel date (e.g., '9999-12-31')
- **Why NULL won:** More semantically correct, supported natively by SQLite and pandas

## Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `src/data/loader.py` | Added NULL handling logic | +5/-1 |
| `src/data/downloader.py` | Made end_date nullable | +1/-1 |
| `src/data/generator/generators.py` | Added documentation comments | +2/-0 |

## Verification

All success criteria verified:
- [x] `pd.isna(pd.NaT)` returns True
- [x] DataLoader contains NULL handling with `pd.isna(end)` check
- [x] downloader.py CREATE TABLE has nullable end_date (no NOT NULL)
- [x] generators.py has nullable end_date with documentation
- [x] All schema definitions are consistent

## Commits

1. **8044fc3** - `fix(01-01): NULL end_date handling in DataLoader`
2. **132a162** - `fix(01-01): allow NULL end_date in downloader.py schema`
3. **9583580** - `docs(01-01): document NULL end_date support in generators.py`

## Deviations from Plan

**None** - All tasks executed exactly as specified in the plan.

## Impact Assessment

### What Now Works
- Open-ended limits (NULL end_date) correctly apply to all dates >= start_date
- Consistent NULL handling across all database modules
- DataLoader correctly processes limits with unknown end dates

### What Could Break
- **Low risk:** Existing code that assumed end_date was always non-NULL
- **Mitigation:** The change is backward compatible - non-NULL end_dates still work exactly as before

### Performance Impact
- **Negligible:** One additional `pd.isna()` check per limit event
- **Alternative:** Could use `end is pd.NaT` but `pd.isna()` handles both NaT and None

## Lessons Learned

1. **NaT comparisons are tricky:** Always use `pd.isna()` for NULL/NaT detection, never direct comparison
2. **Schema consistency matters:** Three different modules had slightly different schema definitions
3. **Documentation is crucial:** The generators.py schema was correct but undocumented - now has clear comments

## Next Phase Readiness

This fix unblocks:
- Phase 2: PDF processing (can now store limits with unknown end dates)
- Phase 3: Timeline integration (correctly handles open-ended limit events)

**No blockers** - Ready to proceed to next plan.

---
*Summary created: 2026-02-06*
*Plan: 01-foundation/01-01-PLAN.md*
