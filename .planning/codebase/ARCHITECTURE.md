<!-- refreshed: 2026-08-18 -->
# Architecture

**Analysis Date:** 2026-08-18

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI Scripts / Streamlit UI                    │
│  `scripts/*.py`, `run_backtest.py`, `app/app.py`, `app/pages/*.py`   │
├──────────────────┬──────────────────┬────────────────────────────────┤
│  Data Acquisition │  Announcement     │      Backtest Runner          │
│  `src/data/       │  Pipeline         │  `run_backtest.py`             │
│  downloader.py`,  │  `src/data/       │                                │
│  `announcement_   │  llm_client.py`,  │                                │
│  downloader.py`   │  `announcement_   │                                │
│  (JoinQuant +      │  processor.py`,   │                                │
│  akshare NAV)      │  `postprocess.py` │                                │
└─────────┬─────────┴────────┬─────────┴──────────────┬─────────────────┘
          │                  │                          │
          ▼                  ▼                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Persistence Layer (per-ticker on disk)            │
│  `data/{dataset}/market/*.parquet`  `data/{dataset}/nav/*.parquet`   │
│  `data/{dataset}/config/fund_status.db` (SQLite: limit_events,       │
│  subscription_restrictions, announcement_parses, limit_event_log)    │
│  `data/{dataset}/announcements/{ticker}/*.pdf`                        │
└─────────────────────────────┬───────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DataLoader (`src/data/loader.py`)                │
│         Aligns market + nav + limit_events into one DataFrame        │
└─────────────────────────────┬───────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│         Backtest Engine (`src/engine/backtest.py`,                   │
│         `src/engine/account.py`) + Strategy (`src/strategy/*.py`)    │
└─────────────────────────────┬───────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│   BacktestResult → CSV export (`output/{timestamp}/`) + console       │
│   report; also consumed by Streamlit `app/pages/3_backtest_results.py`│
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| RealDataDownloader | Downloads market OHLCV from JoinQuant, NAV from akshare, writes parquet + fees.csv + fund_status.db skeleton | `src/data/downloader.py` |
| AnnouncementDownloader | Downloads announcement PDFs per ticker from Eastmoney | `src/data/announcement_downloader.py` |
| LLMClient | Uploads PDF to Kimi K2.5 file API, extracts text, runs structured-extraction chat completion, normalizes records | `src/data/llm_client.py` |
| AnnouncementProcessor | Discovers subscription-restriction PDFs, orchestrates async concurrent LLM extraction with progress tracking/resume, writes `subscription_restrictions` table | `src/data/announcement_processor.py` |
| postprocess module | Dedupes/fixes `subscription_restrictions` event stream, pairs suspend/resume events into `limit_events` intervals, validates data, writes to SQLite | `src/data/postprocess.py` |
| PDF extractor (legacy helper) | Standalone pdfplumber text extraction utility, still used/tested independently | `src/data/pdf_extractor.py` |
| DataLoader | Reads market/nav/limit_events/fees from a dataset dir, merges into one DataFrame with `premium_rate` and `daily_limit`, caches fee config | `src/data/loader.py` |
| BacktestConfig | Dataclass of tunable backtest parameters, YAML (de)serialization | `src/config.py` |
| BaseStrategy / SimpleLOFStrategy | Strategy interface producing `Signal` objects per bar | `src/strategy/base.py`, `src/strategy/simple_lof.py` |
| Account | T+2 settlement cash/position ledger | `src/engine/account.py` |
| BacktestEngine / BacktestResult | Drives day-by-day simulation, applies constraints (limit/liquidity/cash), computes performance metrics | `src/engine/backtest.py` |
| Mock data generator | Synthetic market/nav/limit data for testing without real downloads | `src/data/generator/{config,generators,main}.py` |
| Streamlit app | Interactive UI for data exploration, backtest configuration, results viewing | `app/app.py`, `app/pages/1_data_explorer.py`, `app/pages/2_backtest.py`, `app/pages/3_backtest_results.py`, `app/utils.py` |
| CLI entry scripts | Thin argparse wrappers invoking the above components | `scripts/download_lof.py`, `scripts/download_announcements.py`, `scripts/parse_announcements.py`, `scripts/generate_mock.py`, `scripts/inspect_data.py` |

## Pattern Overview

**Overall:** Layered, file/SQLite-backed batch pipeline feeding a config-driven event-loop backtesting engine. No web server/API layer; all interaction is via CLI scripts and a Streamlit dashboard that shells out to the same library code.

**Key Characteristics:**
- Strict one-way data flow: download → parse/postprocess → load → simulate → report. No component reads back from downstream stages.
- Each pipeline stage is independently runnable via its own CLI script and writes durable state to disk/SQLite, enabling resumable batch processing (see `ProgressTracker` in `announcement_processor.py`).
- Async I/O is isolated to the LLM extraction stage (`asyncio` + `httpx`/`AsyncOpenAI`); the rest of the codebase (loader, engine, strategy) is synchronous/vectorized pandas code.
- Dataclasses (`BacktestConfig`, `Signal`, `Account`, `PendingSettlement`) model core domain objects; the strategy interface is a classic Strategy pattern via `BaseStrategy.generate_signals`.

## Layers

**Acquisition Layer:**
- Purpose: Pull raw external data (market OHLCV, NAV, announcement PDFs) into the local dataset directory.
- Location: `src/data/downloader.py`, `src/data/announcement_downloader.py`
- Contains: JoinQuant SDK calls (market OHLCV, historical fund data), akshare calls (`ak.fund_open_fund_info_em`) for NAV, Eastmoney scraping for PDFs.
- Depends on: External APIs (JoinQuant `jqdatasdk`, `akshare`, Eastmoney HTTP), `.env` credentials.
- Used by: `scripts/download_lof.py`, `scripts/download_announcements.py`.

**Announcement Extraction Layer:**
- Purpose: Turn PDF announcements into structured subscription-restriction records, then normalize into backtest-ready `limit_events`.
- Location: `src/data/llm_client.py`, `src/data/announcement_processor.py`, `src/data/postprocess.py`, `src/data/pdf_extractor.py` (legacy/standalone), `prompts/system_prompt.md`
- Contains: Kimi K2.5 file-upload + chat-completion async client, PDF discovery/filtering (`标题含"申购"且不含"优惠"`), concurrent processing with `asyncio.Semaphore`, JSON progress persistence, event-stream dedup/pairing logic writing SQLite `limit_events`.
- Depends on: `KIMI_API_KEY` env var, `openai` SDK (AsyncOpenAI pointed at Moonshot base URL), `httpx`, SQLite (`fund_status.db`).
- Used by: `scripts/parse_announcements.py`.

**Data Access Layer:**
- Purpose: Present a unified per-ticker DataFrame (market + NAV + limit events + fee attrs) to the backtest engine.
- Location: `src/data/loader.py`
- Contains: `DataLoader.load_bundle()`, ticker discovery, fee-config caching via `DataFrame.attrs`.
- Depends on: Parquet files under `{dataset}/market`, `{dataset}/nav`, SQLite `{dataset}/config/fund_status.db`, CSV `{dataset}/config/fees.csv`.
- Used by: `src/engine/backtest.py`, `run_backtest.py`, `app/pages/1_data_explorer.py`, `scripts/inspect_data.py`.

**Strategy Layer:**
- Purpose: Pure decision logic mapping a market-data row + current positions to buy/sell `Signal`s.
- Location: `src/strategy/base.py`, `src/strategy/simple_lof.py`
- Depends on: `src/config.py` (`BacktestConfig`).
- Used by: `src/engine/backtest.py`.

**Engine Layer:**
- Purpose: Simulate day-by-day trading against strategy signals with T+2 settlement, fee tiers, and constraint clamping (limit/liquidity/cash).
- Location: `src/engine/backtest.py`, `src/engine/account.py`
- Depends on: `DataLoader`, `BaseStrategy`, `BacktestConfig`.
- Used by: `run_backtest.py`, `app/pages/2_backtest.py`.

**Presentation Layer:**
- Purpose: Multi-page Streamlit dashboard wrapping the same library calls used by CLI scripts.
- Location: `app/app.py`, `app/pages/1_data_explorer.py`, `app/pages/2_backtest.py`, `app/pages/3_backtest_results.py`, `app/utils.py`

## Data Flow

### Primary Backtest Path

1. `run_backtest.py` loads `configs/backtest.yaml` into `BacktestConfig` and instantiates `DataLoader(data_dir)`.
2. `DataLoader.load_bundle(ticker)` (`src/data/loader.py:63`) merges market parquet, NAV parquet, and `limit_events` from SQLite into one indexed DataFrame, attaching fee config to `df.attrs`.
3. `BacktestEngine.run()` (`src/engine/backtest.py`) iterates day-by-day, calling `SimpleLOFStrategy.generate_signals()` per row, then applying constraint clamping (limit → liquidity → cash) before executing via `Account`.
4. `Account` (`src/engine/account.py`) tracks cash, positions, and `PendingSettlement` queue for T+2 share availability.
5. Engine returns `BacktestResult` (daily perf, trade logs, computed metrics); `run_backtest.py` prints a report and optionally exports CSVs to `output/{timestamp}/`.

### Announcement Processing Path

1. `scripts/parse_announcements.py` invokes `AnnouncementProcessor.run()` (`src/data/announcement_processor.py:150`), which discovers eligible PDFs via `find_pdfs()` (filename pattern + title contains "申购", excludes "优惠").
2. For each pending PDF, `AnnouncementProcessor._process_one()` calls `LLMClient.extract_from_pdf()` (`src/data/llm_client.py:93`) under an `asyncio.Semaphore(concurrency)` — uploads PDF to Kimi file API, retrieves extracted text, sends a chat completion with the system prompt from `prompts/system_prompt.md`, and parses the JSON response into records.
3. `ProgressTracker` persists interim state to `parse_progress.json` every `SAVE_INTERVAL` (50) completions, enabling resumable batch runs (`--retry-failed`, `--reset`).
4. Results are bulk-inserted into `subscription_restrictions` table via `AnnouncementProcessor._save_records()`.
5. `postprocess.postprocess()` (`src/data/postprocess.py:357`) loads all `subscription_restrictions`, dedupes overlapping annual-arrangement vs single-announcement records, fixes missing `restriction_type` on resume events, validates data quality, pairs suspend/restrict events with matching resume events into `[start, end]` intervals (including synthetic pre-data-range suspensions), and rewrites the `limit_events` table (drop + recreate + reinsert).

**State Management:**
- All pipeline state is persisted to disk (parquet, SQLite, JSON progress file) between stages — no in-memory hand-off across CLI invocations. Within a single `AnnouncementProcessor.run()` call, shared mutable state (`ProgressTracker.results/processed/failed`) is protected by an `asyncio.Lock`.

## Key Abstractions

**BacktestConfig (`src/config.py`):**
- Purpose: Single source of truth for backtest tunables (cash, thresholds, fee rate, risk mode).
- Pattern: Dataclass with `__post_init__` validation and `from_yaml`/`to_yaml` methods.

**Signal / BaseStrategy (`src/strategy/base.py`):**
- Purpose: Decouple trading decision logic from execution mechanics.
- Pattern: Abstract base class (Strategy pattern); `generate_signals(row, positions, config) -> List[Signal]`.

**BundleResult (`src/data/loader.py`):**
- Purpose: Typed return value pairing the merged DataFrame with fee config.
- Pattern: `NamedTuple`.

**ProgressTracker (`src/data/announcement_processor.py:36`):**
- Purpose: Resumable async batch processing with rate reporting and periodic checkpoint saves.
- Pattern: Class wrapping an `asyncio.Lock`-guarded mutable state dict, flushed to `parse_progress.json`.

## Entry Points

**`run_backtest.py`:**
- Triggers: Manual CLI invocation.
- Responsibilities: Load YAML config, run `BacktestEngine`, print report, optionally export CSV to `output/`.

**`scripts/download_lof.py`:**
- Triggers: Manual CLI invocation (requires JoinQuant `.env` credentials).
- Responsibilities: Batch-download market OHLCV + akshare NAV data, write parquet + fees.csv + fund_status.db skeleton to `data/real_all_lof/`.

**`scripts/download_announcements.py`:**
- Triggers: Manual CLI invocation.
- Responsibilities: Download per-ticker announcement PDFs from Eastmoney into `data/real_all_lof/announcements/{ticker}/`.

**`scripts/parse_announcements.py`:**
- Triggers: Manual CLI invocation (requires `KIMI_API_KEY`).
- Responsibilities: Run `AnnouncementProcessor` (async concurrent LLM extraction) then `postprocess()` to produce `limit_events`.

**`scripts/generate_mock.py`:**
- Triggers: Manual CLI invocation.
- Responsibilities: Generate synthetic dataset under `data/mock/` via `src/data/generator`.

**`app/app.py` (+ `app/pages/*.py`):**
- Triggers: `streamlit run app/app.py`.
- Responsibilities: Interactive dashboard — data exploration, backtest configuration/run, results visualization.

## Architectural Constraints

- **Threading:** Single-threaded except for `asyncio` concurrency inside `AnnouncementProcessor`/`LLMClient` (I/O-bound API calls only, no CPU parallelism). Engine/loader code is synchronous.
- **Global state:** None at module level beyond cached prompt template (`SYSTEM_PROMPT_TEMPLATE` loaded once in `src/data/llm_client.py`) and per-instance caches (`DataLoader._fees_cache`).
- **Circular imports:** None observed; dependency direction is strictly acquisition → extraction → loader → engine/strategy.
- **External API coupling:** JoinQuant (`jqdatasdk`) is an optional import guarded by `JQ_AVAILABLE` in `src/data/downloader.py`; akshare NAV fetch (`ak.fund_open_fund_info_em`) is a local import inside the method, so the module loads even without akshare installed until that code path runs.
- **Data format coupling:** `DataLoader` assumes `market/`, `nav/`, `config/` subdirectories exist under `data_dir`; missing any raises `FileNotFoundError` at construction time.

## Anti-Patterns

### Legacy documentation drift

**What happens:** `README.md` and `TECHNICAL_PROPOSAL.md` describe the announcement pipeline as using Ollama (`src/data/llm_client.py` — Ollama) and do not mention `postprocess.py` or akshare NAV sourcing.
**Why it's wrong:** The actual `src/data/llm_client.py` uses Kimi K2.5 via `AsyncOpenAI`/Moonshot API, `src/data/downloader.py` fetches NAV via akshare, and `src/data/postprocess.py` (not present in README's file tree) performs the timeline-integration step the README lists as "Phase 3 — 待开始 (not started)" even though it is implemented and wired into `scripts/parse_announcements.py`.
**Do this instead:** Treat `src/data/*.py` source files as ground truth over `README.md`/`TECHNICAL_PROPOSAL.md` when reasoning about the announcement pipeline; update those docs during any future doc-refresh pass.

### Full-table rewrite for `limit_events`

**What happens:** `postprocess.write_limit_events()` (`src/data/postprocess.py:257`) drops and recreates the entire `limit_events` table on every run.
**Why it's wrong:** Any manual edits or `limit_event_log` audit correlations to prior `limit_events` rows are lost; concurrent readers (e.g., a running backtest) could see a transiently empty table.
**Do this instead:** If incremental updates are needed, migrate to an upsert-by-ticker strategy or wrap the drop/recreate in a transaction with a table-swap (rename) pattern.

## Error Handling

**Strategy:** Fail-soft at the batch-item level, fail-fast at the configuration/setup level.

**Patterns:**
- `AnnouncementProcessor._process_one()` catches all exceptions per-PDF and records them via `ProgressTracker.mark_failed()` rather than aborting the batch (`src/data/announcement_processor.py:131`).
- `LLMClient.extract_from_pdf()` uses `try/finally` to guarantee uploaded file cleanup (`delete_file`) even on failure (`src/data/llm_client.py:107`).
- Setup-time errors (missing `KIMI_API_KEY`, missing `data_dir` subfolders, missing `fund_status.db`) raise/exit immediately (`ValueError` in `LLMClient.__init__`, `FileNotFoundError` in `DataLoader.__init__`, `sys.exit(1)` in `scripts/parse_announcements.py`).
- `postprocess.validate()` collects data-quality issues into a report list and prints (does not raise), acting as a soft warning gate before writing `limit_events`.

## Cross-Cutting Concerns

**Logging:** Standard library `logging` module per-file loggers (`logger = logging.getLogger(__name__)`) in `llm_client.py`, `announcement_processor.py`, `backtest.py`, `account.py`; CLI scripts additionally use `print()` for user-facing progress (bilingual Chinese/English messages throughout).
**Validation:** Dataclass `__post_init__` validation (`BacktestConfig`, `Signal`); explicit `postprocess.validate()` pass for announcement data quality before committing `limit_events`.
**Authentication:** Environment-variable-based secrets only — `KIMI_API_KEY` (Kimi/Moonshot), `JQ_USERNAME`/`JQ_PASSWORD` (JoinQuant), loaded via `python-dotenv` from `.env` in each CLI script's bootstrap.

---

*Architecture analysis: 2026-08-18*
