# Testing Patterns

**Analysis Date:** 2025-02-06

## Test Framework

**Runner:**
- **Framework:** Standard Python `unittest` (evidenced by single test file structure)
- **No pytest.ini, tox.ini, or conftest.py found**
- Tests run directly: `python tests/test_loader.py`

**Assertion Library:**
- Uses manual verification with print statements, not assertions
- Pattern: Print `[OK]` or `[ERROR]` based on verification results

## Test File Organization

**Location:**
- **Root:** `tests/` directory at project root
- **Naming:** `test_{module_name}.py` pattern
- **Structure:** Single test file covering DataLoader verification

**Files:**
- `tests/test_loader.py` - Verification tests for DataLoader class

## Test Structure

**Suite Organization:**
Tests use procedural verification functions, not class-based test suites.

```python
def verify_dataloader():
    """Main test function."""
    # Setup
    loader = DataLoader(data_dir=DATA_DIR)
    
    # Execute
    df = loader.load_bundle(TICKER, start_date='2020-01-01', end_date='2025-01-01')
    
    # Verify
    print(f"[OK] Data loaded successfully! Shape: {df.shape}")
    
    # Run sub-verifications
    verify_limit_logic(df, TICKER)
    verify_fee_logic(df, TICKER)
    verify_premium_calc(df)
```

**Patterns:**
- Manual verification with print statements
- `[OK]` / `[ERROR]` / `[WARN]` status indicators
- Integration-style tests that verify data integrity across multiple components

## Verification Patterns

**Data Integrity Testing:**

```python
def verify_limit_logic(df, ticker):
    """Verify SQLite limit events correctly reflect in DataFrame."""
    # Query database directly
    conn = sqlite3.connect(db_path)
    event = pd.read_sql(f"SELECT * FROM limit_events WHERE ticker='{ticker}' LIMIT 1", conn)
    
    # Verify DataFrame reflects the limit
    mask = (df.index >= pd.to_datetime(start_str)) & (df.index <= pd.to_datetime(end_str))
    actual_limit = df.loc[mask].iloc[0]['daily_limit']
    
    if actual_limit == limit_amount:
        print(f"[OK] Verification passed!")
    else:
        print(f"[ERROR] Verification failed!")
```

**Calculation Verification:**

```python
def verify_premium_calc(df):
    """Verify premium rate calculation formula."""
    sample = df.iloc[10]
    calc_premium = (sample['close'] - sample['nav']) / sample['nav']
    
    if abs(calc_premium - sample['premium_rate']) < 1e-6:
        print(f"[OK] Calculation formula correct: {sample['premium_rate']:.4f}")
    else:
        print(f"[ERROR] Calculation formula wrong!")
```

## Test Data

**Mock Data:**
- Tests use generated mock data from `data/mock/`
- Configurable ticker: `TICKER = '161005'`
- Configurable data directory: `DATA_DIR = './data/mock'`

**Test Fixtures:**
- No formal fixture system
- Setup inline within test functions
- Database connections created per test function

## What to Test

**Integration Tests:**
- Data loading from multiple sources (Parquet, CSV, SQLite)
- Data alignment and merging
- Fee configuration loading
- Limit event resampling to daily series

**Calculation Tests:**
- Premium rate formula: `(close - nav) / nav`
- Fee tier calculations
- Date filtering and indexing

## What NOT to Test

**Missing Coverage:**
- Unit tests for individual methods
- Edge cases (empty data, invalid tickers)
- Error handling paths
- Strategy logic unit tests
- Account management unit tests
- Backtest engine unit tests

## Running Tests

**Command:**
```bash
# Run DataLoader verification
python tests/test_loader.py

# Expected output shows verification status for each component
[OK] Data loaded successfully! Shape: (262, 11)
[OK] Key columns check passed
--- 验证限购逻辑 (Event -> Series) ---
[OK] Verification passed! Date 2024-06-05 daily_limit = 100.0
[OK] Non-limit period verification passed (Limit = inf)
```

## Coverage

**Current State:**
- Single integration test file
- Focuses on DataLoader verification
- No formal coverage measurement configured

**Gaps:**
- No unit tests for `BacktestEngine`
- No unit tests for `Account` class
- No unit tests for strategy implementations
- No unit tests for `calculate_subscription_fee`
- No tests for `RealDataDownloader`
- No tests for data generators

## Testing Philosophy

**Observed Approach:**
- Manual verification scripts over automated assertions
- Integration testing over unit testing
- Data integrity verification over logic testing
- Print-based reporting over assertion-based

**Recommendations:**
1. Add pytest framework for structured testing
2. Convert verification functions to pytest test cases
3. Add unit tests for core calculation functions
4. Add edge case testing for boundary conditions
5. Add mock/stub tests for external dependencies (jqdatasdk)

---

*Testing analysis: 2025-02-06*
