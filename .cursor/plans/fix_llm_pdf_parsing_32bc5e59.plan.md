---
name: Fix LLM PDF Parsing
overview: "Rewrite `llm_client.py` to use the `ollama` Python SDK with the Chat API (matching the working `vier.py` pattern), instead of raw `requests` to `/api/generate` with `format: \"json\"` which conflicts with qwen3's thinking mode."
todos:
  - id: rewrite-llm-client
    content: "Rewrite llm_client.py: replace requests with ollama SDK, use Chat API, remove format:json, add text truncation, handle thinking tokens"
    status: completed
  - id: update-requirements
    content: Add ollama>=0.4.0 to requirements.txt
    status: completed
  - id: update-tests
    content: Update test_llm_client.py mocks from requests.Session.post to ollama.chat
    status: completed
    dependencies:
      - rewrite-llm-client
  - id: verify-e2e
    content: Run tests and verify end-to-end with a real PDF
    status: completed
    dependencies:
      - rewrite-llm-client
      - update-requirements
      - update-tests
---

# Fix LLM-based PDF Announcement Parsing

## Root Cause Analysis

The current [`src/data/llm_client.py`](src/data/llm_client.py) has three compounding issues:

1. **Wrong API endpoint**: Uses `/api/generate` (completion) instead of the Chat API. The Chat API with system/user message separation is designed for instruction-following tasks.
2. **`format: "json"` conflicts with qwen3 thinking mode**: `qwen3:8b` emits `<think>...</think>` tokens by default. The `format: "json"` parameter forces the output to be strictly JSON, which clashes with thinking tokens and produces malformed responses.
3. **No text truncation**: Very long PDFs may exceed model context window, causing failures or degraded output.

The working [`vier.py`](vier.py) avoids all three: it uses `ollama.chat()` (Chat API), does NOT force JSON format, and truncates text to 8000 chars.

## Changes

### 1. Rewrite `llm_client.py` to use `ollama` Python SDK

- Replace `requests.Session` with `ollama.chat()` (Chat API with system + user messages)
- Remove `format: "json"` parameter -- let the model output naturally, then extract JSON from the response
- Add text truncation (8000 chars) to prevent context window overflow
- Handle `<think>...</think>` blocks in response: strip thinking tokens before JSON extraction
- Keep all existing validation, cleaning, and error-handling logic (`_clean_output`, `_validate_date`, etc.)

Key structural change in `parse_announcement()`:

```python
# Before (broken):
response = self.session.post(f"{self.base_url}/api/generate", json={
    "model": self.model, "prompt": prompt, "stream": False, "format": "json"
})

# After (working):
response = ollama.chat(model=self.model, messages=[
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": f"文档内容如下：\n{truncated_text}"},
])
llm_text = response["message"]["content"]
```

### 2. Update `requirements.txt`

- Add `ollama>=0.4.0` dependency
- `pdfplumber` already present (no change needed)

### 3. Update tests in `test_llm_client.py`

- Change mocks from `requests.Session.post` to `ollama.chat`
- Keep same test structure and assertions
- Add test for thinking token stripping

### 4. No changes needed to other files

- [`src/data/pdf_extractor.py`](src/data/pdf_extractor.py) -- PDF extraction with pdfplumber is fine
- [`src/data/announcement_processor.py`](src/data/announcement_processor.py) -- orchestration calls `LLMClient.parse_announcement()` which keeps the same interface
- [`scripts/parse_announcements.py`](scripts/parse_announcements.py) -- CLI unchanged
- [`tests/test_announcement_processor.py`](tests/test_announcement_processor.py) -- uses mock LLM client, unchanged