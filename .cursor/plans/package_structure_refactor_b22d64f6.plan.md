---
name: Package Structure Refactor
overview: Reorganize the flat project structure into a proper Python package layout with `lof_eins` as the main source package, separate `scripts/` for entry points, and `tests/` for test files. This requires creating new directories, moving files, updating import statements, and cleaning up old files.
todos:
  - id: create-package-dirs
    content: Create lof_eins/, scripts/, tests/ directories with __init__.py files
    status: completed
  - id: move-loader
    content: Move data_loader.py to lof_eins/data/loader.py
    status: completed
  - id: move-generator
    content: Move mock_data_generator/* to lof_eins/data/generator/
    status: completed
  - id: move-scripts
    content: Move run_generator.py and inspect_data.py to scripts/ with updated imports
    status: completed
  - id: move-tests
    content: Move test_data_loader.py to tests/test_loader.py with updated imports
    status: completed
  - id: cleanup
    content: Delete old files and mock_data_generator/ directory
    status: completed
---

# Package Structure Refactoring Plan

## Current vs Target Structure

```mermaid
flowchart LR
    subgraph current [Current Structure]
        A1[data_loader.py]
        A2[run_generator.py]
        A3[inspect_data.py]
        A4[test_data_loader.py]
        A5[mock_data_generator/]
    end
    subgraph target [Target Structure]
        B1[lof_eins/data/loader.py]
        B2[scripts/generate_mock.py]
        B3[scripts/inspect_data.py]
        B4[tests/test_loader.py]
        B5[lof_eins/data/generator/]
    end
    A1 --> B1
    A2 --> B2
    A3 --> B3
    A4 --> B4
    A5 --> B5
```

## Key Import Changes

| File | Old Import | New Import |

|------|------------|------------|

| `scripts/generate_mock.py` | `from mock_data_generator import ...` | `from lof_eins.data.generator import ...` |

| `tests/test_loader.py` | `from data_loader import DataLoader` | `from lof_eins.data.loader import DataLoader` |

## Implementation Steps

### 1. Create Package Structure

Create directories and `__init__.py` files:

- `lof_eins/__init__.py` - Package root, export version
- `lof_eins/data/__init__.py` - Export `DataLoader` and generator symbols
- `lof_eins/data/generator/__init__.py` - Same exports as old `mock_data_generator/__init__.py`
- `lof_eins/engine/__init__.py` - Empty placeholder for future use
- `scripts/` and `tests/` directories

### 2. Move and Update Source Files

- Move `data_loader.py` to `lof_eins/data/loader.py` (no import changes needed)
- Move `mock_data_generator/*.py` to `lof_eins/data/generator/` (relative imports stay the same)

### 3. Move and Update Script Files

- Move `run_generator.py` to `scripts/generate_mock.py` with updated imports
- Move `inspect_data.py` to `scripts/inspect_data.py` (no import changes, uses direct file paths)

### 4. Move Test Files

- Move `test_data_loader.py` to `tests/test_loader.py` with updated imports

### 5. Cleanup

Delete old files: `data_loader.py`, `run_generator.py`, `inspect_data.py`, `test_data_loader.py`, and entire `mock_data_generator/` directory