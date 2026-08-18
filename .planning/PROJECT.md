# LOF Fund Arbitrage Backtesting System - Purchase Limit Enhancement

## What This Is

An enhanced LOF (Listed Open-Ended Fund) arbitrage backtesting system that accurately handles real-world purchase limit announcements (限购公告). The system downloads fund announcements from Eastmoney, uses local LLM to extract limit information, integrates timeline events, and provides accurate daily limit data for backtesting strategies.

The enhancement addresses critical gaps in the current system: handling open-ended limits (announcements without end dates), merging overlapping limit periods, and bridging the gap between downloaded PDF announcements and the backtesting database.

## Core Value

**Accurate purchase limit data enables reliable arbitrage strategy backtesting.** If the system cannot correctly identify when funds are under purchase restrictions, all backtest results are unreliable.

## Requirements

### Validated

- ✓ Download LOF fund market data (OHLCV) from JoinQuant — existing
- ✓ Download NAV (Net Asset Value) data from JoinQuant — existing  
- ✓ Download fund announcement PDFs from Eastmoney — existing
- ✓ Mock data generation with synthetic limit events — existing
- ✓ Basic backtest engine with T+2 settlement simulation — existing
- ✓ Tiered fee calculation for subscription/redemption — existing
- ✓ DataLoader for loading and aligning multiple data sources — existing

- ✓ Fix DataLoader to handle NULL end_date (open-ended limits) — done, Phase 1 (v1.0)
- ✓ Parse PDF announcements using an LLM to extract limit information — done, but delivered as an async Kimi K2.5 cloud pipeline (`src/data/llm_client.py`, April 2026 rewrite), not the originally-planned local Ollama client
- ✓ Support four announcement types (complete interval, open-start, end-only resume, end-only extend) — done, via `src/data/postprocess.py::build_limit_events()` state machine, not the originally-planned `LimitEventTimelineBuilder` class
- ✓ Timeline integration algorithm to merge overlapping limit periods — done, same module as above; includes a holiday-resume-vs-real-resume distinction and synthetic pre-data-range suspend intervals discovered necessary after a real production bug (commit `89830c8`)
- ✓ Populate real limit data into fund_status.db from parsed announcements — done, `scripts/parse_announcements.py` runs extraction + postprocess end-to-end
- ✓ Backtest correctly applies purchase limits when generating trading signals — done, verified via `89830c8` bugfix (limit gaps were producing phantom trades and ~7x PnL inflation before the fix)

### Active

*(none carried forward as v1.0 — see Current Milestone below for v1.1 scope)*

### Out of Scope

- Real-time announcement monitoring — focused on historical backtesting only
- Automatic LLM model fine-tuning — use existing LLM providers as-is
- Multi-language announcement support — Chinese announcements only
- Non-LOF fund types — LOF funds only
- Live trading integration — backtesting only
- Mobile app or web UI — command-line and data processing only

## Context

### Technical Environment

- **Language**: Python 3.9+
- **Database**: SQLite (`fund_status.db`: `limit_events`, `subscription_restrictions`, `announcement_parses`, `limit_event_log`)
- **Data Storage**: Parquet files for time-series data (market, NAV), CSV for fee configs
- **External APIs**: JoinQuant (market OHLCV), akshare (NAV, since the April 2026 rewrite — JoinQuant's finance API has row limits), Eastmoney (announcement PDFs), Kimi K2.5 / Moonshot (LLM extraction, cloud, async file-upload + chat API)
- **LLM**: Currently hardcoded to Kimi K2.5 cloud API (`src/data/llm_client.py`); v1.1 restores the dual-provider design (any OpenAI-compatible endpoint via `base_url`, or local Ollama)
- **PDF Processing**: pdfplumber (`src/data/pdf_extractor.py`, still used standalone) for local text extraction; Kimi's file-upload API for cloud extraction

### Current State (as of v1.1 planning, 2026-08-18)

The pipeline is fully built and in production use — this is a working system, not a gap-filling exercise:
- `AnnouncementDownloader`: Downloads PDFs from Eastmoney API
- `RealDataDownloader`: Fetches market OHLCV from JoinQuant, NAV from akshare
- `LLMClient` + `AnnouncementProcessor`: Async concurrent Kimi K2.5 extraction with resumable progress tracking
- `postprocess.py`: Dedupes/pairs suspend↔resume events into `limit_events` intervals
- `DataLoader` + `BacktestEngine`: Loads aligned data, simulates T+2 settlement with purchase limits applied

The v1.0 roadmap's Phase 3/4 design (a `LimitEventTimelineBuilder` class in `src/data/timeline_builder.py`) was never built as specified — the equivalent functionality shipped in April 2026 as `src/data/postprocess.py`, with a different (state-machine) design, outside the tracked GSD phase process. `README.md`/`TECHNICAL_PROPOSAL.md` still describe the original Ollama-based design and don't mention `postprocess.py` or akshare — this is what v1.1 corrects.

A real production bug (commit `89830c8`) was found and fixed post-hoc in `postprocess.py`: holiday-resume announcements were incorrectly closing long-term suspensions, and funds suspended before the data collection window had no synthetic suspend record — together these inflated backtest PnL ~7x. The fix shipped with **no regression tests**, which is the top risk this milestone addresses.

### Known Issues to Address (v1.1)

See `.planning/codebase/CONCERNS.md` (refreshed 2026-08-18) for the full audit. Highlights:
1. `src/data/postprocess.py` has zero dedicated unit tests, including for the `89830c8` fix itself
2. `_is_holiday_resume()` classifies by filename substring match — same fragile-heuristic shape as the bug it patched
3. `validate()` detects data-quality anomalies but never blocks a write
4. `write_limit_events()` does a blind `DROP TABLE` + rewrite with no backup/transaction safety
5. No retry/backoff on Kimi API calls or akshare NAV fetches; akshare has no rate limiting or schema-drift guard
6. `requirements.txt`/`.env.example` reference the old Ollama-only setup and are missing `akshare`/`KIMI_API_KEY`

## Constraints

- **Tech Stack**: Must use existing Python infrastructure, cannot switch to different language
- **Compatibility**: v1.1 must not change existing business behavior (bug fixes excepted) — this is a stabilization/refactor milestone, not a feature milestone
- **Dependencies**: Minimize new dependencies, prefer existing packages
- **LLM Providers**: Support at least one cloud OpenAI-compatible API (Kimi and others) and local Ollama; Ollama cannot use Kimi's file-upload API, so it needs a local-PDF-text-extraction fallback path

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use NULL for open-ended limits | Industry standard (Oracle, PostgreSQL temporal tables), semantically clear | Shipped, v1.0 |
| Event sourcing pattern | Immutable `subscription_restrictions`/`announcement_parses` enables audit trail and reprocessing | Shipped, v1.0 |
| Async Kimi K2.5 cloud API replacing local Ollama | Extraction accuracy and throughput; file-upload API avoids local PDF-parsing edge cases | Shipped, April 2026 (commit `4cc5212`) — v1.1 restores provider choice on top of this |
| akshare replacing JoinQuant for NAV | JoinQuant's finance API has row limits that blocked full-universe NAV downloads | Shipped, April 2026 (commit `4cc5212`) |
| Hand-rolled state machine for suspend/resume pairing (`postprocess.py`) instead of the originally-planned `LimitEventTimelineBuilder` | Emerged organically while wiring the Kimi rewrite; not a deliberate architectural choice | Shipped, but under-tested — v1.1 hardens this |
| O(n log n) merge algorithm | Optimal complexity for interval merging, well-established pattern | Shipped, v1.0 |

## Current Milestone: v1.1 Stabilization & Refactor

**Goal:** Stabilize the announcement-parsing pipeline (its highest-risk module, `postprocess.py`, shipped a 7x-PnL-inflation bug with no regression tests), restore multi-provider LLM support, improve data-fetch reliability, and correct the planning docs to match actual code.

**Target features:**
- Reconcile PROJECT.md/ROADMAP.md with actual shipped architecture (old Phase 3/4 design superseded by `postprocess.py`)
- `LLMClient` dual-provider support: any OpenAI-compatible cloud API (Kimi, others) via `base_url`, or local Ollama, with a local-PDF-text-extraction fallback for providers without file-upload support
- `postprocess.py` test coverage for the suspend/resume state machine, `validate()` promoted to a hard gate that can block bad writes, `write_limit_events()` made transaction-safe (no more blind drop+rewrite)
- Retry/backoff for LLM API calls; rate limiting and schema-drift guards for akshare NAV fetches
- Clean up `requirements.txt`/`.env.example`; update `README.md`/`TECHNICAL_PROPOSAL.md` to reflect the real pipeline
- No new user-facing features; no behavior changes except bug fixes

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-18 — milestone v1.1 started*
