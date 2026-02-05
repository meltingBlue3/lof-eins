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

### Active

- [ ] **LIM-01**: Fix DataLoader to handle NULL end_date (open-ended limits)
- [ ] **LIM-02**: Parse PDF announcements using local LLM to extract limit information
- [ ] **LIM-03**: Support four announcement types: complete interval, open-start, end-only (resume), end-only (extend)
- [ ] **LIM-04**: Implement timeline integration algorithm to merge overlapping limit periods
- [ ] **LIM-05**: Create announcement_parses table to store raw LLM extraction results
- [ ] **LIM-06**: Update limit_events schema to properly support open-ended limits
- [ ] **LIM-07**: Add event sourcing log for debugging and auditing limit changes
- [ ] **LIM-08**: Populate real limit data into fund_status.db from parsed announcements
- [ ] **LIM-09**: Ensure backtest correctly applies purchase limits when generating trading signals
- [ ] **LIM-10**: Add validation to detect gaps or conflicts in limit timeline

### Out of Scope

- Real-time announcement monitoring — focused on historical backtesting only
- Automatic LLM model fine-tuning — use existing local LLM (Ollama)
- Multi-language announcement support — Chinese announcements only
- Non-LOF fund types — LOF funds only
- Live trading integration — backtesting only
- Mobile app or web UI — command-line and data processing only

## Context

### Technical Environment

- **Language**: Python 3.9+
- **Database**: SQLite (fund_status.db, announcement_parses)
- **Data Storage**: Parquet files for time-series data, CSV for configs
- **External APIs**: JoinQuant (market data), Eastmoney (announcements)
- **LLM**: Local deployment via Ollama (qwen2.5 or similar)
- **PDF Processing**: pdfplumber or PyPDF2 for text extraction

### Current State

The existing codebase has a solid foundation:
- `AnnouncementDownloader`: Downloads PDFs from Eastmoney API
- `RealDataDownloader`: Fetches market and NAV data from JoinQuant
- `DataLoader`: Loads and aligns market, NAV, and limit data
- `BacktestEngine`: Runs arbitrage strategy simulation

However, there's a critical gap: **downloaded PDFs are never parsed**, and the `fund_status.db` remains empty for real data.

### User Workflow

1. Run `download_lof.py` to get market/NAV data
2. Run `download_announcements.py` to get PDF announcements
3. **NEW**: Run `process_announcements.py` to extract limits via LLM
4. **NEW**: Timeline integration merges and stores limit events
5. Run `run_backtest.py` with accurate limit data

### Known Issues to Address

1. `loader.py` line 224: NULL end_date causes incorrect mask calculation
2. `downloader.py` line 276: Schema inconsistency (nullable vs NOT NULL)
3. No module exists for PDF → limit event extraction
4. No timeline merging logic for overlapping announcements

## Constraints

- **Tech Stack**: Must use existing Python infrastructure, cannot switch to different language
- **Timeline**: Complete within 2 weeks (8-12 days estimated)
- **Budget**: Use free/local tools only (Ollama for LLM, no cloud API costs)
- **Dependencies**: Minimize new dependencies, prefer existing packages
- **Compatibility**: Must maintain backward compatibility with existing mock data workflow
- **Data Privacy**: Process PDFs locally, no external LLM APIs for sensitive financial documents

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use NULL for open-ended limits | Industry standard (Oracle, PostgreSQL temporal tables), semantically clear | — Pending |
| Event sourcing pattern | Immutable announcement_parses table enables audit trail and reprocessing | — Pending |
| Local LLM (Ollama) vs Cloud API | Cost control, data privacy, offline capability | — Pending |
| Three-table schema (parses/events/log) | Separation of concerns: raw data, integrated timeline, audit trail | — Pending |
| O(n log n) merge algorithm | Optimal complexity for interval merging, well-established pattern | — Pending |

---
*Last updated: 2026-02-06 after technical proposal review*
