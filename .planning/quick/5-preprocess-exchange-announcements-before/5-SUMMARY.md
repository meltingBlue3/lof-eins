---
phase: quick-5
plan: 01
subsystem: data-processing
tags: [preprocessing, text-cleaning, llm, pdf, announcement-processor]
dependency_graph:
  requires: [src/data/announcement_processor.py]
  provides: [AnnouncementProcessor._clean_extracted_text]
  affects: [src/data/llm_client.py]
tech_stack:
  added: []
  patterns: [static-method, regex-text-cleaning, pipeline-step]
key_files:
  modified:
    - src/data/announcement_processor.py
    - tests/test_announcement_processor.py
decisions:
  - "Use ASCII character class [A-Za-z0-9._%+-]+ for email local-part instead of \\S+ to avoid consuming adjacent Chinese characters"
  - "Email regex uses explicit ASCII classes: [A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}"
  - "Cleaning inserted as Step 1.5 between extraction and LLM parse in process_pdf()"
  - "Debug log updated to show both original and cleaned char counts for observability"
metrics:
  duration: "~2 minutes"
  completed: "2026-03-03"
  tasks: 2
  files_modified: 2
  tests_added: 8
  tests_total: 21
---

# Quick Task 5: Preprocess Exchange Announcements Before LLM Summary

**One-liner:** PDF-extracted text cleaning pipeline using regex stripping HTML, URLs, emails, and normalizing whitespace — reducing token count before LLM parsing.

---

## Objective

Add a text preprocessing step in `AnnouncementProcessor.process_pdf()` that sanitizes raw PDF-extracted text before sending it to the LLM. PDF-extracted text from exchange announcements often contains HTML artifacts, embedded URLs, and irregular whitespace that waste LLM tokens and can confuse extraction.

---

## What Was Built

### `AnnouncementProcessor._clean_extracted_text(text: str) -> str`

Static method on `AnnouncementProcessor` that performs the following cleaning pipeline:

1. **Strip HTML tags** — `re.sub(r'<[^>]+>', '', text)`
2. **Remove HTTPS/HTTP URLs** — `re.sub(r'https?://\S+', '', text)`
3. **Remove bare `www.` URLs** — `re.sub(r'www\.\S+', '', text)`
4. **Remove email addresses** — `re.sub(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '', text)`
5. **Collapse 3+ newlines** → 2 newlines
6. **Collapse 2+ spaces** (non-newline) → single space
7. **Per-line strip** of leading/trailing whitespace
8. **Final strip**

Page markers (`--- Page N ---`) are fully preserved through all steps.

### Integration into `process_pdf()`

The cleaning is called as "Step 1.5" between extraction and LLM parsing:

```python
result["extracted"] = True
original_len = len(extraction_result["text"])

# Step 1.5: Clean extracted text to reduce noise before LLM parsing
extracted_text = self._clean_extracted_text(extraction_result["text"])
self.logger.debug(
    f"Extracted {original_len} chars, cleaned to {len(extracted_text)} chars from {pdf_path.name}"
)

# Step 2: Parse with LLM (returns List[Dict])
parse_result = self.llm_client.parse_announcement(extracted_text, ticker=ticker)
```

---

## Test Results

| Suite | Before | After | Status |
|-------|--------|-------|--------|
| TestAnnouncementProcessor | 11 tests | 11 tests | All pass |
| TestCleanExtractedText | 0 tests | 8 tests | All pass |
| TestConvenienceFunctions | 2 tests | 2 tests | All pass |
| **Total** | **13** | **21** | **All pass** |

### New Test Cases (TestCleanExtractedText)

| Test | Covers |
|------|--------|
| test_clean_html_tags | p/br/div/a tags removed, text preserved |
| test_clean_urls | https/http/www URLs removed |
| test_clean_email_addresses | Email removed, adjacent Chinese chars preserved |
| test_clean_excessive_whitespace | 3+ newlines collapsed, double spaces collapsed |
| test_preserve_page_markers | --- Page N --- markers survive cleaning |
| test_clean_real_world_sample | Realistic Chinese announcement with mixed noise |
| test_clean_empty_and_whitespace | Empty/whitespace-only inputs return empty string |
| test_clean_already_clean_text | Clean text unchanged, idempotent |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Email regex consumed adjacent Chinese characters**

- **Found during:** Task 2 (test_clean_email_addresses failed)
- **Issue:** The plan specified `\S+@\S+\.\S+` for email removal. `\S` matches any non-whitespace including Chinese chars, so `联系方式：contact@fund.com` would match `联系方式：contact` as the local part, eating the Chinese prefix.
- **Fix:** Replaced with ASCII character class: `[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}` — limits the local-part match to standard ASCII email characters only.
- **Files modified:** `src/data/announcement_processor.py`
- **Commit:** 6b958e9 (included in Task 2 commit)

---

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 67a9f18 | feat(quick-5-01): add _clean_extracted_text method and integrate into pipeline |
| Task 2 | 6b958e9 | test(quick-5-01): add unit tests for _clean_extracted_text |

---

## Self-Check: PASSED

- `src/data/announcement_processor.py` contains `_clean_extracted_text`: verified
- `tests/test_announcement_processor.py` contains `test_clean_extracted_text` (8 methods): verified
- Commit 67a9f18 exists: verified
- Commit 6b958e9 exists: verified
- All 21 tests pass: verified
