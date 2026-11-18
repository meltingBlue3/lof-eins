"""
OpenAI-compatible chat client for the v2 pipeline.

v2 流水线的 LLM 客户端：任意 OpenAI 兼容端点（目前是本地网关），通过环境变量配置，
支持 tool calling，对网络错误、限流和 5xx 做指数退避重试。

Configuration (`.env` at the project root, never committed):

    LOF_LLM_BASE_URL   e.g. http://127.0.0.1:3425/v1
    LOF_LLM_API_KEY
    LOF_LLM_MODEL      e.g. workbuddy/glm-5.3-flash
    LOF_LLM_REASONING  optional: low / medium / high, sent as `reasoning_effort`
    LOF_LLM_TIMEOUT    optional seconds per request (default 120)
    LOF_LLM_MAX_RETRIES optional (default 4)

The prefix keeps these apart from the legacy Kimi client's settings and from any
OPENAI_* variables in the user's shell.
"""

import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import openai

ENV_PREFIX = "LOF_LLM_"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str = ""
    reasoning: Optional[str] = None
    timeout: float = 120.0
    max_retries: int = 4
    backoff_base: float = 1.0
    backoff_max: float = 30.0

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, load_dotenv_file: bool = True) -> "LLMConfig":
        """Read LOF_LLM_* settings; `env` overrides os.environ (tests). Raises ValueError naming what is missing."""
        if env is None:
            if load_dotenv_file:
                try:
                    from dotenv import load_dotenv
                    load_dotenv(PROJECT_ROOT / ".env", override=False)
                except ImportError:
                    pass
            env = os.environ
        get = lambda k, d=None: (env.get(ENV_PREFIX + k) or d)  # noqa: E731
        missing = [ENV_PREFIX + k for k in ("BASE_URL", "API_KEY", "MODEL") if not get(k)]
        if missing:
            raise ValueError(f"missing LLM settings: {', '.join(missing)} (put them in .env)")
        return cls(
            base_url=get("BASE_URL"),
            api_key=get("API_KEY"),
            model=get("MODEL"),
            reasoning=get("REASONING"),
            timeout=float(get("TIMEOUT", 120)),
            max_retries=int(get("MAX_RETRIES", 4)),
        )


@dataclass
class ChatResult:
    content: str
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]
    reasoning: Optional[str]
    finish_reason: Optional[str]
    usage: Dict[str, int]
    model: str
    raw: Dict[str, Any]


def parse_json_lenient(text: Optional[str]) -> Optional[Any]:
    """Parse JSON from model output: plain, fenced in ``` blocks, or embedded in prose. None if nothing parses."""
    if not text:
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", s):
        try:
            return dec.raw_decode(s[m.start():])[0]
        except json.JSONDecodeError:
            continue
    return None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in RETRYABLE_STATUS
    return False


def _retry_after(exc: BaseException) -> Optional[float]:
    resp = getattr(exc, "response", None)
    value = resp.headers.get("retry-after") if resp is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class ChatLLM:
    """Thread-safe wrapper around one OpenAI-compatible endpoint."""

    def __init__(self, config: LLMConfig, client: Any = None, sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self._client = client or openai.OpenAI(base_url=config.base_url, api_key=config.api_key,
                                               timeout=config.timeout, max_retries=0)
        self._sleep = sleep
        self._lock = threading.Lock()
        self.usage = {"requests": 0, "retries": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _backoff(self, attempt: int, exc: BaseException) -> float:
        hinted = _retry_after(exc)
        if hinted is not None:
            return min(hinted, self.config.backoff_max)
        base = min(self.config.backoff_max, self.config.backoff_base * (2 ** attempt))
        return base * (0.5 + random.random() / 2)

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[list] = None, tool_choice: Any = None,
             reasoning: Optional[str] = None, temperature: Optional[float] = None, **extra) -> ChatResult:
        """
        One chat completion with retries. When `tools` are given, the first tool call's arguments are
        parsed into `tool_args`; if the model answered in plain text instead, JSON found in the content
        is used as a fallback.
        """
        kwargs: Dict[str, Any] = {"model": self.config.model, "messages": messages, **extra}
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        effort = reasoning or self.config.reasoning
        if effort:
            kwargs["reasoning_effort"] = effort
        if temperature is not None:
            kwargs["temperature"] = temperature

        attempt = 0
        while True:
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - classified below
                if not is_retryable(exc) or attempt >= self.config.max_retries:
                    raise
                with self._lock:
                    self.usage["retries"] += 1
                self._sleep(self._backoff(attempt, exc))
                attempt += 1

        choice = resp.choices[0]
        msg = choice.message
        extra_fields = getattr(msg, "model_extra", None) or {}
        reasoning_text = getattr(msg, "reasoning_content", None) or extra_fields.get("reasoning_content")
        tool_name, tool_args = None, None
        calls = getattr(msg, "tool_calls", None) or []
        if calls:
            tool_name = calls[0].function.name
            tool_args = parse_json_lenient(calls[0].function.arguments)
        elif tools:
            tool_args = parse_json_lenient(msg.content)
        if tool_args is not None and not isinstance(tool_args, dict):
            tool_args = None

        usage = getattr(resp, "usage", None)
        u = {"prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
             "completion_tokens": getattr(usage, "completion_tokens", 0) or 0}
        with self._lock:
            self.usage["requests"] += 1
            self.usage["prompt_tokens"] += u["prompt_tokens"]
            self.usage["completion_tokens"] += u["completion_tokens"]
        raw = resp.model_dump() if hasattr(resp, "model_dump") else {}
        return ChatResult(content=msg.content or "", tool_name=tool_name, tool_args=tool_args,
                          reasoning=reasoning_text, finish_reason=getattr(choice, "finish_reason", None),
                          usage=u, model=getattr(resp, "model", self.config.model), raw=raw)
