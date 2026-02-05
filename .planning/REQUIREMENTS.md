# Requirements: LOF Purchase Limit Enhancement

**Defined:** 2026-02-06
**Core Value:** Accurate purchase limit data enables reliable arbitrage strategy backtesting

## v1 Requirements

### Bug Fixes

- [x] **BUG-01**: DataLoader correctly handles NULL end_date for open-ended limits
  - Fix `_resample_limits_to_daily()` to detect pd.isna(end) and apply mask accordingly
  - Test case: Event with end_date=NULL should apply to all dates >= start_date

- [x] **BUG-02**: Database schema allows NULL end_date consistently
  - Update `downloader.py` CREATE TABLE to remove NOT NULL constraint on end_date
  - Ensure `generators.py` mock data respects nullable schema

### PDF Processing

- [ ] **PDF-01**: Extract text from downloaded PDF announcements
  - Implement text extraction using pdfplumber or PyPDF2
  - Handle Chinese text encoding correctly
  - Clean and normalize extracted text

- [ ] **PDF-02**: Parse limit information using local LLM
  - Design extraction prompt for four announcement types
  - Call Ollama API with structured JSON output
  - Extract: has_limit_info, limit_type, start_date, end_date, max_amount, confidence

- [ ] **PDF-03**: Store raw parse results in announcement_parses table
  - Create table with: id, ticker, announcement_date, pdf_filename, parse_result (JSON), parse_type, confidence, processed flag
  - Save each PDF parse result immediately after extraction

### Timeline Integration

- [ ] **TIM-01**: Implement timeline integration algorithm
  - Sort raw parses by announcement_date
  - Handle complete interval: create event with start and end
  - Handle open-start: create event with NULL end_date
  - Handle end-only (resume): close current open event
  - Handle end-only (extend): extend current event end_date

- [ ] **TIM-02**: Merge overlapping limit intervals
  - Implement O(n log n) sort-then-merge algorithm
  - Handle overlap detection: start_date <= last_end
  - Merge by extending end_date to max(end1, end2)
  - Use stricter max_amount when merging (min of both)

- [ ] **TIM-03**: Save integrated events to limit_events table
  - Insert or update events with proper date ranges
  - Store source_announcement_ids as JSON array
  - Set is_open_ended flag based on NULL end_date

### Database Schema

- [x] **DB-01**: Create announcement_parses table
  - Schema: id, ticker, announcement_date, pdf_filename, parse_result (JSON), parse_type, confidence, processed, created_at
  - Add indexes on ticker and processed fields

- [x] **DB-02**: Update limit_events schema
  - Ensure end_date is nullable
  - Add is_open_ended generated column
  - Add source_announcement_ids text field (JSON)
  - Add reason field for audit trail

- [x] **DB-03**: Create limit_event_log table (optional but recommended)
  - Schema: id, ticker, operation, old_start, old_end, new_start, new_end, triggered_by, created_at
  - For debugging and auditing timeline changes

### Integration & Validation

- [ ] **INT-01**: Create process_announcements.py CLI script
  - Accept ticker argument or process all tickers
  - Orchestrate: extract → parse → integrate → save
  - Show progress and summary statistics

- [ ] **INT-02**: Populate fund_status.db with real limit data
  - Ensure all downloaded announcements are processed
  - Handle errors gracefully (skip failed PDFs, log warnings)
  - Validate: no duplicate events, no gaps in coverage

- [ ] **VAL-01**: Backtest correctly applies purchase limits
  - Verify SimpleLOFStrategy respects daily_limit
  - Test: signal generation when premium > threshold but limit = 0
  - Confirm: no trades executed when fund is under restriction

- [ ] **VAL-02**: Add validation to detect timeline issues
  - Detect overlapping events that weren't merged
  - Identify gaps between limit periods
  - Flag events with suspicious dates (future dates, end < start)

## v2 Requirements

### Enhanced Features

- **LLM-01**: Fine-tune local LLM for fund announcement parsing
  - Collect labeled training data from manual validation
  - Improve extraction accuracy for ambiguous announcements
  - Reduce false positives/negatives

- **MON-01**: Real-time announcement monitoring (optional)
  - Periodic check for new announcements
  - Auto-trigger processing pipeline
  - Notification on critical limit changes

- **VIS-01**: Visualize limit timeline
  - Plot limit periods on price chart
  - Highlight restriction periods
  - Show announcement annotations

### Performance & Scale

- **PERF-01**: Batch PDF processing optimization
  - Parallel processing of multiple PDFs
  - Connection pooling for Ollama API
  - Progress bars and ETA estimation

- **CACHE-01**: Cache LLM extraction results
  - Hash PDF content to detect changes
  - Skip re-processing unchanged files
  - Invalidate cache when model updates

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time monitoring | Focus on historical backtesting accuracy first |
| Cloud LLM APIs | Must use local Ollama for cost and privacy |
| Non-LOF fund types | Out of project scope |
| Multi-language support | Chinese announcements only |
| Live trading integration | Backtesting only |
| Web UI | Command-line tools sufficient |
| Mobile app | Not applicable for data processing tool |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BUG-01 | Phase 1 | **Complete** |
| BUG-02 | Phase 1 | **Complete** |
| PDF-01 | Phase 2 | Pending |
| PDF-02 | Phase 2 | Pending |
| PDF-03 | Phase 2 | Pending |
| TIM-01 | Phase 3 | Pending |
| TIM-02 | Phase 3 | Pending |
| TIM-03 | Phase 3 | Pending |
| DB-01 | Phase 1 | **Complete** |
| DB-02 | Phase 1 | **Complete** |
| DB-03 | Phase 1 | **Complete** |
| INT-01 | Phase 4 | Pending |
| INT-02 | Phase 4 | Pending |
| VAL-01 | Phase 4 | Pending |
| VAL-02 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-06*
*Last updated: 2026-02-06 after initial definition*
