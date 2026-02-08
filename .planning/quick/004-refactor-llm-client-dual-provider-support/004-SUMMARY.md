---
phase: quick
plan: 004
subsystem: llm-client
tags: [openai, ollama, dual-provider, refactor]

dependency-graph:
  requires: [quick-002]
  provides: [dual-provider-llm-client, cloud-api-support]
  affects: [02-03-orchestration, phase-3]

tech-stack:
  added: [openai>=1.0.0]
  patterns: [provider-dispatch, env-based-config]

key-files:
  created: [.env.example]
  modified: [src/data/llm_client.py, tests/test_llm_client.py, requirements.txt]

decisions:
  - id: provider-auto-detection
    choice: "LLM_API_KEY env var presence determines cloud vs Ollama mode"
    rationale: "Zero-config for existing Ollama users, simple opt-in for cloud"
  - id: openai-sdk-for-cloud
    choice: "Use openai Python SDK with base_url for all OpenAI-compatible APIs"
    rationale: "Battle-tested SDK, handles auth/retries/streaming, works with Moonshot/DeepSeek/OpenAI"
  - id: no-load-dotenv-in-init
    choice: "Don't call load_dotenv() inside LLMClient.__init__"
    rationale: "Preserves test isolation — existing 29 tests pass without modification"
  - id: call-llm-dispatch
    choice: "Extract _call_llm() method for provider dispatch"
    rationale: "Single dispatch point, all shared logic (prompts, parsing, cleaning) unchanged"

metrics:
  duration: "~6 minutes"
  completed: 2026-02-09
---

# Quick Task 004: Refactor LLM Client for Dual-Provider Support Summary

**One-liner:** Dual-provider LLMClient auto-detecting cloud (OpenAI-compatible) vs local Ollama from LLM_API_KEY env var, using openai SDK with configurable base_url.

## What Was Done

Refactored `LLMClient` to support two LLM provider modes:

1. **Cloud mode** — activated when `LLM_API_KEY` env var is set (or `api_key` constructor param). Uses the `openai` Python SDK with `base_url` parameter, compatible with Moonshot, DeepSeek, OpenAI, and any OpenAI-compatible API.

2. **Ollama mode** — default fallback when no API key is present. Unchanged from previous behavior using the `ollama` Python SDK.

### Key Design Decisions

- **Provider detection via env var:** `LLM_API_KEY` set and non-empty → cloud mode. Absent → Ollama mode. Simple, predictable, zero-config for existing users.
- **`_call_llm()` dispatch method:** Single point of provider dispatch. All shared logic (system prompt building, JSON extraction, thinking token stripping, output cleaning/validation) is completely unchanged.
- **No `load_dotenv()` in `__init__`:** Caller is responsible for loading `.env`. This preserves test isolation — all 29 existing tests continue to pass without any modification.
- **`openai` SDK (not raw requests):** Handles authentication, retries, streaming, error types out of the box. The `base_url` parameter makes it work with any OpenAI-compatible endpoint.

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add openai dependency and update .env.example | `4c28985` | requirements.txt, .env.example |
| 2 | Refactor LLMClient for dual-provider support | `f0225b8` | src/data/llm_client.py |
| 3 | Add tests for cloud provider mode | `9d70d35` | tests/test_llm_client.py |

## Files Changed

| File | Change |
|------|--------|
| `requirements.txt` | Added `openai>=1.0.0` |
| `.env.example` | Documented `LLM_URL`, `LLM_API_KEY`, `LLM_MODEL`, `OLLAMA_HOST`, `OLLAMA_MODEL` |
| `src/data/llm_client.py` | Dual-provider `__init__`, `_call_llm()` dispatch, updated docstrings |
| `tests/test_llm_client.py` | Added `TestLLMClientCloud` class with 6 tests |

## Environment Variables

| Variable | Mode | Default | Description |
|----------|------|---------|-------------|
| `LLM_API_KEY` | Cloud | *(none)* | API key; presence activates cloud mode |
| `LLM_URL` | Cloud | `https://api.openai.com/v1` | Base URL for OpenAI-compatible API |
| `LLM_MODEL` | Both | `moonshot-v1-8k` (cloud) / `qwen3:8b` (Ollama) | Model name override |
| `OLLAMA_HOST` | Ollama | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | Ollama | `qwen3:8b` | Ollama model name |

## Test Results

| Test Class | Tests | Status |
|------------|-------|--------|
| TestLLMClient | 25 | ✅ Pass |
| TestLLMClientEnvironment | 4 | ✅ Pass |
| TestLLMClientCloud | 6 | ✅ Pass (new) |
| TestLLMClientIntegration | 2 | ⏭️ Skipped (requires Ollama) |
| **Total** | **37** | **35 pass, 2 skipped** |

## Deviations from Plan

None — plan executed exactly as written.

## Verification

1. ✅ `python -m pytest tests/test_llm_client.py -v` — 35 pass, 2 skipped
2. ✅ Default `LLMClient()._provider` → `"ollama"`
3. ✅ With `LLM_API_KEY` set → `LLMClient()._provider` → `"cloud"`
4. ✅ `pip show openai` → openai 2.17.0 installed

## Self-Check: PASSED
