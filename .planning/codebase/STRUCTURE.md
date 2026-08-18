# Codebase Structure

**Analysis Date:** 2026-08-18

## Directory Layout

```
lof-eins/
├── src/                                # Main source package
│   ├── __init__.py                     # Public API re-exports (BacktestConfig, DataLoader, engine, strategy)
│   ├── config.py                       # BacktestConfig dataclass (YAML load/save)
│   ├── data/                           # Data acquisition, storage access, announcement pipeline
│   │   ├── loader.py                   # DataLoader — merges market/nav/limit_events into one DataFrame
│   │   ├── downloader.py               # RealDataDownloader — JoinQuant market data + akshare NAV
│   │   ├── announcement_downloader.py  # Downloads announcement PDFs from Eastmoney
│   │   ├── pdf_extractor.py            # Standalone pdfplumber text extraction helper
│   │   ├── llm_client.py               # LLMClient — async Kimi K2.5 PDF upload + structured extraction
│   │   ├── announcement_processor.py   # AnnouncementProcessor — async concurrent batch orchestration
│   │   ├── postprocess.py              # subscription_restrictions → limit_events postprocessing
│   │   └── generator/                  # Synthetic/mock data generator
│   │       ├── config.py               # MockConfig dataclass
│   │       ├── generators.py           # Mock market/nav/limit generation functions
│   │       └── main.py                 # generate_mock_data() entry function
│   ├── strategy/                       # Trading strategy layer
│   │   ├── base.py                     # BaseStrategy (ABC), Signal dataclass
│   │   └── simple_lof.py               # SimpleLOFStrategy implementation
│   └── engine/                         # Backtest execution engine
│       ├── account.py                  # Account, PendingSettlement (T+2 settlement)
│       └── backtest.py                 # BacktestEngine, BacktestResult, fee calc
├── scripts/                            # Executable CLI entry points (thin argparse wrappers over src/)
│   ├── download_lof.py                 # Download market/NAV data (JoinQuant + akshare)
│   ├── download_announcements.py       # Download announcement PDFs (Eastmoney)
│   ├── parse_announcements.py          # Parse PDFs (Kimi K2.5) + postprocess → limit_events
│   ├── generate_mock.py                # Generate mock dataset
│   └── inspect_data.py                 # Visualize/inspect data quality (plotly)
├── app/                                # Streamlit dashboard
│   ├── app.py                          # Landing page / workflow overview
│   ├── utils.py                        # Shared UI helper functions
│   └── pages/
│       ├── 1_data_explorer.py          # Market/NAV/premium visualization
│       ├── 2_backtest.py               # Backtest configuration + run UI
│       └── 3_backtest_results.py       # Results viewer
├── prompts/
│   └── system_prompt.md                # LLM system prompt template for announcement extraction
├── configs/                            # YAML configuration files
│   ├── backtest.yaml                   # Default backtest parameters
│   └── mock.yaml                       # Default mock-data generation parameters
├── tests/                              # Unit/integration tests (pytest/unittest)
│   ├── test_loader.py
│   ├── test_open_ended_limits.py
│   ├── test_database_schema.py
│   ├── test_pdf_extractor.py
│   ├── test_llm_client.py
│   ├── test_announcement_processor.py
│   └── test_architecture_fixes.py
├── data/                               # Data root (gitignored, populated by scripts)
│   ├── mock/                           # Synthetic dataset (market/, nav/, config/)
│   └── real_all_lof/                   # Real downloaded dataset
│       ├── market/                     # {ticker}.parquet OHLCV
│       ├── nav/                        # {ticker}.parquet NAV series
│       ├── config/                     # fees.csv, fund_status.db (SQLite)
│       └── announcements/{ticker}/     # {date}_{title}.pdf announcement files
├── output/                             # Backtest run exports (timestamped dirs, gitignored)
├── docs/                               # Design docs (detailed-design.md, requirements.md)
├── .planning/                          # GSD planning artifacts (phases, quick tasks, roadmap)
├── run_backtest.py                     # Backtest CLI entry point
├── requirements.txt
├── README.md                           # NOTE: describes stale Ollama-based pipeline (see below)
└── TECHNICAL_PROPOSAL.md               # Original technical proposal (also predates Kimi/akshare rewrite)
```

## Directory Purposes

**`src/data/`:**
- Purpose: Everything related to acquiring, storing, and transforming fund data — market/NAV downloads and the announcement→limit_events pipeline.
- Contains: Downloaders, LLM client, batch processor, postprocessing logic, DataLoader.
- Key files: `loader.py` (read path used by engine), `llm_client.py` + `announcement_processor.py` + `postprocess.py` (announcement pipeline, rewritten April 2026).

**`src/data/generator/`:**
- Purpose: Produce synthetic datasets for testing without external API credentials.
- Contains: `MockConfig`, generation functions for market/nav/limit series, `generate_mock_data()` orchestrator.

**`src/strategy/`:**
- Purpose: Pluggable trading decision logic, decoupled from execution mechanics.
- Contains: Abstract interface (`BaseStrategy`) and one concrete implementation (`SimpleLOFStrategy`).

**`src/engine/`:**
- Purpose: Simulate trade execution, cash/position accounting, and settlement timing.
- Contains: `Account` (T+2 ledger), `BacktestEngine`/`BacktestResult` (simulation loop, metrics).

**`scripts/`:**
- Purpose: User-facing CLI entry points; each wraps a `src/` component with argparse and `.env` loading.
- Generated: No. Committed: Yes.

**`app/`:**
- Purpose: Streamlit multi-page dashboard mirroring the CLI workflow (explore data → configure backtest → view results).
- Contains: `app.py` (home), `pages/*.py` (Streamlit auto-routed pages), `utils.py` (shared formatting/plot helpers).

**`prompts/`:**
- Purpose: External prompt template(s) for the LLM extraction step, kept separate from code for easy iteration.
- Key file: `system_prompt.md`, loaded by `src/data/llm_client.py` via `_load_prompt()`.

**`configs/`:**
- Purpose: Default YAML parameter sets consumed by `BacktestConfig.from_yaml()` / mock generator.
- Generated: No. Committed: Yes.

**`data/`:**
- Purpose: All downloaded/generated datasets (market, NAV, announcements, SQLite state).
- Generated: Yes (by `scripts/download_lof.py`, `scripts/download_announcements.py`, `scripts/parse_announcements.py`, `scripts/generate_mock.py`).
- Committed: No (gitignored; large per-ticker fixture data present locally under `data/real_all_lof/announcements/{ticker}/`).

**`output/`:**
- Purpose: Timestamped backtest run exports (CSV daily perf / trade logs, console report).
- Generated: Yes (by `run_backtest.py`). Committed: No.

**`tests/`:**
- Purpose: Unit and integration tests for loader, engine constraints, PDF extraction, LLM client (mocked), announcement processor, DB schema.
- Note: `test_llm_client.py` and `test_announcement_processor.py` test the current Kimi/async implementation, not the legacy Ollama client.

## Key File Locations

**Entry Points:**
- `run_backtest.py`: Backtest CLI runner.
- `scripts/download_lof.py`: Market/NAV data downloader.
- `scripts/download_announcements.py`: Announcement PDF downloader.
- `scripts/parse_announcements.py`: LLM extraction + postprocessing runner.
- `scripts/generate_mock.py`: Mock dataset generator.
- `app/app.py`: Streamlit dashboard entry (`streamlit run app/app.py`).

**Configuration:**
- `configs/backtest.yaml`, `configs/mock.yaml`: Runtime parameters.
- `.env` / `.env.example`: Secrets — `JQ_USERNAME`, `JQ_PASSWORD`, `KIMI_API_KEY` (existence only; contents never inspected here).
- `src/config.py`: `BacktestConfig` dataclass definition and YAML (de)serialization.

**Core Logic:**
- `src/data/loader.py`: Data merge/alignment.
- `src/data/llm_client.py`, `src/data/announcement_processor.py`, `src/data/postprocess.py`: Announcement → limit_events pipeline (current implementation, post-rewrite).
- `src/engine/backtest.py`, `src/engine/account.py`: Simulation core.
- `src/strategy/simple_lof.py`: Default strategy logic.

**Testing:**
- `tests/*.py`: Mirrors `src/` modules by concern (loader, schema, pdf extraction, LLM client, processor, open-ended limits, architecture fixes).

## Naming Conventions

**Files:**
- Snake_case module names matching primary class/function, e.g. `announcement_processor.py` defines `AnnouncementProcessor`.
- Test files: `test_<module_under_test>.py`, mirroring `src/` filenames.
- Downloaded PDFs: `{date:YYYY-MM-DD}_{title}.pdf` under `data/{dataset}/announcements/{ticker}/`.

**Directories:**
- `src/{domain}/` groups by architectural layer (`data`, `strategy`, `engine`), not by feature.
- `data/{dataset_name}/{market,nav,config,announcements}/` — fixed subdirectory contract enforced by `DataLoader.__init__` (raises `FileNotFoundError` if `market`, `nav`, or `config` is missing).
- `output/{YYYYMMDD_HHMMSS}/` — one directory per backtest run.

## Where to Add New Code

**New announcement-pipeline stage/feature:**
- Implementation: `src/data/` (new module) or extend `postprocess.py` / `announcement_processor.py`.
- Prompt changes: `prompts/system_prompt.md`.
- Tests: `tests/test_announcement_processor.py` or a new `tests/test_<feature>.py`.

**New trading strategy:**
- Implementation: `src/strategy/<name>.py`, subclassing `BaseStrategy` from `src/strategy/base.py`.
- Register/use: pass instance to `BacktestEngine(strategy=...)` in `run_backtest.py` or a new script.

**New data source (market/NAV):**
- Implementation: extend `src/data/downloader.py` (`RealDataDownloader`) or add a sibling downloader module following its output contract (`market/{ticker}.parquet`, `nav/{ticker}.parquet`, `config/fees.csv`, `config/fund_status.db`).

**New Streamlit page:**
- Implementation: `app/pages/N_<name>.py` (Streamlit auto-numbers/orders by filename prefix); shared helpers in `app/utils.py`.

**Utilities:**
- Shared backtest/engine helpers: colocate in `src/engine/backtest.py` (e.g., `calculate_subscription_fee`) unless broadly reusable, then add a `src/utils.py`-style module (none currently exists — introduce only if reuse spans layers).

## Special Directories

**`data/`:**
- Purpose: Runtime data root for both mock and real datasets.
- Generated: Yes. Committed: No (gitignored).

**`output/`:**
- Purpose: Backtest result exports, one timestamped subdirectory per run.
- Generated: Yes. Committed: No.

**`.planning/`:**
- Purpose: GSD workflow state — phases, quick-task logs, roadmap, requirements. Not application code.
- Generated: Partially (by GSD tooling). Committed: Yes.

**`.idea/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`:**
- Purpose: IDE/tooling artifacts. Generated: Yes. Committed: No.

---

*Structure analysis: 2026-08-18*
