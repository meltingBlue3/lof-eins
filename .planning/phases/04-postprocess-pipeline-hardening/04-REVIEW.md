---
phase: 04-postprocess-pipeline-hardening
reviewed: 2026-08-18T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - scripts/parse_announcements.py
  - src/data/postprocess.py
  - tests/test_postprocess.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-08-18T00:00:00Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

This phase adds a validation gate (`ValidationBlockedError`), a `KNOWN_RESTRICTION_TYPES`
fail-loud check, an inverted-interval clamp, and an atomic staged-table swap for
`write_limit_events()`. The atomic-swap mechanics (`BEGIN IMMEDIATE` / stage into
`limit_events_new` / rename / rollback-on-failure) are sound and the new tests for it
are solid, real-constraint-violation tests rather than mocks.

However, three reproducible defects undermine the actual goal of this hardening phase —
protecting `limit_events` from being silently corrupted or wiped:

1. `postprocess()` calls `write_limit_events()` unconditionally whenever
   `subscription_restrictions` is non-empty, even if `build_limit_events()` derives **zero**
   intervals from those records. Because `write_limit_events()` unconditionally drops and
   replaces the live `limit_events` table, a batch of records that happens to produce no
   intervals (e.g. an isolated holiday resume with no local prior suspend) silently **wipes
   all previously-computed backtest data for every fund**, and reports `intervals: 0` in the
   stats it returns — this is precisely the kind of catastrophic-swap risk the atomic-table
   rework in this phase was meant to eliminate, and it survives untouched.
2. `validate()`'s "restrict/suspend should have a resume" staleness check pops
   `open_restrictions` on *any* `resume` record, including holiday resumes. `build_limit_events()`
   (correctly, and tested) treats holiday resumes as **not** closing a long-term suspension.
   This means the validation gate can consider a suspension "closed" by a holiday resume that
   `build_limit_events()` itself will treat as still open past 180 days — silently letting a
   genuinely stale/incorrect interval through the exact gate this phase built to catch it.
   Reproduced below.
3. When a `restrict`/`suspend` record already carries its own explicit `end_date` from the
   announcement, and a *later, unrelated* resume exists anywhere further down that fund's
   timeline, `build_limit_events()` silently overwrites the announcement's own end date with
   the date derived from that unrelated resume. Reproduced below.

Two further findings degrade the validation gate's reliability without causing data loss
(false-positive blocking of legitimate runs, misleading stats), and several smaller
maintainability/robustness gaps round out the list.

## Critical Issues

### CR-01: A record set that derives zero intervals silently wipes limit_events

**File:** `src/data/postprocess.py:483-501` (guard) and `309-390` (`write_limit_events`)

**Issue:** `postprocess()` only skips `write_limit_events()` when `subscription_restrictions`
itself is empty (`if not records: ... return`, line 483). There is no check on whether
`build_limit_events(records)` actually produced any intervals before calling
`write_limit_events(db_path, events)` at line 495. `write_limit_events()` unconditionally
drops the live `limit_events` table and replaces it with whatever was staged — including an
empty table.

Reproduced: seeding `limit_events` with a sentinel row and `subscription_restrictions` with a
single fund whose only record is a holiday resume (`action=resume`,
`restriction_type=holiday_suspension`, no other rows for that fund) causes `postprocess()` to
run cleanly (`validate()` reports 0 issues), then call `write_limit_events(db_path, [])`,
which drops and replaces `limit_events` with zero rows — permanently destroying whatever
backtest data was there before, for *every* fund, not just the one whose records happened
to produce no intervals:

```
BEFORE: [(1, '999999', '2020-01-01', '2020-01-05', 0.0, 'sentinel', '[]')]
STATS: {'raw': 1, 'deduped': 1, 'intervals': 0}
AFTER: []
```

This is exactly the failure mode the atomic staged-table swap (T-04-06/07/08/11) was built to
prevent — but the swap only protects against a *partial* write; it does nothing to stop a
*complete but empty* result from being swapped in as if it were valid.

**Fix:** Treat "non-empty input records but zero derived intervals" as a condition requiring
explicit operator confirmation (or at minimum a loud warning + opt-in flag), the same way
`validate()` already blocks on data-quality issues:

```python
events = build_limit_events(records)
if records and not events:
    raise ValidationBlockedError(
        [f"  {len(records)} 条原始记录，但构建出 0 个 limit_events 区间 "
         "-- 拒绝清空现有 limit_events，请人工确认后使用 --force 之类的开关"]
    )
write_limit_events(db_path, events)
```

---

### CR-02: validate()'s staleness check is closed by holiday resumes it should ignore

**File:** `src/data/postprocess.py:422-430`

**Issue:**

```python
open_restrictions = []
for r in fund_records:
    if r["action"] in ("restrict", "suspend"):
        if r.get("restriction_type") not in ("holiday_suspension",):
            open_restrictions.append(r)
    elif r["action"] == "resume":
        if open_restrictions:
            open_restrictions.pop()
```

Any `resume` record pops `open_restrictions`, with no `_is_holiday_resume()` check. But
`build_limit_events()` (lines 233-249, and the whole point of the `_is_holiday_resume()` guard
added for the commit `89830c8` regression) explicitly does **not** let a holiday resume close a
long-term suspension. The two functions now disagree about what "closes" a suspension.

Reproduced: a `full_suspension` that started 400 days ago, followed only by a `holiday_suspension`
resume 5 days later (and nothing else), passes `validate()` with zero issues, yet
`build_limit_events()` correctly emits an **open-ended (NULL end_date)** interval for it — i.e.
a suspension that is, by the codebase's own logic, still open 395+ days later, sails straight
through the staleness gate this phase added:

```
VALIDATE ISSUES: []
EVENTS: [{'ticker': '161129', 'start_date': '2025-07-14', 'end_date': None, ...}]
```

**Fix:** Reuse `_is_holiday_resume()` in `validate()`'s pairing loop so it agrees with
`build_limit_events()`:

```python
elif r["action"] == "resume":
    if open_restrictions and not _is_holiday_resume(r):
        open_restrictions.pop()
```

---

### CR-03: An explicit end_date on a restrict/suspend record is silently overwritten by an unrelated later resume

**File:** `src/data/postprocess.py:208, 230-249`

**Issue:** `end = r.get("end_date")` (line 208) captures whatever end date the announcement
itself specified for a `restrict`/`suspend` record. But for any `rtype` other than
`holiday_suspension`/`application_invalid`, the `else` branch (lines 230-249) unconditionally
searches forward for the next non-holiday resume for that fund and, if one is found anywhere
later in the timeline, **overwrites `end`** with a date derived from that resume — even when
the original record already had its own valid `end_date`.

Reproduced: a record with `end_date="2022-03-01"` explicitly stated in the announcement, for a
fund that also has an unrelated resume on `2022-06-01` (e.g. closing a *different* later
restriction on the same fund), yields an interval ending `2022-05-31` — the announcement's own
end date is discarded:

```python
records[0]["end_date"] == "2022-03-01"   # from the announcement
# build_limit_events(records)[0]["end_date"] == "2022-05-31"  # wrong: derived from unrelated later resume
```

For a backtesting pipeline this silently lengthens (or shortens) restriction windows beyond
what was actually announced — the same class of correctness defect (`89830c8`, ~7x PnL
inflation) this phase's other fixes explicitly guard against.

**Fix:** Prefer the record's own `end_date` when present, and only fall back to resume-lookahead
when it is absent:

```python
if rtype in ("holiday_suspension", "application_invalid"):
    if not end:
        end = start
elif end:
    pass  # explicit end_date from the announcement takes precedence
else:
    # existing resume-lookahead logic
    ...
```

## Warnings

### WR-01: open_restrictions stack pairs LIFO, disagreeing with build_limit_events()'s forward-nearest pairing (false-positive validation blocks)

**File:** `src/data/postprocess.py:422-430`

**Issue:** `open_restrictions.pop()` removes the *most recently appended* open restriction, but
`build_limit_events()` pairs each `suspend`/`restrict` independently with the *nearest following*
resume, regardless of other opens in between (so two stacked `restrict` records that are both
legitimately closed by the same later resume both get correctly closed in
`build_limit_events()`). `validate()`'s stack model instead leaves the *older* one flagged as
still open. Reproduced: two `restrict` records 10 days apart for the same fund followed by a
single resume, all >180 days old — `build_limit_events()` closes both correctly, but
`validate()` still reports one of them as unresolved and blocks the run:

```
VALIDATE ISSUES: ['  160105 2025-07-14 restrict amount_limit 无对应resume（超180天）']
EVENTS: [... two correctly-closed intervals, both ending 2025-08-02 ...]
```

This is a false positive (blocks a legitimate `postprocess()` run rather than silently
corrupting data), but it degrades the validation gate's reliability and will train operators to
distrust or work around it.

**Fix:** Mirror `build_limit_events()`'s actual pairing semantics in `validate()` (e.g. also
search-forward for the nearest non-holiday resume per open restriction) rather than using a
LIFO stack, or explicitly document/test the intentional divergence if the stack model is kept.

### WR-02: postprocess()'s returned "raw" stat is actually the post-dedup count

**File:** `src/data/postprocess.py:480-501`

**Issue:**

```python
records = load_records(db_path)
print(f"加载 {len(records)} 条原始记录")
...
records = dedup_records(records)
records = fix_resume_type(records)
...
return {
    "raw": len(records),
    "deduped": len(records),
    "intervals": len(events),
}
```

`records` is reassigned by `dedup_records()` before the return statement, so `stats["raw"]` and
`stats["deduped"]` are always identical — the true raw (pre-dedup) count is discarded. Any
caller/dashboard relying on `stats["raw"]` to see how many duplicates were removed gets a
silently wrong number.

**Fix:** Capture the raw count before reassigning `records`:

```python
records = load_records(db_path)
raw_count = len(records)
...
records = dedup_records(records)
...
return {"raw": raw_count, "deduped": len(records), "intervals": len(events)}
```

### WR-03: Malformed effective_date is silently swallowed rather than flagged

**File:** `src/data/postprocess.py:432-441`

**Issue:**

```python
for r in open_restrictions:
    try:
        eff = datetime.strptime(r["effective_date"], "%Y-%m-%d")
        if (datetime.now() - eff).days > 180:
            issues.append(...)
    except ValueError:
        pass
```

A malformed `effective_date` on an open restriction silently disables the staleness check for
that record instead of being surfaced as its own validation issue. The same pattern (bare
`except ValueError: end = nxt["effective_date"]` / `except ValueError: synth_end = resume_date`)
recurs in `build_limit_events()` (lines 188-189, 246-247), each time falling back to using the
unparsed string rather than failing loud — inconsistent with the "fail loud on unknown
restriction_type" philosophy this phase otherwise establishes.

**Fix:** Have `validate()` explicitly flag unparseable dates as an issue rather than silently
skipping the staleness check for them.

### WR-04: `adjust_rule` action is a legal DB value but is silently a no-op through the entire pipeline

**File:** `src/data/postprocess.py:126, 206, 424-427`

**Issue:** The `subscription_restrictions.action` CHECK constraint (mirrored in
`tests/test_postprocess.py:64-66`, copied from `src/data/downloader.py`) permits
`'adjust_rule'`, but `fix_resume_type()` (line 126), `build_limit_events()` (line 206), and
`validate()`'s open-restrictions loop (line 424) all only match `("suspend", "restrict",
"invalidate")`/`("restrict", "suspend")` — an `adjust_rule` record is silently dropped at every
stage, produces no interval, and is never referenced in `source_announcement_ids`. There is no
comment (unlike the deliberate, well-documented `None`/empty `restriction_type` tolerance) and
no test explaining whether this is intentional, and no test exercises it at all.

**Fix:** Either explicitly document why `adjust_rule` never produces a limit_events row, or add
handling for it, plus a regression test either way.

### WR-05: CLI subprocess tests have no timeout — a hang in the script hangs the whole suite

**File:** `tests/test_postprocess.py:168-182`

**Issue:** `_run_cli()` calls `subprocess.run([...], capture_output=True, env=env)` with no
`timeout=`. If `scripts/parse_announcements.py` were ever to block (e.g. on unexpected stdin
interaction, or a future regression that introduces an infinite loop), the multiple tests that
use `_run_cli()` (`TestValidationGate`) would hang indefinitely rather than failing fast, taking
down CI without a useful diagnostic.

**Fix:**

```python
result = subprocess.run(
    [sys.executable, str(script), *args],
    cwd=str(PROJECT_ROOT),
    capture_output=True,
    env=env,
    timeout=60,
)
```

## Info

### IN-01: `affected_business` defaults to `None` instead of `[]` for NULL DB values

**File:** `src/data/postprocess.py:64-69`

**Issue:** `ab = r.get("affected_business", "[]")` only applies the `"[]"` default when the key
is *absent*; a `NULL` column value round-trips as the dict value `None` (the key is present),
so `isinstance(ab, str)` is `False` and `r["affected_business"]` is left as `None` rather than
`[]`. Currently unused downstream in this module, so latent, but will break the first caller
that assumes a list (e.g. `for b in r["affected_business"]`).

**Fix:** `ab = r.get("affected_business") or "[]"`.

### IN-02: `--postprocess-only` combined with `--no-postprocess` silently does nothing

**File:** `scripts/parse_announcements.py:99, 119`

**Issue:** `--postprocess-only` skips PDF parsing (line 99) and `--no-postprocess` skips the
postprocess step (line 119). Passing both together makes the CLI a complete no-op with exit
code 0 and no message explaining why nothing happened.

**Fix:** Add a mutually-exclusive-flag check in `argparse` (`parser.add_mutually_exclusive_group`)
or an explicit early error message.

### IN-03: Module/function docstrings omit the validate() step this phase added

**File:** `src/data/postprocess.py:4-9, 462-465`

**Issue:** The module docstring's pipeline list ("1. Load ... 2. Deduplicate ... 3. Fix ...
4. Build ... 5. Write") and `postprocess()`'s own docstring pipeline summary
("dedup → fix → limit_events") never mention the `validate()` gate that now sits between "fix"
and "build" and can abort the whole run — the single most important behavior change in this
phase.

**Fix:** Add the validation step to both docstrings, e.g. "... 3. Fix resume records ...
4. Validate (raises ValidationBlockedError on issues) 5. Build backtest intervals 6. Write ...".

---

_Reviewed: 2026-08-18T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
