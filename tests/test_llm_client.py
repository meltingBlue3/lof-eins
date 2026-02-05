"""
Unit tests for the LLM client module.

Tests cover:
- Successful API parsing
- Non-limit announcement detection
- Connection error handling
- Invalid JSON handling
- Prompt building verification
- Date validation
- Thinking token stripping
- JSON extraction from free-form text

Note: These tests use mocking to avoid requiring a running Ollama instance.
To run tests against a real Ollama server, set OLLAMA_TEST=1 environment variable.
"""

import json
import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.llm_client import LLMClient, LLMError, parse_announcement


def _make_chat_response(content: str) -> dict:
    """Helper to build a mock ollama.chat() return value."""
    return {"message": {"role": "assistant", "content": content}}


class TestLLMClient(unittest.TestCase):
    """Test cases for LLMClient class."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = LLMClient()
        self.mock_json = json.dumps(
            {
                "ticker": "161005",
                "limit_amount": 100.0,
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
                "announcement_type": "complete",
                "is_purchase_limit_announcement": True,
                "confidence": 0.95,
            }
        )

    def test_parse_announcement_success(self):
        """Test successful API call with complete announcement."""
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(self.mock_json)

            result = self.client.parse_announcement("Test announcement text")

            # Verify API was called
            mock_chat.assert_called_once()

            # Verify output structure
            self.assertIn("ticker", result)
            self.assertIn("limit_amount", result)
            self.assertIn("start_date", result)
            self.assertIn("end_date", result)
            self.assertIn("announcement_type", result)
            self.assertIn("is_purchase_limit_announcement", result)
            self.assertIn("confidence", result)

            # Verify values parsed correctly
            self.assertEqual(result["ticker"], "161005")
            self.assertEqual(result["limit_amount"], 100.0)
            self.assertEqual(result["start_date"], "2024-01-01")
            self.assertEqual(result["end_date"], "2024-03-01")
            self.assertEqual(result["announcement_type"], "complete")
            self.assertTrue(result["is_purchase_limit_announcement"])
            self.assertEqual(result["confidence"], 0.95)

    def test_parse_announcement_not_limit(self):
        """Test handling of non-limit announcement."""
        not_limit_json = json.dumps(
            {
                "ticker": "161005",
                "limit_amount": None,
                "start_date": None,
                "end_date": None,
                "announcement_type": None,
                "is_purchase_limit_announcement": False,
                "confidence": 0.88,
            }
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(not_limit_json)

            result = self.client.parse_announcement("Quarterly report announcement")

            self.assertFalse(result["is_purchase_limit_announcement"])
            self.assertIsNone(result["limit_amount"])
            self.assertIsNone(result["announcement_type"])

    def test_parse_announcement_connection_error(self):
        """Test handling of connection failure."""
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = ConnectionError("Connection refused")

            result = self.client.parse_announcement("Test text")

            # Should return error dict, not raise
            self.assertIn("error", result)
            self.assertIn("Connection error", result["error"])
            self.assertFalse(result["is_purchase_limit_announcement"])

    def test_parse_announcement_timeout(self):
        """Test handling of request timeout."""
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = TimeoutError("Request timed out")

            result = self.client.parse_announcement("Test text")

            # Should return error dict, not raise
            self.assertIn("error", result)
            self.assertIn("Timeout error", result["error"])
            self.assertFalse(result["is_purchase_limit_announcement"])

    def test_parse_announcement_invalid_json(self):
        """Test handling of malformed LLM response."""
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(
                "This is not valid JSON {{ invalid"
            )

            result = self.client.parse_announcement("Test text")

            # Should return error dict due to JSON parsing failure
            self.assertIn("error", result)
            self.assertIn("Invalid JSON", result["error"])

    def test_parse_announcement_open_start(self):
        """Test parsing of open-start announcement type."""
        open_start_json = json.dumps(
            {
                "ticker": "162411",
                "limit_amount": 1000.0,
                "start_date": None,
                "end_date": "2024-06-30",
                "announcement_type": "open-start",
                "is_purchase_limit_announcement": True,
                "confidence": 0.90,
            }
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(open_start_json)

            result = self.client.parse_announcement("Open start announcement")

            self.assertEqual(result["announcement_type"], "open-start")
            self.assertIsNone(result["start_date"])
            self.assertEqual(result["end_date"], "2024-06-30")

    def test_parse_announcement_end_only(self):
        """Test parsing of end-only announcement type."""
        end_only_json = json.dumps(
            {
                "ticker": "161725",
                "limit_amount": None,
                "start_date": None,
                "end_date": "2024-02-01",
                "announcement_type": "end-only",
                "is_purchase_limit_announcement": True,
                "confidence": 0.92,
            }
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(end_only_json)

            result = self.client.parse_announcement("End only announcement")

            self.assertEqual(result["announcement_type"], "end-only")
            self.assertIsNone(result["start_date"])
            self.assertEqual(result["end_date"], "2024-02-01")
            self.assertIsNone(result["limit_amount"])

    def test_parse_announcement_modify(self):
        """Test parsing of modify announcement type."""
        modify_json = json.dumps(
            {
                "ticker": "501018",
                "limit_amount": 500.0,
                "start_date": "2024-03-01",
                "end_date": "2024-12-31",
                "announcement_type": "modify",
                "is_purchase_limit_announcement": True,
                "confidence": 0.87,
            }
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(modify_json)

            result = self.client.parse_announcement("Modify announcement")

            self.assertEqual(result["announcement_type"], "modify")
            self.assertEqual(result["limit_amount"], 500.0)

    def test_prompt_building(self):
        """Test that prompt is built correctly with examples."""
        text = "Test announcement"
        prompt = self.client._build_prompt(text)

        # Check for required elements in prompt
        self.assertIn("financial document parser", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("complete", prompt)
        self.assertIn("open-start", prompt)
        self.assertIn("end-only", prompt)
        self.assertIn("modify", prompt)
        self.assertIn("Test announcement", prompt)

        # Check for example announcements
        self.assertIn("Example 1", prompt)
        self.assertIn("Example 2", prompt)
        self.assertIn("Example 3", prompt)

        # Check for Chinese context
        self.assertIn("Chinese", prompt)

    def test_date_validation(self):
        """Test date validation helper."""
        # Valid dates
        self.assertEqual(self.client._validate_date("2024-01-15"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024/01/15"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024年01月15日"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024.01.15"), "2024-01-15")

        # Invalid dates
        self.assertIsNone(self.client._validate_date(""))
        self.assertIsNone(self.client._validate_date(None))
        self.assertIsNone(self.client._validate_date("invalid"))
        self.assertIsNone(self.client._validate_date("15-01-2024"))  # Wrong format

        # Edge cases
        self.assertIsNone(self.client._validate_date("null"))
        self.assertIsNone(self.client._validate_date("none"))

    def test_clean_output(self):
        """Test output cleaning and validation."""
        # Test with valid data
        raw = {
            "ticker": "161005",
            "limit_amount": 100.0,
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "announcement_type": "complete",
            "is_purchase_limit_announcement": True,
            "confidence": 0.95,
        }
        cleaned = self.client._clean_output(raw)
        self.assertEqual(cleaned["ticker"], "161005")
        self.assertEqual(cleaned["confidence"], 0.95)

        # Test with missing fields
        raw_partial = {"ticker": "161005"}
        cleaned = self.client._clean_output(raw_partial)
        self.assertEqual(cleaned["ticker"], "161005")
        self.assertIsNone(cleaned["limit_amount"])
        self.assertFalse(cleaned["is_purchase_limit_announcement"])
        self.assertEqual(cleaned["confidence"], 0.0)

        # Test confidence clamping
        raw_high_conf = {"confidence": 1.5}
        cleaned = self.client._clean_output(raw_high_conf)
        self.assertEqual(cleaned["confidence"], 1.0)

        raw_low_conf = {"confidence": -0.5}
        cleaned = self.client._clean_output(raw_low_conf)
        self.assertEqual(cleaned["confidence"], 0.0)

    def test_empty_text(self):
        """Test handling of empty text input."""
        result = self.client.parse_announcement("")

        self.assertIn("error", result)
        self.assertIn("Empty input text", result["error"])
        self.assertFalse(result["is_purchase_limit_announcement"])

    def test_whitespace_text(self):
        """Test handling of whitespace-only text."""
        result = self.client.parse_announcement("   \n\t  ")

        self.assertIn("error", result)
        self.assertIn("Empty input text", result["error"])

    def test_convenience_function(self):
        """Test the module-level parse_announcement convenience function."""
        with patch("src.data.llm_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = _make_chat_response(self.mock_json)
            mock_client_cls.return_value = mock_instance

            result = parse_announcement("Test text")

            self.assertEqual(result["ticker"], "161005")
            self.assertTrue(result["is_purchase_limit_announcement"])

    def test_json_with_code_blocks(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        code_block_text = "```json\n" + self.mock_json + "\n```"

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(code_block_text)

            result = self.client.parse_announcement("Test text")

            self.assertEqual(result["ticker"], "161005")
            self.assertEqual(result["confidence"], 0.95)

    def test_thinking_tokens_stripped(self):
        """Test that qwen3 thinking tokens are stripped before JSON extraction."""
        thinking_response = (
            "<think>\nLet me analyze this announcement...\n"
            "This appears to be a purchase limit announcement.\n</think>\n"
            + self.mock_json
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(thinking_response)

            result = self.client.parse_announcement("Test text")

            self.assertEqual(result["ticker"], "161005")
            self.assertEqual(result["limit_amount"], 100.0)
            self.assertTrue(result["is_purchase_limit_announcement"])

    def test_thinking_tokens_with_code_blocks(self):
        """Test thinking tokens combined with markdown code blocks."""
        thinking_code_response = (
            "<think>\nThis is a limit announcement for fund 161005.\n</think>\n"
            "```json\n" + self.mock_json + "\n```"
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(thinking_code_response)

            result = self.client.parse_announcement("Test text")

            self.assertEqual(result["ticker"], "161005")
            self.assertTrue(result["is_purchase_limit_announcement"])

    def test_strip_thinking_tokens_static(self):
        """Test the static _strip_thinking_tokens method directly."""
        text_with_thinking = (
            "<think>Some internal reasoning here</think>\n"
            '{"result": "value"}'
        )
        stripped = LLMClient._strip_thinking_tokens(text_with_thinking)
        self.assertNotIn("<think>", stripped)
        self.assertIn('{"result": "value"}', stripped)

        # No thinking tokens
        plain = '{"result": "value"}'
        self.assertEqual(LLMClient._strip_thinking_tokens(plain), plain)

    def test_extract_json_from_response_static(self):
        """Test the static _extract_json_from_response method directly."""
        # Plain JSON
        plain_json = '{"key": "value"}'
        self.assertEqual(
            LLMClient._extract_json_from_response(plain_json), plain_json
        )

        # JSON in code block
        code_block = '```json\n{"key": "value"}\n```'
        result = LLMClient._extract_json_from_response(code_block)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

        # JSON with thinking tokens
        with_thinking = '<think>reasoning</think>\n{"key": "value"}'
        result = LLMClient._extract_json_from_response(with_thinking)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

        # No JSON at all
        with self.assertRaises(ValueError):
            LLMClient._extract_json_from_response("No JSON here at all")

    def test_ollama_response_error(self):
        """Test handling of ollama.ResponseError."""
        import ollama as ollama_module

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = ollama_module.ResponseError("Model not found")

            result = self.client.parse_announcement("Test text")

            self.assertIn("error", result)
            self.assertIn("Ollama API error", result["error"])
            self.assertFalse(result["is_purchase_limit_announcement"])


class TestLLMClientEnvironment(unittest.TestCase):
    """Test cases for environment variable handling."""

    @patch.dict(os.environ, {"OLLAMA_MODEL": "custom-model"})
    def test_custom_env_vars(self):
        """Test that environment variables are respected."""
        client = LLMClient()
        # host is None by default (ollama SDK reads OLLAMA_HOST internally)
        self.assertIsNone(client.host)
        self.assertEqual(client.model, "custom-model")

    def test_explicit_base_url(self):
        """Test that explicit base_url is stored."""
        client = LLMClient(base_url="http://explicit:11434")
        self.assertEqual(client.host, "http://explicit:11434")

    def test_default_host_is_none(self):
        """Test that default host is None (lets ollama SDK pick default)."""
        client = LLMClient()
        self.assertIsNone(client.host)
        self.assertIsNone(client.base_url)

    def test_base_url_alias(self):
        """Test that base_url property returns host value."""
        client = LLMClient(base_url="http://test:11434")
        self.assertEqual(client.base_url, "http://test:11434")
        self.assertEqual(client.base_url, client.host)


@unittest.skipUnless(
    os.environ.get("OLLAMA_TEST") == "1", "Set OLLAMA_TEST=1 to run integration tests"
)
class TestLLMClientIntegration(unittest.TestCase):
    """
    Integration tests that require a running Ollama instance.

    To run these tests:
        1. Install Ollama: https://ollama.com
        2. Pull a model: ollama pull qwen3:8b
        3. Start Ollama: ollama serve
        4. Run tests with: OLLAMA_TEST=1 python -m pytest tests/test_llm_client.py -v
    """

    def setUp(self):
        """Set up real client."""
        self.client = LLMClient()

    def test_real_ollama_call(self):
        """Test with real Ollama API call."""
        sample_text = """
        富国天惠精选成长混合型证券投资基金(LOF)
        暂停大额申购、转换转入及定期定额投资业务的公告
        
        为保护基金份额持有人的利益，本基金将于2024年1月15日起暂停大额申购，
        单日单账户累计申购金额不得超过100元，恢复时间另行通知。
        """

        result = self.client.parse_announcement(sample_text)

        # Basic structure check
        self.assertIn("ticker", result)
        self.assertIn("is_purchase_limit_announcement", result)

        # Should detect this is a limit announcement
        print(f"Real LLM response: {json.dumps(result, ensure_ascii=False, indent=2)}")

    def test_real_non_limit_announcement(self):
        """Test with non-limit announcement text."""
        non_limit_text = """
        关于旗下基金2024年年度报告的公告
        
        根据基金合同和招募说明书的有关规定，基金管理人将于2024年3月31日前
        披露本基金的2024年年度报告。
        """

        result = self.client.parse_announcement(non_limit_text)

        print(
            f"Non-limit announcement response: {json.dumps(result, ensure_ascii=False, indent=2)}"
        )


if __name__ == "__main__":
    # Run tests with verbosity
    unittest.main(verbosity=2)
