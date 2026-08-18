# Requirements: LOF Purchase Limit Enhancement — v1.1 Stabilization & Refactor

**Defined:** 2026-08-18
**Core Value:** Accurate purchase limit data enables reliable arbitrage strategy backtesting — this milestone protects that value by closing the test/safety gaps that let a real 7x PnL-inflation bug ship undetected, and reconciles planning docs with what's actually running in production.

## v1.1 Requirements

### Planning Reconciliation

- [ ] **DOC-01**: PROJECT.md/ROADMAP.md accurately describe the shipped architecture (async Kimi K2.5 → dual-provider LLM client, `postprocess.py` state machine, akshare NAV) instead of the original Ollama-only / `LimitEventTimelineBuilder` design that was never built as specified
- [ ] **DOC-02**: README.md and TECHNICAL_PROPOSAL.md updated to describe the current pipeline — no lingering Ollama-only claims, `postprocess.py` documented as the timeline-integration step

### LLM Provider Flexibility

- [ ] **LLM-01**: `LLMClient` supports switching between Kimi K2.5, other OpenAI-compatible cloud APIs, and local Ollama via configuration (base_url + api_key + model), restoring the quick-004 dual-provider design on top of the current async client
- [ ] **LLM-02**: When configured for a provider without file-upload support (e.g. Ollama), the pipeline falls back to local PDF text extraction (`pdf_extractor.py`) before the chat-completion call
- [ ] **LLM-03**: Default behavior (Kimi K2.5, no provider override) is unchanged — existing extraction accuracy/throughput preserved

### Postprocess Pipeline Hardening

- [x] **STAB-01**: `tests/test_postprocess.py` covers `build_limit_events()`'s suspend/resume pairing — including holiday-resume-in-the-middle and missing-prior-suspend synthetic-interval cases, i.e. regression coverage for the exact bug fixed in commit `89830c8`
- [x] **STAB-02**: `validate()` findings can block `postprocess()` from writing `limit_events` when data-quality issues exceed a configurable threshold, instead of only printing warnings
- [x] **STAB-03**: `write_limit_events()` writes to a staging table and swaps atomically instead of `DROP TABLE` + rewrite, so a bad run can't destroy the last-known-good `limit_events` table

### Data Fetch Reliability

- [ ] **REL-01**: LLM extraction calls retry with backoff on transient errors (429/5xx/timeout) before a PDF is marked failed
- [ ] **REL-02**: akshare NAV fetch loop rate-limits between per-fund calls (matching the existing JoinQuant/announcement-downloader pattern)
- [ ] **REL-03**: akshare NAV response columns are validated against the expected schema, failing loudly on drift instead of silently producing empty/garbage NAV data

### Hygiene

- [ ] **HYG-01**: `requirements.txt` matches actual imports — remove unused `ollama`, add `akshare`
- [ ] **HYG-02**: `.env.example` documents every env var the codebase actually reads (LLM provider config, `KIMI_API_KEY`, `JQ_USERNAME`/`JQ_PASSWORD`)

## Out of Scope

| Feature | Reason |
|---------|--------|
| New user-facing features | This is a stabilization/refactor milestone — behavior changes only where they fix bugs |
| Changing existing backtest/limit-application logic | Already validated correct (post `89830c8`); only the data pipeline feeding it is being hardened |
| Adaptive/dynamic LLM concurrency tuning | `DEFAULT_CONCURRENCY` is already CLI-configurable; auto-tuning is a v2 nicety, not a stability requirement |
| ORM / schema migration framework for SQLite | Out of proportion to project size; transaction-safety fix (STAB-03) addresses the actual risk |
| Incremental/delta postprocessing (only reprocess new announcements) | Performance concern only at much larger data volumes than current; not a correctness or reliability issue |
| Downloader class naming/base-class unification | Low-risk cosmetic issue per CONCERNS.md; not worth the churn in a stabilization milestone |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DOC-01 | Phase 7 | Pending |
| DOC-02 | Phase 7 | Pending |
| LLM-01 | Phase 5 | Pending |
| LLM-02 | Phase 5 | Pending |
| LLM-03 | Phase 5 | Pending |
| STAB-01 | Phase 4 | Complete |
| STAB-02 | Phase 4 | Complete |
| STAB-03 | Phase 4 | Complete |
| REL-01 | Phase 5 | Pending |
| REL-02 | Phase 6 | Pending |
| REL-03 | Phase 6 | Pending |
| HYG-01 | Phase 7 | Pending |
| HYG-02 | Phase 7 | Pending |

**Coverage:**

- v1.1 requirements: 13 total
- Mapped to phases: 13 (Phase 4: STAB-01/02/03; Phase 5: LLM-01/02/03, REL-01; Phase 6: REL-02/03; Phase 7: DOC-01/02, HYG-01/02)
- Unmapped: 0

---
*Requirements defined: 2026-08-18*
*Roadmap mapping completed: 2026-08-18*
