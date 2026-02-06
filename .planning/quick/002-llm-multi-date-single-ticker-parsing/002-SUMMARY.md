---
phase: quick
plan: 002
subsystem: llm-parsing
tags: [ollama, llm, json-array, multi-date, ticker-filter, announcement-parsing]

# Dependency graph
requires:
  - phase: 02-pdf-processing
    provides: LLM client and announcement processor pipeline
provides:
  - "parse_announcement() returns List[Dict] for multi-date announcements"
  - "Ticker filtering in LLM prompt for multi-ticker PDFs"
  - "JSON array storage in announcement_parses table"
affects: [03-timeline-integration, future PDF reprocessing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "List[Dict] return type for LLM parsing (one record per date/range)"
    - "Ticker-scoped system prompt template"
    - "Minimum confidence across records (conservative)"

key-files:
  created: []
  modified:
    - "src/data/llm_client.py"
    - "src/data/announcement_processor.py"
    - "tests/test_llm_client.py"
    - "tests/test_announcement_processor.py"

key-decisions:
  - "List[Dict] return type instead of Dict for parse_announcement()"
  - "SYSTEM_PROMPT_TEMPLATE with {ticker_instruction} placeholder"
  - "Minimum confidence across records for DB confidence column"
  - "First non-null announcement_type for DB parse_type column"
  - "No DB schema changes — JSON array stored in same TEXT column"

patterns-established:
  - "All LLM parse results are List[Dict], even single records"
  - "Ticker parameter flows through: processor -> LLM client -> system prompt"
  - "_clean_output always returns List[Dict] regardless of input type"

# Metrics
duration: 9min
completed: 2026-02-07
---

# Quick 002: LLM Multi-Date Single-Ticker Parsing Summary

**parse_announcement() returns List[Dict] with per-date records, ticker-scoped prompt filters multi-ticker PDFs**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-06T18:18:46Z
- **Completed:** 2026-02-06T18:27:52Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments
- LLM system prompt now instructs JSON array output with multi-date and multi-ticker examples
- `parse_announcement()` accepts `ticker` parameter and returns `List[Dict[str, Any]]`
- `_extract_json_from_response()` handles both JSON arrays and objects with bracket matching
- `_clean_output()` normalizes any input (dict, list, other) to `List[Dict]`
- `AnnouncementProcessor` passes ticker to LLM and stores JSON array in DB
- All 110 tests pass (42 in modified files, 68 in other files), zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Update LLM client — prompt, return type, and cleaning logic** - `118ca6b` (feat)
2. **Task 2: Update announcement processor to handle List[Dict] from LLM** - `2e5c6aa` (feat)
3. **Task 3: Update all tests for List[Dict] return type** - `24371f5` (test)

## Files Created/Modified
- `src/data/llm_client.py` - SYSTEM_PROMPT_TEMPLATE with ticker placeholder, _build_system_prompt(), _clean_single_record()/_clean_output() split, List[Dict] returns, --ticker CLI arg
- `src/data/announcement_processor.py` - Passes ticker to LLM, stores List[Dict] as JSON array, min confidence, first non-null parse_type
- `tests/test_llm_client.py` - All 17 existing tests updated + 5 new tests (multi-date, single-ticker, clean_output wraps dict, build_system_prompt with/without ticker)
- `tests/test_announcement_processor.py` - All 12 existing tests updated + 1 new test (multi-record PDF processing)

## Decisions Made
- **List[Dict] as universal return type:** Even single-record responses are wrapped in a list for consistent downstream handling
- **Minimum confidence for DB column:** Conservative approach — the weakest record's confidence represents the overall extraction quality
- **First non-null announcement_type for DB:** Parse type column uses the first record with a defined type
- **No DB schema changes:** JSON array fits in existing TEXT column, avoiding migration complexity
- **Ticker instruction as template placeholder:** Keeps prompt clean when ticker is not provided

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LLM client and processor now handle real-world multi-date announcements
- Timeline integration (Phase 3) will receive multiple records per PDF, enabling per-date limit events
- No blockers

## Self-Check: PASSED

---
*Quick task: 002-llm-multi-date-single-ticker-parsing*
*Completed: 2026-02-07*
