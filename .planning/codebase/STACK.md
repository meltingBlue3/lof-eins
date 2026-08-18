# Technology Stack

**Analysis Date:** 2026-08-18

## Languages

**Primary:**
- Python 3.13 - entire codebase (backend engine, data pipeline, Streamlit app). Bytecode cache (`__pycache__/*.cpython-313.pyc`) confirms interpreter version.

**Secondary:**
- YAML - configuration files (`configs/backtest.yaml`, `configs/mock.yaml`)
- SQL (SQLite dialect) - schema/queries embedded in `src/data/downloader.py`, `src/data/announcement_processor.py`, `src/data/postprocess.py`
- Markdown - prompt templates (`prompts/system_prompt.md`) and docs

## Runtime

**Environment:**
- CPython 3.13
- Windows development environment (paths use `Path` from `pathlib` throughout for portability)

**Package Manager:**
- pip, dependencies declared in `requirements.txt`
- Lockfile: missing (no `requirements.lock`, `poetry.lock`, or `uv.lock`) — versions pinned loosely with `>=` except `numpy==1.26.4` and `jqdatasdk==1.9.8`

## Frameworks

**Core:**
- Streamlit >=1.30.0 - interactive web app (`app/app.py`, `app/pages/*.py`) for data exploration and backtest execution/results
- pandas >=2.0.0 - primary data manipulation library across data loading, engine, and postprocessing
- Plotly >=5.0.0 - charting in the Streamlit UI (`app/utils.py`)

**Testing:**
- pytest (invoked via `.pytest_cache`, tests in `tests/*.py`) - no explicit version pin in `requirements.txt`; installed separately in dev environment
- pytest-asyncio implied by async test usage in `tests/test_llm_client.py` (verify install if async tests fail)

**Build/Dev:**
- ruff - linter, config cache present at `.ruff_cache/0.12.5/` (version 0.12.5), no dependency line in `requirements.txt` (dev-only tool)
- No bundler/transpiler — pure Python project, no `pyproject.toml` present (only `requirements.txt`)

## Key Dependencies

**Critical:**
- `openai` >=1.0.0 - used as the async HTTP client (`AsyncOpenAI`) for Kimi K2.5 API in `src/data/llm_client.py`; NOT connecting to OpenAI's own API — `base_url` overridden to `https://api.moonshot.cn/v1`
- `httpx` (transitive, imported directly) - async HTTP calls for retrieving extracted PDF file content from Kimi's file API (`src/data/llm_client.py:67`)
- `pdfplumber` >=0.10.0 - PDF text/table extraction (`src/data/pdf_extractor.py`), still present though the current announcement pipeline extracts text via the Kimi file-upload API rather than local pdfplumber parsing for LLM-fed text
- `jqdatasdk` ==1.9.8 - JoinQuant SDK, optional dependency guarded by try/except in `src/data/downloader.py` (`JQ_AVAILABLE` flag); used for market/price data download
- `akshare` (installed in environment, version 1.18.51, but **absent from `requirements.txt`** — dependency-manifest drift) - used in `src/data/downloader.py:176` (`RealDataDownloader._get_nav_data`) to fetch fund NAV data via `ak.fund_open_fund_info_em`, replacing the prior NAV source
- `pyarrow` >=14.0.0 - Parquet I/O backend for pandas (market/nav data stored as `.parquet` under `data/*/market/`, `data/*/nav/`)
- `numpy` ==1.26.4 - numerical operations in engine/backtest code

**Infrastructure:**
- `PyYAML` >=6.0 - config file parsing (`src/config.py` `BacktestConfig.from_yaml`)
- `python-dotenv` >=1.0.0 - loads `.env` for credentials (JoinQuant, Kimi API key)
- `requests` >=2.32.3 - present in requirements but sync HTTP is superseded by `httpx`/`openai` async clients in the current announcement pipeline; may still be used elsewhere (e.g. `scripts/download_announcements.py`)
- SQLite (stdlib `sqlite3`) - primary persistent store, `data/*/config/fund_status.db`, used for fund status, subscription restrictions, and limit events tables

**Stale/unused in current pipeline:**
- `ollama` >=1.0.0 (requirements.txt) - the April 2026 rewrite (commits `4cc5212`, `89830c8`) replaced the Ollama-based sync LLM client with the async Kimi K2.5 client in `src/data/llm_client.py`. No `import ollama` or Ollama references remain in `src/`. This dependency and the `OLLAMA_HOST`/`OLLAMA_MODEL` env vars in `.env.example` are leftover from the prior architecture and should be considered for removal.

## Configuration

**Environment:**
- `.env` file (gitignored) loaded via `python-dotenv`; `.env.example` documents expected vars but is **stale** — still describes the old dual-provider (`LLM_API_KEY`/`LLM_URL` cloud-or-Ollama-fallback) scheme rather than the current single Kimi client
- Current code (`src/data/llm_client.py`) reads `KIMI_API_KEY` directly from `os.environ` — this var is not documented in `.env.example`
- `JQ_USERNAME` / `JQ_PASSWORD` - JoinQuant credentials, still current (used by `src/data/downloader.py` via `jqdatasdk`)
- `.env` and `.env.example` both exist in repo root (contents of `.env` not inspected per policy)

**Build:**
- No `pyproject.toml`, `setup.py`, or build backend — plain script/module execution (`python run_backtest.py`, `streamlit run app/app.py`, `python scripts/*.py`)
- `configs/backtest.yaml`, `configs/mock.yaml` - runtime backtest parameter configs loaded by `BacktestConfig.from_yaml` (`src/config.py`)

## Platform Requirements

**Development:**
- Python 3.13 interpreter
- Windows (primary dev OS per `.idea/` JetBrains project files and path conventions), but code uses `pathlib.Path` so should be cross-platform
- Local SQLite databases under `data/*/config/fund_status.db` — no external DB server required

**Production:**
- No deployment/CI config detected (no Dockerfile, no GitHub Actions workflows found in this scan) — runs as local scripts/Streamlit app
- Network access required at runtime for: JoinQuant API (`jqdatasdk`), akshare (scrapes/queries public fund data endpoints), Kimi/Moonshot API (`https://api.moonshot.cn/v1`)

---

*Stack analysis: 2026-08-18*
