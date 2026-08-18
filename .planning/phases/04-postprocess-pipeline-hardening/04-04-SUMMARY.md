---
phase: 04-postprocess-pipeline-hardening
plan: 04
subsystem: data-pipeline
tags: [validation, real-data, checkpoint, postprocess]

# Dependency graph
requires:
  - "ValidationBlockedError / validate() return-findings gate from 04-01"
  - "KNOWN_RESTRICTION_TYPES / build_limit_events() hardening from 04-02"
  - "write_limit_events() atomic staging-and-swap from 04-03"
provides:
  - "04-REAL-DB-VALIDATION.md — evidence-based measurement of the hardened pipeline against a copy of the real fund_status.db: 390 blocking findings by category, interval statistics, suite baseline, and the developer's checkpoint decision"
  - "Backlog phase 999.1 — overlapping suspend/restrict interval resolution in loader/engine limit-application logic, split out as its own follow-up"
affects: []

# Actuals (#2632)
actuals:
  tokens: 3200
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Real-data validation runs against a scratch copy of the production database, never the file in place — enforced by an acceptance criterion asserting `git status --porcelain` on the production file is empty."
    - "Checkpoint findings are measured, not summarized impressionistically: every count in the report and the checkpoint presentation is reproducible from a named command or direct function call, including the validate()-vs-build_limit_events() holiday-resume pairing comparison run specifically to test the checkpoint's own hypothesis."

key-files:
  created:
    - .planning/phases/04-postprocess-pipeline-hardening/04-REAL-DB-VALIDATION.md
  modified: []

key-decisions:
  - "Checkpoint decision: triage-data. The 390 real-data findings (373 staleness spanning 109 funds, 17 date-order inversions) are left as a hard block per D-01/D-02; they are triaged as genuine data-quality issues rather than treated as false positives from an overly strict check. This was informed by directly measuring the alternative: aligning validate()'s resume-pairing to skip holiday resumes (matching build_limit_events()) would *raise* the staleness count from 373 to 609, not lower it — so fix-validate-pairing was not selected, since the data does not support a false-positive framing."
  - "The pre-existing test_overlapping_limits_last_one_wins failure and the 529 measured overlapping interval pairs (77 funds) are escalated to a new backlog item (ROADMAP.md Phase 999.1) rather than absorbed into this phase or left undocumented, per the checkpoint's new-phase-flavored resolution for that specific sub-question. Phase 4 remains scoped to postprocess.py hardening only."
  - "Task 1's report and commit were produced in a prior sub-session whose executor agent stalled (stream watchdog, no progress for 600s) immediately after finishing the report but before committing it or reaching the Task 2 checkpoint. The orchestrator independently re-verified all of Task 1's acceptance criteria (fail/error count, pytest exit code, production-db-untouched, postprocess.py-unchanged) before committing the already-complete report as-is, rather than re-running the real-database pipeline a second time."

requirements-completed: [STAB-01, STAB-02, STAB-03]

coverage:
  - id: D6-1
    description: "postprocess() has been run once against a copy of the real fund_status.db and the outcome is recorded with exact counts: 390 findings (373 staleness / 109 funds, 17 date-order inversions, 0 unrecognised restriction_type), not summarised impressionistically."
    requirement: "STAB-01"
    verification:
      - kind: manual_procedural
        ref: ".planning/phases/04-postprocess-pipeline-hardening/04-REAL-DB-VALIDATION.md sections 1-2"
        status: pass
    human_judgment: false
  - id: D6-2
    description: "Full test suite recorded against the phase baseline of exactly one pre-existing failure (test_overlapping_limits_last_one_wins); no new failure or error introduced by Phase 4. tests/test_postprocess.py passes under both python -m unittest and python -m pytest."
    requirement: "STAB-02"
    verification:
      - kind: unit
        ref: "python -m unittest discover tests 2>&1 | grep -cE \"^(FAIL|ERROR): \" -> 1"
        status: pass
      - kind: unit
        ref: "python -m pytest tests/test_postprocess.py -q -> 27 passed"
        status: pass
    human_judgment: false
  - id: D6-3
    description: "The production fund_status.db was not modified by the validation run, and src/data/postprocess.py is byte-identical to its 04-03 state — no validation rule was loosened to make the real run pass."
    requirement: "STAB-03"
    verification:
      - kind: other
        ref: "git status --porcelain data/real_all_lof/config/fund_status.db (empty) + git diff --stat 687adbc -- src/data/postprocess.py (empty)"
        status: pass
    human_judgment: false
  - id: D6-4
    description: "The developer decided how to proceed with the real-data findings (triage-data) and how to handle the pre-existing overlapping-limits defect (new backlog phase), rather than the executor assuming or the block being silently loosened."
    verification: []
    human_judgment: true
    rationale: "This is the checkpoint:decision task's entire purpose — a human judgment call on data-triage strategy, not something automatable or auto-passable from a test."

# Metrics
duration: ~45min (includes one stalled sub-session recovered by the orchestrator, plus checkpoint wait time)
completed: 2026-08-18
status: complete
---

# Phase 4 Plan 4: Real-Data Validation & Triage Decision Summary

**The hardened postprocess() pipeline was run once against a copy of the real fund_status.db, producing 390 blocking findings (373 staleness / 109 funds, 17 date-order inversions, 0 unrecognised type) with 3,334 intervals and 529 overlapping pairs measured underneath the block; the developer chose to triage the findings as real data-quality issues (leaving D-01's hard block in force) and to open a separate backlog phase for the overlapping-interval defect.**

## Performance

- **Duration:** ~45 min (includes a stalled sub-session recovered by the orchestrator, plus checkpoint wait time)
- **Tasks:** 2
- **Files created:** 1 (`04-REAL-DB-VALIDATION.md`)
- **Commits:** 2 (plus 1 backlog-capture commit outside this plan's `files_modified` scope)

## Accomplishments

- Copied `data/real_all_lof/config/fund_status.db` read-only into a scratch directory and ran `scripts/parse_announcements.py --postprocess-only` against the copy. Exit code `1` — the validation gate built in 04-01 blocked the write, exactly as D-01/D-02 require when any finding exists.
- Categorized all 390 findings by calling `validate()` directly on the same deduped/fixed record set: 373 staleness (no resume within 180 days, spanning 109 of 247 funds — average ~3.4 findings per affected fund, not 373 independent incidents), 17 `effective_date < announcement_date` inversions, 0 unrecognised `restriction_type`. All three counts match the planning-time figures exactly.
- Measured what `build_limit_events()` would have produced had the block not fired: 3,334 intervals, 7 correctly clamped by 04-02's inverted-interval fix, 529 overlapping interval pairs across 77 funds (planning-time figure: 528 — one-pair drift from new announcements accumulated between planning and this run, through 2026-02).
- Directly tested the checkpoint's own candidate hypothesis: does aligning `validate()`'s resume-pairing to skip holiday resumes (matching `build_limit_events()`) reduce the finding count? Measured result: it *raises* staleness findings from 373 to 609 — the opposite of a false-positive story. This measurement, not a guess, is what ruled out `fix-validate-pairing`.
- Recorded the full-suite baseline: 132 tests, 1 failure (the same pre-existing `test_overlapping_limits_last_one_wins`, out of scope per REQUIREMENTS), 0 new failures or errors from Phase 4. `tests/test_postprocess.py` (27 tests) passes under both `unittest` and `pytest`.
- Confirmed `src/data/postprocess.py` byte-identical to the 04-03 commit (`git diff --stat 687adbc` empty) — no validation rule was loosened to make the real run pass, per D-08's explicit prohibition.
- Presented the full checkpoint (findings, categorized counts, the pairing-hypothesis measurement, and all three options) to the developer. **Decision: `triage-data`** — leave the block in force; the 390 findings are real data-quality issues to be triaged individually, not evidence of an over-strict check.
- Separately decided to open a backlog item (**ROADMAP.md Phase 999.1**) for the overlapping-interval defect (529 pairs + the pre-existing test failure), rather than folding it into the triage-data decision or leaving it undocumented.

## Task Commits

Each task was committed atomically:

1. **Task 1: Measure the phase against the real database and the suite baseline** - `60b0930` (docs) — committed by the orchestrator after independently re-verifying all acceptance criteria, since the executor agent that produced the report stalled before committing it (see Issues Encountered).
2. **Task 2: checkpoint:decision — record the developer's triage decision** - this SUMMARY.md commit (docs)

**Related but outside this plan's `files_modified` scope:** `f839062` (docs: add backlog item 999.1) — the ROADMAP.md backlog entry the checkpoint decision produced.

## Files Created/Modified

- `.planning/phases/04-postprocess-pipeline-hardening/04-REAL-DB-VALIDATION.md` - full evidence report: findings by category with samples, interval statistics, suite baseline, holiday-resume pairing measurement, findings requiring a decision
- `.planning/ROADMAP.md` - Backlog section added, Phase 999.1 entry (outside this plan's declared scope, produced by the checkpoint decision itself)

## Decisions Made

See `key-decisions` in frontmatter: `triage-data` selected for the 390 findings (informed by the pairing measurement ruling out `fix-validate-pairing`); `999.1` backlog phase opened for the overlapping-interval defect.

## Deviations from Plan

None in the plan's own scope. The backlog-phase creation (`f839062`) is a direct, expected consequence of the checkpoint's `<context>` explicitly naming "give the out-of-scope overlapping-limits failure ... a proper home" as part of the decision space — not scope creep, but it touches `ROADMAP.md` which is outside this plan's declared `files_modified: [04-REAL-DB-VALIDATION.md]`, so it is called out here rather than silently folded in.

## Issues Encountered

- **Executor stall on first attempt.** The first `gsd-executor` dispatch for this plan completed all of Task 1's substantive work (the real-database run, categorization, interval statistics, suite baseline, and the pairing-hypothesis measurement — the full `04-REAL-DB-VALIDATION.md` report) but stalled (stream watchdog: no progress for 600s) before committing the file or reaching the Task 2 checkpoint. No commits existed and no files besides the untracked report were touched. Recovery: the orchestrator read the completed report, independently re-ran all four acceptance-criteria commands (`unittest discover` fail/error count, `pytest tests/test_postprocess.py`, production-db git-status check, `postprocess.py` diff-since-04-03 check) to confirm the report's claims rather than trusting them blind, then committed the report as Task 1 directly. This avoided re-running the multi-minute real-database pipeline a second time while still independently verifying every acceptance criterion before commit.
- The pre-existing dirty working tree (milestone-archival renames staged since before this phase started) was left untouched throughout, as in all four plans of this phase — confirmed by a stable `git status --porcelain` line count (20) before and after this plan's commits.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All three phase requirements (STAB-01, STAB-02, STAB-03) are now demonstrated against real production data, not only fixtures. Phase 4's goal — hardening `postprocess.py`'s validation gate, state-machine regression coverage, and crash-safe writes — is complete.
- The pipeline remains blocked on the current production database (390 findings) per the `triage-data` decision; that triage work is now the developer's, not a GSD phase. `git diff --stat 687adbc -- src/data/postprocess.py` (empty) confirms nothing here re-opens or defers that block.
- Backlog Phase 999.1 (overlapping-interval resolution in loader/engine logic) is registered and ready for `/gsd-discuss-phase 999.1` or `/gsd-review-backlog` when the developer wants to promote it.
- No blockers for Phase 4 verification.

## Self-Check: PASSED

`04-REAL-DB-VALIDATION.md` verified present on disk. Commit `60b0930` verified present in `git log`. Backlog commit `f839062` verified present in `git log` and `.planning/ROADMAP.md`'s Backlog section verified to contain the Phase 999.1 entry.

---
*Phase: 04-postprocess-pipeline-hardening*
*Completed: 2026-08-18*
