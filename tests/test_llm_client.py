"""
Unit tests for the LLM client module.

LLM 客户端模块的单元测试。

Tests cover:
测试覆盖：
- Successful API parsing  # 成功的 API 解析
- Non-limit announcement detection  # 非限购公告检测
- Connection error handling  # 连接错误处理
- Invalid JSON handling  # 无效 JSON 处理
- Prompt building verification  # 提示构建验证
- Date validation  # 日期验证
- Thinking token stripping  # 思考标记去除
- JSON extraction from free-form text  # 从自由格式文本中提取 JSON

Note: These tests use mocking to avoid requiring a running Ollama instance.
To run tests against a real Ollama server, set OLLAMA_TEST=1 environment variable.
注意：这些测试使用模拟来避免需要运行中的 Ollama 实例。
要在真实的 Ollama 服务器上运行测试，请设置 OLLAMA_TEST=1 环境变量。
"""

import json
import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add src to path for imports  # 添加 src 到路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.llm_client import LLMClient, LLMError, parse_announcement


def _make_chat_response(content: str) -> dict:
    """Helper to build a mock ollama.chat() return value.
    构建模拟 ollama.chat() 返回值的辅助函数。
    """
    return {"message": {"role": "assistant", "content": content}}


class TestLLMClient(unittest.TestCase):
    """Test cases for LLMClient class.
    LLMClient 类的测试用例。
    """

    def setUp(self):
        """Set up test fixtures.
        设置测试夹具。
        """
        self.client = LLMClient()
        self.mock_json = json.dumps(
            [
                {
                    "ticker": "161005",
                    "limit_amount": 100.0,
                    "start_date": "2024-01-01",
                    "end_date": "2024-03-01",
                    "announcement_type": "complete",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.95,
                }
            ]
        )

    def test_parse_announcement_success(self):
        """Test successful API call with complete announcement.
        测试完整公告的成功 API 调用。
        """
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(self.mock_json)

            result = self.client.parse_announcement("Test announcement text")

            # Verify API was called  # 验证 API 被调用
            mock_chat.assert_called_once()

            # Verify result is a list with one record  # 验证结果是包含一条记录的列表
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)

            # Verify output structure  # 验证输出结构
            self.assertIn("ticker", result[0])
            self.assertIn("limit_amount", result[0])
            self.assertIn("start_date", result[0])
            self.assertIn("end_date", result[0])
            self.assertIn("announcement_type", result[0])
            self.assertIn("is_purchase_limit_announcement", result[0])
            self.assertIn("confidence", result[0])

            # Verify values parsed correctly  # 验证值正确解析
            self.assertEqual(result[0]["ticker"], "161005")
            self.assertEqual(result[0]["limit_amount"], 100.0)
            self.assertEqual(result[0]["start_date"], "2024-01-01")
            self.assertEqual(result[0]["end_date"], "2024-03-01")
            self.assertEqual(result[0]["announcement_type"], "complete")
            self.assertTrue(result[0]["is_purchase_limit_announcement"])
            self.assertEqual(result[0]["confidence"], 0.95)

    def test_parse_announcement_not_limit(self):
        """Test handling of non-limit announcement.
        测试非限购公告的处理。
        """
        not_limit_json = json.dumps(
            [
                {
                    "ticker": "161005",
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": None,
                    "announcement_type": None,
                    "is_purchase_limit_announcement": False,
                    "confidence": 0.88,
                }
            ]
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(not_limit_json)

            result = self.client.parse_announcement("Quarterly report announcement")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertFalse(result[0]["is_purchase_limit_announcement"])
            self.assertIsNone(result[0]["limit_amount"])
            self.assertIsNone(result[0]["announcement_type"])

    def test_parse_announcement_connection_error(self):
        """Test handling of connection failure.
        测试连接失败的处理。
        """
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = ConnectionError("Connection refused")

            result = self.client.parse_announcement("Test text")

            # Should return list with error record, not raise
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertIn("error", result[0])
            self.assertIn("Connection error", result[0]["error"])
            self.assertFalse(result[0]["is_purchase_limit_announcement"])

    def test_parse_announcement_timeout(self):
        """Test handling of request timeout.
        测试请求超时的处理。
        """
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = TimeoutError("Request timed out")

            result = self.client.parse_announcement("Test text")

            # Should return list with error record, not raise
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertIn("error", result[0])
            self.assertIn("Timeout error", result[0]["error"])
            self.assertFalse(result[0]["is_purchase_limit_announcement"])

    def test_parse_announcement_invalid_json(self):
        """Test handling of malformed LLM response.
        测试格式错误的 LLM 响应的处理。
        """
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(
                "This is not valid JSON {{ invalid"
            )

            result = self.client.parse_announcement("Test text")

            # Should return list with error record due to JSON parsing failure  # 由于 JSON 解析失败应返回包含错误记录的列表
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertIn("error", result[0])
            self.assertIn("Invalid JSON", result[0]["error"])

    def test_parse_announcement_open_start(self):
        """Test parsing of open-start announcement type.
        测试 open-start 公告类型的解析。
        """
        open_start_json = json.dumps(
            [
                {
                    "ticker": "162411",
                    "limit_amount": 1000.0,
                    "start_date": None,
                    "end_date": "2024-06-30",
                    "announcement_type": "open-start",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.90,
                }
            ]
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(open_start_json)

            result = self.client.parse_announcement("Open start announcement")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["announcement_type"], "open-start")
            self.assertIsNone(result[0]["start_date"])
            self.assertEqual(result[0]["end_date"], "2024-06-30")

    def test_parse_announcement_end_only(self):
        """Test parsing of end-only announcement type.
        测试 end-only 公告类型的解析。
        """
        end_only_json = json.dumps(
            [
                {
                    "ticker": "161725",
                    "limit_amount": None,
                    "start_date": None,
                    "end_date": "2024-02-01",
                    "announcement_type": "end-only",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.92,
                }
            ]
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(end_only_json)

            result = self.client.parse_announcement("End only announcement")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["announcement_type"], "end-only")
            self.assertIsNone(result[0]["start_date"])
            self.assertEqual(result[0]["end_date"], "2024-02-01")
            self.assertIsNone(result[0]["limit_amount"])

    def test_parse_announcement_modify(self):
        """Test parsing of modify announcement type.
        测试 modify 公告类型的解析。
        """
        modify_json = json.dumps(
            [
                {
                    "ticker": "501018",
                    "limit_amount": 500.0,
                    "start_date": "2024-03-01",
                    "end_date": "2024-12-31",
                    "announcement_type": "modify",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.87,
                }
            ]
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(modify_json)

            result = self.client.parse_announcement("Modify announcement")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["announcement_type"], "modify")
            self.assertEqual(result[0]["limit_amount"], 500.0)

    def test_prompt_building(self):
        """Test that prompt is built correctly with Chinese instructions.
        测试提示使用中文指令正确构建。
        """
        text = "Test announcement"
        prompt = self.client._build_prompt(text)

        # Check for required elements in prompt  # 检查提示中的必需元素
        self.assertIn("基金公告解析器", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("complete", prompt)
        self.assertIn("open-start", prompt)
        self.assertIn("end-only", prompt)
        self.assertIn("modify", prompt)
        self.assertIn("Test announcement", prompt)

        # Check for noise handling instruction  # 检查噪声处理指令
        self.assertIn("PDF", prompt)
        self.assertIn("噪声", prompt)

        # Check for array output instruction  # 检查数组输出指令
        self.assertIn("JSON 数组", prompt)

        # Test with ticker parameter  # 使用 ticker 参数测试
        prompt_with_ticker = self.client._build_prompt(text, ticker="161005")
        self.assertIn("161005", prompt_with_ticker)

    def test_date_validation(self):
        """Test date validation helper.
        测试日期验证辅助函数。
        """
        # Valid dates  # 有效日期
        self.assertEqual(self.client._validate_date("2024-01-15"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024/01/15"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024年01月15日"), "2024-01-15")
        self.assertEqual(self.client._validate_date("2024.01.15"), "2024-01-15")

        # Invalid dates  # 无效日期
        self.assertIsNone(self.client._validate_date(""))
        self.assertIsNone(self.client._validate_date(None))
        self.assertIsNone(self.client._validate_date("invalid"))
        self.assertIsNone(self.client._validate_date("15-01-2024"))  # Wrong format

        # Edge cases  # 边缘情况
        self.assertIsNone(self.client._validate_date("null"))
        self.assertIsNone(self.client._validate_date("none"))

    def test_clean_output(self):
        """Test output cleaning and validation.
        测试输出清理和验证。
        """
        # Test with valid data (dict input -> list output)  # 测试有效数据（字典输入 -> 列表输出）
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
        self.assertIsInstance(cleaned, list)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["ticker"], "161005")
        self.assertEqual(cleaned[0]["confidence"], 0.95)

        # Test with missing fields  # 测试缺失字段
        raw_partial = {"ticker": "161005"}
        cleaned = self.client._clean_output(raw_partial)
        self.assertIsInstance(cleaned, list)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["ticker"], "161005")
        self.assertIsNone(cleaned[0]["limit_amount"])
        self.assertFalse(cleaned[0]["is_purchase_limit_announcement"])
        self.assertEqual(cleaned[0]["confidence"], 0.0)

        # Test confidence clamping  # 测试置信度钳制
        raw_high_conf = {"confidence": 1.5}
        cleaned = self.client._clean_output(raw_high_conf)
        self.assertEqual(cleaned[0]["confidence"], 1.0)

        raw_low_conf = {"confidence": -0.5}
        cleaned = self.client._clean_output(raw_low_conf)
        self.assertEqual(cleaned[0]["confidence"], 0.0)

        # Test with list input  # 测试列表输入
        raw_list = [
            {"ticker": "A", "confidence": 0.9},
            {"ticker": "B", "confidence": 0.8},
        ]
        cleaned = self.client._clean_output(raw_list)
        self.assertIsInstance(cleaned, list)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["ticker"], "A")
        self.assertEqual(cleaned[1]["ticker"], "B")

    def test_empty_text(self):
        """Test handling of empty text input.
        测试空文本输入的处理。
        """
        result = self.client.parse_announcement("")

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIn("Empty input text", result[0]["error"])
        self.assertFalse(result[0]["is_purchase_limit_announcement"])

    def test_whitespace_text(self):
        """Test handling of whitespace-only text.
        测试仅包含空白字符的文本的处理。
        """
        result = self.client.parse_announcement("   \n\t  ")

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIn("Empty input text", result[0]["error"])

    def test_convenience_function(self):
        """Test the module-level parse_announcement convenience function.
        测试模块级 parse_announcement 便捷函数。
        """
        with patch("src.data.llm_client.ollama.Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = _make_chat_response(self.mock_json)
            mock_client_cls.return_value = mock_instance

            result = parse_announcement("Test text")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "161005")
            self.assertTrue(result[0]["is_purchase_limit_announcement"])

    def test_json_with_code_blocks(self):
        """Test parsing JSON wrapped in markdown code blocks.
        测试解析包装在 markdown 代码块中的 JSON。
        """
        code_block_text = "```json\n" + self.mock_json + "\n```"

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(code_block_text)

            result = self.client.parse_announcement("Test text")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "161005")
            self.assertEqual(result[0]["confidence"], 0.95)

    def test_thinking_tokens_stripped(self):
        """Test that qwen3 thinking tokens are stripped before JSON extraction.
        测试 qwen3 思考标记在 JSON 提取前被去除。
        """
        thinking_response = (
            "<think>\nLet me analyze this announcement...\n"
            "This appears to be a purchase limit announcement.\n</think>\n"
            + self.mock_json
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(thinking_response)

            result = self.client.parse_announcement("Test text")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "161005")
            self.assertEqual(result[0]["limit_amount"], 100.0)
            self.assertTrue(result[0]["is_purchase_limit_announcement"])

    def test_thinking_tokens_with_code_blocks(self):
        """Test thinking tokens combined with markdown code blocks.
        测试思考标记与 markdown 代码块组合。
        """
        thinking_code_response = (
            "<think>\nThis is a limit announcement for fund 161005.\n</think>\n"
            "```json\n" + self.mock_json + "\n```"
        )

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(thinking_code_response)

            result = self.client.parse_announcement("Test text")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "161005")
            self.assertTrue(result[0]["is_purchase_limit_announcement"])

    def test_strip_thinking_tokens_static(self):
        """Test the static _strip_thinking_tokens method directly.
        直接测试静态 _strip_thinking_tokens 方法。
        """
        text_with_thinking = (
            '<think>Some internal reasoning here</think>\n{"result": "value"}'
        )
        stripped = LLMClient._strip_thinking_tokens(text_with_thinking)
        self.assertNotIn("<think>", stripped)
        self.assertIn('{"result": "value"}', stripped)

        # No thinking tokens  # 无思考标记
        plain = '{"result": "value"}'
        self.assertEqual(LLMClient._strip_thinking_tokens(plain), plain)

    def test_extract_json_from_response_static(self):
        """Test the static _extract_json_from_response method directly.
        直接测试静态 _extract_json_from_response 方法。
        """
        # Plain JSON object  # 普通 JSON 对象
        plain_json = '{"key": "value"}'
        self.assertEqual(LLMClient._extract_json_from_response(plain_json), plain_json)

        # JSON object in code block  # 代码块中的 JSON 对象
        code_block = '```json\n{"key": "value"}\n```'
        result = LLMClient._extract_json_from_response(code_block)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

        # JSON with thinking tokens  # 带思考标记的 JSON
        with_thinking = '<think>reasoning</think>\n{"key": "value"}'
        result = LLMClient._extract_json_from_response(with_thinking)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

        # No JSON at all  # 完全没有 JSON
        with self.assertRaises(ValueError):
            LLMClient._extract_json_from_response("No JSON here at all")

        # Plain JSON array  # 普通 JSON 数组
        plain_array = '[{"key": "value"}]'
        result = LLMClient._extract_json_from_response(plain_array)
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["key"], "value")

        # JSON array in code block  # 代码块中的 JSON 数组
        array_code_block = '```json\n[{"key": "value"}, {"key": "value2"}]\n```'
        result = LLMClient._extract_json_from_response(array_code_block)
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 2)

    def test_ollama_response_error(self):
        """Test handling of ollama.ResponseError.
        测试 ollama.ResponseError 的处理。
        """
        import ollama as ollama_module

        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.side_effect = ollama_module.ResponseError("Model not found")

            result = self.client.parse_announcement("Test text")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertIn("error", result[0])
            self.assertIn("Ollama API error", result[0]["error"])
            self.assertFalse(result[0]["is_purchase_limit_announcement"])

    def test_parse_announcement_multi_date(self):
        """Test parsing announcement with multiple non-consecutive dates.
        测试解析具有多个非连续日期的公告。
        """
        multi_date_json = json.dumps(
            [
                {
                    "ticker": "160119",
                    "limit_amount": 100.0,
                    "start_date": "2024-04-18",
                    "end_date": "2024-04-18",
                    "announcement_type": "complete",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.90,
                },
                {
                    "ticker": "160119",
                    "limit_amount": 100.0,
                    "start_date": "2024-04-21",
                    "end_date": "2024-04-21",
                    "announcement_type": "complete",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.90,
                },
                {
                    "ticker": "160119",
                    "limit_amount": 100.0,
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-01",
                    "announcement_type": "complete",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.90,
                },
            ]
        )
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(multi_date_json)
            result = self.client.parse_announcement("Multi date text", ticker="160119")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0]["start_date"], "2024-04-18")
            self.assertEqual(result[1]["start_date"], "2024-04-21")
            self.assertEqual(result[2]["start_date"], "2024-07-01")

    def test_parse_announcement_single_ticker_filter(self):
        """Test that ticker parameter is passed to prompt.
        测试 ticker 参数传递到提示。
        """
        with patch.object(self.client._client, "chat") as mock_chat:
            mock_chat.return_value = _make_chat_response(
                json.dumps(
                    [
                        {
                            "ticker": "160127",
                            "limit_amount": 1000.0,
                            "start_date": "2024-03-01",
                            "end_date": None,
                            "announcement_type": "complete",
                            "is_purchase_limit_announcement": True,
                            "confidence": 0.92,
                        }
                    ]
                )
            )
            result = self.client.parse_announcement(
                "Multi ticker text", ticker="160127"
            )
            # Verify ticker was included in the system message  # 验证 ticker 已包含在系统消息中
            call_args = mock_chat.call_args
            messages = call_args[1].get("messages") or call_args[0][0]
            system_msg = messages[0]["content"]
            self.assertIn("160127", system_msg)
            # Verify result only contains our ticker  # 验证结果仅包含我们的 ticker
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ticker"], "160127")

    def test_clean_output_wraps_single_dict(self):
        """Test that _clean_output wraps a single dict in a list.
        测试 _clean_output 将单个字典包装在列表中。
        """
        raw = {
            "ticker": "161005",
            "confidence": 0.9,
            "is_purchase_limit_announcement": True,
        }
        cleaned = self.client._clean_output(raw)
        self.assertIsInstance(cleaned, list)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["ticker"], "161005")

    def test_build_system_prompt_with_ticker(self):
        """Test that _build_system_prompt includes ticker when provided.
        测试 _build_system_prompt 在提供时包含 ticker。
        """
        prompt = self.client._build_system_prompt("161005")
        self.assertIn("161005", prompt)
        self.assertIn("仅提取该基金的限购信息", prompt)

    def test_build_system_prompt_without_ticker(self):
        """Test that _build_system_prompt works without ticker.
        测试 _build_system_prompt 在没有 ticker 时工作。
        """
        prompt = self.client._build_system_prompt()
        self.assertNotIn("仅提取该基金的限购信息", prompt)
        # Should still have the array output format  # 仍应具有数组输出格式
        self.assertIn("JSON 数组", prompt)


class TestLLMClientEnvironment(unittest.TestCase):
    """Test cases for environment variable handling.
    环境变量处理的测试用例。
    """

    @patch.dict(os.environ, {"OLLAMA_MODEL": "custom-model"})
    def test_custom_env_vars(self):
        """Test that environment variables are respected.
        测试环境变量被尊重。
        """
        client = LLMClient()
        # host is None by default (ollama SDK reads OLLAMA_HOST internally)  # host 默认为 None（ollama SDK 内部读取 OLLAMA_HOST）
        self.assertIsNone(client.host)
        self.assertEqual(client.model, "custom-model")

    def test_explicit_base_url(self):
        """Test that explicit base_url is stored.
        测试显式 base_url 被存储。
        """
        client = LLMClient(base_url="http://explicit:11434")
        self.assertEqual(client.host, "http://explicit:11434")

    def test_default_host_is_none(self):
        """Test that default host is None (lets ollama SDK pick default).
        测试默认 host 为 None（让 ollama SDK 选择默认值）。
        """
        client = LLMClient()
        self.assertIsNone(client.host)
        self.assertIsNone(client.base_url)

    def test_base_url_alias(self):
        """Test that base_url property returns host value.
        测试 base_url 属性返回 host 值。
        """
        client = LLMClient(base_url="http://test:11434")
        self.assertEqual(client.base_url, "http://test:11434")
        self.assertEqual(client.base_url, client.host)


@unittest.skipUnless(
    os.environ.get("OLLAMA_TEST") == "1", "Set OLLAMA_TEST=1 to run integration tests"
)
class TestLLMClientIntegration(unittest.TestCase):
    """
    Integration tests that require a running Ollama instance.
    需要运行中的 Ollama 实例的集成测试。

    To run these tests:
    运行这些测试：
        1. Install Ollama: https://ollama.com  # 安装 Ollama
        2. Pull a model: ollama pull qwen3:8b  # 拉取模型
        3. Start Ollama: ollama serve  # 启动 Ollama
        4. Run tests with: OLLAMA_TEST=1 python -m pytest tests/test_llm_client.py -v  # 运行测试
    """

    def setUp(self):
        """Set up real client.
        设置真实客户端。
        """
        self.client = LLMClient()

    def test_real_ollama_call(self):
        """Test with real Ollama API call.
        使用真实 Ollama API 调用测试。
        """
        sample_text = """
        富国天惠精选成长混合型证券投资基金(LOF)
        暂停大额申购、转换转入及定期定额投资业务的公告
        
        为保护基金份额持有人的利益，本基金将于2024年1月15日起暂停大额申购，
        单日单账户累计申购金额不得超过100元，恢复时间另行通知。
        """

        result = self.client.parse_announcement(sample_text, ticker="161005")

        # Result is now a list  # 结果现在是列表
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

        # Basic structure check on first record  # 第一条记录的基本结构检查
        self.assertIn("ticker", result[0])
        self.assertIn("is_purchase_limit_announcement", result[0])

        # Should detect this is a limit announcement  # 应检测到这是限购公告
        print(f"Real LLM response: {json.dumps(result, ensure_ascii=False, indent=2)}")

    def test_real_non_limit_announcement(self):
        """Test with non-limit announcement text.
        使用非限购公告文本测试。
        """
        non_limit_text = """
        关于旗下基金2024年年度报告的公告
        
        根据基金合同和招募说明书的有关规定，基金管理人将于2024年3月31日前
        披露本基金的2024年年度报告。
        """

        result = self.client.parse_announcement(non_limit_text)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

        print(
            f"Non-limit announcement response: {json.dumps(result, ensure_ascii=False, indent=2)}"
        )


class TestLLMClientCloud(unittest.TestCase):
    """Test cases for cloud (OpenAI-compatible) provider mode.
    云（OpenAI 兼容）提供者模式的测试用例。
    """

    def setUp(self):
        """Set up test fixtures with mock JSON response.
        使用模拟 JSON 响应设置测试夹具。
        """
        self.mock_json = json.dumps(
            [
                {
                    "ticker": "161005",
                    "limit_amount": 100.0,
                    "start_date": "2024-01-01",
                    "end_date": "2024-03-01",
                    "announcement_type": "complete",
                    "is_purchase_limit_announcement": True,
                    "confidence": 0.95,
                }
            ]
        )

    @patch.dict(
        os.environ,
        {"LLM_API_KEY": "sk-test-key", "LLM_URL": "https://api.test.com/v1"},
        clear=False,
    )
    @patch("src.data.llm_client.OpenAI")
    def test_cloud_mode_detected(self, MockOpenAI):
        """When LLM_API_KEY env var is set, client uses cloud provider.
        当 LLM_API_KEY 环境变量设置时，客户端使用云提供者。
        """
        mock_openai_instance = MagicMock()
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient()

        self.assertEqual(client._provider, "cloud")
        self.assertIsNotNone(client._openai_client)
        self.assertIsNone(client._client)
        self.assertEqual(client.host, "https://api.test.com/v1")
        MockOpenAI.assert_called_once_with(
            api_key="sk-test-key",
            base_url="https://api.test.com/v1",
        )

    @patch("src.data.llm_client.OpenAI")
    def test_cloud_mode_explicit_api_key(self, MockOpenAI):
        """When api_key passed to constructor, uses cloud mode regardless of env.
        当 api_key 传递给构造函数时，无论环境如何都使用云模式。
        """
        mock_openai_instance = MagicMock()
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient(
            api_key="sk-explicit-key",
            base_url="https://api.explicit.com/v1",
        )

        self.assertEqual(client._provider, "cloud")
        self.assertEqual(client._api_key, "sk-explicit-key")
        self.assertEqual(client.host, "https://api.explicit.com/v1")
        MockOpenAI.assert_called_once_with(
            api_key="sk-explicit-key",
            base_url="https://api.explicit.com/v1",
        )

    def test_ollama_mode_when_no_api_key(self):
        """When LLM_API_KEY not set, client uses ollama provider (existing behavior).
        当 LLM_API_KEY 未设置时，客户端使用 ollama 提供者（现有行为）。
        """
        # Ensure LLM_API_KEY is not set  # 确保 LLM_API_KEY 未设置
        env = os.environ.copy()
        env.pop("LLM_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            client = LLMClient()

            self.assertEqual(client._provider, "ollama")
            self.assertIsNone(client._openai_client)
            self.assertIsNotNone(client._client)

    @patch.dict(
        os.environ,
        {"LLM_API_KEY": "sk-test-key", "LLM_URL": "https://api.test.com/v1"},
        clear=False,
    )
    @patch("src.data.llm_client.OpenAI")
    def test_cloud_parse_announcement_success(self, MockOpenAI):
        """Cloud mode parse_announcement returns correct List[Dict].
        云模式 parse_announcement 返回正确的 List[Dict]。
        """
        mock_openai_instance = MagicMock()
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient()

        # Mock the chat completions response  # 模拟聊天完成响应
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = self.mock_json
        client._openai_client.chat.completions.create.return_value = mock_resp

        result = client.parse_announcement("Test announcement text")

        # Verify result structure  # 验证结果结构
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "161005")
        self.assertEqual(result[0]["limit_amount"], 100.0)
        self.assertEqual(result[0]["start_date"], "2024-01-01")
        self.assertEqual(result[0]["end_date"], "2024-03-01")
        self.assertEqual(result[0]["announcement_type"], "complete")
        self.assertTrue(result[0]["is_purchase_limit_announcement"])
        self.assertEqual(result[0]["confidence"], 0.95)

        # Verify the openai client was called  # 验证 openai 客户端被调用
        client._openai_client.chat.completions.create.assert_called_once()
        call_kwargs = client._openai_client.chat.completions.create.call_args[1]
        self.assertIn("messages", call_kwargs)

    @patch.dict(
        os.environ,
        {"LLM_API_KEY": "sk-test-key", "LLM_URL": "https://api.test.com/v1"},
        clear=False,
    )
    @patch("src.data.llm_client.OpenAI")
    def test_cloud_parse_announcement_api_error(self, MockOpenAI):
        """Cloud mode returns error record when API raises exception.
        当 API 抛出异常时云模式返回错误记录。
        """
        mock_openai_instance = MagicMock()
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient()

        # Make the API call raise an exception  # 使 API 调用抛出异常
        client._openai_client.chat.completions.create.side_effect = Exception(
            "API rate limit exceeded"
        )

        result = client.parse_announcement("Test text")

        # Should return error record, not raise  # 应返回错误记录，而不是抛出
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIn("API rate limit exceeded", result[0]["error"])
        self.assertFalse(result[0]["is_purchase_limit_announcement"])

    @patch.dict(
        os.environ,
        {
            "LLM_API_KEY": "sk-test-key",
            "LLM_URL": "https://api.test.com/v1",
            "LLM_MODEL": "deepseek-chat",
        },
        clear=False,
    )
    @patch("src.data.llm_client.OpenAI")
    def test_cloud_model_from_env(self, MockOpenAI):
        """When LLM_MODEL env var set, it's used as model name in cloud mode.
        当 LLM_MODEL 环境变量设置时，它在云模式中用作模型名称。
        """
        mock_openai_instance = MagicMock()
        MockOpenAI.return_value = mock_openai_instance

        client = LLMClient()

        self.assertEqual(client._provider, "cloud")
        self.assertEqual(client.model, "deepseek-chat")


if __name__ == "__main__":
    # Run tests with verbosity  # 以详细模式运行测试
    unittest.main(verbosity=2)
