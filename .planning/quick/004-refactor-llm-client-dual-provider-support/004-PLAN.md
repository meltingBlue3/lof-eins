---
phase: quick
plan: 004
type: execute
wave: 1
depends_on: []
files_modified:
  - src/data/llm_client.py
  - tests/test_llm_client.py
  - requirements.txt
  - .env.example
autonomous: true

must_haves:
  truths:
    - "When LLM_API_KEY is set in .env, client calls OpenAI-compatible /chat/completions endpoint at LLM_URL"
    - "When LLM_API_KEY is not set, client falls back to local Ollama as before"
    - "All 22 existing tests pass without modification (backward compatibility)"
    - "Prompt template, response parsing, and _clean_output logic are shared across both providers"
  artifacts:
    - path: "src/data/llm_client.py"
      provides: "Dual-provider LLM client (Ollama + OpenAI-compatible)"
      contains: "class LLMClient"
    - path: "tests/test_llm_client.py"
      provides: "Tests for cloud API mode alongside existing Ollama tests"
    - path: ".env.example"
      provides: "Documents LLM_URL and LLM_API_KEY env vars"
  key_links:
    - from: "src/data/llm_client.py"
      to: ".env"
      via: "os.getenv('LLM_API_KEY') detection"
      pattern: "os\\.getenv.*LLM_API_KEY"
    - from: "src/data/llm_client.py"
      to: "OpenAI-compatible API"
      via: "openai.ChatCompletion or requests POST to /chat/completions"
      pattern: "chat/completions|openai"
---

<objective>
Refactor LLMClient to support both local Ollama and cloud OpenAI-compatible APIs (e.g., Moonshot).

Purpose: Enable using cloud LLM APIs when a local Ollama instance isn't available, controlled by .env config. The .env already has LLM_URL and LLM_API_KEY fields ready to use.

Output: Modified llm_client.py with provider auto-detection, updated tests, updated .env.example
</objective>

<context>
@src/data/llm_client.py
@tests/test_llm_client.py
@requirements.txt
@.env.example
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add openai dependency and update .env.example</name>
  <files>requirements.txt, .env.example</files>
  <action>
    1. Add `openai>=1.0.0` to requirements.txt (the openai Python SDK handles any OpenAI-compatible endpoint via `base_url` parameter)
    2. Update .env.example to document the LLM env vars:
       ```
       # LLM Configuration (Cloud API - OpenAI-compatible)
       # If LLM_API_KEY is set, uses cloud API; otherwise falls back to local Ollama
       LLM_URL=https://api.moonshot.cn/v1
       LLM_API_KEY=your_api_key_here
       
       # LLM Configuration (Local Ollama - used when LLM_API_KEY is not set)
       # OLLAMA_HOST=http://localhost:11434
       # OLLAMA_MODEL=qwen3:8b
       ```
    3. Run `pip install openai>=1.0.0` to install the dependency
  </action>
  <verify>pip show openai confirms installation; .env.example contains LLM_URL and LLM_API_KEY documentation</verify>
  <done>openai in requirements.txt, .env.example documents both cloud and Ollama config options</done>
</task>

<task type="auto">
  <name>Task 2: Refactor LLMClient for dual-provider support</name>
  <files>src/data/llm_client.py</files>
  <action>
    Refactor LLMClient.__init__ to auto-detect provider mode:

    **Provider detection logic in __init__:**
    ```python
    def __init__(self, base_url=None, model=None, api_key=None):
        # Load .env if python-dotenv available
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        
        # Determine provider: cloud if api_key provided or LLM_API_KEY env var set
        self._api_key = api_key or os.getenv("LLM_API_KEY")
        
        if self._api_key:
            # Cloud mode: OpenAI-compatible API
            self._provider = "cloud"
            self.host = base_url or os.getenv("LLM_URL", "https://api.openai.com/v1")
            self.model = model or os.getenv("LLM_MODEL", "moonshot-v1-8k")
            from openai import OpenAI
            self._openai_client = OpenAI(
                api_key=self._api_key,
                base_url=self.host,
            )
            self._client = None  # No ollama client needed
        else:
            # Local mode: Ollama (existing behavior)
            self._provider = "ollama"
            self.host = base_url
            self.model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
            if self.host:
                self._client = ollama.Client(host=self.host)
            else:
                self._client = ollama.Client()
            self._openai_client = None
    ```

    **Refactor parse_announcement to dispatch by provider:**

    Keep ALL shared logic (empty text check, truncation, system prompt building, user message building, JSON extraction, _clean_output) exactly the same. Only the API call differs.

    Extract the API call into a private method `_call_llm(messages) -> str` that returns raw response text:

    ```python
    def _call_llm(self, messages: list) -> str:
        """Call the LLM API and return raw response text."""
        if self._provider == "cloud":
            response = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,  # Low temp for structured extraction
            )
            return response.choices[0].message.content
        else:
            # Ollama mode (existing)
            response = self._client.chat(
                model=self.model,
                messages=messages,
                think=True,
            )
            return response["message"]["content"]
    ```

    **Update parse_announcement:** Replace the direct `self._client.chat(...)` call with `self._call_llm(messages)`. The rest of the method stays identical.

    **Update error handling in parse_announcement:**
    - Keep existing `ollama.ResponseError`, `ConnectionError`, `TimeoutError` catches
    - Add catch for `openai.APIError` (or broader Exception already covers it) for cloud mode
    - The existing generic `except Exception` catch already handles cloud API errors gracefully, but add a specific catch for `openai.APIError` before it for better error messages:
      ```python
      except Exception as e:
          if "openai" in type(e).__module__:
              logger.error(f"Cloud API error: {e}")
              return [error_record(f"Cloud API error: {str(e)}")]
          ...
      ```
      Actually, simpler approach: since the generic Exception handler already returns a proper error record, just keep it. No need for openai-specific catch unless we want prettier messages. Keep it simple.

    **Update module docstring:** Add cloud API info to the module docstring, mentioning LLM_URL and LLM_API_KEY env vars.

    **Update the convenience function `parse_announcement`:** No changes needed - it already passes **kwargs to LLMClient, so `api_key` can be passed through.

    **Key constraints:**
    - Do NOT change SYSTEM_PROMPT_TEMPLATE
    - Do NOT change _build_system_prompt, _build_prompt, _strip_thinking_tokens, _extract_json_from_response, _validate_date, _clean_single_record, _clean_output
    - Do NOT change the return type or structure of parse_announcement
    - The `import ollama` at module top stays (Ollama is still the fallback provider)
    - Keep `base_url` property alias for backward compatibility
    - When in cloud mode and `ollama.ResponseError` is raised (shouldn't happen), the generic Exception handler catches it
  </action>
  <verify>
    Run: `python -m pytest tests/test_llm_client.py -v`
    All 22 existing tests must pass. The existing tests create LLMClient() without LLM_API_KEY env var set, so they should all use Ollama mode and work exactly as before.
  </verify>
  <done>LLMClient auto-detects provider from env vars. Cloud mode uses openai SDK with configurable base_url. Ollama mode unchanged. All existing tests pass.</done>
</task>

<task type="auto">
  <name>Task 3: Add tests for cloud provider mode</name>
  <files>tests/test_llm_client.py</files>
  <action>
    Add a new test class `TestLLMClientCloud` with tests for cloud API mode. Use `@patch.dict(os.environ, {"LLM_API_KEY": "test-key", "LLM_URL": "https://api.test.com/v1"})` to activate cloud mode, and mock `openai.OpenAI` to avoid real API calls.

    **Tests to add:**

    1. `test_cloud_mode_detected` — When LLM_API_KEY env var is set, client._provider == "cloud" and _openai_client is not None
    2. `test_cloud_mode_explicit_api_key` — When api_key passed to constructor, uses cloud mode regardless of env
    3. `test_ollama_mode_when_no_api_key` — When LLM_API_KEY not set, client._provider == "ollama" (existing behavior confirmed)
    4. `test_cloud_parse_announcement_success` — Mock openai client, verify parse_announcement returns correct List[Dict] from cloud API response
    5. `test_cloud_parse_announcement_api_error` — Mock openai client to raise Exception, verify error record returned
    6. `test_cloud_model_from_env` — When LLM_MODEL env var set, it's used as model name in cloud mode

    **Mocking strategy for cloud tests:**
    ```python
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key", "LLM_URL": "https://api.test.com/v1"})
    @patch("src.data.llm_client.OpenAI")
    def test_cloud_parse_announcement_success(self, MockOpenAI):
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        
        # Mock the chat completion response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps([{...}])
        mock_client.chat.completions.create.return_value = mock_response
        
        client = LLMClient()
        result = client.parse_announcement("Test text")
        # assert result...
    ```

    Note: The `from openai import OpenAI` happens inside __init__ when cloud mode is detected. Mock at `src.data.llm_client.OpenAI` won't work because it's a local import. Instead, either:
    - Mock `openai.OpenAI` at the openai module level, OR
    - Create the client, then patch `client._openai_client` directly (simpler, like existing tests patch `client._client`)

    **Preferred approach (matches existing test patterns):** Create client with env vars set, then patch `client._openai_client.chat.completions.create` directly:
    ```python
    @patch.dict(os.environ, {"LLM_API_KEY": "sk-test", "LLM_URL": "https://api.test.com/v1"})
    def test_cloud_parse_success(self):
        with patch("src.data.llm_client.OpenAI") as MockOpenAI:
            mock_openai_instance = MagicMock()
            MockOpenAI.return_value = mock_openai_instance
            
            client = LLMClient()
            
            # Now mock the completions call
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = self.mock_json
            client._openai_client.chat.completions.create.return_value = mock_resp
            
            result = client.parse_announcement("Test announcement text")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "161005")
    ```

    Keep all existing tests untouched. Add the new class after existing test classes.
  </action>
  <verify>
    Run: `python -m pytest tests/test_llm_client.py -v`
    All tests pass — both existing 22 and new cloud tests (expect ~28 total).
  </verify>
  <done>Cloud provider mode has dedicated tests. Provider detection, successful parsing, and error handling all verified. Total test count ~28.</done>
</task>

</tasks>

<verification>
1. `python -m pytest tests/test_llm_client.py -v` — all tests pass (existing + new)
2. `python -c "from src.data.llm_client import LLMClient; c = LLMClient(); print(c._provider)"` — prints "ollama" (no API key set)
3. `LLM_API_KEY=test python -c "from src.data.llm_client import LLMClient; c = LLMClient(); print(c._provider)"` — prints "cloud"
4. `pip show openai` — confirms openai package installed
</verification>

<success_criteria>
- LLMClient auto-detects cloud vs local provider based on LLM_API_KEY env var presence
- Cloud mode uses openai SDK with configurable base_url (works with Moonshot, OpenAI, any compatible API)
- Local Ollama mode works exactly as before (full backward compatibility)
- All 22 original tests pass without any modification
- New cloud-mode tests verify the provider detection and API calling
- .env.example documents both configuration modes
</success_criteria>
