"""
Unit tests for the LLM client module (Kimi K2.5 async version).

Tests cover:
- Response JSON parsing (_parse_response)
- System prompt building
- Record post-processing (fund_code fallback, limit_amount normalization)
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.llm_client import LLMClient


class TestParseResponse(unittest.TestCase):
    """Test _parse_response static method for extracting records from raw LLM output."""

    def test_valid_json_array(self):
        raw = json.dumps([
            {
                "fund_code": "160105",
                "action": "restrict",
                "restriction_type": "amount_limit",
                "effective_date": "2022-01-14",
                "limit_amount": 1000000,
            }
        ])
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fund_code"], "160105")
        self.assertEqual(result[0]["limit_amount"], 1000000)

    def test_json_wrapped_in_markdown(self):
        inner = json.dumps([{"fund_code": "160105", "action": "suspend"}])
        raw = f"```json\n{inner}\n```"
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "suspend")

    def test_json_with_surrounding_prose(self):
        inner = json.dumps([{"fund_code": "160105", "action": "resume"}])
        raw = f"Here is the extracted data:\n{inner}\nDone."
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "resume")

    def test_single_dict_wrapped_in_list(self):
        raw = json.dumps({"fund_code": "160105", "action": "restrict"})
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fund_code"], "160105")

    def test_dict_with_data_key(self):
        raw = json.dumps({"data": [{"fund_code": "160105"}]})
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fund_code"], "160105")

    def test_dict_with_records_key(self):
        raw = json.dumps({"records": [{"fund_code": "A"}, {"fund_code": "B"}]})
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 2)

    def test_empty_array(self):
        result = LLMClient._parse_response("[]")
        self.assertEqual(result, [])

    def test_invalid_json_no_brackets(self):
        result = LLMClient._parse_response("This is not JSON at all")
        self.assertEqual(result, [])

    def test_multiple_records(self):
        raw = json.dumps([
            {"fund_code": "165513", "effective_date": "2023-01-03", "action": "restrict"},
            {"fund_code": "165513", "effective_date": "2023-01-09", "action": "restrict"},
            {"fund_code": "165513", "effective_date": "2023-12-25", "action": "restrict"},
        ])
        result = LLMClient._parse_response(raw)
        self.assertEqual(len(result), 3)
        dates = [r["effective_date"] for r in result]
        self.assertEqual(dates, ["2023-01-03", "2023-01-09", "2023-12-25"])


class TestSystemPrompt(unittest.TestCase):
    """Test system prompt building."""

    def setUp(self):
        # Create client with dummy key (won't make API calls)
        os.environ["KIMI_API_KEY"] = "test-key"
        self.client = LLMClient(api_key="test-key")

    def test_prompt_without_ticker(self):
        prompt = self.client._build_system_prompt()
        self.assertIn("基金公告结构化数据提取专家", prompt)
        self.assertIn("restrict", prompt)
        self.assertIn("suspend", prompt)
        self.assertIn("resume", prompt)
        self.assertIn("invalidate", prompt)
        self.assertIn("adjust_rule", prompt)
        self.assertNotIn("仅提取该基金", prompt)

    def test_prompt_with_ticker(self):
        prompt = self.client._build_system_prompt(ticker="160105")
        self.assertIn("160105", prompt)
        self.assertIn("仅提取该基金", prompt)

    def test_prompt_contains_all_restriction_types(self):
        prompt = self.client._build_system_prompt()
        for rtype in [
            "amount_limit", "full_suspension", "holiday_suspension",
            "pre_holiday_suspension", "application_invalid", "rule_change",
        ]:
            self.assertIn(rtype, prompt)

    def test_prompt_contains_all_scopes(self):
        prompt = self.client._build_system_prompt()
        for scope in ["large_only", "all", "partial_channel"]:
            self.assertIn(scope, prompt)

    def test_prompt_contains_all_business_types(self):
        prompt = self.client._build_system_prompt()
        for biz in ["purchase", "fixed_invest", "convert_in", "redemption", "convert_out"]:
            self.assertIn(biz, prompt)


class TestLLMClientInit(unittest.TestCase):
    """Test client initialization."""

    def test_missing_api_key_raises(self):
        old = os.environ.pop("KIMI_API_KEY", None)
        try:
            with self.assertRaises(ValueError):
                LLMClient(api_key="")
        finally:
            if old:
                os.environ["KIMI_API_KEY"] = old

    def test_explicit_api_key(self):
        client = LLMClient(api_key="sk-test-123")
        self.assertEqual(client._api_key, "sk-test-123")


if __name__ == "__main__":
    unittest.main()
