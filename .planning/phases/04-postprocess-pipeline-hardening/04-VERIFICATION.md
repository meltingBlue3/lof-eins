---
phase: 04-postprocess-pipeline-hardening
verified: 2026-08-18T00:00:00Z
status: human_needed
score: 26/27 must-haves verified
behavior_unverified: 1
overrides_applied: 0
requirements_coverage:
  STAB-01: satisfied
  STAB-02: satisfied
  STAB-03: satisfied
behavior_unverified_items:
  - truth: "A hard process kill during the write (not a raised exception) leaves limit_events intact, because the uncommitted transaction is rolled back from the journal when the database is next opened."
    test: "Kill the Python process (SIGKILL / TerminateProcess) mid-way through write_limit_events()'s insert loop, then re-open the same sqlite file and confirm the previous limit_events table is unchanged and no limit_events_new residue exists."
    expected: "SQLite's rollback-journal durability guarantees the transaction never partially commits — limit_events is byte-identical to its pre-write state, with no manual verification step needed beyond opening the file."
    why_human: "This exercises OS-level process-kill durability, which cannot be exercised inside a Python unittest process (the test process would kill itself). The plan's own must_haves list tags this truth verification: backstop for exactly this reason — no test in tests/test_postprocess.py exercises it, only the exception-driven rollback path (TestAtomicSwap) does. The mechanism (BEGIN IMMEDIATE with isolation_level=None, standard SQLite rollback-journal semantics, no WAL/PRAGMA override) is standard and plausible, but unexercised in this codebase's test suite."
human_verification:
  - test: "Kill python mid-write_limit_events() call (e.g. `kill -9` after seeding a large events list) and reopen the DB."
    expected: "limit_events unchanged, no limit_events_new table lingers."
    why_human: "OS-level crash durability cannot be exercised inside the test process itself; explicitly tagged verification: backstop in 04-03-PLAN.md's must_haves."
---

# Phase 4: Postprocess Pipeline Hardening Verification Report

**Phase Goal:** `src/data/postprocess.py`'s suspend/resume interval-building logic (the module responsible for the `89830c8` 7x-PnL-inflation bug) has regression test coverage, a validation gate that can block bad writes, and crash-safe table writes.
**Verified:** 2026-08-18
**Status:** human_needed
**Re-verification:** No — initial verification

**Note on scope:** This verification takes the post-code-review, post-fix state of `src/data/postprocess.py` and `tests/test_postprocess.py` as the delivered code (per task instructions), not the pre-review state described in the individual 04-01/02/03-SUMMARY.md files. The code review (`04-REVIEW.md`, 3 critical + 5 warning findings) and fix pass (`04-REVIEW-FIX.md`, all 8 fixed) are treated as part of the phase's actual delivery, and the real-data validation report's section 8 addendum (re-measured post-fix) is treated as the authoritative numbers.

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `pytest tests/test_postprocess.py` exists, passes, includes holiday-resume-in-the-middle and missing-prior-suspend synthetic-interval cases | ✓ VERIFIED | `python -m pytest tests/test_postprocess.py -q` → 36 passed. `TestBuildLimitEventsRegression.test_holiday_resume_mid_suspension_does_not_close_it` and `.test_missing_prior_suspend_yields_synthetic_interval` / `.test_synthetic_interval_survives_leading_holiday_resume` (lines 967-1058) directly pin both `89830c8` defects, citing the commit in docstrings. |
| 2 | `postprocess()` refuses to write `limit_events` (non-zero exit / clear error) when `validate()` findings exist | ✓ VERIFIED | `postprocess()` (postprocess.py:540-542) raises `ValidationBlockedError` on any non-empty `validate()` result; CLI catches it and exits 1 (parse_announcements.py:125-130). Roadmap text says "exceed a configurable threshold" — 04-01-PLAN.md's documented `assumption_delta_decision` explicitly supersedes this with an unconditional any-issue-blocks rule per D-01/D-02 (deliberate, not a scope reduction — delivered behavior is strictly stricter). |
| 3 | `write_limit_events()` writes to a staging table and swaps atomically; a run that fails partway leaves the previous table intact | ✓ VERIFIED | Code (postprocess.py:331-414): stages into `limit_events_new` inside `BEGIN IMMEDIATE`, drops+renames only after every insert succeeds, rolls back and re-raises on any exception. `TestAtomicSwap` (4 tests) forces a real `NOT NULL` constraint violation mid-write (no mocks, per D-07) and asserts the prior rows survive byte-identical, no `limit_events_new` residue, and a subsequent valid write recovers. |
| 4 | Full existing test suite still passes — no new failures beyond the recorded baseline | ✓ VERIFIED | `python -m unittest discover tests` → 141 tests, 1 failure (`test_overlapping_limits_last_one_wins`, the same pre-existing out-of-scope failure named in the plan baseline). No new failures/errors. `tests/test_announcement_processor` and `tests/test_database_schema` also pass unchanged (55 tests, OK). |

### Observable Truths (Plan must_haves, by requirement)

**STAB-02 (04-01):**

| Truth | Status | Evidence |
|---|---|---|
| Blocked run leaves `limit_events` byte-identical to before | ✓ VERIFIED | `TestValidationGate.test_blocked_run_leaves_limit_events_untouched` |
| Blocked run prints every issue, not truncated | ✓ VERIFIED | CLI catch handler (parse_announcements.py:126-129) iterates the full `e.issues` list to stderr — no `[:20]` slicing at the CLI layer. (Note: `validate()`'s own internal stdout print at line 503 truncates to 20 for readability during a normal run, but that is not the CLI's official blocked-run report, which the must-have specifically targets and which is unconditionally complete.) |
| Clean run writes and exits 0 | ✓ VERIFIED | `TestValidationGate.test_clean_run_writes_limit_events_and_replaces_sentinel` |
| No count threshold / severity tier — 1+ issues always blocks | ✓ VERIFIED | `if issues: raise ValidationBlockedError(issues)` — no threshold logic anywhere in `postprocess()`. |
| Strict >180-day staleness comparison | ✓ VERIFIED | `TestValidationBoundaries` — 180 days exactly → 0 issues, 181 days → 1 issue. |
| `timedelta.days` truncation semantics | ✓ VERIFIED | Comment + tests in `TestValidationBoundaries` (lines 330-343) explain and pin the truncating-not-rounding contract. |
| `build_limit_events([])`/`validate([])` return `[]`, no raise | ✓ VERIFIED | `TestEmptyInput.test_build_limit_events_empty_list` / `.test_validate_empty_list`; also confirmed via direct `python -c` call. |
| `postprocess()` on zero `subscription_restrictions` returns early stats, doesn't call write | ✓ VERIFIED | `TestEmptyInput.test_postprocess_empty_subscription_restrictions_leaves_limit_events` — sentinel row survives. |
| CLI writes blocked-run issues to stderr | ✓ VERIFIED | Code read, parse_announcements.py:126-129 (all `print(..., file=sys.stderr)`). |

**STAB-01 (04-02):**

| Truth | Status | Evidence |
|---|---|---|
| Holiday resume mid-suspension does not close it | ✓ VERIFIED | `test_holiday_resume_mid_suspension_does_not_close_it` — asserts end date `2022-05-31`, explicitly asserts NOT `2022-02-06` with a named-defect failure message. |
| Synthetic interval for missing prior suspend (and composes with leading holiday resume) | ✓ VERIFIED | `test_missing_prior_suspend_yields_synthetic_interval`, `test_synthetic_interval_survives_leading_holiday_resume`. |
| Unmatched suspend produces open (NULL end_date) interval, never dropped | ✓ VERIFIED | `test_unmatched_open_ended_suspend_round_trips_as_null` — round-trips through a real DB write/read, asserts NULL stored + `is_open_ended=1`. |
| Unrecognised non-empty `restriction_type` raises `ValueError` naming the value | ✓ VERIFIED | postprocess.py:234-238; `TestUnknownRestrictionType`. |
| Same case also produces a blocking `validate()` finding | ✓ VERIFIED | postprocess.py:436-442; `TestUnknownRestrictionType`. |
| `None`/empty `restriction_type` treated as unspecified, not unknown | ✓ VERIFIED | Guarded by `if rtype and rtype not in KNOWN_RESTRICTION_TYPES` (both functions); tests assert no raise/no finding for `None`. |
| All six allowlisted values accepted | ✓ VERIFIED | `python -c "from src.data.postprocess import KNOWN_RESTRICTION_TYPES as K; print(sorted(K))"` → exact 6-value match; `tests.test_announcement_processor`'s existing `TestBuildLimitEvents` (4 cases) still pass unchanged. |
| No interval ever has `end_date < start_date` | ✓ VERIFIED | Clamp at postprocess.py:282-283; `TestIntervalOrdering` + real-data measurement (7 clamped intervals in `04-REAL-DB-VALIDATION.md` §3a). |
| Deterministic output (stable sort, repeated calls equal) | ✓ VERIFIED | `TestIntervalOrdering` class present (acceptance-criteria-verified via test enumeration). |
| Happy-path semantics for the six allowlisted types unchanged | ✓ VERIFIED | `tests.test_announcement_processor` (existing `TestBuildLimitEvents`) passes unchanged; `test_normal_suspend_resume_pairing` anchors the happy path in the new file too. |

**STAB-03 (04-03):**

| Truth | Status | Evidence |
|---|---|---|
| Stages every row into `limit_events_new`; live table never dropped ahead of inserts | ✓ VERIFIED | postprocess.py:357-392 — `DROP TABLE IF EXISTS limit_events` (line 391) occurs only after the full insert loop (lines 373-388) completes. |
| Mid-write failure leaves prior table exactly intact | ✓ VERIFIED | `TestAtomicSwap.test_mid_write_failure_leaves_previous_rows_intact_and_reraises` — real `NOT NULL` violation, asserts byte-identical rows. |
| No `limit_events_new` residue after failure | ✓ VERIFIED | `TestAtomicSwap.test_mid_write_failure_leaves_no_staging_table_residue`. |
| Failure re-raises, doesn't swallow | ✓ VERIFIED | `except Exception: ... raise` (postprocess.py:404-410); test asserts `sqlite3.IntegrityError` propagates. |
| Successful write: canonical index names + generated column intact | ✓ VERIFIED | `TestAtomicSwap.test_successful_write_against_fresh_database_creates_indexes`; also `test_unmatched_open_ended_suspend_round_trips_as_null` exercises the STORED generated column. |
| No backup table retained after successful swap | ✓ VERIFIED | Code performs a straight drop+rename, no third table created; `04-REAL-DB-VALIDATION.md` reasoning + code read confirm. |
| All SQL is fixed literals, all values bound | ✓ VERIFIED | `grep -c 'execute(f' src/data/postprocess.py` → `0`. |
| Idempotent shape across repeated writes | ✓ VERIFIED | `TestAtomicSwap.test_two_successive_successful_writes_hold_exactly_second_calls_rows`. |
| Hard process kill (not exception) leaves table intact | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Mechanism is present (transactional DDL via `BEGIN IMMEDIATE`, `isolation_level=None`) and is the standard SQLite crash-durability guarantee, but no test in the suite exercises an actual process kill — explicitly tagged `verification: backstop` in 04-03-PLAN.md's own must_haves. Routed to human verification below. |
| `max_amount` REAL round-trips without precision loss at production magnitudes | ✓ VERIFIED (indirect) | `TestValidationGate.test_clean_run_writes_limit_events_and_replaces_sentinel` writes `1000000` and reads back `max_amount == 1000000` exactly through a real DB round trip; production magnitudes are whole-yuan integers well inside a double's exact-integer range. |

**STAB-01/02/03 (04-04, real-data validation):**

| Truth | Status | Evidence |
|---|---|---|
| `postprocess()` run once against a copy of real `fund_status.db`, outcome recorded with exact counts | ✓ VERIFIED | `04-REAL-DB-VALIDATION.md` §1-3; re-measured in §8 addendum post-fix (434 findings / 3,334 intervals / 504 overlap pairs). |
| Suite baseline recorded, no new failures | ✓ VERIFIED | §5 and §8: 141 tests post-fix, 1 pre-existing out-of-scope failure, confirmed independently by this verification's own `unittest discover` run. |
| `tests/test_postprocess.py` passes under both `unittest` and `pytest` | ✓ VERIFIED | Confirmed directly: both runners exit 0 (36/36). |
| Production DB not modified | ✓ VERIFIED | `git status --porcelain data/real_all_lof/config/fund_status.db` → empty (confirmed independently). |
| Decision made by developer, not assumed | ✓ VERIFIED (procedural) | `checkpoint:decision` task (`autonomous: false`) in 04-04-PLAN.md; decision recorded in 04-04-SUMMARY.md as `triage-data`. Verifier cannot confirm human identity behind the resume-signal — this is a process/procedural truth, not a code truth, and is accepted as documented. |
| Overlapping-interval finding escalated, not absorbed | ✓ VERIFIED | `ROADMAP.md` Backlog Phase 999.1 entry present (lines 124-128), referencing the same test failure and overlap count. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/data/postprocess.py` | `ValidationBlockedError`, gated `postprocess()`, `KNOWN_RESTRICTION_TYPES`, clamp, staged/atomic `write_limit_events()` | ✓ VERIFIED | All present, substantive, wired — read in full (558 lines). |
| `scripts/parse_announcements.py` | Catches `ValidationBlockedError`, exits 1, prints full issue list to stderr | ✓ VERIFIED | Lines 53, 123-130. |
| `tests/test_postprocess.py` | Full must-have test matrix across all three requirements | ✓ VERIFIED | 1277 lines, 14 test classes, 36 tests, all passing under both runners. |
| `.planning/phases/04-postprocess-pipeline-hardening/04-REAL-DB-VALIDATION.md` | D-08 real-data triage report | ✓ VERIFIED | Present, includes post-fix addendum (§8) keeping numbers accurate. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `validate()` return value | `postprocess()` gate decision | `issues = validate(records); if issues: raise ValidationBlockedError(issues)` | ✓ WIRED | postprocess.py:540-542 |
| `postprocess()` raised `ValidationBlockedError` | CLI exit code | `except ValidationBlockedError as e: ... sys.exit(1)` | ✓ WIRED | parse_announcements.py:125-130 |
| `KNOWN_RESTRICTION_TYPES` | `build_limit_events()` dispatch + `validate()` unknown-type check | Both functions import/reference the same frozenset | ✓ WIRED | postprocess.py:234, 438 |
| `_is_holiday_resume()` | Resume-pairing loop, synthetic-interval detector, and `validate()`'s pairing (post-fix) | Called from all three sites | ✓ WIRED | postprocess.py:187, 259, 468 (the last added by the WR-01/CR-02 fix) |
| `write_limit_events()` staging transaction | Live `limit_events` table | `DROP`+`ALTER TABLE ... RENAME` only after full insert loop | ✓ WIRED | postprocess.py:391-392 |
| `validate()` findings on real data | Developer triage decision | `checkpoint:decision` task, recorded `triage-data` | ✓ WIRED (procedural) | 04-04-SUMMARY.md |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| STAB-01 | 04-02 (+04-04 real-data proof) | `build_limit_events()` suspend/resume regression coverage, incl. `89830c8` scenarios | ✓ SATISFIED | See truths table above. |
| STAB-02 | 04-01 (+04-04 real-data proof) | `validate()` gate blocks bad writes | ✓ SATISFIED | See truths table above. |
| STAB-03 | 04-03 (+04-04 real-data proof) | Atomic staged-table swap | ✓ SATISFIED | See truths table above. |

No orphaned requirements — all three IDs mapped to this phase in `.planning/REQUIREMENTS.md` appear in plan frontmatter (`04-01`: STAB-02, `04-02`: STAB-01, `04-03`: STAB-03, `04-04`: all three).

### Anti-Patterns Found

None. `grep -n -E "TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER"` across `src/data/postprocess.py`, `tests/test_postprocess.py`, `scripts/parse_announcements.py` returns no matches. No mocking library used (real temp-SQLite throughout, per D-07). No stub returns, no hardcoded empty data flowing to output.

### Code Review Findings (post-completion, resolved)

A standard-depth code review (`04-REVIEW.md`) found 3 critical + 5 warning issues after the 4 plans completed — all of which materially undermined the phase's stated goal (e.g. CR-01: a record set deriving zero intervals would have silently wiped `limit_events`; CR-02/WR-01: `validate()`'s pairing disagreed with `build_limit_events()`'s, producing both false negatives and false positives). All 8 were fixed in a follow-up pass (`04-REVIEW-FIX.md`), each with its own regression test, verified in this verification run via `git log` (8 distinct `fix(04):` commits present) and direct code/test reading. The 3 Info-tier findings (docstring completeness, an unrelated CLI-flag UX nit, a latent unused-field default) were left unfixed by design (`fix_scope: critical_warning`) and are non-blocking.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| `tests/test_postprocess.py` passes (unittest) | `python -m unittest tests.test_postprocess -v` | 36 tests, OK | ✓ PASS |
| `tests/test_postprocess.py` passes (pytest) | `python -m pytest tests/test_postprocess.py -q` | 36 passed | ✓ PASS |
| Full suite baseline | `python -m unittest discover tests` | 141 tests, 1 pre-existing failure, 0 new | ✓ PASS |
| No interpolated SQL | `grep -c 'execute(f' src/data/postprocess.py` | `0` | ✓ PASS |
| `KNOWN_RESTRICTION_TYPES` exact allowlist | `python -c "..."` | matches 6 expected values | ✓ PASS |
| `validate([])` returns `[]` | `python -c "..."` | `[]` | ✓ PASS |
| `ValidationBlockedError` referenced in `postprocess()` source | `python -c "..."` | `True` | ✓ PASS |
| CLI arg count unchanged | `grep -c 'add_argument' scripts/parse_announcements.py` | `10` | ✓ PASS |
| Production DB untouched | `git status --porcelain data/real_all_lof/config/fund_status.db` | empty | ✓ PASS |
| Existing indirect coverage regression check | `python -m unittest tests.test_announcement_processor tests.test_database_schema` | 55 tests, OK | ✓ PASS |

### Human Verification Required

1. **Hard process-kill durability of `write_limit_events()`**
   **Test:** Seed `limit_events` with known rows, start a `write_limit_events()` call with a large events list, and `kill -9` (or `TerminateProcess`) the Python process partway through the insert loop. Reopen the same SQLite file.
   **Expected:** `limit_events` is byte-identical to its pre-write state; `sqlite_master` contains no `limit_events_new` table.
   **Why human:** This must exercise real OS-level process termination, which cannot run inside the same Python test process that would need to survive to make the assertion. The plan itself (`04-03-PLAN.md`) tags this exact truth `verification: backstop` for this reason — it documents the expected SQLite rollback-journal guarantee but does not (and structurally cannot, from a `unittest` test method) exercise it. The exception-driven rollback path (which is the practically common failure mode) is thoroughly tested by `TestAtomicSwap` and is not in question.

### Gaps Summary

No gaps. All roadmap Success Criteria and all plan-level must-haves are implemented, wired, and covered by passing tests (36/36 in `tests/test_postprocess.py`, 141/142 in the full suite with the one pre-existing, explicitly out-of-scope failure). The post-completion code review caught three critical correctness defects that would have undermined the phase's core promise (silent data-wipe on zero-interval batches; `validate()`/`build_limit_events()` disagreement); all were fixed with dedicated regression tests, verified present in git history and in the current source. The single open item is a `backstop`-tagged truth about OS-level crash durability that the plan authors themselves flagged as untestable from within the test suite — routed to human verification rather than treated as a gap, since the code, transaction structure, and every exception-driven failure path are fully verified.

---

_Verified: 2026-08-18_
_Verifier: Claude (gsd-verifier)_
