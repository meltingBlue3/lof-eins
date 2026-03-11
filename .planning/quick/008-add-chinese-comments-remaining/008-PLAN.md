---
phase: quick
plan: 008
type: execute
wave: 1
depends_on: []
files_modified:
  - app/app.py
  - app/utils.py
  - app/pages/1_data_explorer.py
  - app/pages/2_backtest.py
  - app/pages/3_backtest_results.py
  - tests/test_announcement_processor.py
  - tests/test_open_ended_limits.py
  - tests/test_architecture_fixes.py
  - tests/test_database_schema.py
  - tests/test_llm_client.py
  - tests/test_loader.py
  - tests/test_pdf_extractor.py
  - run_backtest.py
  - src/data/downloader.py
  - src/data/announcement_downloader.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "All missed files have bilingual (English + Chinese) comments"
    - "Code functionality unchanged (no logic modifications)"
    - "All modules import successfully"
  artifacts:
    - path: "app/**/*.py"
      provides: "Streamlit frontend with bilingual comments"
    - path: "tests/test_*.py"
      provides: "Test files with bilingual comments"
    - path: "run_backtest.py"
      provides: "CLI entry point with bilingual comments"
    - path: "src/data/downloader.py"
      provides: "LOF downloader with bilingual comments"
    - path: "src/data/announcement_downloader.py"
      provides: "Announcement downloader with bilingual comments"
  key_links:
    - from: "English comment"
      to: "Chinese translation"
      via: "bilingual format"
      pattern: "# English comment  # 中文注释"
---

<objective>
Add Chinese translations to English comments in files missed during quick-007.

Purpose: Complete bilingual documentation coverage for the entire codebase
Output: 15 files with bilingual (English + Chinese) comments
</objective>

<execution_context>
@C:/Users/zhang/.config/opencode/get-shit-done/workflows/execute-plan.md
@C:/Users/zhang/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/007-add-chinese-comments/007-PLAN.md

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

## Files Missed in quick-007

**Streamlit app (app/):**
- app/app.py - Main Streamlit application
- app/utils.py - Utility functions for the app
- app/pages/1_data_explorer.py - Data explorer page
- app/pages/2_backtest.py - Backtest configuration page
- app/pages/3_backtest_results.py - Backtest results page

**Tests (tests/):**
- test_announcement_processor.py - 21 tests for PDF processing
- test_open_ended_limits.py - 12 tests for open-ended limits
- test_architecture_fixes.py - Architecture validation tests
- test_database_schema.py - 47 tests for database schema
- test_llm_client.py - 35 tests for LLM client
- test_loader.py - 4 tests for data loader
- test_pdf_extractor.py - 9 tests for PDF extraction

**Root and src/data/:**
- run_backtest.py - Main backtest entry point
- src/data/downloader.py - LOF data downloader
- src/data/announcement_downloader.py - Announcement downloader
</context>

<tasks>

<task type="auto">
  <name>Add Chinese comments to app/ and root files</name>
  <files>
    app/app.py
    app/utils.py
    app/pages/1_data_explorer.py
    app/pages/2_backtest.py
    app/pages/3_backtest_results.py
    run_backtest.py
    src/data/downloader.py
    src/data/announcement_downloader.py
  </files>
  <action>
For each Python file, add Chinese translations to all English comments:

1. **Module docstrings**: Add Chinese translation after the English description
2. **Class docstrings**: Add Chinese translation summarizing the class purpose
3. **Method/function docstrings**: Add Chinese for Args, Returns, Raises sections
4. **Inline comments**: Append Chinese translation with `  # 中文` format
5. **Streamlit elements**: Add Chinese for st.title, st.header, st.write descriptions in comments

Translation guidelines:
- Use professional technical Chinese terminology
- Keep translations concise but accurate
- Preserve original English (bilingual, not replacement)
- Do NOT modify any code logic, only add comments
- For Streamlit UI text (st.title, st.header, etc.), do NOT translate - only translate code comments
  </action>
  <verify>
    <automated>python -c "import app.utils; print('app/ imports OK')" && python -c "import ast; ast.parse(open('run_backtest.py').read()); print('run_backtest.py parses OK')" && python -c "import src.data.downloader; import src.data.announcement_downloader; print('src/data/ imports OK')"</automated>
  </verify>
  <done>8 app/ and root files have bilingual comments and import/parse successfully</done>
</task>

<task type="auto">
  <name>Add Chinese comments to test files</name>
  <files>
    tests/test_announcement_processor.py
    tests/test_open_ended_limits.py
    tests/test_architecture_fixes.py
    tests/test_database_schema.py
    tests/test_llm_client.py
    tests/test_loader.py
    tests/test_pdf_extractor.py
  </files>
  <action>
For each test file, add Chinese translations to all English comments:

1. **Module docstrings**: Add Chinese translation describing the test suite purpose
2. **Class docstrings**: Add Chinese translation for test class purpose
3. **Test method docstrings**: Add Chinese for what each test validates
4. **Inline comments**: Append Chinese translation with `  # 中文` format
5. **Test case descriptions**: Add Chinese explanation in comments

Translation guidelines:
- Use professional technical Chinese terminology
- Keep translations concise but accurate
- Preserve original English (bilingual, not replacement)
- Do NOT modify any test logic, only add comments
- Test names (def test_xxx) remain in English - only translate comments
  </action>
  <verify>
    <automated>python -c "import ast; files = ['tests/test_announcement_processor.py', 'tests/test_open_ended_limits.py', 'tests/test_architecture_fixes.py', 'tests/test_database_schema.py', 'tests/test_llm_client.py', 'tests/test_loader.py', 'tests/test_pdf_extractor.py']; [ast.parse(open(f).read()) for f in files]; print('All 7 test files parse OK')"</automated>
  </verify>
  <done>7 test files have bilingual comments and parse successfully</done>
</task>

</tasks>

<verification>
1. All 15 missed files have bilingual comments
2. All modules import without errors (no syntax errors introduced)
3. No code logic was modified (only comments added)
4. Tests still pass after comment additions
</verification>

<success_criteria>
- [ ] All 5 app/ files have Chinese translations for English comments
- [ ] All 7 test files have Chinese translations for English comments
- [ ] run_backtest.py has Chinese translations
- [ ] src/data/downloader.py has Chinese translations
- [ ] src/data/announcement_downloader.py has Chinese translations
- [ ] All files parse without syntax errors
- [ ] All imports succeed
</success_criteria>

<output>
After completion, create `.planning/quick/008-add-chinese-comments-remaining/008-SUMMARY.md`
</output>
