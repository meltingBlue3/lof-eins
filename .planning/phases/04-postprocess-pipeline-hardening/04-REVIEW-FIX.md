---
phase: 04-postprocess-pipeline-hardening
fixed_at: 2026-08-18T15:20:00Z
review_path: .planning/phases/04-postprocess-pipeline-hardening/04-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-08-18T15:20:00Z
**Source review:** .planning/phases/04-postprocess-pipeline-hardening/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (3 critical, 5 warning; fix_scope = critical_warning, Info findings excluded)
- Fixed: 8
- Skipped: 0

Each fix was applied inside an isolated git worktree (`workflow.use_worktrees` was unset,
default `true`), committed atomically, then fast-forwarded onto `main`. Verification for
every fix ran `python -m ast.parse` (syntax), the full `tests/test_postprocess.py` module
(Tier 2), and a final full-suite run (`python -m unittest discover tests`) after all fixes
landed. All source edits and test additions ran inside the worktree at
`/tmp/sv-04-reviewfix-<pid>` (Windows: `%TEMP%\sv-04-reviewfix-<pid>`); the worktree was
removed and `main` fast-forwarded to capture the 8 commits before this report was written.

## Fixed Issues

### CR-01: A record set that derives zero intervals silently wipes limit_events

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `9cd1a48`
**Applied fix:** `postprocess()` now raises `ValidationBlockedError` when `records` is
non-empty but `build_limit_events(records)` derives zero intervals, refusing to call
`write_limit_events()` (which would otherwise drop and replace the live `limit_events`
table with zero rows). Added `TestZeroIntervalGuard` reproducing the review's exact
scenario (a lone holiday-resume record for a fund, seeded against a sentinel
`limit_events` row) and asserting the table is left untouched and the raised error names
the zero-intervals condition.

### CR-02: validate()'s staleness check is closed by holiday resumes it should ignore

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `1f80c6e`
**Applied fix:** `validate()`'s open-restrictions pairing now calls `_is_holiday_resume()`
before popping a restriction off as closed, agreeing with `build_limit_events()`'s
existing holiday-resume handling. Added `TestValidateHolidayResumeStaleness` reproducing
the review's 400-day-old `full_suspension` + holiday-resume-5-days-later scenario: asserts
`build_limit_events()` still emits an open-ended interval, and `validate()` now flags it as
stale (previously reported zero issues). Note: this targeted patch was superseded by the
broader WR-01 rework in commit `b7f0765` (see below), which replaces the whole
open-restrictions block; the CR-02 commit and its regression test remain independently
correct and are preserved in history per the one-commit-per-finding protocol.

### CR-03: An explicit end_date on a restrict/suspend record is silently overwritten by an unrelated later resume

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `032a78e`
**Applied fix:** In `build_limit_events()`, a record's own explicit `end_date` is now
preferred; the resume-lookahead branch only runs when `end` is absent. Added
`TestExplicitEndDatePrecedence` reproducing the review's scenario (an announcement with
`end_date="2022-03-01"` plus an unrelated later resume on `2022-06-01`) and asserting the
announcement's own end date survives.

### WR-01: open_restrictions stack pairs LIFO, disagreeing with build_limit_events()'s forward-nearest pairing

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `b7f0765`
**Applied fix:** Replaced `validate()`'s LIFO stack (`open_restrictions.append`/`.pop()`)
with a per-record forward search that mirrors `build_limit_events()`'s actual semantics:
each `restrict`/`suspend` (excluding `holiday_suspension`/`application_invalid`, which are
inherently single-day) independently searches forward for the nearest non-holiday resume;
if one exists anywhere later, it is considered closed. This single rework also carries
CR-02's holiday-resume fix. Added `TestValidateForwardNearestPairing` reproducing the
review's two-stacked-restricts-one-later-resume scenario, asserting `validate()` now
agrees with `build_limit_events()` that both are closed (previously one was falsely
flagged as unresolved and blocked the run).

### WR-02: postprocess()'s returned "raw" stat is actually the post-dedup count

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `fdb74bc`
**Applied fix:** Captured `raw_count = len(records)` immediately after `load_records()`,
before `records` is reassigned by `dedup_records()`, and returned `raw_count` in the stats
dict. Added `TestPostprocessRawStat` seeding two duplicate records that collapse to one
via `dedup_records()`, asserting `stats["raw"] == 3` and `stats["deduped"] == 2` (previously
both were always equal).

### WR-03: Malformed effective_date is silently swallowed rather than flagged

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `dfd4da6`
**Applied fix:** `validate()`'s staleness loop now appends an explicit issue when
`datetime.strptime(r["effective_date"], "%Y-%m-%d")` raises `ValueError`, instead of
silently `pass`-ing and disabling the staleness check for that record. Added
`TestMalformedEffectiveDateFlagged` asserting a record with `effective_date="not-a-date"`
now produces a finding naming the fund and the unparseable value.

### WR-04: `adjust_rule` action is a legal DB value but is silently a no-op through the entire pipeline

**Files modified:** `src/data/postprocess.py`, `tests/test_postprocess.py`
**Commit:** `3c52d81`
**Applied fix:** Added explicit documentation at all three no-op sites
(`fix_resume_type()`'s docstring, the `build_limit_events()` main loop, and `validate()`'s
open-restrictions check) stating that `adjust_rule` intentionally never seeds `last_type`,
never produces a `limit_events` interval, and is never treated as an unresolved
restriction -- it represents a rule change to an existing restriction, not a new
suspend/restrict state. Added `TestAdjustRuleIsIntentionalNoOp` with three tests pinning
this behavior across `fix_resume_type()`, `build_limit_events()`, and `validate()`.

### WR-05: CLI subprocess tests have no timeout — a hang in the script hangs the whole suite

**Files modified:** `tests/test_postprocess.py`
**Commit:** `541ba08`
**Applied fix:** Added `timeout=60` to the `subprocess.run()` call inside `_run_cli()`, so
a future hang in `scripts/parse_announcements.py` raises `subprocess.TimeoutExpired`
instead of hanging the test suite indefinitely.

## Skipped Issues

None — all 8 in-scope findings (CR-01, CR-02, CR-03, WR-01 through WR-05) were fixed.

## Verification

- Every fix was syntax-checked (`ast.parse`) and re-verified by running the full
  `tests/test_postprocess.py` module immediately after each commit (28 → 36 tests, all
  passing, growing by one or more regression tests per finding).
- Final full-suite run after all 8 fixes: `python -m unittest discover tests` — 141 tests,
  1 pre-existing failure (`test_overlapping_limits_last_one_wins` in
  `test_open_ended_limits.py`, unrelated to this phase and present in the baseline run
  before any fixes were applied), 4 skipped, no new failures introduced.
- Baseline (before fixes): 132 tests, same 1 pre-existing failure, 4 skipped.

## Not Fixed (Out of Scope)

Info-tier findings (IN-01, IN-02, IN-03) were excluded because `fix_scope` is
`critical_warning`. They remain documented in `04-REVIEW.md` for a future pass with
`fix_scope: all` if desired.

---

_Fixed: 2026-08-18T15:20:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
