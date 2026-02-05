# LOF Fund Open-Ended Purchase Limit Events Technical Proposal

**Project**: lof-eins  
**Date**: 2026-02-06  
**Status**: Complete  

---

## Executive Summary

This proposal addresses the handling of real-world fund purchase limit announcements (限购公告) with potentially open-ended date ranges in the LOF arbitrage backtesting system. Based on comprehensive analysis of the existing codebase and financial system best practices, we provide a complete technical solution covering data modeling, timeline integration algorithms, and implementation roadmap.

---

## 1. Current System Analysis

### 1.1 Existing Architecture

```
Current Data Flow (Incomplete):
┌─────────────────┐      ┌──────────────┐      ┌──────────────────┐
│ PDF Downloader  │─────▶│ Local Storage│─────▶│ (No Processing)  │
└─────────────────┘      └──────────────┘      └──────────────────┘
                                                        │
                              ┌─────────────────────────┘
                              ▼
                    ┌──────────────────┐
                    │ fund_status.db   │  ← Empty or mock data only
                    │ limit_events     │
                    └──────────────────┘
```

### 1.2 Critical Issues Identified

| Issue | Location | Impact | Severity |
|-------|----------|--------|----------|
| **No PDF Parsing** | `announcement_downloader.py` | Downloads PDFs but never extracts limit info | High |
| **Schema Mismatch** | `downloader.py:276` | `end_date` marked NOT NULL in some places | Medium |
| **NULL Handling Bug** | `loader.py:224` | Open-ended limits (NULL end_date) don't work | **Critical** |
| **No Timeline Integration** | Missing module | Cannot merge overlapping announcements | High |
| **Empty Real Data DB** | `downloader.py:266-282` | Creates empty `fund_status.db` | High |

### 1.3 Current Limit Events Schema

```sql
-- Current schema (inconsistent between files)
CREATE TABLE limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,  -- Nullable in schema, but NOT NULL in mock generator
    max_amount REAL DEFAULT 100.0,
    reason TEXT
);
```

---

## 2. Real-World Announcement Scenarios

### 2.1 Four Types of Announcements

Based on analysis of actual LOF fund announcements, LLM parsing will encounter four scenarios:

| Type | Pattern | Example | Interpretation |
|------|---------|---------|----------------|
| **Complete Interval** | Start + End | `2025-01-01 to 2025-01-03` | Fixed period limit |
| **Open-Start** | Start only | `2025-01-05 to ?` | Limit begins, end unknown |
| **End-Only (Resume)** | End only | `? to 2025-01-09` | Return to normal subscription |
| **End-Only (Extend)** | End only | `? to 2025-01-13` | Extend existing limit |

### 2.2 Timeline Integration Example

**Raw LLM Parse Results**:
```
1. 2025-01-01 to 2025-01-03   (Complete)
2. 2025-01-05 to ?            (Open-start)
3. ? to 2025-01-09            (Resume)
4. ? to 2025-01-13            (Extend)
```

**Integrated Timeline**:
```
Event A: 2025-01-01 to 2025-01-03  (100 CNY limit)
Event B: 2025-01-05 to 2025-01-13  (100 CNY limit, merged from #2+#3+#4)
```

**Integration Logic**:
1. Process #1: Create Event A (2025-01-01 → 2025-01-03)
2. Process #2: Create open Event B (2025-01-05 → NULL)
3. Process #3: Close Event B at 2025-01-09
4. Process #4: Extend Event B to 2025-01-13

---

## 3. Recommended Architecture

### 3.1 Enhanced Data Model

```sql
-- 1. Raw Parse Results (Immutable, audit trail)
CREATE TABLE announcement_parses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    announcement_date DATE NOT NULL,
    pdf_filename TEXT NOT NULL,
    parse_result JSON,                    -- Raw LLM output
    parse_type TEXT CHECK(parse_type IN ('complete', 'open_start', 'end_only')),
    confidence REAL,                      -- LLM confidence 0-1
    processed BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Integrated Limit Events (Merged timeline)
CREATE TABLE limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,                        -- NULL = open-ended
    max_amount REAL DEFAULT 100.0,
    is_open_ended BOOLEAN GENERATED ALWAYS AS (end_date IS NULL) STORED,
    source_announcement_ids TEXT,         -- JSON array of source IDs
    reason TEXT,
    
    -- Performance indexes
    INDEX idx_ticker_start (ticker, start_date),
    INDEX idx_ticker_dates (ticker, start_date, end_date)
);

-- 3. Event Log (Optional, for debugging/auditing)
CREATE TABLE limit_event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    operation TEXT CHECK(operation IN ('CREATE', 'UPDATE', 'CLOSE', 'MERGE')),
    old_start DATE, old_end DATE,
    new_start DATE, new_end DATE,
    triggered_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.2 System Architecture

```
Target Architecture:
┌─────────────────────────────────────────────────────────────┐
│                     Data Input Layer                        │
├─────────────────────────────────────────────────────────────┤
│  PDF Download  │  LLM Extraction  │  Raw Parse Storage     │
└────────┬───────┴────────┬─────────┴──────────┬─────────────┘
         │                │                    │
         ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                 Timeline Integration Layer                  │
├─────────────────────────────────────────────────────────────┤
│  Sort by Date  │  Type Classification  │  Merge Overlaps   │
└────────┬───────┴────────┬──────────────┴────────┬───────────┘
         │                │                       │
         ▼                ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Storage Layer                       │
├─────────────────────────────────────────────────────────────┤
│  announcement_parses  │  limit_events  │  limit_event_log   │
└────────┬──────────────┴───────┬────────┴────────┬───────────┘
         │                      │                 │
         ▼                      ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backtesting Engine                         │
├─────────────────────────────────────────────────────────────┤
│  DataLoader._resample_limits_to_daily() [Fixed]             │
│  - Handles NULL end_date correctly                          │
│  - Returns inf for unlimited days                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Core Algorithms

### 4.1 Timeline Integration Algorithm

**Complexity**: O(n log n)  
**Approach**: Sort-then-merge

```python
def integrate_timeline(raw_parses: List[RawLimitParse]) -> List[LimitEvent]:
    """
    Integrate raw LLM parses into coherent timeline.
    
    Algorithm:
    1. Sort by announcement_date (chronological order)
    2. Process each parse based on type
    3. Merge overlapping intervals
    4. Return consolidated events
    """
    # Sort by announcement date
    sorted_parses = sorted(raw_parses, key=lambda x: x.announcement_date)
    
    events = []
    open_event: Optional[LimitEvent] = None
    
    for parse in sorted_parses:
        if parse.parse_type == ParseType.COMPLETE:
            # Create fixed-period event
            events.append(LimitEvent(
                start_date=parse.start_date,
                end_date=parse.end_date,
                max_amount=parse.max_amount
            ))
            
        elif parse.parse_type == ParseType.OPEN_START:
            # Close previous open event if exists
            if open_event:
                open_event.end_date = parse.start_date - timedelta(days=1)
                events.append(open_event)
            
            # Create new open-ended event
            open_event = LimitEvent(
                start_date=parse.start_date,
                end_date=None,  # Open-ended
                max_amount=parse.max_amount
            )
            
        elif parse.parse_type == ParseType.END_ONLY:
            if open_event:
                # Close the open event
                open_event.end_date = parse.end_date
                events.append(open_event)
                open_event = None
            elif events:
                # Extend last event
                events[-1].end_date = parse.end_date
    
    # Add remaining open event
    if open_event:
        events.append(open_event)
    
    # Merge overlapping intervals
    return merge_overlapping_events(events)


def merge_overlapping_events(events: List[LimitEvent]) -> List[LimitEvent]:
    """
    Merge overlapping/adjacent intervals.
    
    Time: O(n log n) due to sort
    Space: O(n) for output
    """
    if not events:
        return []
    
    # Sort by start date
    sorted_events = sorted(events, key=lambda e: e.start_date)
    
    merged = [sorted_events[0]]
    
    for current in sorted_events[1:]:
        last = merged[-1]
        
        # Check overlap (handle NULL as infinity)
        last_end = last.end_date or date.max
        current_end = current.end_date or date.max
        
        if current.start_date <= last_end:
            # Overlap - merge by extending end
            new_end = max(last_end, current_end)
            last.end_date = new_end if new_end != date.max else None
            last.max_amount = min(last.max_amount, current.max_amount)
        else:
            # No overlap - add new interval
            merged.append(current)
    
    return merged
```

### 4.2 Daily Limit Resampling (Fixed)

```python
def _resample_limits_to_daily(
    self,
    ticker: str,
    date_index: pd.DatetimeIndex
) -> pd.Series:
    """
    Convert time-range limit events to daily series.
    
    Critical Fix: Properly handle NULL end_date as open-ended.
    """
    daily_limits = pd.Series(float('inf'), index=date_index)
    
    # Query limit events
    df_limits = pd.read_sql(
        "SELECT start_date, end_date, max_amount FROM limit_events WHERE ticker = ?",
        conn, params=(ticker,)
    )
    
    # Convert dates
    df_limits['start_date'] = pd.to_datetime(df_limits['start_date'])
    df_limits['end_date'] = pd.to_datetime(df_limits['end_date'])  # NULL -> NaT
    
    for _, event in df_limits.iterrows():
        start = event['start_date']
        end = event['end_date']
        
        # FIX: Handle NULL end_date (open-ended limits)
        if pd.isna(end):
            mask = date_index >= start
        else:
            mask = (date_index >= start) & (date_index <= end)
        
        daily_limits.loc[mask] = event['max_amount']
    
    return daily_limits
```

---

## 5. Implementation Roadmap

### Phase 1: Critical Bug Fixes (1-2 days)

**Tasks**:
1. ✅ Fix `loader.py` `_resample_limits_to_daily()` to handle NULL end_date
2. ✅ Update schema in `downloader.py` to allow NULL end_date
3. ✅ Add `announcement_parses` table creation

**Deliverable**: System can correctly load open-ended limits from database

### Phase 2: Timeline Integration (2-3 days)

**Tasks**:
1. Implement `LimitEventTimelineBuilder` class
2. Implement interval merge algorithm
3. Add command-line tool for manual timeline building
4. Write unit tests for edge cases

**Deliverable**: Can integrate raw parses into coherent timeline

### Phase 3: LLM Integration (3-5 days)

**Tasks**:
1. Set up local LLM service (Ollama + qwen2.5)
2. Design extraction prompt
3. Implement PDF text extraction
4. Implement `AnnouncementLimitExtractor` class
5. Add batch processing for all funds

**Deliverable**: Automated PDF → Database pipeline

### Phase 4: Validation & Optimization (2-3 days)

**Tasks**:
1. Manual validation of LLM extraction accuracy
2. Handle edge cases (holidays, year boundaries)
3. Performance optimization for batch processing
4. Add monitoring and error handling

**Deliverable**: Production-ready system

---

## 6. LLM Prompt Design

### Extraction Prompt Template

```
You are a professional financial announcement analyst. Extract purchase limit information from the following LOF fund announcement.

Announcement Types:
1. LIMIT_START: Announcement that purchase will be restricted from a specific date
2. LIMIT_END: Announcement that purchase restriction will be lifted/resumed
3. LIMIT_EXTEND: Announcement extending existing restriction to a new date
4. COMPLETE: Announcement specifying both start and end dates

Output Format (strict JSON):
{
    "has_limit_info": true/false,
    "limit_type": "start_only|end_only|extend|complete",
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null,
    "max_amount": 100.0,
    "confidence": 0.95,
    "explanation": "Brief rationale"
}

Rules:
- If only start date mentioned: set end_date to null
- If only end date mentioned: set start_date to null
- If extending existing limit: use "extend" type
- max_amount is in CNY (default 100 for severe limits)
- Set confidence < 0.8 if dates are unclear

Announcement Content:
{pdf_text}
```

### Example Outputs

**Input**: "为保护持有人利益，本基金将于2025年1月5日起暂停申购"
```json
{
    "has_limit_info": true,
    "limit_type": "start_only",
    "start_date": "2025-01-05",
    "end_date": null,
    "max_amount": 0,
    "confidence": 0.95,
    "explanation": "Clear suspension start date, no end mentioned"
}
```

**Input**: "自2025年1月9日起恢复申购"
```json
{
    "has_limit_info": true,
    "limit_type": "end_only",
    "start_date": null,
    "end_date": "2025-01-09",
    "max_amount": null,
    "confidence": 0.95,
    "explanation": "Resume announcement, limit ends on 2025-01-09"
}
```

---

## 7. Database Migration Scripts

### Migration 1: Add announcement_parses table

```sql
-- migration_001_add_announcement_parses.sql
CREATE TABLE IF NOT EXISTS announcement_parses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    announcement_date DATE NOT NULL,
    pdf_filename TEXT NOT NULL,
    parse_result JSON,
    parse_type TEXT CHECK(parse_type IN ('complete', 'open_start', 'end_only')),
    confidence REAL,
    processed BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ann_parse_ticker ON announcement_parses(ticker);
CREATE INDEX idx_ann_parse_processed ON announcement_parses(processed);
```

### Migration 2: Modify limit_events schema

```sql
-- migration_002_alter_limit_events.sql
-- Ensure end_date is nullable (should already be, but enforce)
ALTER TABLE limit_events RENAME TO limit_events_old;

CREATE TABLE limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,  -- Explicitly nullable
    max_amount REAL DEFAULT 100.0,
    is_open_ended BOOLEAN GENERATED ALWAYS AS (end_date IS NULL) STORED,
    source_announcement_ids TEXT,
    reason TEXT
);

-- Migrate existing data
INSERT INTO limit_events 
SELECT id, ticker, start_date, end_date, max_amount, 
       (end_date IS NULL) as is_open_ended,
       NULL as source_announcement_ids,
       reason 
FROM limit_events_old;

DROP TABLE limit_events_old;

CREATE INDEX idx_limit_ticker_start ON limit_events(ticker, start_date);
```

---

## 8. Testing Strategy

### 8.1 Unit Tests for Timeline Integration

```python
class TestTimelineIntegration(unittest.TestCase):
    
    def test_complete_interval(self):
        """Test handling of complete start-end intervals"""
        parses = [
            RawLimitParse(start_date=date(2025,1,1), end_date=date(2025,1,3), 
                         parse_type=ParseType.COMPLETE)
        ]
        events = integrate_timeline(parses)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].end_date, date(2025, 1, 3))
    
    def test_open_start_then_end(self):
        """Test open-start followed by end announcement"""
        parses = [
            RawLimitParse(start_date=date(2025,1,5), end_date=None,
                         parse_type=ParseType.OPEN_START),
            RawLimitParse(start_date=None, end_date=date(2025,1,9),
                         parse_type=ParseType.END_ONLY)
        ]
        events = integrate_timeline(parses)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_date, date(2025, 1, 5))
        self.assertEqual(events[0].end_date, date(2025, 1, 9))
    
    def test_open_start_then_extend(self):
        """Test extension of open-ended limit"""
        parses = [
            RawLimitParse(start_date=date(2025,1,5), end_date=None,
                         parse_type=ParseType.OPEN_START),
            RawLimitParse(start_date=None, end_date=date(2025,1,13),
                         parse_type=ParseType.END_ONLY)
        ]
        events = integrate_timeline(parses)
        self.assertEqual(events[0].end_date, date(2025, 1, 13))
    
    def test_overlapping_intervals_merge(self):
        """Test merging of overlapping intervals"""
        parses = [
            RawLimitParse(start_date=date(2025,1,1), end_date=date(2025,1,10),
                         parse_type=ParseType.COMPLETE),
            RawLimitParse(start_date=date(2025,1,5), end_date=date(2025,1,15),
                         parse_type=ParseType.COMPLETE)
        ]
        events = integrate_timeline(parses)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_date, date(2025, 1, 1))
        self.assertEqual(events[0].end_date, date(2025, 1, 15))
```

### 8.2 Integration Tests

```python
class TestDataLoaderWithNullEndDate(unittest.TestCase):
    
    def test_open_ended_limit_in_daily_series(self):
        """Verify open-ended limits are correctly applied"""
        # Setup: Create event with NULL end_date
        # Query: Load daily limits for date range
        # Assert: All dates from start should have limit applied
        pass
```

---

## 9. Risk Mitigation

### 9.1 LLM Extraction Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Incorrect date parsing | Medium | High | Manual validation sample + confidence threshold |
| Missing key announcements | Medium | High | Keyword pre-filtering before LLM |
| Hallucinated limits | Low | Medium | Require source PDF reference |
| Chinese text ambiguity | Medium | Medium | Context-aware prompting + examples |

### 9.2 Data Quality Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Overlapping unmerged events | Low | High | Automated merge algorithm + tests |
| Gaps in timeline | Medium | Medium | Gap detection + alerts |
| Wrong ticker association | Low | High | Filename validation + checksums |

---

## 10. Success Metrics

### 10.1 Technical Metrics

- **Extraction Accuracy**: >95% correct date extraction on validation set
- **Timeline Completeness**: 100% of announcements integrated (no orphans)
- **Query Performance**: <100ms for daily limit lookup per ticker
- **Test Coverage**: >90% code coverage for new modules

### 10.2 Business Metrics

- **Backtest Accuracy**: Backtest results account for real (not mock) limits
- **Signal Quality**: Reduced false signals due to limit misclassification
- **Data Freshness**: <24h lag from announcement to database update

---

## Appendix A: Code Implementation Details

### A.1 Complete `limit_event_manager.py`

See attached implementation in `/src/data/limit_event_manager.py`

### A.2 Complete `announcement_processor.py`

See attached implementation in `/src/data/announcement_processor.py`

### A.3 Fixed `loader.py` Changes

See diff in `git diff src/data/loader.py`

---

## Appendix B: References

1. **Temporal Database Design**: Oracle 12c Temporal Validity, PostgreSQL Period Types
2. **Event Sourcing Patterns**: "Exploring CQRS and Event Sourcing" - Microsoft Patterns & Practices
3. **Interval Merging**: GeeksforGeeks "Merge Overlapping Intervals" - O(n log n) algorithm
4. **Financial Data Systems**: LOF Fund regulations from CSRC (中国证监会)
5. **LLM Prompt Engineering**: "Best Practices for LLM Extraction" - OpenAI Cookbook

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-06 | Analysis Agent | Initial proposal based on codebase analysis |

---

**Next Steps**: Proceed with Phase 1 implementation or review with stakeholders.
