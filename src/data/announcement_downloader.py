"""
Announcement Downloader for LOF funds.

Downloads announcement PDFs from Eastmoney within each fund's backtest period.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests


class AnnouncementDownloader:
    """Downloads LOF fund announcement PDFs within backtest date ranges.

    Attributes:
        data_dir: Root directory for LOF data (market data required).
        announcement_type: 0=all announcements, 5=periodic reports.
        page_size: Number of announcements per API page.
        delay: Delay between requests in seconds.
    """

    API_URL = "https://api.fund.eastmoney.com/f10/JJGG"
    PDF_URL_TEMPLATE = "http://pdf.dfcfw.com/pdf/H2_{doc_id}_1.pdf"

    def __init__(
        self,
        data_dir: str = "./data/real_all_lof",
        announcement_type: int = 0,
        page_size: int = 50,
        delay: float = 1.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.announcement_type = announcement_type
        self.page_size = page_size
        self.delay = delay

        self.market_dir = self.data_dir / "market"
        self.announcements_dir = self.data_dir / "announcements"

        if not self.market_dir.exists():
            raise FileNotFoundError(f"Market directory not found: {self.market_dir}")

    @staticmethod
    def clean_filename(text: str, max_length: int = 120) -> str:
        """Clean filename for Windows compatibility."""
        cleaned = re.sub(r"[\\/:*?\"<>|]", "_", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip()
        return cleaned or "announcement"

    def list_available_tickers(self) -> List[str]:
        """Discover available LOF tickers from market data directory."""
        return sorted([f.stem for f in self.market_dir.glob("*.parquet")])

    def get_fund_date_range(self, ticker: str) -> Tuple[str, str]:
        """Get backtest date range from market data parquet file."""
        market_path = self.market_dir / f"{ticker}.parquet"
        if not market_path.exists():
            raise FileNotFoundError(f"Market data not found: {market_path}")

        df = pd.read_parquet(market_path)
        if "date" not in df.columns:
            raise ValueError(f"Market data missing 'date' column: {market_path}")

        df["date"] = pd.to_datetime(df["date"])
        if df["date"].isna().all():
            raise ValueError(f"Market data has invalid dates: {market_path}")

        start_date = df["date"].min().strftime("%Y-%m-%d")
        end_date = df["date"].max().strftime("%Y-%m-%d")
        return start_date, end_date

    def _build_headers(self, fund_code: str) -> Dict[str, str]:
        return {
            "Referer": f"http://fundf10.eastmoney.com/jjgg_{fund_code}.html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

    def get_announcement_list(self, fund_code: str, page_index: int = 1) -> List[Dict]:
        """Fetch announcement list from Eastmoney API with pagination."""
        params = {
            "fundcode": fund_code,
            "pageIndex": page_index,
            "pageSize": self.page_size,
            "type": self.announcement_type,
            "_": int(time.time() * 1000),
        }

        try:
            resp = requests.get(
                self.API_URL,
                params=params,
                headers=self._build_headers(fund_code),
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"[ERROR] API request failed ({fund_code} p{page_index}): {exc}")
            return []

        match = re.search(r"\{.*\}", resp.text, re.S)
        if not match:
            print(f"[WARN] No JSON payload found ({fund_code} p{page_index})")
            return []

        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError as exc:
            print(f"[WARN] JSON decode failed ({fund_code} p{page_index}): {exc}")
            return []

        data = payload.get("Data")
        if isinstance(data, dict):
            return data.get("Data", []) or []
        if isinstance(data, list):
            return data
        return []

    def _parse_publish_date(self, publish_date: str) -> Optional[pd.Timestamp]:
        if not publish_date:
            return None
        try:
            return pd.to_datetime(publish_date)
        except (ValueError, TypeError):
            return None

    def get_all_announcements(
        self,
        fund_code: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """Get ALL announcements for a fund within date range."""
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        all_items: List[Dict] = []
        page_index = 1

        while True:
            items = self.get_announcement_list(fund_code, page_index=page_index)
            if not items:
                break

            for item in items:
                publish_dt = self._parse_publish_date(item.get("PUBLISHDATE"))
                if publish_dt is None:
                    continue
                if start_dt <= publish_dt <= end_dt:
                    all_items.append(item)

            if len(items) < self.page_size:
                break

            page_index += 1
            if self.delay > 0:
                time.sleep(self.delay)

        return all_items

    def download_pdf(self, doc_id: str, filepath: str, max_retries: int = 3) -> bool:
        """Download single PDF with retry logic."""
        pdf_url = self.PDF_URL_TEMPLATE.format(doc_id=doc_id)
        target_path = Path(filepath)
        temp_path = target_path.with_suffix(target_path.suffix + ".part")

        for attempt in range(1, max_retries + 1):
            try:
                with requests.get(
                    pdf_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    stream=True,
                    timeout=30,
                ) as resp:
                    if resp.status_code != 200:
                        raise requests.RequestException(f"HTTP {resp.status_code}")

                    with open(temp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)

                temp_path.replace(target_path)
                return True
            except requests.RequestException as exc:
                print(f"[WARN] PDF download failed ({doc_id}) attempt {attempt}: {exc}")
            except OSError as exc:
                print(f"[WARN] File write failed ({target_path}): {exc}")

            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

            if self.delay > 0:
                time.sleep(self.delay * attempt)

        return False

    def download_fund_announcements(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """Download all announcements for a single fund."""
        if start_date is None or end_date is None:
            start_date, end_date = self.get_fund_date_range(ticker)

        output_dir = self.announcements_dir / ticker
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n>>> {ticker} | Date Range: {start_date} ~ {end_date}")
        announcements = self.get_all_announcements(ticker, start_date, end_date)

        stats = {"downloaded": 0, "skipped": 0, "failed": 0}

        for item in announcements:
            doc_id = item.get("ID")
            title = item.get("TITLE", "")
            publish_dt = self._parse_publish_date(item.get("PUBLISHDATE"))

            if not doc_id or publish_dt is None:
                stats["failed"] += 1
                print(f"[WARN] Missing fields for {ticker}: {item}")
                continue

            date_str = publish_dt.strftime("%Y-%m-%d")
            filename = f"{date_str}_{self.clean_filename(title)}.pdf"
            filepath = output_dir / filename

            if filepath.exists():
                stats["skipped"] += 1
                continue

            if self.download_pdf(doc_id=str(doc_id), filepath=str(filepath)):
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1

            if self.delay > 0:
                time.sleep(self.delay)

        print(
            f"    [OK] Downloaded: {stats['downloaded']} | "
            f"Skipped: {stats['skipped']} | Failed: {stats['failed']}"
        )

        return stats

    def download_all_lof_announcements(
        self, tickers: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """Download announcements for all LOFs using their backtest periods."""
        if tickers is None:
            tickers = self.list_available_tickers()

        total = {"downloaded": 0, "skipped": 0, "failed": 0}

        for idx, ticker in enumerate(tickers, start=1):
            print(f"\n[{idx}/{len(tickers)}] Processing {ticker}...")
            try:
                stats = self.download_fund_announcements(ticker)
            except Exception as exc:
                print(f"[ERROR] Failed on {ticker}: {exc}")
                total["failed"] += 1
                continue

            for key in total:
                total[key] += stats.get(key, 0)

        print(
            f"\n[SUCCESS] All funds complete | "
            f"Downloaded: {total['downloaded']} | "
            f"Skipped: {total['skipped']} | Failed: {total['failed']}"
        )

        return total
