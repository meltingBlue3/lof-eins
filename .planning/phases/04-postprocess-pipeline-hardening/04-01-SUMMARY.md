---
phase: 04-postprocess-pipeline-hardening
plan: 01
subsystem: data-pipeline
tags: [sqlite, unittest, postprocess, validation-gate, cli]

# Dependency graph
requires: []
provides:
  - "ValidationBlockedError exception (carries .issues: List[str]) in src/data/postprocess.py"
  - "validate() -> List[str] return contract (was implicit None)"
  - "postprocess() raises ValidationBlockedError before build_limit_events()/write_limit_events() when validate() finds issues"
  - "scripts/parse_announcements.py non-zero exit path with full issue list on stderr"
  - "tests/test_postprocess.py with PostprocessDBTestCase, a reusable real-temp-SQLite harness every later plan in this phase builds on"
affects: [04-02, 04-03, 04-04]

# Actuals (#2632)
actuals:
  tokens: 4483
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Real temp-SQLite-DB test harness (tempfile.mkdtemp + shutil.rmtree, schema copied verbatim from production CREATE TABLE statements) — no mocking library, per D-07/TESTING.md convention."
    - "CLI subprocess testing via sys.executable with PYTHONIOENCODING=utf-8 and errors='replace' decoding to survive Windows GBK console code page."
    - "Unconditional hard-block validation gate: any non-empty issues list blocks the write, no severity tiers, no opt-in flag (D-01/D-02)."

key-files:
  created:
    - tests/test_postprocess.py
  modified:
    - src/data/postprocess.py
    - scripts/parse_announcements.py

key-decisions:
  - "Promoted the 'configurable threshold' language in ROADMAP/REQUIREMENTS to an unconditional any-issue-blocks rule per CONTEXT.md D-01/D-02 (assumption-delta decision recorded in the plan) — deliberate supersession, not a scope reduction."
  - "Task 2's boundary tests build effective_date/announcement_date from datetime.now() at test-run time rather than hardcoded dates, so the 180-day staleness assertions do not rot."
  - "The 180-days-and-23-hours case named in the plan is pinned by contract (180-day case = 0 issues, 181-day case = 1 issue) plus an explanatory code comment, rather than a third literal test, because validate() parses effective_date with a date-only format and cannot carry a sub-day component through that field."

patterns-established:
  - "PostprocessDBTestCase._run_cli() subprocess pattern for exercising scripts/parse_announcements.py end-to-end from tests."

requirements-completed: [STAB-02]

coverage:
  - id: D1
    description: "A blocked run (validation finding present) exits 1, prints every issue, and leaves a previously-written limit_events table byte-identical."
    requirement: "STAB-02"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestValidationGate.test_blocked_run_leaves_limit_events_untouched"
        status: pass
    human_judgment: false
  - id: D2
    description: "A clean run (no validation findings) exits 0, writes limit_events from the seeded records, and replaces (not merges with) the previous sentinel row."
    requirement: "STAB-02"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestValidationGate.test_clean_run_writes_limit_events_and_replaces_sentinel"
        status: pass
    human_judgment: false
  - id: D3
    description: "The 180-day staleness boundary is a strict greater-than comparison: exactly 180 days old yields 0 issues, 181 days old yields exactly 1 issue naming the fund."
    requirement: "STAB-02"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestValidationBoundaries.test_exactly_180_days_yields_no_issue"
        status: pass
      - kind: unit
        ref: "tests/test_postprocess.py#TestValidationBoundaries.test_181_days_yields_exactly_one_issue_naming_the_fund"
        status: pass
    human_judgment: false
  - id: D4
    description: "build_limit_events([]), validate([]), and postprocess() against zero subscription_restrictions rows all handle empty input without raising and without wiping a pre-seeded limit_events table."
    requirement: "STAB-02"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestEmptyInput.test_build_limit_events_empty_list"
        status: pass
      - kind: unit
        ref: "tests/test_postprocess.py#TestEmptyInput.test_validate_empty_list"
        status: pass
      - kind: unit
        ref: "tests/test_postprocess.py#TestEmptyInput.test_postprocess_empty_subscription_restrictions_leaves_limit_events"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min (across two sessions; Task 1 ~8min, Task 2 ~10min active work)
completed: 2026-08-18
status: complete
---

# Phase 4 Plan 1: Validation Gate Tracer + Boundary/Empty-Input Pinning Summary

**Unconditional validation gate wired end-to-end (validate() -> postprocess() -> CLI exit code) with a reusable real-temp-SQLite test harness, plus tests pinning the pass side, the exact 180-day staleness boundary, and all empty-input shapes.**

## Performance

- **Duration:** ~20 min total across two sessions (Task 1 tracer + checkpoint approval, Task 2 this continuation)
- **Started:** 2026-08-18T18:16:12+08:00 (plan creation)
- **Completed:** 2026-08-18T20:27:54+08:00
- **Tasks:** 2
- **Files modified:** 3 (`src/data/postprocess.py`, `scripts/parse_announcements.py`, `tests/test_postprocess.py`)

## Accomplishments

- `ValidationBlockedError` (subclass of `RuntimeError`, carries `.issues: List[str]`) raised by `postprocess()` before any write reaches `limit_events` when `validate()` reports one or more issues — no severity tiers, no threshold, no opt-in flag.
- `validate()` now returns its findings as `List[str]` instead of only printing them; every existing check, format, and summary print is unchanged.
- `scripts/parse_announcements.py` catches `ValidationBlockedError`, prints every issue to stderr (not a truncated preview) plus a count line, and exits 1 — the CLI's argument set is unchanged (still 10 `add_argument` calls).
- `tests/test_postprocess.py` created with `PostprocessDBTestCase`, a shared real-temp-SQLite-DB harness (`_seed_subscription_restrictions`, `_seed_limit_events`, `_read_limit_events`, `_table_names`, `_run_cli`) that every later plan in this phase reuses.
- Task 1's tracer test proves the blocked path end-to-end: a validation finding blocks the write, exits 1, and leaves a previously-written `limit_events` table byte-identical.
- Task 2 pins the pass side (clean matched restrict/resume pair -> exit 0, `limit_events` populated, sentinel row replaced), the exact 180-day staleness boundary (180 days = 0 issues, 181 days = exactly 1 issue naming the fund), and all three empty-input shapes (`build_limit_events([])`, `validate([])`, `postprocess()` against zero `subscription_restrictions` rows).
- 7 tests total, all passing under both `python -m unittest tests.test_postprocess -v` and `python -m pytest tests/test_postprocess.py -q`.

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end "validation blocks the write" — one path only (tracer)** - `da80aae` (feat)
2. **Task 2: Pin the pass side, the 180-day boundary, and empty input** - `f8376cb` (test)

**Plan metadata:** committed via `docs(04-01)` final commit (see below)

_Note: Task 2 is test-only pinning of already-implemented behavior (per plan's explicit framing), so it landed as a single `test(...)` commit rather than a RED/GREEN/REFACTOR sequence — no production code changes were needed or made._

## Files Created/Modified

- `tests/test_postprocess.py` - New file; `PostprocessDBTestCase` harness, `TestValidationGate` (tracer + pass-side), `TestValidationBoundaries` (180-day boundary), `TestEmptyInput` (empty-input shapes) — 7 tests total
- `src/data/postprocess.py` - `ValidationBlockedError` class added; `validate()` changed to return `List[str]`; `postprocess()` raises before write on any finding
- `scripts/parse_announcements.py` - Imports and catches `ValidationBlockedError`; prints full issue list to stderr and exits 1 on block

## Decisions Made

- Promoted "configurable threshold" wording in ROADMAP/REQUIREMENTS to an unconditional any-issue-blocks rule per CONTEXT.md D-01/D-02 — this was a plan-level assumption-delta decision, not something decided during execution, and is documented in the plan's `<assumption_delta_decision>` block.
- Task 2's 180-day boundary tests build `effective_date`/`announcement_date` from `datetime.now()` at test-run time (not hardcoded literal dates), so the assertions do not rot as calendar time passes.
- The "180 days and 23 hours" truncation case named in the plan's `<behavior>` block is pinned by contract (180-day case yields 0 issues, 181-day case yields exactly 1) plus an explanatory code comment rather than a third literal test — `validate()` parses `effective_date` with the date-only format `"%Y-%m-%d"`, so a record cannot carry a sub-day component through that field, making a direct "180 days + 23 hours" fixture inexpressible as a `subscription_restrictions` row.

## Deviations from Plan

None - plan executed exactly as written. Task 2 was test-only work against already-implemented behavior (as the plan's `<action>` explicitly frames it); no bugs were found in `validate()` or `postprocess()` requiring a fix.

## Issues Encountered

- Git commit for Task 2 initially swept in unrelated pre-staged file renames (milestone archiving from earlier, unrelated work) because they were already in the index before this session started and `git commit -m` commits the whole index by default. Caught immediately via the post-commit deletion/diff check, fixed with `git reset --soft HEAD^` followed by `git commit --only tests/test_postprocess.py`, restoring the pre-existing staged renames to their original untouched state. No functional impact; both task commits (`da80aae`, `f8376cb`) contain exactly their intended files.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The validation gate is fully wired and tested end-to-end (blocked path, pass path, boundary, empty input) — plans 04-02, 04-03, and 04-04 can build directly on `PostprocessDBTestCase` and the `ValidationBlockedError`/`validate()` contract established here.
- No blockers identified for 04-02 (build_limit_events regression coverage / KNOWN_RESTRICTION_TYPES) or 04-03 (atomic swap for write_limit_events).
- The one pre-existing test failure (`tests/test_open_ended_limits.py::TestOpenEndedLimits::test_overlapping_limits_last_one_wins`) remains the phase baseline's sole failure — confirmed unchanged by `python -m unittest discover tests` (`grep -cE "^(FAIL|ERROR): "` returns 1), out of scope per REQUIREMENTS and escalated in plan 04-04 as planned.

---
*Phase: 04-postprocess-pipeline-hardening*
*Completed: 2026-08-18*
