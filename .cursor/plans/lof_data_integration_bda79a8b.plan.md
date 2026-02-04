---
name: LOF Data Integration
overview: Integrate the JoinQuant real data downloader into the project and add auto-discovery of available LOF tickers to eliminate the need for explicit ticker lists in configuration.
todos:
  - id: create-downloader
    content: Create src/data/downloader.py with refactored RealDataDownloader class
    status: completed
  - id: enhance-loader
    content: Add list_available_tickers() method to DataLoader
    status: completed
    dependencies:
      - create-downloader
  - id: update-exports
    content: Update src/data/__init__.py to export new classes
    status: completed
  - id: update-config
    content: "Update backtest.yaml with data_dir and tickers: all support"
    status: completed
  - id: update-runner
    content: Modify run_backtest.py to handle data_dir and auto-discovery
    status: completed
    dependencies:
      - enhance-loader
      - update-config
---

# LOF Real Data Integration Plan

## Goals

- Integrate `eins.py` as a proper module under `src/data/`
- Support auto-discovery of tickers from data directory
- Allow config to specify `tickers: all` instead of explicit lists
- Make data source (mock/real) configurable

---

## Implementation

### 1. Create Downloader Module

Move `eins.py` logic to [`src/data/downloader.py`](src/data/downloader.py):

- Refactor `RealDataDownloader` class with cleaner interface
- Move credentials and constants to config or environment variables
- Keep the same output structure (compatible with `DataLoader`)

### 2. Enhance DataLoader with Ticker Discovery

Add method to [`src/data/loader.py`](src/data/loader.py):

```python
def list_available_tickers(self) -> List[str]:
    """Discover all tickers available in the data directory."""
    market_dir = self.data_dir / 'market'
    return [f.stem for f in market_dir.glob('*.parquet')]
```

### 3. Update Configuration Schema

Modify [`configs/backtest.yaml`](configs/backtest.yaml):

```yaml
# Data source path (relative or absolute)
data_dir: ./data/real_all_lof

# Tickers: explicit list, or "all" to auto-discover
tickers: all
# Or with filters:
# tickers:
#   mode: all
#   exclude: ["502010", "502011"]
```

### 4. Update Run Script

Modify [`run_backtest.py`](run_backtest.py) to:

- Read `data_dir` from config
- Pass `data_dir` to `DataLoader`
- Handle `tickers: all` by calling `loader.list_available_tickers()`

---

## Data Flow Diagram

```mermaid
flowchart TB
    subgraph download [Download Phase]
        JQ[JoinQuant API]
        DL[downloader.py]
        JQ --> DL
        DL --> MarketData[market/*.parquet]
        DL --> NAVData[nav/*.parquet]
        DL --> Config[config/fees.csv]
    end
    
    subgraph backtest [Backtest Phase]
        YAML[backtest.yaml]
        Runner[run_backtest.py]
        Loader[DataLoader]
        Engine[BacktestEngine]
        
        YAML -->|data_dir, tickers| Runner
        Runner --> Loader
        Loader -->|list_available_tickers| Runner
        MarketData --> Loader
        NAVData --> Loader
        Config --> Loader
        Loader --> Engine
    end
```

---

## File Changes Summary

| File | Change |

|------|--------|

| `src/data/downloader.py` | New file - refactored from `eins.py` |

| `src/data/loader.py` | Add `list_available_tickers()` method |

| `src/data/__init__.py` | Export `RealDataDownloader` |

| `configs/backtest.yaml` | Add `data_dir` option, support `tickers: all` |

| `run_backtest.py` | Handle `data_dir` and auto-discovery |

| `eins.py` | Can be deleted or kept as CLI wrapper |