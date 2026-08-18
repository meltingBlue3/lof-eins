---
phase: 04-postprocess-pipeline-hardening
plan: 02
subsystem: data-pipeline
tags: [unittest, postprocess, state-machine, regression-tests]

# Dependency graph
requires:
  - "PostprocessDBTestCase real-temp-SQLite harness from 04-01"
  - "validate() -> List[str] return contract from 04-01"
provides:
  - "KNOWN_RESTRICTION_TYPES frozenset constant in src/data/postprocess.py, mirroring the subscription_restrictions CHECK constraint"
  - "build_limit_events() raises ValueError naming fund/date/value for a non-empty unrecognised restriction_type"
  - "validate() mirror finding for the same unknown-type case, so postprocess() blocks before build_limit_events()'s exception fires"
  - "Inverted-interval clamp: a non-holiday resume sharing the suspend's effective_date yields a single-day interval instead of end < start"
  - "TestUnknownRestrictionType, TestIntervalOrdering, TestBuildLimitEventsRegression test classes in tests/test_postprocess.py"
affects: [04-03, 04-04]

# Actuals (#2632)
actuals:
  tokens: 5054
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-loud allowlist dispatch: a module-level frozenset constant checked at the earliest point in the branch, mirroring a DB CHECK constraint, with a comment tying the two together so they can't silently drift apart."
    - "Defence-in-depth validation: the same unknown-value check exists in both validate() (blocks the pipeline early with a readable message) and build_limit_events() (protects any direct caller) rather than relying on one gate alone."
    - "Regression-test docstrings that cite the fixing commit hash (89830c8), so a future reader deleting the test knows what defect they'd be un-pinning."

key-files:
  created: []
  modified:
    - src/data/postprocess.py
    - tests/test_postprocess.py

key-decisions:
  - "The unknown-restriction_type check sits in build_limit_events() right after rtype is extracted (before the holiday/pairing branch), not just before the amount branch as the plan's read_first pointed to — this covers the check for every downstream use of rtype in one place rather than duplicating it."
  - "Task 2 (regression matrix) landed as a single test(...) commit, not RED/GREEN/REFACTOR — all five scenarios passed against already-correct existing behavior on first run, consistent with the plan's framing that this task pins existing behavior rather than fixing a defect. This mirrors the same pattern used for 04-01 Task 2."

requirements-completed: [STAB-01]

coverage:
  - id: D6-1
    description: "Unknown non-empty restriction_type raises ValueError naming the value from build_limit_events(), and produces a validate() finding naming the value and fund; None/empty is tolerated by both."
    requirement: "STAB-01"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestUnknownRestrictionType"
        status: pass
    human_judgment: false
  - id: D6-2
    description: "A suspend/restrict paired with a non-holiday resume on the same effective_date clamps to a single-day interval instead of running backwards; build_limit_events() is deterministic across repeated calls; same-effective_date records preserve id order through load_records()."
    requirement: "STAB-01"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestIntervalOrdering"
        status: pass
    human_judgment: false
  - id: D6-3
    description: "The full D-06 scenario matrix: normal pairing, holiday-resume-mid-suspension (89830c8 defect 1), missing-prior-suspend synthetic interval (89830c8 defect 2), synthetic-survives-leading-holiday-resume compose case, and unmatched open-ended suspend round-tripped through a real write/read cycle with NULL end_date and is_open_ended=1."
    requirement: "STAB-01"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestBuildLimitEventsRegression"
        status: pass
    human_judgment: false

# Metrics
duration: ~25min
completed: 2026-08-18
status: complete
---

# Phase 4 Plan 2: build_limit_events() Regression Coverage + Fail-Loud Restriction-Type Gate Summary

**KNOWN_RESTRICTION_TYPES allowlist mirroring the DB CHECK constraint, a fail-loud unknown-type path in both build_limit_events() and validate(), an inverted-interval clamp, and the full D-06 regression matrix pinning both 89830c8 defects.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2
- **Files modified:** 2 (`src/data/postprocess.py`, `tests/test_postprocess.py`)
- **Commits:** 3

## Accomplishments

- `KNOWN_RESTRICTION_TYPES` — a module-level frozenset in `src/data/postprocess.py` holding exactly the six values the `subscription_restrictions.restriction_type` CHECK constraint in `src/data/downloader.py` permits, with a comment recording that the two must be kept in step.
- `build_limit_events()` now raises `ValueError` (naming the fund code, effective date, and offending value) when a record's `restriction_type` is a non-empty value outside the allowlist, instead of silently falling through to the existing zero-amount default branch. `None`/empty is untouched — this is the "unspecified" case 32 production records carry after `fix_resume_type()` runs.
- `validate()` gained a mirror check that appends a finding (same two-space-indented format as the two existing checks) for the same unknown-type case, so `postprocess()` blocks the run with a readable message before `build_limit_events()`'s exception is ever reached. This is intentional defence-in-depth: `validate()` guards the CLI path, the exception guards any direct caller of `build_limit_events()`.
- Inverted-interval clamp: when a non-holiday resume shares its paired suspend/restrict's `effective_date`, the previously-computed `end = resume_date - 1 day` ran backwards (end < start). The interval is now clamped to a single day (`end = start`) instead. The NULL open-ended case is untouched.
- `tests/test_postprocess.py` gained three new test classes:
  - `TestUnknownRestrictionType` (7 tests): the allowlist's exact contents, the raise-with-value behavior, the mirror `validate()` finding, `None`/empty tolerance on both `build_limit_events()` and `validate()`, and all six allowlisted types accepted without raising.
  - `TestIntervalOrdering` (3 tests): the same-day clamp producing exactly `2022-03-01`→`2022-03-01` with no backwards interval anywhere in output, determinism across two calls on identical input, and id-order preservation through `load_records()` for records sharing an `effective_date`.
  - `TestBuildLimitEventsRegression` (5 tests): the full D-06 scenario matrix — normal pairing (happy-path anchor), holiday-resume-mid-suspension not closing a long suspension (89830c8 defect 1, asserting the end date is `2022-05-31` and explicitly *not* `2022-02-06`), missing-prior-suspend synthetic interval (89830c8 defect 2), the synthetic interval surviving a leading holiday resume (proving the two fixes compose), and an unmatched open-ended suspend round-tripped through a real write/read cycle against the temp database, asserting a NULL stored `end_date` and `is_open_ended = 1`.
- 22 tests total in `tests/test_postprocess.py`, all passing under both `python -m unittest tests.test_postprocess -v` and `python -m pytest tests/test_postprocess.py -q`. `python -m unittest tests.test_announcement_processor` (20 tests, including the four pre-existing `TestBuildLimitEvents` cases) still passes unchanged, confirming the six allowlisted types kept their existing semantics.

## Task Commits

Each task was committed atomically. Task 1 followed a full RED/GREEN cycle (production code change); Task 2 landed as a single test-only commit because all five scenarios already passed against existing behavior.

1. **Task 1 RED — failing tests for the allowlist and clamp** - `80f5595` (test)
2. **Task 1 GREEN — implement the allowlist, fail-loud dispatch, mirror check, and clamp** - `8757c57` (feat)
3. **Task 2 — D-06 regression matrix (test-only, pins existing behavior)** - `a2532ee` (test)

## Files Created/Modified

- `src/data/postprocess.py` — `KNOWN_RESTRICTION_TYPES` constant added; `build_limit_events()` gains the fail-loud unknown-type check and the inverted-interval clamp; `validate()` gains the mirror unknown-type finding
- `tests/test_postprocess.py` — `TestUnknownRestrictionType`, `TestIntervalOrdering`, `TestBuildLimitEventsRegression` added (15 new tests, 22 total in the file); imports extended to include `KNOWN_RESTRICTION_TYPES`, `load_records`, `write_limit_events`

## Decisions Made

- Placed the unknown-type check immediately after `rtype = r.get("restriction_type", "")` is set in `build_limit_events()`, rather than strictly "before the amount branch" as the plan's `read_first` pointer described — this is earlier in the same code path and covers every subsequent use of `rtype` (the holiday check, the pairing loop, and the amount branch) with a single guard, which is a stricter reading of the same requirement, not a deviation from it.
- Task 2 landed as a single `test(...)` commit with no accompanying `feat`/`fix` commit, matching the pattern established in 04-01's Task 2: all five D-06 scenarios (normal pairing, both `89830c8` defects, the compose case, and the open-ended round-trip) passed against the already-implemented state machine on first run — no production bug was found, so no RED/GREEN cycle applied.

## Deviations from Plan

None — plan executed as written. Both tasks' behavior blocks, acceptance criteria, and threat-model mitigations (T-04-04, T-04-05, T-04-10) are fully covered by the tests added.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `KNOWN_RESTRICTION_TYPES`, the fail-loud dispatch, the `validate()` mirror check, and the inverted-interval clamp are all in place and tested — plan 04-03 (atomic table swap for `write_limit_events()`) can build directly on this without further changes to `build_limit_events()`/`validate()`.
- The D-06 regression matrix (`TestBuildLimitEventsRegression`) directly guards `write_limit_events()`'s generated `is_open_ended` column via a real write/read cycle, which plan 04-03 explicitly rebuilds when it introduces the staging-table swap — this test will need to keep passing through that change.
- The one pre-existing test failure (`tests/test_open_ended_limits.py::TestOpenEndedLimits::test_overlapping_limits_last_one_wins`) remains the sole baseline failure — confirmed unchanged by `python -m unittest discover tests` (`grep -cE "^(FAIL|ERROR): "` returns 1), out of scope per REQUIREMENTS and escalated in plan 04-04 as planned.

---
*Phase: 04-postprocess-pipeline-hardening*
*Completed: 2026-08-18*
