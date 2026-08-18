# Roadmap: LOF Fund Arbitrage Backtesting System

## Milestones

- ✅ **v1.0 Purchase Limit Enhancement** — Phases 1-3 planned (shipped; Phase 3/4 scope delivered ad-hoc as `postprocess.py`, see note below)
- 🚧 **v1.1 Stabilization & Refactor** — Phases 4-7 (in progress)

## Overview

v1.1 does not add user-facing features. It hardens the announcement-parsing pipeline that shipped in the April 2026 Kimi/akshare rewrite (commits `4cc5212`, `89830c8`) — the same rewrite that shipped a 7x-PnL-inflation bug with no regression tests — then restores dual-provider LLM support, improves data-fetch reliability, and reconciles planning docs with the actual shipped architecture. Phases 4-7 map 1:1 onto the four requirement clusters in `.planning/REQUIREMENTS.md`.

## Phases

**Phase Numbering:**

- Continues from v1.0 (Phases 1-3). v1.1 starts at Phase 4 — never restart at 01.
- Integer phases (4, 5, 6, 7): Planned milestone work.
- Decimal phases (e.g. 4.1): Urgent insertions (marked with INSERTED).

- [ ] **Phase 4: Postprocess Pipeline Hardening** - Add regression tests, a hard validation gate, and transaction-safe writes to `postprocess.py`'s suspend/resume interval logic
- [ ] **Phase 5: Dual-Provider LLM Client & Extraction Reliability** - Restore Kimi/OpenAI-compatible/Ollama provider switching with local-PDF fallback, and add retry/backoff to LLM extraction calls
- [ ] **Phase 6: Data Fetch Reliability (akshare NAV)** - Rate-limit and schema-validate the akshare NAV fetch loop
- [ ] **Phase 7: Planning Docs & Hygiene Reconciliation** - Correct PROJECT.md/ROADMAP.md/README.md/TECHNICAL_PROPOSAL.md and clean up requirements.txt/.env.example to match the shipped pipeline

## Phase Details

<details>
<summary>✅ v1.0 Purchase Limit Enhancement (Phases 1-3) - SHIPPED</summary>

Original phase plans and summaries are archived at `.planning/milestones/v1.0-phases/`. The originally-planned Phase 3/4 design (`LimitEventTimelineBuilder` in `src/data/timeline_builder.py`) was never built as specified — equivalent functionality shipped in April 2026 as `src/data/postprocess.py` (a different, state-machine design), outside the tracked GSD phase process, alongside the async Kimi K2.5 rewrite and the akshare NAV switch. See PROJECT.md "Validated" and "Current State" sections for what actually shipped. v1.1 (this roadmap) reconciles the docs and hardens that delivered code.

</details>

### Phase 4: Postprocess Pipeline Hardening

**Goal**: `src/data/postprocess.py`'s suspend/resume interval-building logic (the module responsible for the `89830c8` 7x-PnL-inflation bug) has regression test coverage, a validation gate that can block bad writes, and crash-safe table writes.
**Depends on**: Nothing (first phase of v1.1; deliberately independent of Phase 5's LLM work — highest-priority, highest-risk phase in this milestone)
**Requirements**: STAB-01, STAB-02, STAB-03
**Success Criteria** (what must be TRUE):

  1. `pytest tests/test_postprocess.py` exists, passes, and includes cases for holiday-resume-in-the-middle and missing-prior-suspend synthetic-interval scenarios — regression coverage for the exact bug fixed in commit `89830c8`
  2. `postprocess()` refuses to write `limit_events` (returns a clear error/non-zero exit rather than only printing) when `validate()` findings exceed a configurable threshold
  3. `write_limit_events()` writes to a staging table and swaps atomically, so a run that fails partway through leaves the previous `limit_events` table intact and queryable
  4. The full existing test suite still passes — no behavior change on the happy path (bug fixes excepted). Baseline recorded at planning time: 105 tests, 1 pre-existing failure (`test_open_ended_limits.TestOpenEndedLimits.test_overlapping_limits_last_one_wins`, loader/engine limit-application logic, out of scope per REQUIREMENTS). Criterion is read as "no new failures beyond that baseline".

**Plans**: 3/4 plans executed

Plans:
**Wave 1**

- [x] 04-01-PLAN.md — Tracer: validation gate blocks the write end-to-end (`validate()` returns findings, `postprocess()` refuses, CLI exits non-zero) + temp-DB test harness (STAB-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02-PLAN.md — `89830c8` regression matrix, fail-loud on unknown `restriction_type`, inverted-interval clamp (STAB-01)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-03-PLAN.md — `write_limit_events()` staging table + single-transaction atomic swap (STAB-03)

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 04-04-PLAN.md — D-08 real-database validation run, suite baseline, blocking triage decision (STAB-01/02/03)

### Phase 5: Dual-Provider LLM Client & Extraction Reliability

**Goal**: `LLMClient` can be pointed at Kimi K2.5, another OpenAI-compatible cloud API, or local Ollama via configuration, with a local-PDF-extraction fallback for providers without file-upload support, and transient API errors are retried with backoff — all without changing default (Kimi) behavior.
**Depends on**: Nothing (independent of Phase 4 — different files/subsystem; may proceed in parallel or before/after per milestone priority)
**Requirements**: LLM-01, LLM-02, LLM-03, REL-01
**Success Criteria** (what must be TRUE):

  1. `LLMClient` accepts `base_url`/`api_key`/`model` configuration that switches between Kimi K2.5, another OpenAI-compatible endpoint, and local Ollama, demonstrated by tests/runs exercising each mode
  2. When configured for a provider without file-upload support (e.g. Ollama), extraction runs `pdf_extractor.py`'s local text extraction before the chat-completion call and produces correct records for a sample PDF
  3. Running `scripts/parse_announcements.py` with default configuration (no provider override) produces the same extraction behavior as before this phase — existing Kimi-path tests still pass unchanged
  4. A transient LLM API error (429/5xx/timeout) is retried with backoff and a PDF is only marked failed after retries are exhausted, verified by a test simulating a transient failure

**Plans**: TBD

### Phase 6: Data Fetch Reliability (akshare NAV)

**Goal**: The akshare NAV fetch loop in `RealDataDownloader` is resilient to rate limits and fails loudly instead of silently on upstream schema drift.
**Depends on**: Nothing (independent — touches `src/data/downloader.py` only, unrelated to Phases 4/5)
**Requirements**: REL-02, REL-03
**Success Criteria** (what must be TRUE):

  1. `_get_nav_data()`'s per-ticker loop pauses between akshare calls, matching the existing rate-limiting pattern already used by the JoinQuant batch loop and the announcement downloader
  2. akshare NAV response columns are validated against the expected schema immediately after fetch; a schema mismatch raises/logs a clear error instead of silently producing empty or garbage NAV data, verified by a test simulating an unexpected column set

**Plans**: TBD

### Phase 7: Planning Docs & Hygiene Reconciliation

**Goal**: PROJECT.md/ROADMAP.md, README.md/TECHNICAL_PROPOSAL.md, requirements.txt, and .env.example all accurately describe the shipped pipeline (dual-provider LLM client, `postprocess.py` state machine, akshare NAV) instead of the original Ollama-only / `LimitEventTimelineBuilder` design.
**Depends on**: Phase 4, Phase 5, Phase 6 (documents the final architecture shipped across this milestone, including the new provider-config env vars from Phase 5 and reliability additions from Phases 4/6)
**Requirements**: DOC-01, DOC-02, HYG-01, HYG-02
**Success Criteria** (what must be TRUE):

  1. PROJECT.md and ROADMAP.md describe the shipped architecture (async Kimi K2.5 → dual-provider LLM client, `postprocess.py` state machine, akshare NAV) with no lingering references to the original Ollama-only / `LimitEventTimelineBuilder` design as if still pending
  2. README.md and TECHNICAL_PROPOSAL.md describe the current pipeline — `postprocess.py` documented as the timeline-integration step, no lingering Ollama-only claims
  3. `requirements.txt` matches actual imports: unused `ollama` package removed, `akshare` present
  4. `.env.example` documents every env var the codebase actually reads, including LLM provider config (base_url/api_key/model switching from Phase 5), `KIMI_API_KEY`, and `JQ_USERNAME`/`JQ_PASSWORD`

**Plans**: TBD

## Progress

**Execution Order:**
Phases 4, 5, and 6 have no hard interdependency and may be executed in any order (Phase 4 is highest-priority per milestone goal). Phase 7 executes last, after Phases 4-6.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Foundation | v1.0 | 4/4 | Complete | 2026-02-06 |
| 2. PDF Processing | v1.0 | 3/3 | Complete | 2026-02-06 |
| 3. Timeline Integration | v1.0 | — | Superseded by `postprocess.py` (shipped outside GSD process) | 2026-04 |
| 4. Postprocess Pipeline Hardening | v1.1 | 3/4 | In Progress|  |
| 5. Dual-Provider LLM Client & Extraction Reliability | v1.1 | 0/? | Not started | - |
| 6. Data Fetch Reliability (akshare NAV) | v1.1 | 0/? | Not started | - |
| 7. Planning Docs & Hygiene Reconciliation | v1.1 | 0/? | Not started | - |

---

## Backlog

### Phase 999.1: Resolve overlapping suspend/restrict intervals (BACKLOG)

**Goal:** [Captured for future planning] Resolve overlapping suspend/restrict intervals in loader and engine limit-application logic, so overlapping intervals are deconflicted before being applied to trading signals instead of leaving the "last one wins" behavior unverified.
**Requirements:** TBD
**Plans:** 0 plans

Captured from Phase 4's real-data validation checkpoint (`04-04`, decision: `triage-data` for the 390 blocking validation findings; this item is the separate "give overlap resolution a proper home" follow-up the checkpoint context called for). Evidence:
- 529 overlapping interval pairs across 77 distinct funds, measured by `build_limit_events()` against a copy of the real `fund_status.db` — see `.planning/phases/04-postprocess-pipeline-hardening/04-REAL-DB-VALIDATION.md` section 3b.
- Pre-existing test failure `test_overlapping_limits_last_one_wins` (`tests/test_open_ended_limits.py`) — same underlying gap, unresolved since before Phase 4 and explicitly out of scope for it (see `.planning/REQUIREMENTS.md` Out of Scope table and `04-REAL-DB-VALIDATION.md` section 5).
- Lives in `src/data/loader.py` and `src/backtest/engine.py`, not `src/data/postprocess.py` — outside Phase 4's module boundary.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

*Roadmap created: 2026-02-06 (v1.0) — updated 2026-08-18 for milestone v1.1*
