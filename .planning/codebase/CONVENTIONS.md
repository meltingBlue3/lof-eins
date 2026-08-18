# Coding Conventions

**Analysis Date:** 2026-08-18

## Naming Patterns

**Files:**
- Snake_case module names: `src/data/llm_client.py`, `src/data/announcement_processor.py`, `src/data/postprocess.py`
- One primary class/concept per file, file name matches the concept (e.g. `LLMClient` lives in `llm_client.py`)
- Scripts under `scripts/` are verb-first CLI entry points: `scripts/download_announcements.py`, `scripts/parse_announcements.py`, `scripts/generate_mock.py`
- Test files mirror the module under test with a `test_` prefix: `tests/test_llm_client.py` tests `src/data/llm_client.py`; some tests are organized by concern rather than 1:1 module (`tests/test_architecture_fixes.py`, `tests/test_database_schema.py`, `tests/test_open_ended_limits.py`)

**Functions:**
- snake_case throughout: `load_records`, `dedup_records`, `build_limit_events`, `_parse_response`
- Leading underscore for internal/private helpers: `_build_system_prompt`, `_process_and_save`, `_is_holiday_resume`, `_load_prompt`
- Async functions use standard verb names with no special suffix (no `_async` suffix): `async def extract_from_pdf`, `async def upload_pdf`, `async def get_file_content`

**Variables:**
- snake_case: `pdf_path`, `db_path`, `fund_records`, `by_fund`
- Short accumulator names in loops (`r`, `rec`, `nxt`) are common in `src/data/postprocess.py` — acceptable for tight, well-scoped loops but avoid in longer functions

**Types/Classes:**
- PascalCase: `LLMClient`, `AnnouncementProcessor`, `ProgressTracker`, `DataLoader`, `BacktestConfig`
- Dataclasses used for structured config/state objects (see `src/strategy/base.py`, `src/engine/account.py`) via `@dataclass`

## Code Style

**Formatting:**
- No formatter config detected (no `.prettierrc`/`black`/`ruff` config files found in repo root). Code is manually kept close to PEP 8: 4-space indent, double-quoted strings predominant, trailing commas in multi-line calls.
- No `.flake8`, `pyproject.toml` lint section, or `setup.cfg` present — treat existing file style as the de facto standard when adding code.

**Linting:**
- No linter configured. Follow existing patterns exactly (import grouping, docstring style, print-based status output) rather than introducing new tooling opinions.

**Type hints:**
- Consistent use of `typing` (`Optional`, `List`, `Dict`, `Any`) plus modern `X | Y` union syntax in newer modules (`src/data/postprocess.py`: `db_path: str | Path`, `src/data/announcement_processor.py`: `db_path: Path | str`)
- Function signatures are fully typed for public methods; return types included (`-> List[Dict[str, Any]]`, `-> dict`)

## Import Organization

**Order (observed convention):**
1. stdlib (`json`, `logging`, `os`, `re`, `sqlite3`, `asyncio`, `pathlib.Path`)
2. third-party (`httpx`, `pandas as pd`, `openai.AsyncOpenAI`)
3. local/relative imports (`from .llm_client import LLMClient`, `from src.config import BacktestConfig`)

**Path Aliases:**
- None configured. Local imports use either package-relative (`from .llm_client import LLMClient` inside `src/data/`) or absolute-from-root (`from src.config import BacktestConfig`, `from src.data.loader import DataLoader`) — absolute form is used from `app/`, `scripts/`, and `tests/`.
- Tests manually add project root to `sys.path` before importing local modules, since there is no installed package / `pyproject.toml` entry point:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.data.llm_client import LLMClient
```

## Error Handling

**Patterns:**
- Prefer specific exceptions where the failure mode is known, falling back to broad `except Exception` at integration boundaries (external APIs, file I/O) so a single bad record/file doesn't abort a batch job:
```python
# src/data/pdf_extractor.py
except pdfplumber.exceptions.PDFException as e:
    ...
except PermissionError as e:
    ...
except Exception as e:
    ...
```
- Async batch processing swallows and records per-item errors instead of raising (`src/data/announcement_processor.py::_process_one`) — failures go through `tracker.mark_failed(rel_path, str(e)[:120])`, truncated to 120 chars, so one bad PDF does not kill the whole run.
- `LLMClient.delete_file` intentionally suppresses all exceptions on cleanup (`except Exception: pass`) since file deletion failure is non-critical.
- Config/init validation raises `ValueError` early with an actionable message (`src/data/llm_client.py::__init__` raises if `KIMI_API_KEY` is missing).
- `try/finally` used to guarantee cleanup of uploaded remote resources regardless of success/failure (`LLMClient.extract_from_pdf` deletes the uploaded file in a `finally` block).

## Logging vs. Print

**Two parallel channels exist — match the one used by the module you're editing:**
- `logging` module (`logger = logging.getLogger(__name__)`) is declared in library-style modules (`src/data/llm_client.py`, `src/data/announcement_processor.py`) but is minimally used; most operational status is via `print()`.
- `print()` is the dominant status/progress channel for scripts and pipeline modules (`src/data/postprocess.py`, `src/data/announcement_processor.py`, `src/data/downloader.py`) — including bilingual (Chinese) progress messages and `[OK]`/`[WARN]`/[ERROR]` tags:
```python
print(f"[OK] JoinQuant login successful | Quota: {count['spare']}/{count['total']}")
print(f"    [WARN] Market data batch error: {e}")
```
- When adding new pipeline/CLI code, follow the `print()` + bracket-tag convention (`[OK]`, `[WARN]`, `[ERROR]`) already established in `src/data/downloader.py`. Reserve `logging` for library code that may be imported without wanting stdout noise (current usage is sparse, so this is aspirational rather than fully enforced).

## Comments

**Bilingual documentation is standard in newer/data-pipeline modules:**
- Many docstrings and inline comments are given in English followed by a Chinese translation on the next line, e.g.:
```python
def _get_nav_data(self, codes, start_date, end_date) -> pd.DataFrame:
    """Fetch NAV data for a batch of codes via akshare.
    通过 akshare 获取一批代码的净值数据。
    """
```
- This pattern appears throughout `src/data/downloader.py` and `tests/test_open_ended_limits.py`. Older modules (`src/data/llm_client.py`, `src/data/postprocess.py`, `src/data/announcement_processor.py`) are English-only in docstrings, with occasional inline Chinese literals for user-facing print output (since the tool serves Chinese fund data).
- When touching data/download/announcement pipeline files, follow the bilingual docstring pattern for new public methods. Print statements aimed at the operator (progress, warnings) are commonly in Chinese; code comments explaining logic are usually in English.

**Module docstrings:** every module opens with a triple-quoted docstring summarizing purpose, and pipeline modules include a `Usage:` example with an interactive-shell (`>>>`) snippet showing the primary entry point call, e.g. `src/data/postprocess.py`, `src/data/llm_client.py`, `src/data/announcement_processor.py`.

## Function Design

**Size:** Functions are typically 15–60 lines; pipeline "orchestrator" functions like `AnnouncementProcessor.run` and `postprocess()` are longer (60–120 lines) but stay flat (few nested branches) by delegating to well-named helpers.

**Parameters:** Keyword-style call sites are preferred for functions with more than 2-3 args; defaults are given for optional pipeline knobs (`concurrency: int = DEFAULT_CONCURRENCY`, `limit: int = 0`). Module-level constants (`DEFAULT_CONCURRENCY = 50`, `SAVE_INTERVAL = 50`, `BASE_URL`, `MODEL`) hold tunable pipeline parameters instead of magic numbers inline.

**Return Values:** Functions that produce pipeline stats return a plain `dict` with fixed keys (e.g. `{"completed": ..., "failed": ..., "total_records": ..., "pending": ...}` from `AnnouncementProcessor.run`; `{"raw": ..., "deduped": ..., "intervals": ...}` from `postprocess()`) rather than custom result classes — follow this convention for new pipeline stage functions.

## Module Design

**Exports:** No `__all__` lists used; public API is whatever is not underscore-prefixed. `src/data/__init__.py`, `src/engine/__init__.py`, `src/strategy/__init__.py` exist as plain namespace markers (check contents before assuming they re-export anything).

**Config objects:** Backtest/strategy configuration is centralized in dataclasses (`src/config.py::BacktestConfig`, consumed by `src/strategy/base.py` and `src/engine/`), rather than passing loose kwargs through the engine.

**Optional dependencies:** External SDKs that are not always installed are imported defensively at module load time with a boolean availability flag, e.g. `src/data/downloader.py`:
```python
try:
    import jqdatasdk as jq
    from jqdatasdk import finance
    JQ_AVAILABLE = True
except ImportError:
    JQ_AVAILABLE = False
```
`akshare` (the current NAV data source, replacing the legacy JoinQuant NAV path) is instead imported lazily inside `_get_nav_data()` with a friendly error message printed if missing — prefer this lazy-import style for optional dependencies scoped to a single method rather than the whole module.

---

*Convention analysis: 2026-08-18*
