# External Integrations

**Analysis Date:** 2026-08-18

## APIs & External Services

**LLM / Document Extraction:**
- Kimi K2.5 (Moonshot AI) - `src/data/llm_client.py`
  - Purpose: async structured-data extraction from fund subscription-restriction PDF announcements (replaces the prior Ollama sync client as of commits `4cc5212`/`89830c8`, April 2026)
  - SDK/Client: `openai.AsyncOpenAI` pointed at `base_url = "https://api.moonshot.cn/v1"`, `MODEL = "kimi-k2.5"` (`src/data/llm_client.py:28-29`)
  - Auth: `KIMI_API_KEY` env var (read directly via `os.environ.get`, `src/data/llm_client.py:52`) — **not documented** in `.env.example` (which still shows stale `LLM_API_KEY`/`LLM_URL`)
  - Flow: `upload_pdf()` → Kimi file API (`purpose="file-extract"`) → `get_file_content()` via raw `httpx` GET to `{BASE_URL}/files/{file_id}/content` → `chat.completions.create()` for structured JSON extraction → `delete_file()` cleanup in a `finally` block
  - Orchestration: `src/data/announcement_processor.py` (`AnnouncementProcessor`) runs many PDFs concurrently via `asyncio.Semaphore` (default concurrency 50), with JSON-file progress tracking/resume (`parse_progress.json`) and periodic partial saves

**Financial Data - Market/Price:**
- JoinQuant (`jqdatasdk`) - `src/data/downloader.py` (`RealDataDownloader`)
  - Purpose: downloads LOF fund daily market data (OHLCV) and fee/status metadata
  - SDK/Client: `jqdatasdk` (optional import, guarded by `JQ_AVAILABLE` flag so the module degrades gracefully without the package)
  - Auth: `JQ_USERNAME` / `JQ_PASSWORD` env vars (`.env.example`)

**Financial Data - Fund NAV:**
- akshare - `src/data/downloader.py:176` (`RealDataDownloader._get_nav_data`)
  - Purpose: fetches fund unit-NAV time series (`ak.fund_open_fund_info_em(symbol=..., indicator="单位净值走势")`) — this is the **new NAV source** introduced in the April 2026 rewrite, replacing whatever NAV source the pipeline used previously
  - SDK/Client: `akshare` (lazy `import akshare as ak` inside the method, with a friendly error if not installed — no auth/API key required, akshare scrapes public data sources)
  - Note: package is installed in the environment (v1.18.51) but is **not listed in `requirements.txt`** — dependency manifest is out of date relative to actual code

## Data Storage

**Databases:**
- SQLite - local file-based, no server
  - Path: `data/{dataset}/config/fund_status.db` (e.g. `data/real_all_lof/config/fund_status.db`, `data/mock/config/`)
  - Client: Python stdlib `sqlite3`, raw SQL (no ORM)
  - Key tables:
    - `subscription_restrictions` - raw event stream written by `AnnouncementProcessor._save_records` (`src/data/announcement_processor.py:247`); schema includes `fund_code`, `effective_date`, `end_date`, `action`, `restriction_type`, `scope`, `limit_amount`, `affected_business` (JSON-encoded list), `source_file`
    - `limit_events` - derived backtest-ready intervals produced by `src/data/postprocess.py` (`postprocess()` function): loads raw records, deduplicates (annual arrangement vs single announcement overlap), fixes missing `restriction_type` on resume records, pairs suspend/restrict events with resume events into intervals
    - `fees` / fund status tables - written by `RealDataDownloader` in `src/data/downloader.py`

**File Storage:**
- Local filesystem only
  - `.parquet` files (via `pyarrow`) for market and NAV time series: `data/{dataset}/market/{ticker}.parquet`, `data/{dataset}/nav/{ticker}.parquet`
  - PDF announcements stored under `data/real_all_lof/announcements/{ticker}/{date}_{title}.pdf`, downloaded by `scripts/download_announcements.py`
  - Backtest run outputs written to `output/{timestamp}/` (daily_perf.csv, daily_snapshots.csv, summary.txt, trade_logs.csv)

**Caching:**
- None detected (no Redis/memcached). Progress/resume state for the LLM pipeline uses a plain JSON file (`parse_progress.json`) rather than a cache service.

## Authentication & Identity

**Auth Provider:**
- None — this is a local data-pipeline/backtesting tool, not a multi-user service. No user auth system.
- Third-party service credentials only: JoinQuant (`JQ_USERNAME`/`JQ_PASSWORD`), Kimi/Moonshot (`KIMI_API_KEY`)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry or similar). Errors surfaced via Python `logging` module (`logger = logging.getLogger(__name__)` pattern in `src/data/llm_client.py`, `src/data/announcement_processor.py`) and printed to stdout with Chinese-language progress/error messages.

**Logs:**
- `backtest_execution.log` at repo root — plain text log file from backtest runs
- Console/stdout progress reporting in `AnnouncementProcessor` (rate, completed/failed counts, elapsed time)

## CI/CD & Deployment

**Hosting:**
- Not detected — no Dockerfile, no cloud deployment config found. Runs locally via `python run_backtest.py`, `streamlit run app/app.py`, and standalone scripts in `scripts/`.

**CI Pipeline:**
- None detected (no `.github/workflows/`)

## Environment Configuration

**Required env vars (current, per actual code):**
- `KIMI_API_KEY` - Kimi/Moonshot LLM API key (`src/data/llm_client.py`) — **undocumented in `.env.example`**
- `JQ_USERNAME`, `JQ_PASSWORD` - JoinQuant credentials (`.env.example`, `src/data/downloader.py`)

**Stale env vars (documented in `.env.example` but no longer used):**
- `LLM_API_KEY`, `LLM_URL`, `LLM_MODEL` - remnants of a prior dual-provider (cloud/local) LLM client design
- `OLLAMA_HOST`, `OLLAMA_MODEL` - remnants of the pre-rewrite Ollama-based sync LLM client, superseded by Kimi K2.5

**Secrets location:**
- `.env` file at repo root (gitignored per `.gitignore`), loaded via `python-dotenv`

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None (all external calls are synchronous/async request-response API calls initiated by the pipeline scripts, not event-driven webhooks)

---

*Integration audit: 2026-08-18*
