---
phase: quick
plan: 002
type: execute
wave: 1
depends_on: []
files_modified:
  - src/data/llm_client.py
  - src/data/announcement_processor.py
  - tests/test_llm_client.py
  - tests/test_announcement_processor.py
autonomous: true

must_haves:
  truths:
    - "LLM returns multiple records for announcements with non-consecutive limit dates"
    - "LLM only extracts info for the current ticker, ignoring other tickers mentioned"
    - "parse_announcement() returns List[Dict] instead of Dict"
    - "AnnouncementProcessor stores list of records as JSON in parse_result column"
    - "All existing tests updated and passing with new return type"
  artifacts:
    - path: "src/data/llm_client.py"
      provides: "Updated prompt, parse_announcement returns List[Dict]"
      contains: "List[Dict]"
    - path: "src/data/announcement_processor.py"
      provides: "Handles list output from LLM client"
    - path: "tests/test_llm_client.py"
      provides: "Tests for multi-date, multi-ticker, and updated return type"
    - path: "tests/test_announcement_processor.py"
      provides: "Updated tests for list-based parse results"
  key_links:
    - from: "src/data/llm_client.py"
      to: "src/data/announcement_processor.py"
      via: "parse_announcement() return type List[Dict]"
      pattern: "parse_announcement.*List"
---

<objective>
Enhance LLM PDF parsing to support multiple non-consecutive limit dates per announcement and restrict output to the current ticker only.

Purpose: Real PDFs contain announcements with multiple non-consecutive dates (e.g., "4月18日, 4月21日, 7月1日") and multi-ticker references. Current code returns a single Dict; need List[Dict] with one record per date/range, filtered to current ticker only.

Output: Updated llm_client.py (prompt + return type), updated announcement_processor.py (handles list), updated tests.
</objective>

<execution_context>
@C:\Users\zhang\.config\opencode/get-shit-done/workflows/execute-plan.md
@C:\Users\zhang\.config\opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@src/data/llm_client.py
@src/data/announcement_processor.py
@tests/test_llm_client.py
@tests/test_announcement_processor.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update LLM client — prompt, return type, and cleaning logic</name>
  <files>src/data/llm_client.py</files>
  <action>
**1. Update SYSTEM_PROMPT** to instruct the LLM to return a JSON **array** of records:

- Change output schema from single JSON object to JSON array. Each element has the same fields as before: `ticker`, `limit_amount`, `start_date`, `end_date`, `announcement_type`, `is_purchase_limit_announcement`, `confidence`.
- Add instruction: "You are parsing an announcement that belongs to ticker `{ticker}`. Only extract purchase limit information for THIS ticker. If the announcement mentions other tickers, ignore them completely."
- The `{ticker}` placeholder will be filled dynamically (see `_build_prompt` changes below).
- Add instruction for multi-date handling: "If the announcement specifies multiple non-consecutive dates (e.g., '4月18日、4月21日、7月1日'), create a SEPARATE record for each date or consecutive date range. Consecutive dates (e.g., '12月25日、26日') should be merged into one record with start_date and end_date."
- Add few-shot example for multi-date case:
  ```
  Example 4 (Multiple non-consecutive dates):
  Input: "南方中证500ETF联接基金(LOF)(160119)自2024年4月18日、4月21日、7月1日起暂停大额申购，单日限额100元。"
  Output:
  [
    {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-04-18", "end_date": "2024-04-18", "announcement_type": "complete", "is_purchase_limit_announcement": true, "confidence": 0.90},
    {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-04-21", "end_date": "2024-04-21", "announcement_type": "complete", "is_purchase_limit_announcement": true, "confidence": 0.90},
    {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-07-01", "end_date": "2024-07-01", "announcement_type": "complete", "is_purchase_limit_announcement": true, "confidence": 0.90}
  ]
  ```
- Add few-shot example for multi-ticker case:
  ```
  Example 5 (Multi-ticker — extract only the specified ticker):
  Input (ticker=160127): "南方消费活力灵活配置混合型证券投资基金(160127)及南方中证互联网指数分级证券投资基金(160142)暂停大额申购，限额1000元，自2024年3月1日起。"
  Output:
  [
    {"ticker": "160127", "limit_amount": 1000.0, "start_date": "2024-03-01", "end_date": null, "announcement_type": "complete", "is_purchase_limit_announcement": true, "confidence": 0.92}
  ]
  ```
- Update existing examples 1-3 to wrap their output in arrays (single-element arrays).
- Change final instruction to "Return ONLY the JSON array, no additional explanation."

**2. Make SYSTEM_PROMPT a template** — Change `SYSTEM_PROMPT` from a plain string to a string with `{ticker}` placeholder. Create a method `_build_system_prompt(self, ticker: str) -> str` that fills the placeholder. If ticker is None/empty, omit the ticker-filtering instruction.

**3. Update `_build_prompt()`** to accept optional `ticker` parameter (for backward compat) and incorporate it.

**4. Update `_extract_json_from_response()`** to handle JSON arrays:
- After stripping think tokens and code blocks, try `json.loads()` — if result is a list, return it.
- Add bracket matching alongside existing brace matching: if text starts with `[`, find matching `]`.
- If a single JSON object `{...}` is found (LLM didn't follow array instruction), wrap it in a list automatically.

**5. Update `_clean_output()`** to accept either a single dict OR a list of dicts:
- Rename current `_clean_output` to `_clean_single_record(self, raw: Dict) -> Dict` (same logic).
- Create new `_clean_output(self, raw: Any) -> List[Dict]` that:
  - If `raw` is a list: call `_clean_single_record` on each element, return list.
  - If `raw` is a dict: call `_clean_single_record`, return `[result]`.
  - If `raw` is anything else: return a list with one default error record.

**6. Update `parse_announcement()` signature and logic:**
- Add `ticker: Optional[str] = None` parameter.
- Return type: `List[Dict[str, Any]]` instead of `Dict[str, Any]`.
- Empty text: return `[{...error dict...}]` (list with one error record).
- Build system prompt using `_build_system_prompt(ticker)`.
- Update user message to include ticker hint: `"你正在解析基金代码 {ticker} 的公告。文档内容如下：\n{text}"` (if ticker provided).
- JSON extraction: use updated `_extract_json_from_response` that returns the raw string, then `json.loads` it — the result may be a list or dict.
- Cleaning: pass parsed result to updated `_clean_output()` which returns `List[Dict]`.
- Error paths: all return `[{...error dict...}]` instead of `{...error dict...}`.
- Update log messages to indicate number of records returned.

**7. Update convenience function `parse_announcement()`:**
- Add `ticker: Optional[str] = None` as explicit parameter.
- Pass ticker to `client.parse_announcement(text, ticker=ticker)`.
- Return type: `List[Dict[str, Any]]`.

**8. Update `__main__` block:**
- Accept optional `--ticker` argument.
- Pass ticker to parse_announcement.
- Print result as JSON array.

**Type import updates:** Add `List` to imports from typing. Change return type annotations throughout.
  </action>
  <verify>
  Run `python -c "from src.data.llm_client import LLMClient; c = LLMClient(); print(type(c._clean_output({'ticker': '161005', 'is_purchase_limit_announcement': True, 'confidence': 0.9})))"` — should print `<class 'list'>`.

  Run `python -c "from src.data.llm_client import LLMClient; c = LLMClient(); print(c._clean_output([{'ticker': '161005', 'confidence': 0.9}, {'ticker': '161005', 'confidence': 0.8}]))"` — should print list of 2 cleaned dicts.
  </verify>
  <done>
  - SYSTEM_PROMPT is a template with {ticker} placeholder and multi-date/multi-ticker instructions + examples
  - parse_announcement() accepts ticker parameter and returns List[Dict]
  - _extract_json_from_response handles both JSON arrays and objects
  - _clean_output handles both list and dict input, always returns List[Dict]
  - All error paths return List[Dict] (single-element list with error record)
  - Convenience function updated with ticker parameter
  </done>
</task>

<task type="auto">
  <name>Task 2: Update announcement processor to handle List[Dict] from LLM</name>
  <files>src/data/announcement_processor.py</files>
  <action>
**1. Update `process_pdf()` method:**
- Pass `ticker` to `self.llm_client.parse_announcement(extracted_text, ticker=ticker)`.
- `parse_result` is now `List[Dict]`. Store it as-is.
- Check for errors: if any record in the list has an `error` key, treat as error (use first error found).
- `is_limit_announcement`: True if ANY record in the list has `is_purchase_limit_announcement: True`.
- `result["parse_result"]` stores the full list.

**2. Update `_save_parse_result()` method:**
- `parse_result` parameter is now `List[Dict]` (or could still be a single dict for backward compat — handle both).
- Serialize the entire list as JSON into the `parse_result` column (one DB row per PDF, the JSON blob is now an array).
- For `parse_type` column: use the first record's `announcement_type` (or the first non-null one).
- For `confidence` column: use the **minimum** confidence across all records (conservative).
- This avoids any DB schema changes — the `parse_result` column just stores `[{...}, {...}]` instead of `{...}`.

**3. Update `process_pdf` log messages** to indicate number of records parsed (e.g., "Parsed 3 records from announcement").

**4. Update convenience functions** `process_pdf()` and `process_ticker()` — no signature changes needed since ticker is already passed through.
  </action>
  <verify>
  Run `python -c "from src.data.announcement_processor import AnnouncementProcessor; print('import ok')"` — should succeed.
  </verify>
  <done>
  - process_pdf passes ticker to LLM client
  - _save_parse_result stores List[Dict] as JSON array in parse_result column
  - parse_type uses first non-null announcement_type from list
  - confidence uses minimum confidence from list
  - No DB schema changes required
  </done>
</task>

<task type="auto">
  <name>Task 3: Update all tests for List[Dict] return type</name>
  <files>tests/test_llm_client.py, tests/test_announcement_processor.py</files>
  <action>
**A. Update `tests/test_llm_client.py`:**

1. **Update `_make_chat_response` helper** — no changes needed (it just wraps content).

2. **Update `setUp`** — `self.mock_json` should be a JSON **array** wrapping the existing dict:
   ```python
   self.mock_json = json.dumps([{
       "ticker": "161005",
       "limit_amount": 100.0,
       ...existing fields...
   }])
   ```

3. **Update ALL existing test assertions** that check `result["ticker"]`, `result["limit_amount"]`, etc.:
   - `result` is now a `List[Dict]`. Change assertions to check `result[0]["ticker"]`, `result[0]["limit_amount"]`, etc.
   - For tests checking `result["error"]`: error results are now `[{...error dict...}]`, so check `result[0]["error"]`.
   - Tests to update:
     - `test_parse_announcement_success` — check `result[0]` for all fields
     - `test_parse_announcement_not_limit` — check `result[0]`
     - `test_parse_announcement_connection_error` — check `result[0]["error"]`
     - `test_parse_announcement_timeout` — check `result[0]["error"]`
     - `test_parse_announcement_invalid_json` — check `result[0]["error"]`
     - `test_parse_announcement_open_start` — check `result[0]`
     - `test_parse_announcement_end_only` — check `result[0]`
     - `test_parse_announcement_modify` — check `result[0]`
     - `test_empty_text` — check `result[0]["error"]`
     - `test_whitespace_text` — check `result[0]["error"]`
     - `test_convenience_function` — check `result[0]`
     - `test_json_with_code_blocks` — check `result[0]`
     - `test_thinking_tokens_stripped` — check `result[0]`
     - `test_thinking_tokens_with_code_blocks` — check `result[0]`
     - `test_ollama_response_error` — check `result[0]`
   - Also verify `isinstance(result, list)` and `len(result) == 1` for single-record tests.

4. **Update `test_clean_output`** — `_clean_output` now returns `List[Dict]`. Adjust assertions:
   - `cleaned = self.client._clean_output(raw)` → `cleaned` is now a list, check `cleaned[0]`.
   - Add test for list input: `self.client._clean_output([raw1, raw2])` → verify 2 cleaned dicts.

5. **Update `test_extract_json_from_response_static`** — Add test cases for JSON arrays:
   - Plain JSON array: `'[{"key": "value"}]'`
   - JSON array in code block
   - Single JSON object still works (will be wrapped by _clean_output)

6. **Add NEW test: `test_parse_announcement_multi_date`:**
   ```python
   def test_parse_announcement_multi_date(self):
       """Test parsing announcement with multiple non-consecutive dates."""
       multi_date_json = json.dumps([
           {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-04-18", "end_date": "2024-04-18", "announcement_type": "complete", "is_purchase_limit_announcement": True, "confidence": 0.90},
           {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-04-21", "end_date": "2024-04-21", "announcement_type": "complete", "is_purchase_limit_announcement": True, "confidence": 0.90},
           {"ticker": "160119", "limit_amount": 100.0, "start_date": "2024-07-01", "end_date": "2024-07-01", "announcement_type": "complete", "is_purchase_limit_announcement": True, "confidence": 0.90},
       ])
       with patch.object(self.client._client, "chat") as mock_chat:
           mock_chat.return_value = _make_chat_response(multi_date_json)
           result = self.client.parse_announcement("Multi date text", ticker="160119")
           self.assertIsInstance(result, list)
           self.assertEqual(len(result), 3)
           self.assertEqual(result[0]["start_date"], "2024-04-18")
           self.assertEqual(result[1]["start_date"], "2024-04-21")
           self.assertEqual(result[2]["start_date"], "2024-07-01")
   ```

7. **Add NEW test: `test_parse_announcement_single_ticker_filter`:**
   ```python
   def test_parse_announcement_single_ticker_filter(self):
       """Test that ticker parameter is passed to prompt."""
       with patch.object(self.client._client, "chat") as mock_chat:
           mock_chat.return_value = _make_chat_response(json.dumps([{
               "ticker": "160127", "limit_amount": 1000.0,
               "start_date": "2024-03-01", "end_date": None,
               "announcement_type": "complete",
               "is_purchase_limit_announcement": True, "confidence": 0.92
           }]))
           result = self.client.parse_announcement("Multi ticker text", ticker="160127")
           # Verify ticker was included in the system message
           call_args = mock_chat.call_args
           messages = call_args[1].get("messages") or call_args[0][0] if call_args[0] else call_args[1]["messages"]
           system_msg = messages[0]["content"]
           self.assertIn("160127", system_msg)
           # Verify result only contains our ticker
           self.assertEqual(len(result), 1)
           self.assertEqual(result[0]["ticker"], "160127")
   ```

8. **Add NEW test: `test_clean_output_wraps_single_dict`:**
   ```python
   def test_clean_output_wraps_single_dict(self):
       """Test that _clean_output wraps a single dict in a list."""
       raw = {"ticker": "161005", "confidence": 0.9, "is_purchase_limit_announcement": True}
       cleaned = self.client._clean_output(raw)
       self.assertIsInstance(cleaned, list)
       self.assertEqual(len(cleaned), 1)
       self.assertEqual(cleaned[0]["ticker"], "161005")
   ```

9. **Update integration tests** (TestLLMClientIntegration) — update assertions to handle list return type.

**B. Update `tests/test_announcement_processor.py`:**

1. **Update mock LLM returns** — all `self.mock_llm_client.parse_announcement.return_value` should be wrapped in lists:
   - `test_process_pdf_success`: wrap in `[{...}]`
   - `test_process_pdf_not_limit_announcement`: wrap in `[{...}]`
   - `test_process_ticker_batch`: wrap in `[{...}]`
   - `test_error_handling_continues_processing`: wrap in `[{...}]`
   - `test_parse_result_with_error_field`: wrap in `[{...}]`

2. **Update `test_process_pdf_success` DB verification:**
   - `parse_result = json.loads(entry[4])` now returns a list. Check `parse_result[0]["limit_amount"]`.
   - Or check that it's a valid JSON array.

3. **Update `test_process_pdf_not_limit_announcement` DB verification:**
   - Same pattern: `parse_result` in DB is now a JSON array.

4. **Update `test_database_insertion_format` assertions** to handle list JSON.

5. **Update `test_parse_result_with_error_field`:**
   - DB `parse_result` is now a JSON array.

6. **Add NEW test: `test_process_pdf_multi_record`:**
   ```python
   def test_process_pdf_multi_record(self, mock_extract):
       """Test processing PDF that yields multiple records."""
       mock_extract.return_value = {"success": True, "text": "multi date text", "pages": 1, "error": None}
       self.mock_llm_client.parse_announcement.return_value = [
           {"ticker": "161005", "limit_amount": 100.0, "start_date": "2024-04-18", "end_date": "2024-04-18", "announcement_type": "complete", "is_purchase_limit_announcement": True, "confidence": 0.90},
           {"ticker": "161005", "limit_amount": 100.0, "start_date": "2024-07-01", "end_date": "2024-07-01", "announcement_type": "complete", "is_purchase_limit_announcement": True, "confidence": 0.85},
       ]
       pdf_path = self.ticker_dir / "2024-01-15_限购公告.pdf"
       result = self.processor.process_pdf("161005", pdf_path)
       self.assertTrue(result["success"])
       self.assertTrue(result["is_limit_announcement"])
       # Verify DB stores the array
       entries = self._get_db_entries("161005")
       self.assertEqual(len(entries), 1)  # Still one row per PDF
       parse_result = json.loads(entries[0][4])
       self.assertIsInstance(parse_result, list)
       self.assertEqual(len(parse_result), 2)
       # Confidence should be minimum
       self.assertEqual(entries[0][6], 0.85)
   ```

7. **Verify `parse_announcement` is called with `ticker` kwarg** in `test_process_pdf_success`:
   ```python
   self.mock_llm_client.parse_announcement.assert_called_once_with(
       "测试公告内容：限购金额100元，从2024-01-15开始", ticker="161005"
   )
   ```
  </action>
  <verify>
  Run `python -m pytest tests/test_llm_client.py tests/test_announcement_processor.py -v` — all tests pass.
  </verify>
  <done>
  - All 17 existing LLM client tests updated for List[Dict] return type
  - All 12 existing processor tests updated for list-based parse results
  - 3+ new tests added: multi-date, single-ticker filter, clean_output wraps dict, multi-record processing
  - All tests pass with `python -m pytest`
  </done>
</task>

</tasks>

<verification>
1. `python -m pytest tests/test_llm_client.py -v` — all tests pass
2. `python -m pytest tests/test_announcement_processor.py -v` — all tests pass
3. `python -c "from src.data.llm_client import LLMClient; c = LLMClient(); r = c._clean_output([{'ticker':'A','confidence':0.9},{'ticker':'B','confidence':0.8}]); assert len(r)==2 and isinstance(r, list)"` — passes
4. `python -c "from src.data.llm_client import LLMClient; r = LLMClient._extract_json_from_response('[{\"a\":1}]'); import json; assert isinstance(json.loads(r), list)"` — passes
</verification>

<success_criteria>
- parse_announcement() returns List[Dict] in all code paths (success, error, empty)
- SYSTEM_PROMPT includes ticker filtering and multi-date instructions with examples
- AnnouncementProcessor passes ticker to LLM and stores JSON array in DB
- No DB schema changes needed
- All existing + new tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/002-llm-multi-date-single-ticker-parsing/002-SUMMARY.md`
</output>
