---
phase: quick-5
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/data/announcement_processor.py
  - tests/test_announcement_processor.py
autonomous: true
requirements: [QUICK-5]
must_haves:
  truths:
    - "Extracted PDF text is cleaned of HTML tags before LLM receives it"
    - "URLs are stripped from text before LLM receives it"
    - "Excessive whitespace is collapsed to single spaces/newlines"
    - "Page markers (--- Page N ---) are preserved through cleaning"
    - "Cleaning reduces token count without losing meaningful content"
    - "Existing tests still pass after changes"
  artifacts:
    - path: "src/data/announcement_processor.py"
      provides: "_clean_extracted_text() method and integration into process_pdf pipeline"
      contains: "_clean_extracted_text"
    - path: "tests/test_announcement_processor.py"
      provides: "Unit tests for text cleaning function"
      contains: "test_clean_extracted_text"
  key_links:
    - from: "src/data/announcement_processor.py::process_pdf"
      to: "src/data/announcement_processor.py::_clean_extracted_text"
      via: "Called between extract_pdf_text() result and llm_client.parse_announcement()"
      pattern: "_clean_extracted_text"
---

<objective>
Add a text preprocessing/cleaning step in AnnouncementProcessor.process_pdf() that sanitizes
raw PDF-extracted text before sending it to the LLM. This removes HTML tags, URLs, excessive
whitespace, and other noise to reduce token consumption and improve LLM parsing quality.

Purpose: PDF-extracted text from exchange announcements often contains HTML artifacts, embedded
URLs, and irregular whitespace that waste LLM tokens and can confuse extraction. Cleaning
before LLM input improves both cost efficiency and parsing accuracy.

Output: Updated announcement_processor.py with _clean_extracted_text() method, integrated
into process_pdf() pipeline between Step 1 (extraction) and Step 2 (LLM parsing).
</objective>

<execution_context>
@C:/Users/zhang/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/zhang/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@src/data/announcement_processor.py
@tests/test_announcement_processor.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add _clean_extracted_text method and integrate into pipeline</name>
  <files>src/data/announcement_processor.py</files>
  <action>
Add a static method `_clean_extracted_text(text: str) -> str` to `AnnouncementProcessor` that performs the following cleaning steps in order:

1. **Strip HTML tags**: Remove all HTML/XML tags using `re.sub(r'<[^>]+>', '', text)`. Exchange announcements sometimes contain residual HTML from web scraping.

2. **Remove URLs**: Remove http/https URLs using `re.sub(r'https?://\S+', '', text)`. Also remove bare `www.` URLs: `re.sub(r'www\.\S+', '', text)`.

3. **Remove email addresses**: `re.sub(r'\S+@\S+\.\S+', '', text)`.

4. **Collapse excessive whitespace**: Replace runs of 3+ newlines with 2 newlines: `re.sub(r'\n{3,}', '\n\n', text)`. Replace runs of 2+ spaces (not newlines) with single space: `re.sub(r'[^\S\n]{2,}', ' ', text)`.

5. **Strip leading/trailing whitespace** from each line: `'\n'.join(line.strip() for line in text.split('\n'))`.

6. **Final strip**: `text.strip()`.

IMPORTANT: Preserve `--- Page N ---` markers — these are used by the LLM for multi-page context. The cleaning regex patterns above will NOT affect these markers, but verify this explicitly.

Then integrate the method into `process_pdf()`. After line 128 (`extracted_text = extraction_result["text"]`), add:

```python
# Step 1.5: Clean extracted text to reduce noise before LLM parsing
extracted_text = self._clean_extracted_text(extracted_text)
```

Update the debug log on line 129-131 to log BOTH original and cleaned lengths:

```python
original_len = len(extraction_result["text"])
extracted_text = self._clean_extracted_text(extracted_text)
self.logger.debug(
    f"Extracted {original_len} chars, cleaned to {len(extracted_text)} chars from {pdf_path.name}"
)
```

Import `re` at the top of the file (it is not currently imported).
  </action>
  <verify>python -c "from src.data.announcement_processor import AnnouncementProcessor; t = AnnouncementProcessor._clean_extracted_text; print('Method exists:', callable(t))"</verify>
  <done>_clean_extracted_text() method exists on AnnouncementProcessor, is called in process_pdf() between extraction and LLM parsing, handles HTML tags, URLs, emails, and whitespace normalization while preserving page markers</done>
</task>

<task type="auto">
  <name>Task 2: Add unit tests for text cleaning</name>
  <files>tests/test_announcement_processor.py</files>
  <action>
Add a new test class `TestCleanExtractedText` (or add methods to the existing test structure) in `tests/test_announcement_processor.py` with the following test cases:

1. `test_clean_html_tags` — Input with `<p>`, `<br>`, `<div>`, `<a href="...">` tags. Assert all tags removed, text content preserved.

2. `test_clean_urls` — Input with `https://www.example.com/path?q=1` and `http://fund.com` and `www.bare-url.com`. Assert all URLs removed.

3. `test_clean_email_addresses` — Input with `contact@fund.com`. Assert email removed.

4. `test_clean_excessive_whitespace` — Input with 5+ consecutive newlines and multiple spaces. Assert collapsed to max 2 newlines and single spaces.

5. `test_preserve_page_markers` — Input containing `--- Page 1 ---\n content \n--- Page 2 ---`. Assert markers are fully preserved.

6. `test_clean_real_world_sample` — A realistic Chinese announcement snippet with mixed HTML, URLs, and content. Assert the meaningful Chinese text (fund names, dates, amounts) is preserved while noise is removed.

7. `test_clean_empty_and_whitespace` — Empty string returns empty string, whitespace-only returns empty string.

8. `test_clean_already_clean_text` — Clean text passes through unchanged (idempotent for clean input).

Use the existing test patterns in the file (unittest framework, setUp/tearDown conventions). Since `_clean_extracted_text` is a static method, call it directly as `AnnouncementProcessor._clean_extracted_text(text)` — no processor instance needed for these tests.
  </action>
  <verify>python -m pytest tests/test_announcement_processor.py -x -v -k "clean" 2>&1 | tail -20</verify>
  <done>All 8 test cases pass, covering HTML removal, URL removal, email removal, whitespace normalization, page marker preservation, real-world Chinese text, empty input, and idempotency</done>
</task>

</tasks>

<verification>
```bash
# All new cleaning tests pass
python -m pytest tests/test_announcement_processor.py -x -v -k "clean"

# All existing tests still pass (no regressions)
python -m pytest tests/test_announcement_processor.py -x -v

# Quick smoke test of the cleaning function
python -c "
from src.data.announcement_processor import AnnouncementProcessor
sample = '<p>本基金将于2024年1月1日起</p>\nhttps://www.example.com\n\n\n\n限购金额为100万元'
cleaned = AnnouncementProcessor._clean_extracted_text(sample)
print('Before:', len(sample), 'chars')
print('After:', len(cleaned), 'chars')
print('Result:', repr(cleaned))
assert '<p>' not in cleaned
assert 'https://' not in cleaned
assert '\n\n\n' not in cleaned
assert '本基金' in cleaned
assert '100万元' in cleaned
print('All assertions passed')
"
```
</verification>

<success_criteria>
- _clean_extracted_text() static method exists on AnnouncementProcessor
- Method removes HTML tags, URLs, emails, and normalizes whitespace
- Method preserves page markers (--- Page N ---) and meaningful Chinese content
- Method is called in process_pdf() between extraction and LLM parsing
- All 8+ new test cases pass
- All existing tests pass without regression
</success_criteria>

<output>
After completion, create `.planning/quick/5-preprocess-exchange-announcements-before/5-SUMMARY.md`
</output>
