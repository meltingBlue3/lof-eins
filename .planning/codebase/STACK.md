# Technology Stack

**Analysis Date:** 2026-02-06

## Languages

**Primary:**
- **Python 3.13.5** - All application code, backtesting engine, and data processing

**Secondary:**
- **YAML** - Configuration files (`configs/backtest.yaml`, `configs/mock.yaml`)
- **SQL** - SQLite queries for fund status database (`src/data/loader.py`, `scripts/download_lof.py`)

## Runtime

**Environment:**
- Python 3.13.5
- Virtual environment: `.venv/` (present but not required)

**Package Manager:**
- pip (standard Python package manager)
- Lockfile: Not present (no `requirements.lock` or `Pipfile.lock`)

## Frameworks

**Core:**
- **pandas 2.x** - Data manipulation and analysis, primary data structure for market data
- **numpy 1.26.4** - Numerical computations, random number generation for mock data
- **pyarrow >=14.0.0** - Parquet file I/O for efficient columnar data storage

**Configuration:**
- **PyYAML >=6.0** - YAML configuration parsing (`src/config.py`, `src/data/generator/config.py`)
- **python-dotenv >=1.0.0** - Environment variable loading from `.env` file

**External Data:**
- **jqdatasdk 1.9.8** - JoinQuant API SDK for downloading real LOF market data (optional)

**Visualization:**
- **plotly >=5.0.0** - Interactive charts for data inspection (`scripts/inspect_data.py`)

**Build/Dev:**
- **ruff** - Python linter and formatter (cache directory `.ruff_cache/` exists)
- No formal test framework configured (tests use basic assertions)

## Key Dependencies

**Critical:**
- `pandas` - Core data structure for all market data, backtest results, and trade logs
- `numpy` - Statistical calculations, random walks for mock NAV generation
- `pyarrow` - Parquet file format for efficient storage of OHLCV and NAV data
- `sqlite3` (stdlib) - Fund purchase limit events database

**Infrastructure:**
- `jqdatasdk` - External market data provider integration (JoinQuant)
- `python-dotenv` - Secure credential management
- `yaml` - Human-readable configuration files

## Configuration

**Environment:**
- Configuration via `.env` file in project root
- Required variables:
  - `JQ_USERNAME` - JoinQuant API username
  - `JQ_PASSWORD` - JoinQuant API password
- Example file: `.env.example`

**Application:**
- Backtest config: `configs/backtest.yaml`
- Mock data config: `configs/mock.yaml`
- Config classes:
  - `src/config.py` - `BacktestConfig` dataclass
  - `src/data/generator/config.py` - `MockConfig` dataclass

**Build:**
- No formal build step (Python interpreted)
- No `setup.py`, `pyproject.toml`, or `setup.cfg` found

## Platform Requirements

**Development:**
- Python 3.11+
- pip package manager
- Git for version control

**Production:**
- Local execution only (no server deployment)
- Data storage: Local filesystem (Parquet + SQLite + CSV)
- Optional: JoinQuant API access for real data downloads

---

*Stack analysis: 2026-02-06*
