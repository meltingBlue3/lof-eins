# Phase 04 Real-Database Validation Report

**Purpose:** D-08 required that the hardened `postprocess()` pipeline be run once against a copy of the real production `fund_status.db`, and that any hard-block finding be surfaced for developer triage rather than silently softened. This report is that run's evidence.

**Run date:** 2026-08-18

**Production database:** `data/real_all_lof/config/fund_status.db` (7,557,120 bytes at time of copy)

## 1. Copy and CLI run

The production database was copied read-only into a scratch directory laid out as `<scratch>/config/fund_status.db`, so `scripts/parse_announcements.py --data-dir <scratch>`'s convention resolves it without ever opening the production file for write. The scratch directory lives outside the repository (`$TEMP/claude/.../scratchpad/04-04-validation/`).

Command run (with `PYTHONIOENCODING=utf-8` set in the subprocess environment, since the Windows console's GBK code page otherwise mangles the Chinese status output):

```
python scripts/parse_announcements.py --postprocess-only --data-dir <scratch>
```

**Exit code:** `1` (validation blocked the write, as D-01/D-02 require when any finding exists)

**stdout tail** (last section before the block):
```
============================================================
后处理: subscription_restrictions → limit_events
============================================================
加载 11875 条原始记录
去重: 11875 → 5111 (移除 6764 条重复)
修复 resume restriction_type: 338 条

回测校验问题: 390 个
```

**stderr** carried the full 390-issue list (all issues, not a truncated preview) plus the trailing count line `共 390 个问题`, matching `scripts/parse_announcements.py`'s catch handler for `ValidationBlockedError`.

**Production database verification:** `git status --porcelain data/real_all_lof/config/fund_status.db` produced no output — the production file was not modified by this run.

## 2. Findings by category

`validate()` was also called directly (via the standard library import path, on the same deduped/fixed record set the CLI run produced) to categorize every one of the 390 issue strings programmatically rather than by eyeballing a printed list.

| Category | Observed count | Planning-time figure | Match |
|---|---|---|---|
| Open restriction past 180-day staleness threshold, no matching resume | 373 | 373 | exact |
| `effective_date` precedes `announcement_date` | 17 | 17 | exact |
| Unrecognised `restriction_type` (outside `KNOWN_RESTRICTION_TYPES`) | 0 | 0 | exact |
| **Total** | **390** | **390** | **exact** |

**Distinct funds spanned by the staleness category:** 109 of the 247 funds present in the deduped record set. This means the 373 staleness findings are not 373 independent problems — they average ~3.4 findings per affected fund, consistent with a fund carrying a long unresolved run of `restrict`/`suspend` announcements against a single ongoing situation rather than 373 unrelated incidents.

### 2a. Sample: staleness (no resume >180 days) — first 10 of 373

```
160128 2024-06-15 suspend full_suspension 无对应resume（超180天）
160211 2022-01-09 suspend full_suspension 无对应resume（超180天）
160211 2022-08-01 suspend full_suspension 无对应resume（超180天）
160211 2022-08-27 suspend full_suspension 无对应resume（超180天）
160211 2023-05-13 suspend full_suspension 无对应resume（超180天）
160211 2023-05-14 suspend full_suspension 无对应resume（超180天）
160211 2023-05-16 suspend full_suspension 无对应resume（超180天）
160211 2023-06-17 suspend full_suspension 无对应resume（超180天）
160211 2023-06-19 suspend full_suspension 无对应resume（超180天）
160211 2023-06-20 suspend full_suspension 无对应resume（超180天）
```

### 2b. Sample: effective_date < announcement_date — all 17

```
160505 effective_date(2022-01-07) < announcement_date(2022-01-08)
160924 effective_date(2023-07-17) < announcement_date(2023-07-18)
160924 effective_date(2023-09-01) < announcement_date(2023-09-02)
160925 effective_date(2023-07-17) < announcement_date(2023-07-18)
160925 effective_date(2023-09-01) < announcement_date(2023-09-02)
160925 effective_date(2023-09-01) < announcement_date(2023-09-02)
161229 effective_date(2022-11-02) < announcement_date(2022-11-03)
161229 effective_date(2023-07-17) < announcement_date(2023-07-18)
164403 effective_date(2022-11-02) < announcement_date(2022-11-03)
164403 effective_date(2023-07-17) < announcement_date(2023-07-18)
```
(7 more not shown; all are one-day announcement/effective-date inversions, the same shape as these 10.)

### 2c. Sample: unrecognised restriction_type

None — 0 findings in this category against current production data. The only non-allowlisted value encountered in production is the tolerated `None`/empty "unspecified" case, which both `validate()` and `build_limit_events()` intentionally do not flag.

## 3. What the pipeline would have produced (interval statistics)

Since the CLI run blocked before reaching `build_limit_events()`/`write_limit_events()`, `build_limit_events()` was called directly (same import, same deduped/fixed record set) to measure what the interval set would have looked like had the block not fired. This is a read-only, in-memory call — nothing was written to any database.

| Metric | Observed | Planning-time figure | Match |
|---|---|---|---|
| Total intervals | 3,334 | 3,334 | exact |
| Intervals clamped by the 04-02 inverted-interval fix (would have run backwards pre-fix) | 7 | 7 | exact |
| Funds represented | 247 | — | — |
| Synthetic pre-data-range suspend intervals | 90 | — | — |

### 3a. Clamped intervals — all 7

```
160216 2025-12-26 paired resume 2025-12-26 (unclamped end 2025-12-25 < start 2025-12-26, clamped to 2025-12-26)
162411 2025-03-06 paired resume 2025-03-06 (unclamped end 2025-03-05 < start 2025-03-06, clamped to 2025-03-06)
161912 2025-06-17 paired resume 2025-06-17 (unclamped end 2025-06-16 < start 2025-06-17, clamped to 2025-06-17)
162415 2025-03-06 paired resume 2025-03-06 (unclamped end 2025-03-05 < start 2025-03-06, clamped to 2025-03-06)
162719 2024-01-16 paired resume 2024-01-16 (unclamped end 2024-01-15 < start 2024-01-16, clamped to 2024-01-16)
164701 2025-03-07 paired resume 2025-03-07 (unclamped end 2025-03-06 < start 2025-03-07, clamped to 2025-03-07)
164902 2024-12-24 paired resume 2024-12-24 (unclamped end 2024-12-23 < start 2024-12-24, clamped to 2024-12-24)
```

### 3b. Overlapping interval pairs — out-of-scope finding for a later milestone

**Observed: 529 overlapping pairs, across 77 distinct funds** (adjacent-pair method: intervals sorted by `start_date` per fund, boundary-inclusive comparison between each consecutive pair — this reproduces the planning-time methodology). **Planning-time figure: 528.** The one-pair difference is within expected drift for a production database that continues to accumulate new announcements between planning time and this run (records in this dataset run through 2026-02).

A full-pairwise count (every intersecting pair per fund, including an open-ended interval's overlap with every later interval it subsumes) was also computed for context: 5,301 pairs across the same 77 funds. This alternate method is reported only to show the sensitivity of "overlap count" to definition — it is not the figure being compared against the planning-time 528.

Sample (first 10, adjacent-pair method):
```
160125: [2022-04-15, 2022-04-18] overlaps [2022-04-18, 2022-04-18]
160125: [2022-12-26, 2022-12-27] overlaps [2022-12-27, 2022-12-27]
160125: [2023-04-07, 2023-04-10] overlaps [2023-04-10, 2023-04-10]
160125: [2023-12-25, 2023-12-26] overlaps [2023-12-26, 2023-12-26]
160125: [2024-03-29, 2024-04-01] overlaps [2024-04-01, 2024-04-01]
160125: [2024-12-25, 2024-12-26] overlaps [2024-12-26, 2024-12-26]
160125: [2025-04-18, 2025-04-21] overlaps [2025-04-21, 2025-04-21]
160125: [2025-12-25, 2025-12-26] overlaps [2025-12-26, 2025-12-26]
160127: [2023-01-19, 2023-01-20] overlaps [2023-01-20, 2023-01-20]
160127: [2023-04-07, 2023-04-10] overlaps [2023-04-10, 2023-04-10]
```

**This finding is recorded and moved on, not investigated further here.** Overlap resolution lives in loader and engine limit-application logic (`src/data/loader.py`, `src/backtest/engine.py`), which `.planning/REQUIREMENTS.md`'s Out of Scope table places outside this milestone.

## 4. Evidence for the checkpoint decision: does validate()'s resume-pairing disagree with build_limit_events()'s?

The checkpoint task's context raises a specific, testable question: `validate()`'s staleness check pops its `open_restrictions` stack on *any* resume record, while `build_limit_events()`'s pairing loop explicitly skips holiday resumes (`_is_holiday_resume()`) when searching for a matching resume. If these two functions disagree about the same data, the checkpoint's "fix-validate-pairing" option treats that as a consistency bug, not a loosening.

This was measured directly, not guessed at. Two variants of the staleness check were run against the same deduped/fixed record set:

| Pairing logic | Findings | Distinct funds |
|---|---|---|
| **Current `validate()`** — pops stack on any resume, including holiday resumes | 373 | 109 |
| **Aligned to `build_limit_events()`** — skips holiday resumes when popping, matching the interval builder exactly | 609 | 120 |

**The result is the opposite of what the checkpoint context speculated.** Aligning `validate()`'s pairing to skip holiday resumes (as `build_limit_events()` does) does not reduce the staleness count — it *increases* it, from 373 to 609. This is because `validate()`'s current behavior (popping on any resume, including holiday ones) closes out more open restrictions than the interval builder does, which means the current 373 is already an *under-count* relative to interval-builder-consistent logic, not an over-count produced by an overly strict check. A holiday resume in the current data currently masks a still-open long-term suspension in `validate()`'s eyes; `build_limit_events()` correctly does not let that happen when building intervals, but `validate()`'s check does.

This is presented as measured fact for the developer's triage decision, not as a recommendation. The `fix-validate-pairing` option in the checkpoint task, if selected, would raise the finding count rather than lower it.

## 5. Suite baseline

Full test suite, run via the project's documented runner (`python -m unittest discover tests`):

```
Ran 132 tests in 6.195s
FAILED (failures=1)
```

**Single failure:** `test_overlapping_limits_last_one_wins (test_open_ended_limits.TestOpenEndedLimits.test_overlapping_limits_last_one_wins)`

This is the phase's recorded pre-existing failure — the same test named in the plan's `<action>` block, in loader and engine limit-application logic that `.planning/REQUIREMENTS.md`'s Out of Scope table places outside this milestone. **It was not fixed here, per the plan's explicit prohibition.**

| Metric | Observed | Phase baseline (pre-Phase-4) |
|---|---|---|
| Total tests | 132 | 105 |
| Failures | 1 | 1 (same test) |
| Errors | 0 | 0 |
| New failures/errors introduced by Phase 4 | **none** | — |

The test count grew from 105 to 132 because plans 04-01 through 04-03 added 27 tests to `tests/test_postprocess.py` (which had zero tests before this phase). `grep -cE "^(FAIL|ERROR): "` against the full suite output returns exactly `1`, confirming no other test regressed.

`tests/test_postprocess.py` specifically, under both runners named in the plan and roadmap:

- `python -m unittest tests.test_postprocess -v`: **27 tests, OK** (exit 0)
- `python -m pytest tests/test_postprocess.py -q`: **27 passed** (exit 0)

Both runners agree on the same 27/27 pass count, satisfying roadmap success criterion 1's stated runner (`pytest`) while keeping the project's documented runner (`unittest`) authoritative.

## 6. Confirmation: no validation rule was changed

`git diff --stat 687abcd -- src/data/postprocess.py` (against the plan 04-03 commit `687adbc`, the last commit before this plan) shows **no output** — `src/data/postprocess.py` is byte-identical to its state at the end of plan 04-03. No validation rule was loosened, narrowed, or given a new exclusion in response to what this run found, per D-08 and the plan's explicit prohibition.

## 7. Findings requiring a decision

The following are presented as evidence only. Nothing below has been decided by this report or by the executor that produced it.

1. **The 390 blocking findings** (373 staleness spanning 109 distinct funds; 17 date-order inversions; 0 unknown-type). Under D-01/D-02's unconditional any-issue-blocks rule, every run against current production data blocks until these are triaged. See the checkpoint task's three options (`triage-data`, `fix-validate-pairing`, `new-phase`).

2. **The `validate()` vs `build_limit_events()` pairing disagreement measured in section 4.** If `fix-validate-pairing` is selected, it would raise the staleness finding count (373 → 609), not lower it — the opposite of what a "false positive" framing would predict.

3. **The pre-existing `test_overlapping_limits_last_one_wins` failure** (section 5) and **the 529 overlapping interval pairs across 77 funds** (section 3b), both in loader/engine limit-application logic that REQUIREMENTS places out of scope for this milestone. These are related symptoms of the same underlying gap (overlapping suspend/restrict intervals are not resolved before being applied to trading signals) and want a home — the checkpoint's `new-phase` option addresses this explicitly regardless of which option is chosen for finding 1.

---
*Phase: 04-postprocess-pipeline-hardening — Plan 04*
