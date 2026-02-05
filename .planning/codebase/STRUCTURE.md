# Codebase Structure

**Analysis Date:** 2025-02-06

## Directory Layout

```
lof-eins/
├── src/                          # Main source package
│   ├── __init__.py               # Package exports
│   ├── config.py                 # BacktestConfig (central config)
│   ├── data/                     # Data layer
│   │   ├── __init__.py
│   │   ├── loader.py             # DataLoader (unified data access)
│   │   ├── downloader.py         # RealDataDownloader (JoinQuant)
│   │   ├── announcement_downloader.py  # Fund announcement scraper
│   │   └── generator/            # Mock data generator
│   │       ├── __init__.py
│   │       ├── config.py         # MockConfig
│   │       ├── generators.py     # Data generation logic
│   │       └── main.py           # Generator entry point
│   ├── strategy/                 # Strategy layer
│   │   ├── __init__.py
│   │   ├── base.py               # BaseStrategy (ABC), Signal
│   │   └── simple_lof.py         # SimpleLOFStrategy (implementation)
│   └── engine/                   # Backtest engine
│       ├── __init__.py
│       ├── account.py            # Account (T+2 settlement)
│       └── backtest.py           # BacktestEngine, BacktestResult
├── configs/                      # YAML configuration files
│   ├── backtest.yaml             # Backtest parameters
│   └── mock.yaml                 # Mock data generation parameters
├── scripts/                      # Executable scripts
│   ├── download_lof.py           # Download real data from JoinQuant
│   ├── download_announcements.py # Download fund announcements
│   ├── generate_mock.py          # Generate mock test data
│   └── inspect_data.py           # Visualize data with Plotly
├── tests/                        # Test files
│   └── test_loader.py            # DataLoader unit tests
├── data/                         # Data directory (gitignored)
│   ├── mock/                     # Generated mock data
│   │   ├── market/               # OHLCV Parquet files
│   │   ├── nav/                  # NAV Parquet files
│   │   └── config/               # fees.csv, fund_status.db
│   └── real_all_lof/             # Downloaded real data (same structure)
├── run_backtest.py               # Main backtest entry point
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
└── README.md                     # Documentation
```

## Directory Purposes

### `src/`
- Purpose: Main Python package
- Contains: All source code organized by layer
- Key files: `__init__.py` (exports main classes)

### `src/data/`
- Purpose: Data loading, downloading, and generation
- Contains: DataLoader, downloaders, generator subpackage
- Key files: `loader.py` (core data access)

### `src/data/generator/`
- Purpose: Mock data generation
- Contains: Config, generators, entry point
- Key files: `generators.py` (GBM simulation, limit event generation)

### `src/strategy/`
- Purpose: Trading strategy implementations
- Contains: Base class and concrete strategies
- Key files: `base.py` (abstract interface), `simple_lof.py` (example implementation)

### `src/engine/`
- Purpose: Backtest execution engine
- Contains: Account management, backtest orchestration, results
- Key files: `backtest.py` (main engine), `account.py` (T+2 settlement)

### `configs/`
- Purpose: YAML configuration files
- Contains: Parameter files for backtest and data generation
- Key files: `backtest.yaml`, `mock.yaml`

### `scripts/`
- Purpose: Executable utilities
- Contains: CLI tools for data operations
- Key files: `download_lof.py`, `generate_mock.py`, `inspect_data.py`

### `data/`
- Purpose: Data storage (not committed)
- Contains: Market data, NAV data, configuration, limit events
- Structure: `market/`, `nav/`, `config/` subdirectories

### `tests/`
- Purpose: Unit tests
- Contains: Test files
- Key files: `test_loader.py`

## Key File Locations

### Entry Points
- `run_backtest.py`: Main backtest runner (CLI)
- `scripts/generate_mock.py`: Mock data generator (CLI)
- `scripts/download_lof.py`: Real data downloader (CLI)
- `src/data/generator/main.py`: Generator programmatic entry

### Configuration
- `src/config.py`: `BacktestConfig` class
- `src/data/generator/config.py`: `MockConfig` class
- `configs/backtest.yaml`: Runtime backtest parameters
- `configs/mock.yaml`: Mock generation parameters
- `.env.example`: Environment variable template (JoinQuant credentials)

### Core Logic
- `src/engine/backtest.py`: `BacktestEngine` (586 lines)
- `src/engine/account.py`: `Account` with T+2 settlement (292 lines)
- `src/data/loader.py`: `DataLoader` (246 lines)
- `src/strategy/base.py`: `BaseStrategy` ABC, `Signal` dataclass

### Data Files (Generated)
- `data/{source}/market/{ticker}.parquet`: OHLCV market data
- `data/{source}/nav/{ticker}.parquet`: NAV data
- `data/{source}/config/fees.csv`: Tiered fee configuration
- `data/{source}/config/fund_status.db`: Limit events (SQLite)

## Naming Conventions

### Files
- Python modules: `snake_case.py` (e.g., `simple_lof.py`, `backtest.py`)
- Configuration: `lowercase.yaml` (e.g., `backtest.yaml`)
- Scripts: `snake_case.py` with action prefix (e.g., `download_lof.py`, `generate_mock.py`)

### Directories
- Source directories: `lowercase/` (e.g., `src/`, `data/`, `strategy/`)
- Generated data: `{source}_{descriptor}/` (e.g., `real_all_lof/`, `mock/`)

### Classes
- Config classes: `{Name}Config` (e.g., `BacktestConfig`, `MockConfig`)
- Strategy classes: `{Name}Strategy` (e.g., `SimpleLOFStrategy`)
- Engine classes: `{Name}Engine` (e.g., `BacktestEngine`)
- Result classes: `{Name}Result` (e.g., `BacktestResult`)
- Account classes: `{Name}` (e.g., `Account`, `PendingSettlement`)

### Functions/Methods
- Public methods: `snake_case` (e.g., `run()`, `load_bundle()`, `generate_signals()`)
- Private methods: `_snake_case` with underscore prefix (e.g., `_execute_buy()`, `_calculate_t2_date()`)

## Where to Add New Code

### New Strategy
- Implementation: `src/strategy/{name}.py`
- Inherit from: `BaseStrategy`
- Implement: `generate_signals(row, positions, config) -> List[Signal]`
- Export from: `src/__init__.py` (optional)

### New Data Source
- Downloader: `src/data/{name}_downloader.py`
- Follow pattern: `RealDataDownloader` in `downloader.py`
- Implement: `authenticate()`, `download_tickers()` methods

### New Configuration Parameter
- Backtest config: Add field to `src/config.py` `BacktestConfig`
- Mock config: Add field to `src/data/generator/config.py` `MockConfig`
- Add validation in `__post_init__`

### New Engine Feature
- Core engine: Extend `src/engine/backtest.py` `BacktestEngine`
- Account feature: Extend `src/engine/account.py` `Account`
- Result metric: Add `@cached_property` to `src/engine/backtest.py` `BacktestResult`

### New Script
- Location: `scripts/{action}_{target}.py`
- Pattern: CLI with argparse, load config, execute operation
- Example: Follow `download_lof.py` or `generate_mock.py`

### Utilities/Helpers
- Shared helpers: Add to appropriate module or create new module in `src/`
- Data utilities: `src/data/` or `src/data/generator/`
- Math utilities: Consider `src/utils.py` (doesn't exist yet)

## Special Directories

### `.venv/`
- Purpose: Python virtual environment
- Generated: Yes (by user)
- Committed: No (gitignored)

### `data/`
- Purpose: All data files (mock and real)
- Generated: Yes (by scripts)
- Committed: No (gitignored)
- Structure:
  - `market/`: Parquet files named `{ticker}.parquet`
  - `nav/`: Parquet files named `{ticker}.parquet`
  - `config/`: `fees.csv`, `fund_status.db`

### `.cursor/`
- Purpose: Cursor IDE plans
- Generated: Yes
- Committed: No (typically)

### `.planning/`
- Purpose: GSD planning documents
- Generated: Yes
- Committed: Yes

---

*Structure analysis: 2025-02-06*
