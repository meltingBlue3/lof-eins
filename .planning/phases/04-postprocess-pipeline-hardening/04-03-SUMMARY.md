---
phase: 04-postprocess-pipeline-hardening
plan: 03
subsystem: data-pipeline
tags: [sqlite, transactions, atomic-swap, unittest, postprocess]

# Dependency graph
requires:
  - "PostprocessDBTestCase real-temp-SQLite harness from 04-01"
  - "KNOWN_RESTRICTION_TYPES / build_limit_events() hardening from 04-02"
provides:
  - "write_limit_events() staging-and-swap: inserts into limit_events_new inside one explicit BEGIN IMMEDIATE transaction, only drops/renames the live limit_events table after the last insert succeeds"
  - "TestAtomicSwap in tests/test_postprocess.py proving the mid-write failure path leaves the previous limit_events table byte-identical, leaves no staging residue, re-raises, and does not wedge the database"
affects: [04-04]

# Actuals (#2632)
actuals:
  tokens: 3039
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Explicit transaction control via isolation_level=None + BEGIN IMMEDIATE, because the sqlite3 driver only opens an implicit transaction ahead of DML statements, not DDL -- table DROP/CREATE/ALTER/rename statements would otherwise each commit immediately."
    - "Stage-then-swap: all writes land in a scratch limit_events_new table first; the live table is dropped and the staging table renamed into place only after every insert succeeds, inside the same transaction that created the staging table -- so a rollback (exception or hard kill) removes the staging table for free and never touches the live table."
    - "Mid-write failure induced with a real NOT NULL constraint violation (start_date=None), not a mocking library, per D-07."

key-files:
  created: []
  modified:
    - src/data/postprocess.py
    - tests/test_postprocess.py

key-decisions:
  - "Task 2 landed as a single test(...) commit, not RED/GREEN/REFACTOR: write_limit_events()'s atomic swap was already implemented in Task 1 (this plan requires the swap to exist before the failure-path tests can meaningfully target it), and all 5 TestAtomicSwap scenarios passed against that implementation on first run. This mirrors the pattern already established in 04-01 and 04-02's Task 2."
  - "Indexes are created only on the live limit_events table after the rename, never on limit_events_new, per the plan's explicit instruction -- SQLite does not rename indexes along with a table rename, so creating them on the staging table under the canonical names would collide with the live table's indexes during the transition window."

requirements-completed: [STAB-03]

coverage:
  - id: D5-1
    description: "write_limit_events() stages every row into limit_events_new and only replaces the live table after the last insert succeeds; the live table is never dropped ahead of the inserts."
    requirement: "STAB-03"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_mid_write_failure_leaves_previous_rows_intact_and_reraises"
        status: pass
    human_judgment: false
  - id: D5-2
    description: "A write_limit_events() call that raises partway through its inserts leaves the pre-existing limit_events table with exactly its prior row count and contents, re-raises the original exception, and leaves no limit_events_new residue in sqlite_master."
    requirement: "STAB-03"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_mid_write_failure_leaves_previous_rows_intact_and_reraises"
        status: pass
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_mid_write_failure_leaves_no_staging_table_residue"
        status: pass
    human_judgment: false
  - id: D5-3
    description: "A subsequent valid write succeeds immediately after a failed one and leaves exactly the new rows -- the database is not wedged."
    requirement: "STAB-03"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_valid_write_after_failed_write_succeeds_and_replaces"
        status: pass
    human_judgment: false
  - id: D5-4
    description: "A successful write against a fresh database (no pre-existing limit_events table) succeeds and creates both canonical index names (idx_limit_events_ticker, idx_limit_events_is_open_ended) on the live table; repeated successful writes remain replace-semantics idempotent."
    requirement: "STAB-03"
    verification:
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_successful_write_against_fresh_database_creates_indexes"
        status: pass
      - kind: unit
        ref: "tests/test_postprocess.py#TestAtomicSwap.test_two_successive_successful_writes_hold_exactly_second_calls_rows"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-08-18
status: complete
---

# Phase 4 Plan 3: Atomic Table Swap for write_limit_events() Summary

**write_limit_events() now stages every row into limit_events_new inside a single explicit transaction and only swaps the live table in after the final insert succeeds, so a crash mid-write leaves the last known-good limit_events table byte-identical, proven by a forced real NOT NULL constraint failure.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2
- **Files modified:** 2 (`src/data/postprocess.py`, `tests/test_postprocess.py`)
- **Commits:** 2

## Accomplishments

- `write_limit_events()` rewritten to open the connection with `isolation_level=None` and an explicit `BEGIN IMMEDIATE`, so every DDL and DML statement in the write participates in one transaction (the driver only auto-opens implicit transactions ahead of DML, not DDL, so this was required for the DROP/CREATE/ALTER sequence to be atomic at all).
- Every event is inserted into a scratch `limit_events_new` table first. Only after the last insert succeeds does the function drop the live `limit_events` table, rename `limit_events_new` into its place, and recreate the two canonical indexes (`idx_limit_events_ticker`, `idx_limit_events_is_open_ended`) on the now-live table.
- On any exception, the transaction is rolled back (which also removes the staging table, since it was created inside the same transaction — no separate cleanup needed) and the original exception is re-raised unchanged, so `postprocess()`/the CLI surface it instead of reporting a silent success. The rollback is guarded so a pre-transaction failure cannot mask the real error.
- A defensive `DROP TABLE IF EXISTS limit_events_new` at the start of the transaction clears residue from a hard process kill on a prior run.
- Every statement in the rewritten function is a fixed string literal; all six per-row values continue to travel as bound parameters — `grep -c 'execute(f' src/data/postprocess.py` returns `0`.
- `TestAtomicSwap` added to `tests/test_postprocess.py` (5 tests): forces a mid-write failure with a real `sqlite3.IntegrityError` (NULL `start_date`, no mocking library per D-07) and asserts the two previously-seeded rows are byte-identical afterward; asserts `limit_events_new` is absent from `sqlite_master` after the failure; asserts a subsequent valid write succeeds and holds exactly its own rows; covers the fresh-database path (both canonical indexes present) and the repeated-write replace-semantics contract.
- 27 tests total in `tests/test_postprocess.py`, all passing under both `python -m unittest tests.test_postprocess -v` and `python -m pytest tests/test_postprocess.py -q`. `python -m unittest tests.test_announcement_processor tests.test_database_schema` also pass unchanged, confirming the three existing `TestWriteLimitEvents` cases and the schema assertions still hold against the new implementation.
- `python -m unittest discover tests 2>&1 | grep -cE "^(FAIL|ERROR): "` returns `1` — the recorded pre-existing out-of-scope failure only, unchanged from the phase baseline.

## Task Commits

Each task was committed atomically:

1. **Task 1: Stage into limit_events_new and swap inside one transaction** - `6ce75e9` (feat)
2. **Task 2: Prove the failure path leaves the previous table intact** - `687adbc` (test)

_Note: Task 2 is test-only pinning of behavior already implemented in Task 1 (the atomic swap has to exist before its failure path can be meaningfully tested), so it landed as a single `test(...)` commit rather than a RED/GREEN/REFACTOR sequence — no production code changes were needed or made in Task 2. This mirrors the pattern used in 04-01 and 04-02's Task 2._

## Files Created/Modified

- `src/data/postprocess.py` — `write_limit_events()` rewritten: explicit `isolation_level=None` + `BEGIN IMMEDIATE` transaction; stages into `limit_events_new`; swaps the live table in only after every insert succeeds; recreates canonical indexes on the live table; rolls back and re-raises on any failure
- `tests/test_postprocess.py` — `TestAtomicSwap` added (5 tests): mid-write-failure-leaves-rows-intact, no-staging-residue, valid-write-after-failure-succeeds, fresh-database-creates-indexes, repeated-writes-replace-semantics

## Decisions Made

- Indexes are created only on the live `limit_events` table after the rename, never on `limit_events_new` — per the plan's explicit instruction, since SQLite does not rename indexes along with a table rename, creating them on the staging table under canonical names would collide with the live table's indexes during the transition window.
- Task 2's mid-write failure is induced with a real `start_date=None` value against the schema's `NOT NULL` constraint on that column, producing a genuine `sqlite3.IntegrityError` — no mocking library was introduced, per D-07.
- Task 2 landed as a single `test(...)` commit rather than following RED/GREEN/REFACTOR, since the behavior under test was already correctly implemented by Task 1 within this same plan; this is the same pattern 04-01 and 04-02 used for their respective Task 2s.

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria (grep counts, statement-ordering check, index-presence check) and all `<behavior>` scenarios in Task 2 passed without requiring any fix beyond the planned implementation.

## Issues Encountered

- Both task commits initially swept in unrelated pre-staged file renames (milestone archiving from an earlier, unrelated session) because they were already in the git index before this session started, and a plain `git commit -m` commits the whole index by default. Caught immediately via the post-commit deletion check on Task 1's commit, fixed with `git reset --soft HEAD^` followed by `git commit --only <file> -m "..."` for both task commits, restoring the pre-existing staged renames to their original untouched state each time. No functional impact; both task commits (`6ce75e9`, `687adbc`) contain exactly their intended files, and `git diff --diff-filter=D --name-only HEAD~1 HEAD` confirmed no deletions in either commit.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `write_limit_events()`'s atomic staging-and-swap is fully implemented and tested — the last of the three known `postprocess.py` hardening gaps named in `PROJECT.md`'s Known Issues (validation gate, `build_limit_events()` regression coverage, and this transaction safety) is now closed.
- The one pre-existing test failure (`tests/test_open_ended_limits.py::TestOpenEndedLimits::test_overlapping_limits_last_one_wins`) remains the sole baseline failure — confirmed unchanged by `python -m unittest discover tests` (`grep -cE "^(FAIL|ERROR): "` returns 1), out of scope per REQUIREMENTS and escalated in plan 04-04 as planned.
- No blockers identified for plan 04-04.

## Self-Check: PASSED

All modified files verified present on disk (`src/data/postprocess.py`, `tests/test_postprocess.py`, this SUMMARY.md). Both commit hashes (`6ce75e9`, `687adbc`) verified present in `git log`.

---
*Phase: 04-postprocess-pipeline-hardening*
*Completed: 2026-08-18*
