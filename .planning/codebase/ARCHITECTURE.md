# Architecture

**Analysis Date:** 2025-02-06

## Pattern Overview

**Overall:** Configuration-Driven Layered Architecture with Pipeline Pattern

**Key Characteristics:**
- Layered architecture with clear separation of concerns
- Configuration-driven design (YAML-based)
- Pipeline pattern for backtest execution
- Plugin architecture for strategies (abstract base class)
- T+2 settlement simulation
- Hybrid storage model (Parquet + SQLite + CSV)

## Layers

### Configuration Layer
- Purpose: Centralize all backtest and data generation parameters
- Location: `src/config.py`, `src/data/generator/config.py`
- Contains: `BacktestConfig` dataclass, `MockConfig` dataclass
- Depends on: PyYAML for serialization
- Used by: BacktestEngine, MockDataGenerator, CLI scripts

**Pattern:** Dataclass with validation (`__post_init__`), YAML serialization via `from_yaml()` / `to_yaml()`

### Data Layer
- Purpose: Load, merge, and align data from multiple sources
- Location: `src/data/loader.py`
- Contains: `DataLoader` class
- Depends on: pandas, SQLite3, Parquet files
- Used by: BacktestEngine, CLI scripts

**Key Capabilities:**
- Loads market data (OHLCV) from Parquet files
- Loads NAV data from Parquet files
- Reads limit events from SQLite database
- Loads fee configuration from CSV
- Merges and aligns data by date
- Auto-discovers available tickers

### Strategy Layer
- Purpose: Abstract trading signal generation
- Location: `src/strategy/base.py`, `src/strategy/simple_lof.py`
- Contains: `BaseStrategy` (ABC), `Signal` dataclass, `SimpleLOFStrategy`
- Depends on: pandas, BacktestConfig
- Used by: BacktestEngine

**Pattern:** Abstract base class with `generate_signals()` method. Strategies receive market data row and positions, return list of `Signal` objects.

### Engine Layer
- Purpose: Execute backtests with proper settlement mechanics
- Location: `src/engine/backtest.py`, `src/engine/account.py`
- Contains: `BacktestEngine`, `Account`, `BacktestResult`
- Depends on: DataLayer, StrategyLayer, ConfigLayer
- Used by: CLI scripts, direct usage

**Key Capabilities:**
- T+2 settlement simulation
- Tiered subscription fee calculation
- Multi-ticker support with unified capital pool
- Performance metrics calculation (Sharpe, drawdown, etc.)

### Generator Layer
- Purpose: Generate mock data for testing
- Location: `src/data/generator/`
- Contains: `MockConfig`, `generate_mock_data()`, data generators
- Depends on: pandas, numpy
- Used by: `scripts/generate_mock.py`

## Data Flow

### Backtest Execution Flow:

1. **Configuration Load** (`BacktestConfig.from_yaml()`)
   - Load parameters from YAML file
   - Validate configuration values

2. **Data Loading** (`DataLoader.load_bundle()`)
   - Read market data (OHLCV) from `data/market/{ticker}.parquet`
   - Read NAV data from `data/nav/{ticker}.parquet`
   - Query limit events from `data/config/fund_status.db`
   - Load fees from `data/config/fees.csv`
   - Merge and align data by date
   - Calculate premium rate: `(close - nav) / nav`

3. **Backtest Loop** (`BacktestEngine.run()`)
   - For each trading day:
     a. Settle T+2 positions (`account.update_date()`)
     b. SELL Phase: Execute all sell signals (T+0 settlement)
     c. BUY Phase: Collect candidates, sort by premium_rate, buy greedily
     d. Record daily performance

4. **Result Calculation** (`BacktestResult`)
   - Calculate total return: `(end / start) - 1`
   - Calculate annualized return with geometric mean
   - Calculate max drawdown
   - Calculate Sharpe ratio

### Data Generation Flow:

1. **Configuration** (`MockConfig.from_yaml()`)
2. **NAV Generation**: Geometric Brownian Motion
3. **Premium Generation**: Normal distribution + spike events
4. **Market Data**: Derive OHLC from NAV and premium
5. **Limit Events**: Generate SQLite records based on thresholds
6. **Fee Config**: Generate CSV with tiered structure

## Key Abstractions

### Signal
- Purpose: Represents a trading signal
- Location: `src/strategy/base.py`
- Pattern: `@dataclass` with validation
- Fields: `action` ('buy'|'sell'), `ticker`, `amount`

### Account
- Purpose: Track cash, positions, and pending settlements
- Location: `src/engine/account.py`
- Pattern: Dataclass with business logic methods
- Key behaviors:
  - T+2 settlement via `PendingSettlement` queue
  - T+0 sell (cash immediately available)
  - T+2 buy (shares added to pending)

### DataBundle
- Purpose: Unified data for a single ticker
- Format: pandas DataFrame with columns:
  - `open`, `high`, `low`, `close`, `volume` (market)
  - `nav` (net asset value)
  - `premium_rate` (calculated)
  - `daily_limit` (from limit events)
- Metadata: Fee configuration attached via `df.attrs`

## Entry Points

### Main Entry: `run_backtest.py`
- CLI entry point for backtesting
- Loads config from YAML
- Auto-discovers tickers (supports `tickers: all`)
- Runs multi-ticker backtest
- Prints results and trade logs

### Data Generation: `scripts/generate_mock.py`
- Generates mock data for testing
- Uses YAML configuration
- Outputs Parquet + SQLite + CSV

### Real Data Download: `scripts/download_lof.py`
- Downloads real LOF data from JoinQuant API
- Handles authentication via `.env`
- Batches requests to avoid timeouts

### Data Inspection: `scripts/inspect_data.py`
- Visualizes data with Plotly
- Shows price vs NAV, premium rate, volume
- Highlights limit periods

## Error Handling

**Strategy:** Validation at boundaries + logging

**Patterns:**
- Configuration validation in `__post_init__` (raises `ValueError`)
- Data validation in DataLoader (raises `FileNotFoundError`)
- Trade execution validation in Account (raises `ValueError` for insufficient funds/shares)
- Graceful degradation (missing fee config → use defaults)

## Cross-Cutting Concerns

**Logging:** Python standard logging, configured in `run_backtest.py` to write to both file and console

**Validation:** Dataclass-level validation with descriptive error messages

**Configuration:** Centralized YAML-based configuration with defaults

**Data Storage:**
- Time-series data: Parquet (efficient, typed)
- Event data: SQLite (relational, queryable)
- Configuration: CSV (simple, readable)

---

*Architecture analysis: 2025-02-06*
