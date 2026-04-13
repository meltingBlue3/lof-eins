"""
Announcement processor: async concurrent PDF parsing with Kimi K2.5.

Orchestrates the full pipeline:
1. Discover PDFs (标题含"申购"且不含"优惠")
2. Upload to Kimi file API → extract text → LLM structured extraction
3. Store records in subscription_restrictions table
4. Support progress tracking and resume

Usage:
    >>> from src.data.announcement_processor import AnnouncementProcessor
    >>> processor = AnnouncementProcessor(
    ...     db_path="data/real_all_lof/config/fund_status.db",
    ...     announcements_dir="data/real_all_lof/announcements"
    ... )
    >>> import asyncio
    >>> asyncio.run(processor.run())
"""

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 50
SAVE_INTERVAL = 50


class ProgressTracker:
    """Thread-safe progress tracking with periodic persistence."""

    def __init__(self, progress_file: Path):
        self.lock = asyncio.Lock()
        self.progress_file = progress_file
        self.processed: List[str] = []
        self.failed: List[str] = []
        self.results: List[dict] = []
        self.completed = 0
        self.fail_count = 0
        self.total = 0
        self.start_time = time.time()
        self._unsaved = 0

    def load(self):
        if self.progress_file.exists():
            data = json.loads(self.progress_file.read_text(encoding="utf-8"))
            self.processed = data.get("processed", [])
            self.failed = data.get("failed", [])
            self.results = data.get("results", [])

    def save(self):
        data = {
            "processed": self.processed,
            "failed": self.failed,
            "results": self.results,
        }
        self.progress_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def mark_done(self, rel_path: str, records: List[dict]):
        async with self.lock:
            self.results.extend(records)
            self.processed.append(rel_path)
            self.completed += 1
            self._unsaved += 1
            elapsed = time.time() - self.start_time
            rate = self.completed / elapsed * 60 if elapsed > 0 else 0
            print(
                f"\r  进度: {self.completed + self.fail_count}/{self.total} "
                f"(成功 {self.completed}, 失败 {self.fail_count}, "
                f"记录 {len(self.results)}, "
                f"{rate:.0f}/min, "
                f"已用 {elapsed:.0f}s)",
                end="",
                flush=True,
            )
            if self._unsaved >= SAVE_INTERVAL:
                self.save()
                self._unsaved = 0

    async def mark_failed(self, rel_path: str, error: str):
        async with self.lock:
            self.failed.append(rel_path)
            self.fail_count += 1
            self._unsaved += 1
            print(f"\n  失败: {rel_path}: {error}")


class AnnouncementProcessor:
    """
    Async concurrent processor for fund announcement PDFs.

    Attributes:
        db_path: Path to fund_status.db
        announcements_dir: Base directory with {ticker}/{date}_{title}.pdf structure
    """

    def __init__(
        self,
        db_path: Path | str,
        announcements_dir: Path | str,
        api_key: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.announcements_dir = Path(announcements_dir)
        self._api_key = api_key
        self._progress_file = self.db_path.parent / "parse_progress.json"

    def find_pdfs(self) -> List[str]:
        """
        Find all subscription-restriction-related PDFs.
        Rule: title contains '申购' AND does not contain '优惠'.
        Returns relative paths like "160105/2022-01-14_xxx.pdf".
        """
        pdfs = []
        for pdf_path in sorted(self.announcements_dir.glob("*/????-??-??_*.pdf")):
            title = pdf_path.stem
            if "申购" in title and "优惠" not in title:
                rel = pdf_path.relative_to(self.announcements_dir).as_posix()
                pdfs.append(rel)
        return pdfs

    async def _process_one(
        self,
        client: LLMClient,
        semaphore: asyncio.Semaphore,
        rel_path: str,
        tracker: ProgressTracker,
    ):
        """Process a single PDF file."""
        async with semaphore:
            pdf_full = self.announcements_dir / rel_path
            ticker = Path(rel_path).parts[0]
            try:
                records = await client.extract_from_pdf(
                    str(pdf_full), ticker, rel_path
                )
                await tracker.mark_done(rel_path, records)
            except Exception as e:
                await tracker.mark_failed(rel_path, str(e)[:120])

    async def run(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        limit: int = 0,
        file: str = "",
        retry_failed: bool = False,
        reset: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """
        Run the full processing pipeline.

        Args:
            concurrency: Max concurrent API calls.
            limit: Process at most N files (0 = all).
            file: Process only this specific file.
            retry_failed: Re-process previously failed files.
            reset: Clear progress and start fresh.
            dry_run: Only list files, don't process.

        Returns:
            Stats dict with completed, failed, total_records counts.
        """
        if reset:
            if self._progress_file.exists():
                self._progress_file.unlink()
            # Clear existing records
            self._clear_restrictions()
            print("已清除进度和数据")

        all_pdfs = self.find_pdfs()
        print(f"共找到 {len(all_pdfs)} 个申购限制相关PDF")

        tracker = ProgressTracker(self._progress_file)
        tracker.load()

        if file:
            pending = [file]
        elif retry_failed:
            pending = [f for f in tracker.failed if f in all_pdfs]
            tracker.failed = [f for f in tracker.failed if f not in pending]
            tracker.save()
            print(f"重试 {len(pending)} 个之前失败的文件")
        else:
            done = set(tracker.processed)
            pending = [f for f in all_pdfs if f not in done]

        print(f"待处理: {len(pending)} 个")

        if dry_run:
            for p in pending[:30]:
                print(f"  {p}")
            if len(pending) > 30:
                print(f"  ... 还有 {len(pending) - 30} 个")
            return {"completed": 0, "failed": 0, "total_records": 0, "pending": len(pending)}

        if limit > 0:
            pending = pending[:limit]

        if not pending:
            print("没有待处理的文件")
            return {"completed": 0, "failed": 0, "total_records": 0, "pending": 0}

        client = LLMClient(api_key=self._api_key)
        tracker.total = len(pending)
        tracker.start_time = time.time()

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            self._process_one(client, semaphore, p, tracker) for p in pending
        ]

        print(f"开始处理 {len(pending)} 个PDF，并发数 {concurrency}")
        await asyncio.gather(*tasks)
        print()

        # Save progress
        tracker.save()

        # Store records to DB
        if tracker.results:
            self._save_records(tracker.results)
            print(f"已写入 {len(tracker.results)} 条记录到 subscription_restrictions")

        elapsed = time.time() - tracker.start_time
        print(
            f"完成！成功 {tracker.completed}, 失败 {tracker.fail_count}, "
            f"共 {len(tracker.results)} 条记录, 耗时 {elapsed:.0f}s"
        )

        return {
            "completed": tracker.completed,
            "failed": tracker.fail_count,
            "total_records": len(tracker.results),
            "pending": 0,
        }

    def _save_records(self, records: List[dict]):
        """Insert records into subscription_restrictions table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_restrictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                fund_name TEXT,
                announcement_date DATE NOT NULL,
                effective_date DATE NOT NULL,
                end_date DATE,
                action TEXT NOT NULL,
                restriction_type TEXT,
                scope TEXT,
                limit_amount REAL,
                affected_business TEXT DEFAULT '[]',
                reason TEXT,
                source_file TEXT NOT NULL,
                fund_company TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        skipped = 0
        for r in records:
            # Skip records missing required fields
            if not r.get("effective_date") or not r.get("fund_code"):
                skipped += 1
                continue

            affected = r.get("affected_business", [])
            if isinstance(affected, list):
                affected = json.dumps(affected, ensure_ascii=False)

            cursor.execute(
                """
                INSERT INTO subscription_restrictions
                (fund_code, fund_name, announcement_date, effective_date, end_date,
                 action, restriction_type, scope, limit_amount, affected_business,
                 reason, source_file, fund_company)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.get("fund_code", ""),
                    r.get("fund_name"),
                    r.get("announcement_date", ""),
                    r.get("effective_date", ""),
                    r.get("end_date"),
                    r.get("action", ""),
                    r.get("restriction_type"),
                    r.get("scope"),
                    r.get("limit_amount"),
                    affected,
                    r.get("reason"),
                    r.get("source_file", ""),
                    r.get("fund_company"),
                ),
            )

        conn.commit()
        conn.close()
        if skipped:
            print(f"  [WARN] 跳过 {skipped} 条缺少关键字段的记录")

    def _clear_restrictions(self):
        """Clear all records from subscription_restrictions table."""
        if not self.db_path.exists():
            return
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM subscription_restrictions")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        conn.close()
