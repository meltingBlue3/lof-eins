---
phase: quick-001
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/download_lof.py
  - src/data/generator/generators.py
  - scripts/migrate_fund_status_db.py
  - src/data/migrations/002_update_limit_events.py
autonomous: true

must_haves:
  truths:
    - "All 3 CREATE TABLE statements for limit_events have identical schema"
    - "end_date is nullable (DATE, not DATE NOT NULL) in all locations"
    - "Generator produces None for open-ended limits instead of last-date hack"
    - "Migration scripts are removed (no real data to migrate)"
    - "All existing tests pass"
  artifacts:
    - path: "scripts/download_lof.py"
      provides: "Updated limit_events schema matching canonical version"
      contains: "end_date DATE,"
    - path: "src/data/generator/generators.py"
      provides: "None for open-ended limit end_date"
      contains: '"end_date": None'
  key_links:
    - from: "scripts/download_lof.py"
      to: "src/data/downloader.py"
      via: "identical CREATE TABLE schema"
      pattern: "end_date DATE,"
---

<objective>
Unify all limit_events CREATE TABLE statements to use a single canonical schema with nullable end_date, fix the mock generator to emit None for open-ended limits, and remove obsolete migration scripts.

Purpose: Eliminate schema drift across 3 locations that define the same table, preventing runtime errors from NOT NULL constraint violations when open-ended limits are inserted.

Output: Consistent schema everywhere, clean generator output, no dead migration code.
</objective>

<execution_context>
@C:\Users\zhang\.config\opencode/get-shit-done/workflows/execute-plan.md
@C:\Users\zhang\.config\opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@scripts/download_lof.py (lines 217-233 — old schema with end_date NOT NULL)
@src/data/downloader.py (lines 285-298 — canonical new schema)
@src/data/generator/generators.py (lines 208-221 — schema, lines 364-374 — end_date hack)
@scripts/migrate_fund_status_db.py (entire file — to be deleted)
@src/data/migrations/002_update_limit_events.py (entire file — to be deleted)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Unify download_lof.py schema and fix generator end_date</name>
  <files>
    scripts/download_lof.py
    src/data/generator/generators.py
  </files>
  <action>
1. In `scripts/download_lof.py`, replace the `_generate_limit_db` method's CREATE TABLE (lines 222-231) with the canonical schema matching `src/data/downloader.py:285-298`:

```sql
CREATE TABLE IF NOT EXISTS limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    max_amount REAL NOT NULL,
    reason TEXT,
    source_announcement_ids TEXT DEFAULT '[]',
    is_open_ended INTEGER GENERATED ALWAYS AS (
        CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
    ) STORED
)
```

Also add the index creation after the CREATE TABLE:
```sql
CREATE INDEX IF NOT EXISTS idx_limit_events_is_open_ended
ON limit_events(is_open_ended)
```

2. In `src/data/generator/generators.py`, fix the "limit extends to end of data" case (lines 364-374). Change the end_date from `pd.Timestamp(dates[-1]).strftime("%Y-%m-%d")` to `None`. This represents a genuinely open-ended limit — the limit hasn't ended, we just ran out of data.

3. In `src/data/generator/generators.py`, also unify the schema: change `max_amount REAL DEFAULT 100.0` to `max_amount REAL NOT NULL` to match `downloader.py`. The DEFAULT 100.0 is misleading since every insert provides a value explicitly.
  </action>
  <verify>
    - `python -c "import ast; ast.parse(open('scripts/download_lof.py').read())"` succeeds (syntax check)
    - `python -c "import ast; ast.parse(open('src/data/generator/generators.py').read())"` succeeds
    - Search all 3 CREATE TABLE locations and confirm: all say `end_date DATE,` (no NOT NULL), all say `max_amount REAL NOT NULL`, all have `source_announcement_ids` and `is_open_ended`
  </verify>
  <done>
    - download_lof.py schema matches downloader.py exactly (nullable end_date, generated columns, indexes)
    - generators.py schema has `max_amount REAL NOT NULL` matching downloader.py
    - Generator emits `None` for end_date when limit extends to end of data
  </done>
</task>

<task type="auto">
  <name>Task 2: Remove migration scripts and run tests</name>
  <files>
    scripts/migrate_fund_status_db.py
    src/data/migrations/002_update_limit_events.py
  </files>
  <action>
1. Delete `scripts/migrate_fund_status_db.py` — this migration adds announcement_parses and limit_event_log tables to old databases. Since there's no real data yet, the canonical CREATE TABLE in downloader.py already creates these tables fresh.

2. Delete `src/data/migrations/002_update_limit_events.py` — this migration upgrades old limit_events schemas. Same reason: no real data, fresh creation is the path.

3. Check if `src/data/migrations/` directory has any other files. If 002 was the only file (besides __init__.py), delete the directory. If there are other migration files, leave the directory.

4. Run the full test suite to verify nothing breaks:
   - `python -m pytest tests/test_database_schema.py -v`
   - `python -m pytest tests/test_open_ended_limits.py -v`
   - `python -m pytest tests/ -v` (full suite)

No test files should need modification — the test files already use the correct schema with nullable end_date and don't reference the migration scripts.
  </action>
  <verify>
    - `scripts/migrate_fund_status_db.py` does not exist
    - `src/data/migrations/002_update_limit_events.py` does not exist
    - `python -m pytest tests/test_database_schema.py tests/test_open_ended_limits.py -v` all pass
    - `python -m pytest tests/ -v` full suite passes
  </verify>
  <done>
    - Migration scripts removed (no references remain in importable code)
    - All tests pass, confirming no runtime dependency on deleted files
    - Schema is unified across all 3 locations
  </done>
</task>

</tasks>

<verification>
1. Grep all Python files for `end_date DATE NOT NULL` — should return 0 results
2. Grep all Python files for `end_date DATE` — should return results only in the 3 canonical locations (download_lof.py, downloader.py, generators.py) plus test files
3. Grep generators.py for `"end_date": None` — should find the open-ended case
4. `python -m pytest tests/ -v` — all tests pass
5. Verify the 3 CREATE TABLE statements are identical (same columns, same types, same constraints)
</verification>

<success_criteria>
- All 3 limit_events CREATE TABLE statements are identical (nullable end_date, is_open_ended generated column, source_announcement_ids, indexes)
- Generator uses None for open-ended limits instead of last date
- Migration scripts deleted
- Full test suite passes
</success_criteria>

<output>
After completion, create `.planning/quick/001-unify-db-schema-end-date-nullable/001-SUMMARY.md`
</output>
