---
phase: quick
plan: 007
type: execute
wave: 1
depends_on: []
files_modified:
  - src/data/llm_client.py
  - src/data/announcement_processor.py
  - src/data/pdf_extractor.py
  - src/data/loader.py
  - src/data/downloader.py
  - src/data/announcement_downloader.py
  - src/data/__init__.py
  - src/data/generator/generators.py
  - src/data/generator/main.py
  - src/data/generator/config.py
  - src/data/generator/__init__.py
  - src/engine/backtest.py
  - src/engine/account.py
  - src/engine/__init__.py
  - src/strategy/simple_lof.py
  - src/strategy/base.py
  - src/strategy/__init__.py
  - src/config.py
  - src/__init__.py
  - scripts/download_lof.py
  - scripts/inspect_data.py
  - scripts/parse_announcements.py
  - scripts/download_announcements.py
  - scripts/generate_mock.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "All English docstrings have Chinese translations"
    - "All inline English comments have Chinese translations"
    - "Code functionality unchanged (no logic modifications)"
  artifacts:
    - path: "src/**/*.py"
      provides: "Core source with bilingual comments"
    - path: "scripts/**/*.py"
      provides: "CLI tools with bilingual comments"
  key_links:
    - from: "English comment"
      to: "Chinese translation"
      via: "bilingual format"
      pattern: "# English comment  # 中文注释"
---

<objective>
Add Chinese translations to all English comments in the Python codebase.

Purpose: Improve code accessibility for Chinese-speaking developers
Output: All source files with bilingual (English + Chinese) comments
</objective>

<execution_context>
@C:/Users/zhang/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/zhang/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

## Comment Translation Format

For **inline comments**, use the format:
```python
# English comment  # 中文注释
```

For **docstrings**, add Chinese translation as a second paragraph or within the same docstring:
```python
"""
English description.

中文描述。
"""
```

Or for Google-style docstrings:
```python
"""
English description.

中文描述。

Args:
    arg1: English description / 中文描述
"""
```

## Files to Process

**Core data modules (src/data/):**
- llm_client.py - LLM client for PDF parsing
- announcement_processor.py - PDF processing orchestration
- pdf_extractor.py - PDF text extraction
- loader.py - Data loading utilities
- downloader.py - LOF data download
- announcement_downloader.py - Announcement download
- __init__.py - Package init

**Generator modules (src/data/generator/):**
- generators.py - Mock data generators
- main.py - Generator entry point
- config.py - Generator config
- __init__.py - Package init

**Engine modules (src/engine/):**
- backtest.py - Backtesting engine
- account.py - Account management
- __init__.py - Package init

**Strategy modules (src/strategy/):**
- simple_lof.py - Simple LOF strategy
- base.py - Strategy base class
- __init__.py - Package init

**Config and root:**
- src/config.py - Global configuration
- src/__init__.py - Package init

**Scripts (scripts/):**
- download_lof.py - LOF download CLI
- inspect_data.py - Data inspection CLI
- parse_announcements.py - PDF parsing CLI
- download_announcements.py - Announcement download CLI
- generate_mock.py - Mock data generation CLI

**Tests:** Skip (tests are typically kept in original language)
</context>

<tasks>

<task type="auto">
  <name>Add Chinese comments to src/ modules</name>
  <files>
    src/data/llm_client.py
    src/data/announcement_processor.py
    src/data/pdf_extractor.py
    src/data/loader.py
    src/data/downloader.py
    src/data/announcement_downloader.py
    src/data/__init__.py
    src/data/generator/generators.py
    src/data/generator/main.py
    src/data/generator/config.py
    src/data/generator/__init__.py
    src/engine/backtest.py
    src/engine/account.py
    src/engine/__init__.py
    src/strategy/simple_lof.py
    src/strategy/base.py
    src/strategy/__init__.py
    src/config.py
    src/__init__.py
  </files>
  <action>
For each Python file in src/, add Chinese translations to all English comments:

1. **Module docstrings**: Add Chinese translation after the English description
2. **Class docstrings**: Add Chinese translation summarizing the class purpose
3. **Method/function docstrings**: Add Chinese for Args, Returns, Raises sections
4. **Inline comments**: Append Chinese translation with `  # 中文` format
5. **Configuration constants**: Add Chinese explanation for each constant

Translation guidelines:
- Use professional technical Chinese terminology
- Keep translations concise but accurate
- Preserve original English (bilingual, not replacement)
- Do NOT modify any code logic, only add comments
  </action>
  <verify>
    <automated>python -c "import src.data.llm_client; import src.data.announcement_processor; import src.data.loader; import src.engine.backtest; import src.strategy.simple_lof; print('All imports OK')"</automated>
  </verify>
  <done>All src/ modules have bilingual comments and import successfully</done>
</task>

<task type="auto">
  <name>Add Chinese comments to scripts/ modules</name>
  <files>
    scripts/download_lof.py
    scripts/inspect_data.py
    scripts/parse_announcements.py
    scripts/download_announcements.py
    scripts/generate_mock.py
  </files>
  <action>
For each Python file in scripts/, add Chinese translations to all English comments:

1. **Module docstrings**: Add Chinese translation describing the script purpose
2. **Function docstrings**: Add Chinese for Args, Returns sections
3. **Inline comments**: Append Chinese translation with `  # 中文` format
4. **CLI argument descriptions**: Add Chinese for help text if applicable

Translation guidelines:
- Use professional technical Chinese terminology
- Keep translations concise but accurate
- Preserve original English (bilingual, not replacement)
- Do NOT modify any code logic, only add comments
  </action>
  <verify>
    <automated>python -c "import ast; [ast.parse(open(f).read()) for f in ['scripts/download_lof.py', 'scripts/inspect_data.py', 'scripts/parse_announcements.py', 'scripts/download_announcements.py', 'scripts/generate_mock.py']]; print('All scripts parse OK')"</automated>
  </verify>
  <done>All scripts/ modules have bilingual comments and parse successfully</done>
</task>

</tasks>

<verification>
1. All Python files in src/ and scripts/ have bilingual comments
2. All modules import without errors (no syntax errors introduced)
3. No code logic was modified (only comments added)
</verification>

<success_criteria>
- [ ] All 24 source files have Chinese translations for English comments
- [ ] All imports succeed (python -c "import src..." works)
- [ ] All scripts parse without syntax errors
- [ ] Code functionality unchanged (tests still pass)
</success_criteria>

<output>
After completion, create `.planning/quick/007-add-chinese-comments/007-SUMMARY.md`
</output>
