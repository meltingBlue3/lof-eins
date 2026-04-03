"""
LLM Client for parsing fund announcement PDFs via Kimi K2.5 API.

Uses Moonshot Kimi K2.5 with file upload API for PDF text extraction
and structured data extraction from fund announcements.

Environment Variables:
    KIMI_API_KEY: API key for Kimi (Moonshot) platform. Required.

Usage:
    >>> from src.data.llm_client import LLMClient
    >>> client = LLMClient()
    >>> records = await client.extract_from_pdf("path/to/file.pdf", "160105")
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

BASE_URL = "https://api.moonshot.cn/v1"
MODEL = "kimi-k2.5"

# Prompt directory: <project_root>/prompts/
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


SYSTEM_PROMPT_TEMPLATE = _load_prompt("system_prompt.md")


class LLMClient:
    """
    Async client for extracting subscription restriction data from PDFs
    using Kimi K2.5 file upload API + chat completion.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("KIMI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "KIMI_API_KEY not set. Set it as environment variable or pass api_key."
            )
        self._client = AsyncOpenAI(api_key=self._api_key, base_url=BASE_URL)

    async def upload_pdf(self, pdf_path: str) -> str:
        """Upload PDF to Kimi file API, return file_id."""
        with open(pdf_path, "rb") as f:
            file_obj = await self._client.files.create(file=f, purpose="file-extract")
        return file_obj.id

    async def get_file_content(self, file_id: str) -> str:
        """Retrieve extracted text from uploaded PDF via Kimi file API."""
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                f"{BASE_URL}/files/{file_id}/content",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.text

    async def delete_file(self, file_id: str):
        """Clean up uploaded file."""
        try:
            await self._client.files.delete(file_id)
        except Exception:
            pass

    def _build_system_prompt(self, ticker: Optional[str] = None) -> str:
        if ticker:
            ticker_instruction = (
                f"\n当前解析的公告属于基金代码 `{ticker}`。"
                "仅提取该基金的限购信息，忽略公告中提到的其他基金。"
            )
        else:
            ticker_instruction = ""
        return SYSTEM_PROMPT_TEMPLATE.format(ticker_instruction=ticker_instruction)

    async def extract_from_pdf(
        self, pdf_path: str, ticker: str, source_file: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Full pipeline: upload PDF → extract text → LLM parse → return records.

        Args:
            pdf_path: Absolute path to the PDF file.
            ticker: Fund code (from directory name).
            source_file: Relative path for source_file field (e.g. "160105/2022-01-14_xxx.pdf").

        Returns:
            List of subscription restriction records.
        """
        file_id = None
        try:
            file_id = await self.upload_pdf(pdf_path)
            pdf_text = await self.get_file_content(file_id)

            filename = Path(source_file or pdf_path).name
            ann_date = filename[:10] if len(filename) >= 10 else ""

            system_prompt = self._build_system_prompt(ticker)
            user_msg = (
                f"请从以下基金公告中提取申购限制相关的结构化数据。\n"
                f"目标基金代码: {ticker}（只提取该基金的记录，忽略公告中其他基金）\n"
                f"公告日期（从文件名提取）: {ann_date}\n\n"
                f"--- 公告正文 ---\n{pdf_text}\n--- 正文结束 ---\n\n"
                f"请严格按照系统提示中的JSON格式输出，只返回JSON数组。"
            )

            resp = await self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=1,
            )

            raw = resp.choices[0].message.content.strip()
            records = self._parse_response(raw)

            # Post-process each record
            for record in records:
                record["source_file"] = source_file or Path(pdf_path).name
                # Normalize limit_amount
                amt = record.get("limit_amount")
                if amt is not None:
                    try:
                        record["limit_amount"] = float(amt)
                    except (ValueError, TypeError):
                        record["limit_amount"] = None
                # Ensure fund_code from path
                if not record.get("fund_code") or record["fund_code"] == "multiple":
                    record["fund_code"] = ticker

            return records

        finally:
            if file_id:
                await self.delete_file(file_id)

    @staticmethod
    def _parse_response(raw: str) -> List[Dict[str, Any]]:
        """Parse LLM response text into a list of records."""
        # Try direct parse
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Extract JSON array from markdown/prose
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
            else:
                return []

        if isinstance(data, dict):
            for key in ("data", "records", "results"):
                if key in data:
                    data = data[key]
                    break
            else:
                data = [data]

        if not isinstance(data, list):
            return []

        return data
