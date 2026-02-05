"""
Ollama LLM Client for parsing fund announcement PDFs.

This module provides an interface to a local Ollama LLM instance for extracting
structured purchase limit information from fund announcement text.

Setup:
    1. Install Ollama from https://ollama.com
    2. Pull a suitable model: `ollama pull qwen3:8b` (recommended for Chinese)
    3. Ensure Ollama is running: `ollama serve` (or let it auto-start)

Environment Variables:
    OLLAMA_HOST: Base URL for Ollama API (default: http://localhost:11434)
    OLLAMA_MODEL: Model name to use (default: qwen3:8b)

Example Usage:
    >>> from src.data.llm_client import LLMClient, parse_announcement
    >>>
    >>> # Using the client class
    >>> client = LLMClient()
    >>> result = client.parse_announcement(extracted_text)
    >>>
    >>> # Using the convenience function
    >>> result = parse_announcement(extracted_text)
    >>>
    >>> print(result)
    {
        "ticker": "161005",
        "limit_amount": 100.0,
        "start_date": "2024-01-01",
        "end_date": "2024-03-01",
        "announcement_type": "complete",
        "is_purchase_limit_announcement": True,
        "confidence": 0.95
    }
"""

import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional

import ollama

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_MODEL = "qwen3:8b"  # Good for Chinese text processing
MAX_TEXT_LENGTH = 8000  # Truncate input text to prevent context window overflow

# System prompt: instructions, schema, and few-shot examples
SYSTEM_PROMPT = """You are a financial document parser specializing in Chinese fund announcements.

Your task is to extract purchase limit information from the provided fund announcement text.
Analyze the text carefully and return a JSON object with the extracted information.

**Output Format (JSON):**
```json
{
    "ticker": "string or null - Fund ticker code (e.g., '161005')",
    "limit_amount": "number or null - Maximum purchase amount in CNY (e.g., 100.0 for 100元)",
    "start_date": "YYYY-MM-DD or null - Limit start date",
    "end_date": "YYYY-MM-DD or null - Limit end date",
    "announcement_type": "complete|open-start|end-only|modify|null",
    "is_purchase_limit_announcement": "boolean - true if this is a purchase limit announcement",
    "confidence": "number 0-1 - Confidence score for this extraction"
}
```

**Announcement Type Definitions:**
1. **complete**: Has both start_date and end_date (完整公告 - 限购开始和结束日期都明确)
2. **open-start**: Only has end_date, limit is already active (开放开始 - 已经开始，只告知结束日期)
3. **end-only**: Announces end/closing of an existing limit (仅结束 - 宣布取消或结束限购)
4. **modify**: Changes parameters of an existing limit (修改 - 修改限购金额或日期)

**Field Guidelines:**
- ticker: Extract fund code if present, otherwise null
- limit_amount: Numeric value only (e.g., 100 for "100元"), use null if unlimited or not specified
- start_date: Use YYYY-MM-DD format, null if not specified
- end_date: Use YYYY-MM-DD format, null if open-ended or not specified
- announcement_type: One of the four types above, or null if unclear
- is_purchase_limit_announcement: Set to false if this is not a purchase restriction announcement (e.g., regular report, dividend notice, etc.)
- confidence: Your confidence in this extraction (0.0-1.0). Use lower values for ambiguous cases.

**Few-shot Examples:**

Example 1 (Complete announcement):
Input: "富国天惠精选成长混合型证券投资基金(LOF)暂停大额申购、转换转入及定期定额投资业务的公告 为保护基金份额持有人的利益，本基金将于2024年1月15日起暂停大额申购，单日单账户累计申购金额不得超过100元，恢复时间另行通知。预计恢复时间为2024年3月1日。"
Output:
```json
{
    "ticker": "161005",
    "limit_amount": 100.0,
    "start_date": "2024-01-15",
    "end_date": "2024-03-01",
    "announcement_type": "complete",
    "is_purchase_limit_announcement": true,
    "confidence": 0.95
}
```

Example 2 (Open-start announcement):
Input: "关于限制旗下基金大额申购业务的公告 即日起，本基金单日单账户申购限额调整为1000元，上述限制将维持至2024年6月30日。"
Output:
```json
{
    "ticker": null,
    "limit_amount": 1000.0,
    "start_date": null,
    "end_date": "2024-06-30",
    "announcement_type": "open-start",
    "is_purchase_limit_announcement": true,
    "confidence": 0.90
}
```

Example 3 (End-only announcement):
Input: "关于恢复旗下基金大额申购业务的公告 本基金将于2024年2月1日起恢复大额申购业务，取消此前100元的单日申购限额。"
Output:
```json
{
    "ticker": null,
    "limit_amount": null,
    "start_date": null,
    "end_date": "2024-02-01",
    "announcement_type": "end-only",
    "is_purchase_limit_announcement": true,
    "confidence": 0.92
}
```

**Important Notes:**
- If the text is NOT a purchase limit announcement (e.g., quarterly report, dividend announcement, manager change), set `is_purchase_limit_announcement: false`
- Use null for any field that is not clearly specified in the text
- Chinese dates may be in various formats (e.g., "2024年1月15日", "2024-01-15"), normalize to YYYY-MM-DD
- Amounts may be specified in different units (元, 万元), convert to numeric CNY

Return ONLY the JSON object, no additional explanation."""


class LLMError(Exception):
    """Raised when LLM API call fails or returns invalid response."""

    pass


class LLMClient:
    """
    Client for interacting with local Ollama LLM to parse fund announcements.

    Uses the ollama Python SDK with the Chat API for reliable instruction-following.

    Attributes:
        host: The base URL for the Ollama API
        model: The model name to use for inference
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the LLM client.

        Args:
            base_url: Ollama API base URL. If None, the ollama SDK uses its own
                      default (reads OLLAMA_HOST env var, falls back to 127.0.0.1:11434).
            model: Model name to use. Defaults to OLLAMA_MODEL env var or qwen3:8b.
        """
        self.host = base_url  # None lets ollama SDK pick its default
        self.model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
        # Only pass host when explicitly set; otherwise let the SDK resolve it
        # (avoids localhost → IPv6 issues on Windows)
        if self.host:
            self._client = ollama.Client(host=self.host)
        else:
            self._client = ollama.Client()
        logger.info(f"Initialized LLMClient with model {self.model}")

    # Keep base_url as an alias for backward compatibility
    @property
    def base_url(self) -> Optional[str]:
        return self.host

    def _build_prompt(self, text: str) -> str:
        """
        Build the system prompt with instructions and few-shot examples.

        This is kept for backward compatibility and testing. The actual prompt
        sent to the model is split into system + user messages in parse_announcement().

        Args:
            text: The extracted text from the PDF announcement

        Returns:
            A formatted prompt string with instructions and few-shot examples
        """
        return f"""{SYSTEM_PROMPT}

Now analyze the following announcement text:

---
{text}
---

Return ONLY the JSON object, no additional explanation."""

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
        Extract JSON object from free-form LLM response text.

        Handles markdown code blocks, thinking tokens, and surrounding prose.

        Args:
            text: LLM response text potentially containing JSON

        Returns:
            Extracted JSON string

        Raises:
            ValueError: If no JSON object can be found
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

        raise ValueError(f"No valid JSON object found in response")

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

    def _clean_output(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean and validate the LLM output, ensuring all required fields exist.

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

    def parse_announcement(self, text: str, timeout: int = 120) -> Dict[str, Any]:
        """
        Parse fund announcement text and extract structured limit information.

        Uses the Ollama Chat API with system/user message separation for reliable
        instruction-following. Input text is truncated to prevent context overflow.

        Args:
            text: The extracted text from the PDF announcement
            timeout: Request timeout in seconds (default: 120)

        Returns:
            Dictionary containing extracted information with keys:
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
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": "Empty input text",
            }

        # Truncate long texts to prevent context window overflow
        truncated_text = text[:MAX_TEXT_LENGTH]
        if len(text) > MAX_TEXT_LENGTH:
            logger.info(
                f"Truncated input from {len(text)} to {MAX_TEXT_LENGTH} characters"
            )

        # Build messages for the Chat API (system + user separation)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"文档内容如下：\n{truncated_text}"},
        ]

        try:
            logger.debug(f"Sending chat request to Ollama")
            response = self._client.chat(
                model=self.model,
                messages=messages,
                format="json",
            )

            # Extract the response content
            llm_response_text = response["message"]["content"]
            logger.debug(f"Raw LLM response length: {len(llm_response_text)} chars")

            # Extract JSON from the response (handles thinking tokens, code blocks)
            try:
                json_str = self._extract_json_from_response(llm_response_text)
                parsed = json.loads(json_str)
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"Failed to extract JSON from LLM response: {e}")
                logger.debug(f"Raw response: {llm_response_text[:500]}")
                return {
                    "ticker": None,
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.0,
                    "error": f"Invalid JSON in LLM response: {e}",
                }

            # Clean and validate the output
            cleaned = self._clean_output(parsed)

            logger.info(
                f"Successfully parsed announcement: ticker={cleaned['ticker']}, "
                f"type={cleaned['announcement_type']}, "
                f"is_limit={cleaned['is_purchase_limit_announcement']}"
            )

            return cleaned

        except ollama.ResponseError as e:
            logger.error(f"Ollama API error: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Ollama API error: {str(e)}",
            }
        except ConnectionError as e:
            host_display = self.host or "default (127.0.0.1:11434)"
            logger.error(f"Failed to connect to Ollama at {host_display}: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Connection error: Cannot connect to Ollama at {host_display}. "
                f"Ensure Ollama is installed and running. Visit https://ollama.com for setup instructions.",
            }
        except TimeoutError as e:
            logger.error(f"Request to Ollama timed out after {timeout}s: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Timeout error: Request took longer than {timeout} seconds",
            }
        except LLMError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during parsing: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Unexpected error: {str(e)}",
            }


def parse_announcement(text: str, **kwargs) -> Dict[str, Any]:
    """
    Convenience function to parse announcement text using default client.

    This function creates a new LLMClient instance with default configuration
    and parses the provided text.

    Args:
        text: The extracted text from the PDF announcement
        **kwargs: Additional arguments passed to LLMClient constructor
                  (base_url, model, etc.)

    Returns:
        Dictionary containing extracted limit information

    Example:
        >>> result = parse_announcement("本基金将于2024年1月1日起暂停大额申购...")
        >>> print(result['is_purchase_limit_announcement'])
        True
    """
    client = LLMClient(**kwargs)
    return client.parse_announcement(text)


if __name__ == "__main__":
    """
    CLI mode for testing the LLM client with a text file.
    
    Usage:
        python src/data/llm_client.py extracted_text.txt
        
    The text file should contain the extracted text from a PDF announcement.
    """
    if len(sys.argv) < 2:
        print("Usage: python src/data/llm_client.py <text_file_path>")
        print("\nExample:")
        print("  python src/data/llm_client.py announcement_text.txt")
        print("\nEnvironment Variables:")
        print("  OLLAMA_HOST   - Ollama API URL (default: http://localhost:11434)")
        print("  OLLAMA_MODEL  - Model name (default: qwen3:8b)")
        sys.exit(1)

    text_file = sys.argv[1]

    if not os.path.exists(text_file):
        print(f"Error: File not found: {text_file}")
        sys.exit(1)

    # Read the text file
    with open(text_file, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"Processing file: {text_file}")
    print(f"Text length: {len(text)} characters")
    print("\n" + "=" * 60)

    # Parse the announcement
    try:
        result = parse_announcement(text)

        print("\nExtracted Information:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except LLMError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
