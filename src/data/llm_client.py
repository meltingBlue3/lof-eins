"""
Ollama LLM Client for parsing fund announcement PDFs.

This module provides an interface to a local Ollama LLM instance for extracting
structured purchase limit information from fund announcement text.

Setup:
    1. Install Ollama from https://ollama.com
    2. Pull a suitable model: `ollama pull qwen2.5:7b` (recommended for Chinese)
    3. Ensure Ollama is running: `ollama serve` (or let it auto-start)

Environment Variables:
    OLLAMA_URL: Base URL for Ollama API (default: http://localhost:11434)
    OLLAMA_MODEL: Model name to use (default: qwen2.5:7b)

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

import requests

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"  # Good for Chinese text processing


class LLMError(Exception):
    """Raised when LLM API call fails or returns invalid response."""

    pass


class LLMClient:
    """
    Client for interacting with local Ollama LLM to parse fund announcements.

    Attributes:
        base_url: The base URL for the Ollama API
        model: The model name to use for inference
        session: A requests.Session for connection pooling
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the LLM client.

        Args:
            base_url: Ollama API base URL. Defaults to OLLAMA_URL env var or localhost.
            model: Model name to use. Defaults to OLLAMA_MODEL env var or qwen2.5:7b.
        """
        self.base_url = base_url or os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        self.model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
        self.session = requests.Session()
        logger.info(f"Initialized LLMClient with model {self.model} at {self.base_url}")

    def _build_prompt(self, text: str) -> str:
        """
        Build a structured prompt for the LLM to extract purchase limit information.

        Args:
            text: The extracted text from the PDF announcement

        Returns:
            A formatted prompt string with instructions and few-shot examples
        """
        prompt = f"""You are a financial document parser specializing in Chinese fund announcements.

Your task is to extract purchase limit information from the following fund announcement text.
Analyze the text carefully and return a JSON object with the extracted information.

**Output Format (JSON):**
```json
{{
    "ticker": "string or null - Fund ticker code (e.g., '161005')",
    "limit_amount": "number or null - Maximum purchase amount in CNY (e.g., 100.0 for 100元)",
    "start_date": "YYYY-MM-DD or null - Limit start date",
    "end_date": "YYYY-MM-DD or null - Limit end date",
    "announcement_type": "complete|open-start|end-only|modify|null",
    "is_purchase_limit_announcement": "boolean - true if this is a purchase limit announcement",
    "confidence": "number 0-1 - Confidence score for this extraction"
}}
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
{{
    "ticker": "161005",
    "limit_amount": 100.0,
    "start_date": "2024-01-15",
    "end_date": "2024-03-01",
    "announcement_type": "complete",
    "is_purchase_limit_announcement": true,
    "confidence": 0.95
}}
```

Example 2 (Open-start announcement):
Input: "关于限制旗下基金大额申购业务的公告 即日起，本基金单日单账户申购限额调整为1000元，上述限制将维持至2024年6月30日。"
Output:
```json
{{
    "ticker": null,
    "limit_amount": 1000.0,
    "start_date": null,
    "end_date": "2024-06-30",
    "announcement_type": "open-start",
    "is_purchase_limit_announcement": true,
    "confidence": 0.90
}}
```

Example 3 (End-only announcement):
Input: "关于恢复旗下基金大额申购业务的公告 本基金将于2024年2月1日起恢复大额申购业务，取消此前100元的单日申购限额。"
Output:
```json
{{
    "ticker": null,
    "limit_amount": null,
    "start_date": null,
    "end_date": "2024-02-01",
    "announcement_type": "end-only",
    "is_purchase_limit_announcement": true,
    "confidence": 0.92
}}
```

**Important Notes:**
- If the text is NOT a purchase limit announcement (e.g., quarterly report, dividend announcement, manager change), set `is_purchase_limit_announcement: false`
- Use null for any field that is not clearly specified in the text
- Chinese dates may be in various formats (e.g., "2024年1月15日", "2024-01-15"), normalize to YYYY-MM-DD
- Amounts may be specified in different units (元, 万元), convert to numeric CNY

Now analyze the following announcement text:

---
{text}
---

Return ONLY the JSON object, no additional explanation."""
        return prompt

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
        # Match patterns like 2024-01-15, 2024/01/15, 2024年01月15日
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

    def _extract_amount(self, text: str) -> Optional[float]:
        """
        Extract numeric amount from Chinese text.

        Args:
            text: Text containing amount information

        Returns:
            Extracted amount as float, or None if not found
        """
        if not text:
            return None

        # Match patterns like "100元", "100.5元", "100万元", "100万"
        # Handle both Chinese and Arabic numerals
        patterns = [
            r"(\d+(?:\.\d+)?)\s*[万亿]元?",
            r"(\d+(?:\.\d+)?)\s*元",
            r"限额.*?([\d,]+(?:\.\d+)?)",
            r"限制.*?([\d,]+(?:\.\d+)?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                amount_str = match.group(1).replace(",", "")
                try:
                    amount = float(amount_str)
                    # Convert 万元 to yuan
                    if "万" in text[match.start() : match.end() + 5]:
                        amount *= 10000
                    return amount
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
        # Define default values for all fields
        cleaned = {
            "ticker": None,
            "limit_amount": None,
            "start_date": None,
            "end_date": None,
            "announcement_type": None,
            "is_purchase_limit_announcement": False,
            "confidence": 0.0,
        }

        # Update with actual values, validating as we go
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

    def parse_announcement(self, text: str, timeout: int = 60) -> Dict[str, Any]:
        """
        Parse fund announcement text and extract structured limit information.

        Args:
            text: The extracted text from the PDF announcement
            timeout: Request timeout in seconds (default: 60)

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

        # Build the prompt
        prompt = self._build_prompt(text)

        # Prepare the API request
        api_url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            logger.debug(f"Sending request to Ollama API: {api_url}")
            response = self.session.post(api_url, json=payload, timeout=timeout)
            response.raise_for_status()

            # Parse the response
            result = response.json()

            if "response" not in result:
                logger.error(f"Unexpected API response format: {result}")
                raise LLMError(f"Invalid API response: missing 'response' field")

            # Extract and parse the JSON response from the LLM
            llm_response_text = result["response"].strip()

            # Handle code block formatting if present
            if llm_response_text.startswith("```json"):
                llm_response_text = llm_response_text[7:]
            if llm_response_text.startswith("```"):
                llm_response_text = llm_response_text[3:]
            if llm_response_text.endswith("```"):
                llm_response_text = llm_response_text[:-3]

            llm_response_text = llm_response_text.strip()

            try:
                parsed = json.loads(llm_response_text)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                logger.debug(f"Raw response: {llm_response_text}")
                raise LLMError(f"Invalid JSON in LLM response: {e}")

            # Clean and validate the output
            cleaned = self._clean_output(parsed)

            logger.info(
                f"Successfully parsed announcement: ticker={cleaned['ticker']}, "
                f"type={cleaned['announcement_type']}, "
                f"is_limit={cleaned['is_purchase_limit_announcement']}"
            )

            return cleaned

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Ollama API at {self.base_url}: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Connection error: Cannot connect to Ollama at {self.base_url}. "
                f"Ensure Ollama is installed and running. Visit https://ollama.com for setup instructions.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"Request to Ollama API timed out after {timeout}s: {e}")
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Request to Ollama API failed: {e}")
            return {
                "ticker": None,
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.0,
                "error": f"Request error: {str(e)}",
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
        print("  OLLAMA_URL    - Ollama API URL (default: http://localhost:11434)")
        print("  OLLAMA_MODEL  - Model name (default: qwen2.5:7b)")
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
