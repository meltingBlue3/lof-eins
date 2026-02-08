---
phase: quick-003
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [README.md]
autonomous: true

must_haves:
  truths:
    - "README reflects current project purpose: LOF purchase limit enhancement for backtesting"
    - "README documents the full project structure including new Phase 1-2 modules"
    - "README includes setup instructions for Ollama and new dependencies"
    - "README describes the announcement processing pipeline workflow"
  artifacts:
    - path: "README.md"
      provides: "Complete, up-to-date project documentation"
      contains: "purchase limit"
  key_links: []
---

<objective>
Update README.md to reflect the current state of the project after Phase 1 (Foundation) and Phase 2 (PDF Processing) completion.

Purpose: The existing README.md (900 lines) only documents the original backtesting system. It has no mention of the purchase limit enhancement project — the new database schema (announcement_parses, limit_event_log, updated limit_events), PDF text extraction (pdfplumber), LLM parsing (Ollama), announcement processing pipeline, or the new scripts (parse_announcements.py, download_announcements.py). The README needs a comprehensive rewrite to reflect what this project actually does now.

Output: Updated README.md that accurately documents the complete system.
</objective>

<execution_context>
@C:\Users\zhang\.config\opencode/get-shit-done/workflows/execute-plan.md
@C:\Users\zhang\.config\opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@README.md
@requirements.txt
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rewrite README.md to reflect full project state</name>
  <files>README.md</files>
  <action>
Rewrite README.md comprehensively. The README should be in Chinese (matching the existing style). Key structural changes:

**1. Updated 概述 (Overview)**
- Describe the project as a LOF fund arbitrage backtesting system WITH purchase limit enhancement
- Mention the core value: accurate purchase limit data from fund announcements enables reliable backtesting
- Note the project status: Phase 1 (Foundation) and Phase 2 (PDF Processing) complete, Phases 3-4 upcoming

**2. Updated 项目结构 (Project Structure)**
Update the file tree to reflect ALL current files:
```
lof-eins/
├── src/
│   ├── __init__.py
│   ├── config.py                    # BacktestConfig
│   ├── data/
│   │   ├── __init__.py
│   │   ├── loader.py                # DataLoader (supports NULL end_date)
│   │   ├── downloader.py            # RealDataDownloader (JoinQuant)
│   │   ├── announcement_downloader.py  # PDF downloader (Eastmoney)
│   │   ├── pdf_extractor.py         # PDF text extraction (pdfplumber)
│   │   ├── llm_client.py            # LLM parsing (Ollama API)
│   │   ├── announcement_processor.py   # Orchestration pipeline
│   │   └── generator/               # Mock data generator
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── generators.py
│   │       └── main.py
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── simple_lof.py
│   └── engine/
│       ├── __init__.py
│       ├── account.py
│       └── backtest.py
├── scripts/
│   ├── download_lof.py              # Download market/NAV data
│   ├── download_announcements.py    # Download announcement PDFs
│   ├── parse_announcements.py       # Parse PDFs via LLM (NEW)
│   ├── generate_mock.py             # Generate mock data
│   └── inspect_data.py              # Data visualization
├── tests/
│   ├── test_loader.py
│   ├── test_open_ended_limits.py
│   ├── test_database_schema.py
│   ├── test_pdf_extractor.py
│   ├── test_llm_client.py
│   └── test_announcement_processor.py
├── configs/
│   ├── backtest.yaml
│   └── mock.yaml
├── data/                            # Data directory (gitignored)
├── requirements.txt
├── run_backtest.py
└── TECHNICAL_PROPOSAL.md
```

**3. NEW section: 限购增强功能 (Purchase Limit Enhancement)**
Add a section explaining:
- The problem: downloaded PDFs aren't parsed, fund_status.db has no real limit data
- The solution: PDF extraction → LLM parsing → timeline integration → backtest
- The 4-phase plan with current progress
- The 3-table database schema:
  - `announcement_parses` — raw LLM extraction results
  - `limit_events` — integrated timeline (supports NULL end_date for open-ended limits)
  - `limit_event_log` — audit trail

**4. NEW section: 公告处理流程 (Announcement Processing Pipeline)**
Document the new workflow:
```
1. python scripts/download_announcements.py --ticker 161005
2. python scripts/parse_announcements.py --ticker 161005
3. (Phase 3: Timeline integration - coming soon)
4. python run_backtest.py
```
Include key technical details:
- Uses pdfplumber for Chinese PDF text extraction
- Uses Ollama (qwen2.5:7b) for LLM parsing
- Supports 4 announcement types: complete interval, open-start, end-only, modify
- Stores results in announcement_parses table with JSON parse_result

**5. Updated 依赖安装 (Dependencies)**
Update the dependency list to include new packages:
- pdfplumber >= 0.10.0 (PDF text extraction)
- requests >= 2.32.3 (HTTP client)
- ollama >= 0.4.0 (LLM API client)
Add Ollama setup instructions:
- Install Ollama from https://ollama.com
- Pull model: `ollama pull qwen2.5:7b`

**6. Keep existing sections that are still valid:**
- 回测引擎架构 (Backtest Engine Architecture) — keep as-is
- BacktestConfig 参数 — keep as-is
- SimpleLOFStrategy 逻辑 — keep as-is
- T+2 结算机制 — keep as-is
- 费率计算 — keep as-is
- DataLoader 使用 — update to mention NULL end_date support
- 配置文件管理 — keep as-is
- 数据格式 — keep as-is, add new tables
- 自定义策略 — keep as-is
- API 参考 — keep as-is

**7. Updated 数据库架构 (Database Schema)**
Add documentation for the new/updated tables:
- announcement_parses (columns: id, ticker, pdf_filename, extracted_text, parse_result JSON, confidence, parsed_at)
- limit_events updated (now with is_open_ended generated column, source_announcement_ids JSON, nullable end_date)
- limit_event_log (columns: id, ticker, operation, old_start/end_date, new_start/end_date, source, reason, logged_at)

**8. Updated 测试 (Tests)**
Document the test suite: 103+ tests across 6 test files, all passing.

**Important constraints:**
- Keep the README in Chinese (consistent with existing style)
- Keep all still-valid original sections — this is an UPDATE, not a delete-and-rewrite
- The original README is ~900 lines. The updated one should be similar length, not significantly longer. Consolidate/trim verbose sections (like the long mock data generation details) to make room for the new content.
- Use the same formatting style (mermaid diagrams, tables, code blocks)
  </action>
  <verify>
    - README.md exists and is well-formed markdown
    - Contains "限购" (purchase limit) in overview
    - Contains documentation for pdf_extractor, llm_client, announcement_processor
    - Contains Ollama setup instructions
    - Contains updated project structure tree
    - Contains new database schema documentation
    - Retains backtest engine documentation
  </verify>
  <done>
    README.md accurately reflects the full project: original backtesting system + purchase limit enhancement (Phases 1-2 complete, Phases 3-4 planned). A new developer reading this README would understand what the project does, how to set it up, and how to use both the backtesting and announcement processing features.
  </done>
</task>

</tasks>

<verification>
- README.md contains all major sections: overview, structure, setup, usage, architecture, database schema, tests
- New modules (pdf_extractor, llm_client, announcement_processor) are documented
- Ollama setup instructions are present
- Project structure tree matches actual files on disk
- Existing valid content (backtest engine, strategy, DataLoader) is preserved
</verification>

<success_criteria>
README.md is comprehensive, accurate, and reflects the current project state including Phase 1-2 deliverables.
</success_criteria>

<output>
After completion, create `.planning/quick/003-readme-md/003-SUMMARY.md`
</output>
