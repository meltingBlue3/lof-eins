# External Integrations

**Analysis Date:** 2026-02-06

## APIs & External Services

**JoinQuant (聚宽):**
- **Purpose:** Primary data source for real LOF fund market data and NAV
- **SDK:** `jqdatasdk==1.9.8`
- **Auth:** Environment variables `JQ_USERNAME` and `JQ_PASSWORD` (loaded via `python-dotenv` from `.env` file)
- **Usage locations:**
  - `scripts/download_lof.py` - Standalone download script
  - `src/data/downloader.py` - `RealDataDownloader` class
- **APIs used:**
  - `jq.auth()` - Authentication
  - `jq.get_all_securities()` - List all LOF funds
  - `jq.get_price()` - OHLCV market data
  - `finance.run_query()` - NAV/fundamental data
  - `jq.get_query_count()` - API quota monitoring
- **Rate limits:** Batch size 50 (configurable) to avoid timeouts

## Data Storage

**Databases:**
- **SQLite** - Fund purchase limit events and fund status
  - Location: `data/{source}/config/fund_status.db`
  - Schema: `limit_events` table with columns: `id`, `ticker`, `start_date`, `end_date`, `max_amount`, `reason`
  - Connection: Direct `sqlite3` standard library (no ORM)
  - Access: `src/data/loader.py` `_resample_limits_to_daily()` method

**File Storage:**
- **Parquet** - Primary format for time-series data (market OHLCV, NAV)
  - Structure: `data/{source}/market/{ticker}.parquet`, `data/{source}/nav/{ticker}.parquet`
  - Library: `pyarrow`
  - Access: `src/data/loader.py` via `pd.read_parquet()`
- **CSV** - Fee configuration
  - Location: `data/{source}/config/fees.csv`
  - Columns: `ticker`, `fee_rate_tier_1`, `fee_limit_1`, `fee_rate_tier_2`, `fee_limit_2`, `fee_fixed`, `redeem_fee_7d`
  - Access: `src/data/loader.py` `load_fees()` method

**Caching:**
- In-memory DataFrame caching for fees (`_fees_cache` in `DataLoader`)
- No external caching service (Redis, etc.)

## Authentication & Identity

**Auth Provider:**
- **JoinQuant API** - External authentication only
- **Implementation:**
  - Environment-based credentials (`.env` file)
  - Class: `src/data/downloader.py` `RealDataDownloader.authenticate()`
  - Script: `scripts/download_lof.py` loads from `JQ_USERNAME`/`JQ_PASSWORD` env vars
- **No user authentication** for the backtesting system itself (local tool)

## Monitoring & Observability

**Error Tracking:**
- **None** - No Sentry, Rollbar, or similar service
- Errors logged to console and `backtest_execution.log` file

**Logs:**
- **File logging:** `backtest_execution.log` (created by `run_backtest.py`)
- **Format:** `%(asctime)s - %(levelname)s - %(message)s`
- **Console output:** All scripts print progress to stdout
- **Levels:** INFO and above

## CI/CD & Deployment

**Hosting:**
- **None** - Local execution only
- No Docker, no cloud deployment

**CI Pipeline:**
- **None** - No GitHub Actions, Jenkins, or similar

## Environment Configuration

**Required env vars:**
- `JQ_USERNAME` - JoinQuant account username
- `JQ_PASSWORD` - JoinQuant account password
- Both read from `.env` file via `python-dotenv`

**Secrets location:**
- `.env` file (gitignored, see `.gitignore` line 40)
- Example template: `.env.example`
- **WARNING:** Actual credentials present in `.env` (should not be committed)

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Data Flow Architecture

**Download Flow:**
```
JoinQuant API → jqdatasdk → pandas DataFrame → parquet/csv/sqlite → local filesystem
```

**Backtest Flow:**
```
local filesystem (parquet/csv/sqlite) → DataLoader → pandas DataFrame → BacktestEngine
```

**Key Integration Points:**
1. `src/data/downloader.py` - JoinQuant API integration
2. `scripts/download_lof.py` - CLI wrapper for downloading
3. `src/data/loader.py` - Unified data loading from local storage

## Offline Capability

**Fully offline capable** after initial data download:
- Mock data generation requires no external services
- Backtesting runs entirely on local Parquet/SQLite files
- JoinQuant only needed for downloading real historical data

---

*Integration audit: 2026-02-06*
