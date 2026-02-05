# Codebase Concerns

**Analysis Date:** 2026-02-06

## Tech Debt

**RealDataDownloader: Empty Exception Handling**
- Issue: Multiple `except Exception as e` blocks silently swallow errors and print warnings
- Files: `src/data/downloader.py` (lines 115-121, 131-153, 166-191)
- Impact: API failures are logged but not properly handled, could result in missing data without clear error
- Fix approach: Implement proper retry logic with exponential backoff, return error codes, or raise specific exceptions for caller handling

**AnnouncementDownloader: Raw SQL Query with String Interpolation**
- Issue: Uses f-string SQL interpolation in `verify_limit_logic()`: `pd.read_sql(f"SELECT * FROM limit_events WHERE ticker='{ticker}' LIMIT 1", conn)`
- Files: `tests/test_loader.py` (line 56)
- Impact: SQL injection risk, though currently only in test code
- Fix approach: Use parameterized queries consistently

**Hardcoded Default Tickers**
- Issue: Default ticker list duplicated in multiple places
- Files: `run_backtest.py` (line 60), `src/data/generator/config.py` (default value)
- Impact: Maintenance burden when defaults change
- Fix approach: Centralize defaults in config module

**Type Inconsistency in Fee Lookup**
- Issue: Fee lookup compares ticker as string against potentially int column: `self._fees_cache[self._fees_cache['ticker'] == str(ticker)]`
- Files: `src/data/loader.py` (line 151)
- Impact: Potential lookup failures if types don't match
- Fix approach: Ensure consistent type conversion at data load time

## Known Bugs

**T+2 Settlement Date Calculation Fallback**
- Issue: When current date not in trading calendar, falls back to `timedelta(days=2)` which doesn't account for weekends/holidays
- Files: `src/engine/account.py` (lines 199-212)
- Impact: Settlement dates may be off by 1-2 days when using real trading data with missing dates
- Trigger: When backtest includes dates not present in the data (e.g., holidays)
- Workaround: Ensure complete trading calendar data

**Float('inf') Comparison in DataFrame**
- Issue: `daily_limit` uses `float('inf')` for unlimited, but test checks for `-1` or `> 1e10` as alternatives
- Files: `src/data/loader.py` (line 184), `tests/test_loader.py` (line 92)
- Impact: Inconsistent handling of "unlimited" values across codebase
- Fix approach: Standardize on `float('inf')` and update tests accordingly

**Risk Mode 'infinite' Logic Inconsistency**
- Issue: Config validates `'infinite'` risk mode but engine may not fully support it
- Files: `src/config.py` (line 30), `src/engine/backtest.py` (line 534-538)
- Impact: Setting `risk_mode='infinite'` may not behave as expected

## Security Considerations

**Credentials in Environment Variables**
- Risk: JoinQuant credentials stored in plain text `.env` file
- Files: `.env`, `src/data/downloader.py` (lines 90-96)
- Current mitigation: `.env` is in `.gitignore`
- Recommendations: Document security best practices, consider credential rotation, add `.env.example` with dummy values

**Announcement Downloader: HTTP not HTTPS**
- Risk: PDF downloads use HTTP endpoint (`http://pdf.dfcfw.com/...`)
- Files: `src/data/announcement_downloader.py` (line 30)
- Current mitigation: None
- Recommendations: Upgrade to HTTPS if available, verify SSL certificates

**No Input Validation on Ticker Symbols**
- Risk: Ticker strings are used directly in file paths and SQL queries without sanitization
- Files: `src/data/loader.py`, `src/data/downloader.py`
- Current mitigation: Limited by file system permissions
- Recommendations: Add ticker format validation (e.g., regex for valid fund codes)

## Performance Bottlenecks

**Pandas DataFrame Copy Operations in Backtest Loop**
- Problem: `_load_multi_data()` creates copies of DataFrames and calculates rolling mean for each ticker
- Files: `src/engine/backtest.py` (lines 258-272)
- Cause: DataFrame operations in hot loop
- Improvement path: Pre-compute MA5 in data generation phase, use numpy arrays for calculations

**SQLite Query per Ticker in Backtest**
- Problem: Limit events queried from SQLite for each ticker during data loading
- Files: `src/data/loader.py` (lines 164-227)
- Cause: Individual SQL queries per ticker instead of batch loading
- Improvement path: Cache all limit events at DataLoader initialization, batch query with `WHERE ticker IN (...)`

**Announcement Downloader Sequential Processing**
- Problem: Downloads announcements fund-by-fund without parallelization
- Files: `src/data/announcement_downloader.py` (lines 259-285)
- Cause: Single-threaded loop over potentially hundreds of funds
- Improvement path: Implement async/concurrent downloads with `asyncio` or `concurrent.futures`

## Fragile Areas

**RealDataDownloader API Dependency**
- Files: `src/data/downloader.py`
- Why fragile: Relies on external JoinQuant API with rate limits, quota restrictions, and potential breaking changes
- Safe modification: Wrap all API calls in retry logic, cache responses, implement graceful degradation
- Test coverage: No automated tests for downloader (requires credentials)

**Fund Status Database Schema**
- Files: `src/data/generator/generators.py` (lines 206-215), `src/data/loader.py` (lines 190-228)
- Why fragile: SQLite schema created in multiple places, changes must be synchronized
- Safe modification: Centralize schema definition, use ORM or migration system
- Test coverage: Limited schema validation

**Premium Rate Calculation Assumptions**
- Files: `src/data/loader.py` (line 91), `src/data/generator/generators.py` (line 107)
- Why fragile: Assumes NAV and close price are aligned; doesn't handle missing values robustly
- Safe modification: Add data quality checks before calculation
- Test coverage: Tests exist but don't cover edge cases

## Scaling Limits

**DataLoader Memory Usage**
- Current capacity: Loads entire ticker history into memory
- Limit: System RAM constrains number of tickers that can be backtested simultaneously
- Scaling path: Implement chunked/lazy loading for large ticker universes

**SQLite Concurrent Access**
- Current capacity: Single-writer SQLite database for limit events
- Limit: Cannot parallelize data generation across multiple processes
- Scaling path: Use connection pooling, or migrate to PostgreSQL for multi-process writes

**Backtest Result Storage**
- Current capacity: Results stored in memory as DataFrames
- Limit: Very long backtests with many tickers could exhaust memory
- Scaling path: Stream results to disk, use Vaex or Polars for larger-than-memory datasets

## Dependencies at Risk

**jqdatasdk (JoinQuant SDK)**
- Risk: Proprietary SDK with version-specific API, no guarantees of backward compatibility
- Impact: Downloader could break with SDK updates
- Migration plan: Pin to specific version (`jqdatasdk==1.9.8` in `requirements.txt`), monitor for updates

**pandas (Version Not Pinned)**
- Risk: `pandas>=2.0.0` allows major version updates that may have breaking changes
- Impact: API changes in pandas 3.x could break code
- Migration plan: Pin to tested minor version, add compatibility layer for critical functions

## Missing Critical Features

**Real Limit Event Parsing**
- Problem: `RealDataDownloader._generate_limit_db()` creates empty database without actual limit events
- Blocks: Cannot backtest with real historical limit events
- Priority: High - essential for realistic backtests

**Redemption Fee Enforcement**
- Problem: `redeem_fee_7d` is loaded but never used in backtest engine
- Files: `src/data/loader.py` (line 117), `src/engine/backtest.py`
- Blocks: Accurate cost calculation for short-term trades
- Priority: Medium

**Comprehensive Unit Tests**
- Problem: Only one test file exists (`tests/test_loader.py`) and it's more of a validation script
- Blocks: Confidence in code changes, regression detection
- Priority: High

## Test Coverage Gaps

**Backtest Engine**
- What's not tested: All core logic in `BacktestEngine.run()`, `_execute_buy()`, `_execute_sell()`
- Files: `src/engine/backtest.py` (586 lines)
- Risk: Logic errors in trade execution could go unnoticed
- Priority: High

**Account T+2 Settlement**
- What's not tested: `Account._calculate_t2_date()`, `Account.update_date()` with edge cases
- Files: `src/engine/account.py` (lines 47-81, 186-212)
- Risk: Settlement timing errors
- Priority: High

**Fee Calculation**
- What's not tested: Tiered fee calculation logic
- Files: `src/engine/backtest.py` (lines 22-48)
- Risk: Incorrect transaction costs
- Priority: Medium

**Strategy Base Classes**
- What's not tested: `BaseStrategy.generate_signals()` interface compliance, `Signal` validation
- Files: `src/strategy/base.py`
- Risk: Custom strategies may not implement interface correctly
- Priority: Medium

**Data Generators**
- What's not tested: `NAVGenerator`, `PriceGenerator`, `FundStatusGenerator`
- Files: `src/data/generator/generators.py`
- Risk: Mock data may not represent real market conditions
- Priority: Low

---

*Concerns audit: 2026-02-06*
