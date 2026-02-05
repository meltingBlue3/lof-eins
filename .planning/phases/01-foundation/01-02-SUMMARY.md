---
phase: "01"
plan: "02"
subsystem: "database"
tags:
  - sqlite
  - schema
  - migration
  - pdf-processing

dependency_graph:
  requires:
    - "01-01"
  provides:
    - "Database schema for PDF announcement processing"
    - "Audit trail for limit event changes"
    - "LLM extraction result storage"
  affects:
    - "02-01"
    - "02-02"

tech_stack:
  added:
    - "SQLite (existing)"
  patterns:
    - "Event sourcing (limit_event_log)"
    - "Idempotent migrations"

key_files:
  created:
    - scripts/migrate_fund_status_db.py
  modified:
    - src/data/downloader.py
    - src/data/generator/generators.py

decisions:
  - id: "001"
    type: "technical"
    description: "Use IF NOT EXISTS for idempotent table creation"
    rationale: "Allows safe re-runs of downloader/generator without errors"
  - id: "002"
    type: "technical"
    description: "Store LLM parse result as JSON TEXT field"
    rationale: "Flexible schema for varying extraction formats; can normalize later if needed"
  - id: "003"
    type: "technical"
    description: "Use NULL for optional date fields in limit_event_log"
    rationale: "Supports operations without old/new values (e.g., CREATE vs UPDATE)"

metrics:
  duration: "~10 minutes"
  completed: "2026-02-06"
---

# Phase 1 Plan 2: Database Schema for PDF Processing Summary

## Overview

**One-liner:** Created two new database tables (announcement_parses, limit_event_log) with indexes and migration support for the PDF announcement processing pipeline.

## What Was Built

### 1. announcement_parses Table

Stores raw LLM extraction results from PDF announcements.

**Schema:**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Unique identifier |
| ticker | TEXT NOT NULL | Fund ticker symbol |
| announcement_date | DATE NOT NULL | Date of the announcement |
| pdf_filename | TEXT NOT NULL | Name of the PDF file |
| parse_result | TEXT | JSON string of LLM extraction |
| parse_type | TEXT | Type of parsing performed |
| confidence | REAL | Confidence score (0.0-1.0) |
| processed | INTEGER DEFAULT 0 | Processing status flag |
| created_at | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | Record creation time |

**Indexes:**
- `idx_announcement_parses_ticker` on ticker
- `idx_announcement_parses_processed` on processed

### 2. limit_event_log Table

Provides an audit trail for debugging timeline changes in purchase limit processing.

**Schema:**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | Unique identifier |
| ticker | TEXT NOT NULL | Fund ticker symbol |
| operation | TEXT NOT NULL | Operation type (CREATE/UPDATE/DELETE) |
| old_start | DATE | Previous start date (if applicable) |
| old_end | DATE | Previous end date (if applicable) |
| new_start | DATE | New start date (if applicable) |
| new_end | DATE | New end date (if applicable) |
| triggered_by | TEXT | Source that triggered change |
| created_at | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | Record creation time |

**Indexes:**
- `idx_limit_event_log_ticker` on ticker
- `idx_limit_event_log_created_at` on created_at

### 3. Integration Points

**Real Data Path (downloader.py):**
- `_create_announcement_parses_table()` method added
- `_create_limit_event_log_table()` method added
- Both methods called from `download()` flow after `_generate_limit_db()`

**Mock Data Path (generators.py):**
- `FundStatusGenerator.generate()` creates all three tables
- Consistent schema between real and mock data paths

### 4. Migration Script

**scripts/migrate_fund_status_db.py:**
- Idempotent migrations (safe to run multiple times)
- Single database: `--db-path path/to/fund_status.db`
- Batch migration: `--all` to migrate all databases in data/
- Checks for table existence before creating

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| src/data/downloader.py | Added two table creation methods | +78 |
| src/data/generator/generators.py | Added two CREATE TABLE blocks with indexes | +50 |
| scripts/migrate_fund_status_db.py | New migration script | +207 |

## Verification

### Schema Verification

```sql
-- Verify announcement_parses table exists with correct schema
SELECT sql FROM sqlite_master 
WHERE type='table' AND name='announcement_parses';

-- Verify limit_event_log table exists with correct schema
SELECT sql FROM sqlite_master 
WHERE type='table' AND name='limit_event_log';

-- Verify indexes exist
SELECT name FROM sqlite_master 
WHERE type='index' AND name LIKE 'idx_announcement_parses%';

SELECT name FROM sqlite_master 
WHERE type='index' AND name LIKE 'idx_limit_event_log%';
```

### Migration Script Test

```bash
# Test migration on mock data
python scripts/migrate_fund_status_db.py --db-path data/mock/config/fund_status.db

# Test batch migration
python scripts/migrate_fund_status_db.py --all
```

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

✅ **Ready for Phase 2: PDF Processing**

The database schema now supports:
- Storing LLM extraction results (announcement_parses)
- Auditing timeline changes (limit_event_log)
- Both real and mock data workflows

**No blockers for Phase 2.**

## Decisions Made

1. **IF NOT EXISTS clause**: Used for idempotent table creation, allowing safe re-runs
2. **JSON TEXT for parse_result**: Flexible schema that can evolve with LLM output formats
3. **NULLable date fields in limit_event_log**: Supports various operation types (CREATE without old values, DELETE without new values)
4. **Indexes on query patterns**: ticker is indexed for lookups; processed/created_at for filtering

## Technical Notes

- Schema is identical between `downloader.py` (real data) and `generators.py` (mock data)
- All tables use AUTOINCREMENT for safe concurrent inserts
- Migration script uses `CREATE TABLE` (not IF NOT EXISTS) for explicit control
- Foreign keys not used for flexibility; referential integrity handled at application level
