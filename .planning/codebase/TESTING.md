# Testing Patterns

**Analysis Date:** 2026-08-18

## Test Framework

**Runner:**
- Standard library `unittest` — no pytest, no pytest config file exists anywhere in the repo (verified: no `pytest.ini`, `conftest.py`, or `[tool.pytest.ini_options]`).
- All 7 test files under `tests/` import `unittest` directly and subclass `unittest.TestCase`.

**Assertion Library:**
- Built-in `unittest.TestCase` assertions only: `assertEqual`, `assertTrue`, `assertRaises`, `assertGreaterEqual`, `assertLessEqual`. No `pytest.raises`, no third-party assertion libs.

**Run Commands:**
```bash
python -m unittest discover tests           # Run all tests
python -m unittest tests.test_llm_client     # Run one module
python tests/test_open_ended_limits.py       # Some files are directly executable (see below)
```
Note: `pytest` IS installed in `.venv` as a transitive dependency of other packages, and would auto-discover these `unittest.TestCase` classes if invoked (`pytest tests/`), but it is not the documented/intended runner — no CI config or Makefile target references it. Prefer `python -m unittest discover tests` to match project convention.

## Test File Organization

**Location:**
- All tests live in a single flat `tests/` directory (no `tests/unit/`, `tests/integration/` split).

**Naming:**
- `test_<subject>.py` where subject is either a specific module (`test_llm_client.py` ↔ `src/data/llm_client.py`, `test_pdf_extractor.py` ↔ `src/data/pdf_extractor.py`, `test_loader.py` ↔ `src/data/loader.py`) or a cross-cutting concern (`test_architecture_fixes.py`, `test_database_schema.py`, `test_open_ended_limits.py`, `test_announcement_processor.py` — this last one actually tests both `announcement_processor.py` and `postprocess.py`-equivalent dedup/build logic).

**Structure:**
```
tests/
├── test_announcement_processor.py   # PDF discovery, record storage, dedup, resume-type fix, limit_events build/write (416 lines)
├── test_architecture_fixes.py       # DataLoader BundleResult, T+2 settlement, trade log casing, fee calc (443 lines)
├── test_database_schema.py          # SQLite schema assertions for limit_events / announcement_parses (776 lines)
├── test_llm_client.py               # LLMClient._parse_response, prompt building, init validation (149 lines)
├── test_loader.py                   # DataLoader basics (178 lines)
├── test_open_ended_limits.py        # NULL end_date / open-ended limit handling, extensive edge cases (818 lines)
└── test_pdf_extractor.py            # PDF text extraction (217 lines)
```
Each file groups related tests into multiple `TestCase` subclasses by behavior, e.g. `test_announcement_processor.py` has `TestPDFDiscovery`, `TestRecordStorage`, `TestDedup`, `TestFixResumeType`, `TestBuildLimitEvents`, `TestWriteLimitEvents`.

## Test Structure

**Suite Organization (actual pattern from `tests/test_llm_client.py`):**
```python
class TestParseResponse(unittest.TestCase):
    """Test _parse_response static method for extracting records from raw LLM output."""

    def test_valid_json_array(self):
        raw = json.dumps([{"fund_code": "160105", "action": "restrict", ...}])
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fund_code"], "160105")
```
- Class docstring states what unit/behavior is under test; each `test_*` method covers one specific case/scenario, named descriptively (`test_json_wrapped_in_markdown`, `test_dict_with_records_key`, `test_missing_api_key_raises`).
- `if __name__ == "__main__": unittest.main()` at the bottom of every file, so any test file can be run standalone with `python tests/test_x.py`.

**Setup/Teardown:**
- `setUp`/`tearDown` used for stateful/file-system tests. Standard pattern (from `tests/test_open_ended_limits.py`):
```python
def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix="lof_test_")
    self.data_dir = Path(self.temp_dir) / "data"
    (self.data_dir / "market").mkdir(parents=True)
    (self.data_dir / "nav").mkdir(parents=True)
    (self.data_dir / "config").mkdir(parents=True)

def tearDown(self):
    import shutil
    shutil.rmtree(self.temp_dir, ignore_errors=True)
```
- Env var mutation is manually saved/restored in `setUp`/`test` bodies rather than via mocking, e.g. `tests/test_llm_client.py::TestLLMClientInit.test_missing_api_key_raises`:
```python
def test_missing_api_key_raises(self):
    old = os.environ.pop("KIMI_API_KEY", None)
    try:
        with self.assertRaises(ValueError):
            LLMClient(api_key="")
    finally:
        if old:
            os.environ["KIMI_API_KEY"] = old
```

## Mocking

**Framework:** None used. No `unittest.mock`, no `pytest-mock`, no `responses`/`httpretty` for HTTP. This is a deliberate gap (see Coverage Gaps below) — the async Kimi K2.5 API calls (`LLMClient.upload_pdf`, `get_file_content`, `extract_from_pdf`'s `chat.completions.create` call) are NOT unit tested; only the pure/synchronous helper logic (`_parse_response`, `_build_system_prompt`) is tested directly against `LLMClient` static/instance methods that don't touch the network.

**What IS tested without mocking:**
- Pure functions/static methods operating on in-memory data (`LLMClient._parse_response`, `postprocess.py` helpers via `announcement_processor` tests).
- Real SQLite databases created in temp directories (`sqlite3.connect(db_path)` against a `tempfile.mkdtemp()` path) rather than mocking the DB layer — this is the dominant "integration-lite" test strategy across `test_database_schema.py`, `test_open_ended_limits.py`, `test_announcement_processor.py`.
- Real parquet/CSV files written via pandas to a temp directory, then read back through `DataLoader` — full round-trip, not mocked.

**What is NOT tested / would need mocking if covered:**
- Any live call into `AsyncOpenAI` / Kimi K2.5 API (`src/data/llm_client.py`'s network methods)
- `akshare`/`jqdatasdk` network calls in `src/data/downloader.py`
- If adding tests for these, introduce `unittest.mock.patch` / `AsyncMock` for the `AsyncOpenAI` client and `httpx.AsyncClient` — no existing precedent in this codebase, so establish the pattern deliberately and document it if introduced.

## Fixtures and Factories

**Test Data:** No shared fixture/factory module (no `tests/fixtures.py`, no `conftest.py`). Each `TestCase` builds its own minimal data inline via private helper methods on the test class itself, e.g.:
```python
# tests/test_open_ended_limits.py
def _create_market_data(self, ticker: str, dates: pd.DatetimeIndex) -> None:
    df = pd.DataFrame({"date": dates, "ticker": ticker, "open": np.ones(...), ...})
    df.to_parquet(self.data_dir / "market" / f"{ticker}.parquet", index=False)

def _create_limit_events_db(self, events: list) -> None:
    db_path = self.data_dir / "config" / "fund_status.db"
    conn = sqlite3.connect(db_path)
    ...
```
- Follow this pattern for new tests needing DB/file fixtures: private `_create_*` helper methods on the TestCase, using `tempfile.mkdtemp()` for isolation, cleaned up in `tearDown`.

**Location:** No dedicated fixtures directory; test data is generated programmatically at test time rather than checked-in sample files (though `data/` and `output/` directories exist in the repo for real pipeline data — not used by tests).

## Coverage

**Requirements:** None enforced. No `coverage.py` config (`.coveragerc`), no CI coverage gate found.

**View Coverage:** Not currently supported out of the box; would require `pip install coverage` then `coverage run -m unittest discover tests && coverage report`.

## Test Types

**Unit Tests:** Majority of the suite — isolated logic (dedup rules, response parsing, fee-tier calculation, prompt building).

**"Integration-lite" Tests:** Tests that spin up a real temp SQLite DB and/or real parquet files and exercise a full component (`DataLoader.load_bundle`, `AnnouncementProcessor`'s DB write path) end-to-end without mocking the storage layer. This is the majority pattern for anything touching `src/data/loader.py`, `src/data/postprocess.py`-equivalent logic, and `src/engine/`.

**E2E Tests:** Not used. No tests invoke the live Kimi K2.5 API, live JoinQuant/akshare APIs, or drive the Streamlit app (`app/`).

## Coverage Gaps (relevant to CONCERNS.md)

- `src/data/llm_client.py`: network methods (`upload_pdf`, `get_file_content`, `delete_file`, the `chat.completions.create` call inside `extract_from_pdf`) are untested — only the pure parsing/prompt-building logic is covered.
- `src/data/downloader.py`: `RealDataDownloader` (JoinQuant + akshare integration) has no test coverage at all; no test file targets it.
- `src/data/announcement_processor.py`: `ProgressTracker` save/load-to-disk logic and the async `run()` orchestration (concurrency, retry, resume-from-progress-file) are not directly tested — `tests/test_announcement_processor.py` covers `find_pdfs`, record storage/dedup/fix/build/write helpers, but not the `AnnouncementProcessor.run()` orchestrator or `ProgressTracker` itself.
- `app/` (Streamlit UI) has no tests.

## Common Patterns

**Async Testing:**
No async test cases exist in the current suite (no `IsolatedAsyncioTestCase`, no `asyncio.run()` inside a test). Despite `LLMClient` and `AnnouncementProcessor` being async, their async entry points are untested; only synchronous helper methods are unit tested. If adding async tests, use `unittest.IsolatedAsyncioTestCase` (stdlib, consistent with the rest of the suite) rather than pulling in `pytest-asyncio`.

**Error Testing:**
```python
def test_missing_api_key_raises(self):
    ...
    with self.assertRaises(ValueError):
        LLMClient(api_key="")
```

**Numeric/DataFrame assertions:**
```python
self.assertTrue(
    (during_limit["daily_limit"] == 500.0).all(),
    "All dates from limit start should have the limit applied",
)
```
Vectorized pandas boolean comparisons combined with `.all()`, wrapped in `assertTrue` with a descriptive failure message — the standard idiom for DataFrame-column assertions in this codebase (`tests/test_open_ended_limits.py`, `tests/test_architecture_fixes.py`).

---

*Testing analysis: 2026-08-18*
