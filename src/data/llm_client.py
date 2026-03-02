"""
LLM Client for parsing fund announcement PDFs.

This module provides a dual-provider interface for extracting structured purchase
limit information from fund announcement text:

1. **Cloud API mode** (OpenAI-compatible): Used when LLM_API_KEY env var is set.
   Works with any OpenAI-compatible endpoint (Moonshot, DeepSeek, OpenAI, etc.)
   via the ``openai`` Python SDK with configurable ``base_url``.

2. **Local Ollama mode** (default fallback): Used when LLM_API_KEY is not set.
   Connects to a local Ollama instance via the ``ollama`` Python SDK.

Provider auto-detection: if ``LLM_API_KEY`` is set and non-empty, cloud mode is
used; otherwise local Ollama mode is used.

Environment Variables:
    LLM_API_KEY: API key for cloud provider. If set, enables cloud mode.
    LLM_URL: Base URL for cloud API (default: https://api.openai.com/v1)
    LLM_MODEL: Model name override (used in both modes)
    OLLAMA_HOST: Base URL for Ollama API (default: http://localhost:11434)
    OLLAMA_MODEL: Model name for Ollama (default: qwen3:8b)

Setup (Cloud API):
    1. Set LLM_API_KEY and LLM_URL in .env
    2. Optionally set LLM_MODEL to override the default model

Setup (Local Ollama):
    1. Install Ollama from https://ollama.com
    2. Pull a suitable model: ``ollama pull qwen3:8b`` (recommended for Chinese)
    3. Ensure Ollama is running: ``ollama serve`` (or let it auto-start)

Example Usage:
    >>> from src.data.llm_client import LLMClient, parse_announcement
    >>>
    >>> # Using the client class (auto-detects provider from env)
    >>> client = LLMClient()
    >>> result = client.parse_announcement(extracted_text)
    >>>
    >>> # Explicit cloud mode
    >>> client = LLMClient(api_key="sk-xxx", base_url="https://api.moonshot.cn/v1")
    >>> result = client.parse_announcement(extracted_text, ticker="161005")
    >>>
    >>> # Using the convenience function
    >>> result = parse_announcement(extracted_text, ticker="161005")
    >>>
    >>> print(result)
    [
        {
            "ticker": "161005",
            "limit_amount": 100.0,
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "announcement_type": "complete",
            "is_purchase_limit_announcement": True,
            "confidence": 0.95
        }
    ]
"""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import ollama
from openai import OpenAI

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_MODEL = "qwen3:8b"  # Good for Chinese text processing
MAX_TEXT_LENGTH = 8000  # Truncate input text to prevent context window overflow

# Prompt directory: <project_root>/prompts/
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """
    Load a prompt template from the prompts/ directory.

    Args:
        name: Filename (without path) inside the prompts/ directory,
              e.g. "system_prompt.md".

    Returns:
        The file content as a string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


# System prompt template: loaded from prompts/system_prompt.md
# Contains {ticker_instruction} placeholder filled by _build_system_prompt()
SYSTEM_PROMPT_TEMPLATE = _load_prompt("system_prompt.md")


class LLMError(Exception):
    """Raised when LLM API call fails or returns invalid response."""

    pass


class LLMClient:
    """
    Dual-provider client for parsing fund announcements with LLMs.

    Supports two modes:
    - **Cloud mode**: OpenAI-compatible API (Moonshot, DeepSeek, OpenAI, etc.)
      Activated when ``api_key`` is provided or ``LLM_API_KEY`` env var is set.
    - **Ollama mode**: Local Ollama instance (default fallback)
      Used when no API key is available.

    Attributes:
        host: The base URL for the API endpoint
        model: The model name to use for inference
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the LLM client with auto-detected provider.

        Args:
            base_url: API base URL. For cloud mode, defaults to LLM_URL env var.
                      For Ollama mode, defaults to ollama SDK default.
            model: Model name to use. Defaults to LLM_MODEL or OLLAMA_MODEL env var.
            api_key: API key for cloud provider. If provided (or LLM_API_KEY env var
                     is set and non-empty), cloud mode is activated.
        """
        # Determine provider: cloud if api_key provided or LLM_API_KEY env var set
        # Note: Caller is responsible for loading .env (e.g., via dotenv.load_dotenv())
        # before instantiating LLMClient if env-based config is desired.
        self._api_key = api_key or os.getenv("LLM_API_KEY", "").strip() or None

        if self._api_key:
            # Cloud mode: OpenAI-compatible API
            self._provider = "cloud"
            self.host = base_url or os.getenv("LLM_URL", "https://api.openai.com/v1")
            self.model = model or os.getenv("LLM_MODEL", "moonshot-v1-8k")
            self._openai_client = OpenAI(
                api_key=self._api_key,
                base_url=self.host,
            )
            self._client = None  # No Ollama client needed
            logger.info(
                f"Initialized LLMClient in cloud mode: "
                f"base_url={self.host}, model={self.model}"
            )
        else:
            # Local mode: Ollama (existing behavior)
            self._provider = "ollama"
            self.host = base_url  # None lets ollama SDK pick its default
            self.model = (
                model
                or os.getenv("LLM_MODEL")
                or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
            )
            # Only pass host when explicitly set; otherwise let the SDK resolve it
            # (avoids localhost → IPv6 issues on Windows)
            if self.host:
                self._client = ollama.Client(host=self.host)
            else:
                self._client = ollama.Client()
            self._openai_client = None
            logger.info(f"Initialized LLMClient in ollama mode: model={self.model}")

    # Keep base_url as an alias for backward compatibility
    @property
    def base_url(self) -> Optional[str]:
        return self.host

    def _build_system_prompt(self, ticker: Optional[str] = None) -> str:
        """
        Build the system prompt with ticker-specific filtering instruction.

        Args:
            ticker: Fund ticker code. If provided, adds instruction to only extract
                    information for this ticker.

        Returns:
            Formatted system prompt string
        """
        if ticker:
            ticker_instruction = (
                f"\n当前解析的公告属于基金代码 `{ticker}`。"
                "仅提取该基金的限购信息，忽略公告中提到的其他基金。"
            )
        else:
            ticker_instruction = ""
        return SYSTEM_PROMPT_TEMPLATE.format(ticker_instruction=ticker_instruction)

    def _build_prompt(self, text: str, ticker: Optional[str] = None) -> str:
        """
        Build the full prompt with instructions.

        This is kept for backward compatibility and testing. The actual prompt
        sent to the model is split into system + user messages in parse_announcement().

        Args:
            text: The extracted text from the PDF announcement
            ticker: Optional fund ticker code for filtering

        Returns:
            A formatted prompt string with instructions
        """
        system_prompt = self._build_system_prompt(ticker)
        return f"""{system_prompt}

请分析以下公告原文：

---
{text}
---

仅返回 JSON 数组，不要输出任何其他内容。"""

    @staticmethod
    def _strip_thinking_tokens(text: str) -> str:
        """
        Strip qwen3 thinking tokens (<think>...</think>) from LLM response.

        Args:
            text: Raw LLM response text

        Returns:
            Text with thinking blocks removed
        """
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    @staticmethod
    def _extract_json_from_response(text: str) -> str:
        """
        Extract JSON array or object from free-form LLM response text.

        Handles markdown code blocks, thinking tokens, and surrounding prose.
        Supports both JSON arrays and single JSON objects.

        Args:
            text: LLM response text potentially containing JSON

        Returns:
            Extracted JSON string (may be array or object)

        Raises:
            ValueError: If no valid JSON can be found
        """
        # Strip thinking tokens first
        text = LLMClient._strip_thinking_tokens(text)

        # Remove markdown code blocks
        cleaned = re.sub(r"```json\s*", "", text)
        cleaned = re.sub(r"```\s*", "", cleaned)
        cleaned = cleaned.strip()

        # Try parsing directly first
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            pass

        # Try to find a JSON array in the text using bracket matching
        bracket_start = cleaned.find("[")
        if bracket_start != -1:
            depth = 0
            for i in range(bracket_start, len(cleaned)):
                if cleaned[i] == "[":
                    depth += 1
                elif cleaned[i] == "]":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[bracket_start : i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except json.JSONDecodeError:
                            break

        # Try to find a JSON object in the text using brace matching
        brace_start = cleaned.find("{")
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[brace_start : i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except json.JSONDecodeError:
                            break

        raise ValueError(f"No valid JSON found in response")

    def _validate_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Validate and normalize a date string to YYYY-MM-DD format.

        Args:
            date_str: Date string to validate

        Returns:
            Normalized date string or None if invalid
        """
        if not date_str or date_str.lower() in ("null", "none", ""):
            return None

        # Try common date formats
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%Y.%m.%d",
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Try to extract date using regex as fallback
        patterns = [
            r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                year, month, day = match.groups()
                try:
                    parsed = datetime(int(year), int(month), int(day))
                    return parsed.strftime("%Y-%m-%d")
                except ValueError:
                    continue

        return None

    def _clean_single_record(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean and validate a single LLM output record, ensuring all required fields exist.

        Args:
            raw: Raw dictionary from LLM response

        Returns:
            Cleaned dictionary with all required fields
        """
        cleaned = {
            "ticker": None,
            "limit_amount": None,
            "start_date": None,
            "end_date": None,
            "announcement_type": None,
            "is_purchase_limit_announcement": False,
            "confidence": 0.0,
        }

        if isinstance(raw.get("ticker"), str):
            cleaned["ticker"] = raw["ticker"].strip() or None

        if raw.get("limit_amount") is not None:
            try:
                cleaned["limit_amount"] = float(raw["limit_amount"])
            except (ValueError, TypeError):
                cleaned["limit_amount"] = None

        # Validate dates
        if raw.get("start_date"):
            cleaned["start_date"] = self._validate_date(str(raw["start_date"]))

        if raw.get("end_date"):
            cleaned["end_date"] = self._validate_date(str(raw["end_date"]))

        # Validate announcement type
        valid_types = ["complete", "open-start", "end-only", "modify"]
        if raw.get("announcement_type") in valid_types:
            cleaned["announcement_type"] = raw["announcement_type"]

        # Boolean field
        if isinstance(raw.get("is_purchase_limit_announcement"), bool):
            cleaned["is_purchase_limit_announcement"] = raw[
                "is_purchase_limit_announcement"
            ]

        # Confidence score (0-1)
        if raw.get("confidence") is not None:
            try:
                conf = float(raw["confidence"])
                cleaned["confidence"] = max(0.0, min(1.0, conf))
            except (ValueError, TypeError):
                cleaned["confidence"] = 0.0

        return cleaned

    def _clean_output(self, raw: Any) -> List[Dict[str, Any]]:
        """
        Clean and validate LLM output, handling both single dicts and lists.

        Always returns a List[Dict] for consistent downstream handling.

        Args:
            raw: Raw output from LLM — may be a dict, list of dicts, or other

        Returns:
            List of cleaned dictionaries with all required fields
        """
        if isinstance(raw, list):
            return [self._clean_single_record(item) for item in raw]
        elif isinstance(raw, dict):
            return [self._clean_single_record(raw)]
        else:
            # Unexpected type — return a single error record
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Unexpected LLM output type: {type(raw).__name__}",
                }
            ]

    def _call_llm(self, messages: list) -> str:
        """
        Call the LLM API and return raw response text.

        Dispatches to either OpenAI-compatible cloud API or local Ollama
        based on the detected provider.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.

        Returns:
            Raw response text from the LLM.

        Raises:
            Various API-specific exceptions (handled by caller).
        """
        if self._provider == "cloud":
            response = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return response.choices[0].message.content
        else:
            # Ollama mode (existing behavior)
            response = self._client.chat(
                model=self.model,
                messages=messages,
                think=True,
            )
            return response["message"]["content"]

    def parse_announcement(
        self, text: str, ticker: Optional[str] = None, timeout: int = 120
    ) -> List[Dict[str, Any]]:
        """
        Parse fund announcement text and extract structured limit information.

        Uses the Chat API with system/user message separation for reliable
        instruction-following. Input text is truncated to prevent context overflow.
        Dispatches to cloud or Ollama provider based on auto-detection.

        Args:
            text: The extracted text from the PDF announcement
            ticker: Optional fund ticker code. If provided, the LLM is instructed
                    to only extract information for this ticker.
            timeout: Request timeout in seconds (default: 120)

        Returns:
            List of dictionaries, each containing extracted information with keys:
            - ticker: Fund ticker code or null
            - limit_amount: Maximum purchase amount or null
            - start_date: Limit start date (YYYY-MM-DD) or null
            - end_date: Limit end date (YYYY-MM-DD) or null
            - announcement_type: One of complete/open-start/end-only/modify/null
            - is_purchase_limit_announcement: Boolean indicating if this is a limit announcement
            - confidence: Confidence score (0-1)

        Raises:
            LLMError: If the API call fails or returns an invalid response
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to parse_announcement")
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": "Empty input text",
                }
            ]

        # Truncate long texts to prevent context window overflow
        truncated_text = text[:MAX_TEXT_LENGTH]
        if len(text) > MAX_TEXT_LENGTH:
            logger.info(
                f"Truncated input from {len(text)} to {MAX_TEXT_LENGTH} characters"
            )

        # Build system prompt with ticker filtering
        system_prompt = self._build_system_prompt(ticker)

        # Build user message with optional ticker hint
        if ticker:
            user_content = (
                f"你正在解析基金代码 {ticker} 的公告。文档内容如下：\n{truncated_text}"
            )
        else:
            user_content = f"文档内容如下：\n{truncated_text}"

        # Build messages for the Chat API (system + user separation)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            logger.debug(f"Sending chat request via {self._provider} provider")
            llm_response_text = self._call_llm(messages)
            logger.debug(f"Raw LLM response length: {len(llm_response_text)} chars")

            # Extract JSON from the response (handles thinking tokens, code blocks)
            try:
                json_str = self._extract_json_from_response(llm_response_text)
                parsed = json.loads(json_str)
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"Failed to extract JSON from LLM response: {e}")
                logger.debug(f"Raw response: {llm_response_text[:500]}")
                return [
                    {
                        "ticker": None,
                        "limit_amount": None,
                        "start_date": None,
                        "end_date": None,
                        "announcement_type": None,
                        "is_purchase_limit_announcement": False,
                        "confidence": 0.0,
                        "error": f"Invalid JSON in LLM response: {e}",
                    }
                ]

            # Clean and validate the output (returns List[Dict])
            cleaned = self._clean_output(parsed)

            if not cleaned:
                logger.warning("LLM returned empty result list")
                return [
                    {
                        "ticker": None,
                        "limit_amount": None,
                        "start_date": None,
                        "end_date": None,
                        "announcement_type": None,
                        "is_purchase_limit_announcement": False,
                        "confidence": 0.0,
                        "error": "LLM returned empty result list",
                    }
                ]

            logger.info(
                f"Successfully parsed announcement: {len(cleaned)} record(s), "
                f"ticker={cleaned[0]['ticker']}, "
                f"type={cleaned[0]['announcement_type']}, "
                f"is_limit={cleaned[0]['is_purchase_limit_announcement']}"
            )

            return cleaned

        except ollama.ResponseError as e:
            logger.error(f"Ollama API error: {e}")
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Ollama API error: {str(e)}",
                }
            ]
        except ConnectionError as e:
            host_display = self.host or "default (127.0.0.1:11434)"
            logger.error(
                f"Failed to connect to {self._provider} at {host_display}: {e}"
            )
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Connection error: Cannot connect to {self._provider} at {host_display}. "
                    f"Ensure the service is running and accessible.",
                }
            ]
        except TimeoutError as e:
            logger.error(f"Request timed out after {timeout}s: {e}")
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Timeout error: Request took longer than {timeout} seconds",
                }
            ]
        except LLMError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during parsing ({self._provider}): {e}")
            return [
                {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Unexpected error: {str(e)}",
                }
            ]


def parse_announcement(
    text: str, ticker: Optional[str] = None, **kwargs
) -> List[Dict[str, Any]]:
    """
    Convenience function to parse announcement text using default client.

    This function creates a new LLMClient instance with default configuration
    and parses the provided text.

    Args:
        text: The extracted text from the PDF announcement
        ticker: Optional fund ticker code for filtering results to this ticker
        **kwargs: Additional arguments passed to LLMClient constructor
                  (base_url, model, etc.)

    Returns:
        List of dictionaries containing extracted limit information

    Example:
        >>> result = parse_announcement("本基金将于2024年1月1日起暂停大额申购...", ticker="161005")
        >>> print(result[0]['is_purchase_limit_announcement'])
        True
    """
    client = LLMClient(**kwargs)
    return client.parse_announcement(text, ticker=ticker)


if __name__ == "__main__":
    """
    CLI mode for testing the LLM client with a text file.
    
    Usage:
        python src/data/llm_client.py extracted_text.txt [--ticker TICKER]
        
    The text file should contain the extracted text from a PDF announcement.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse fund announcement text with LLM"
    )
    parser.add_argument("text_file", help="Path to text file with announcement content")
    parser.add_argument(
        "--ticker", default=None, help="Fund ticker code to filter results"
    )
    args = parser.parse_args()

    if not os.path.exists(args.text_file):
        print(f"Error: File not found: {args.text_file}")
        sys.exit(1)

    # Read the text file
    with open(args.text_file, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"Processing file: {args.text_file}")
    print(f"Text length: {len(text)} characters")
    if args.ticker:
        print(f"Ticker filter: {args.ticker}")
    print("\n" + "=" * 60)

    # Parse the announcement
    try:
        result = parse_announcement(text, ticker=args.ticker)

        print(f"\nExtracted {len(result)} record(s):")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except LLMError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
