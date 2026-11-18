"""
Per-fund trading terms for the backtest (redesign §8.4, phase F): subscription fee tiers,
confirmation days, and how late the NAV is published.

各基金的交易条款：申购费率档位、确认天数、净值公布滞后。

Source: the Eastmoney fund fee page (fundf10.eastmoney.com/jjfl_<code>.html), which transcribes
the prospectus fee table and the transfer agent's confirmation day. The page is current as of
the fetch date; fee changes inside the backtest window are listed by ``fee_change_notices``.
来源：天天基金"基金费率"页（转录自招募说明书），反映抓取当天的条款。

Derived terms:
- sell_days = buy_confirm_days + 1: on-exchange subscription shares are registered on the
  confirmation day and can be sold on the next trading day (domestic T+1 -> sell T+2,
  QDII T+2 -> sell T+3). A page without a confirmation day (a fund not sold there) falls
  back on the type: 3 for a late-NAV fund, 2 otherwise (``sell_days_basis`` says which).
- nav_lag: the lag of the newest NAV a buyer can see when deciding at T. 1 for domestic
  funds (NAV of T-1 is out the evening before); 2 for late-NAV funds -- overseas (QDII or
  海外 in the type) and funds of funds, or any fund confirmed at T+2 -- whose NAV of T-1
  only comes out after the T close.
"""

import html as html_lib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

PAGE_URL = "https://fundf10.eastmoney.com/jjfl_{code}.html"
SOURCE = "eastmoney_jjfl"
TERMS_FILE = "fund_terms.csv"
PAGES_DIR = "fund_pages"

_CONDITION = r"((?:大于等于|大于|小于等于|小于)\s*[\d.]+\s*万?元(?:\s*[，,]\s*(?:小于等于|小于)\s*[\d.]+\s*万?元)?|---)"
_CHARGE = r"(每笔\s*[\d.]+\s*元|[\d.]+\s*%)"
_TIER = re.compile(_CONDITION + r"\s*" + _CHARGE)
_UPPER = re.compile(r"(?:小于等于|小于)\s*([\d.]+)\s*(万?)元")


@dataclass
class FundTerms:
    """Trading terms of one fund. tiers: [[upper_bound_yuan, rate, fixed_fee], ...], upper None = no bound."""

    ticker: str
    name: str = ""
    fund_type: str = ""
    buy_confirm_days: Optional[int] = None
    sub_fee_tiers: List[list] = field(default_factory=list)
    error: str = ""

    @property
    def late_nav(self) -> bool:
        return ((self.buy_confirm_days or 0) >= 2
                or any(k in self.fund_type for k in ("QDII", "海外", "FOF")))

    @property
    def sell_days_basis(self) -> str:
        return "type" if self.buy_confirm_days is None else "confirm"

    @property
    def sell_days(self) -> int:
        if self.buy_confirm_days is None:
            return 3 if self.late_nav else 2
        return self.buy_confirm_days + 1

    @property
    def nav_lag(self) -> int:
        return 2 if self.late_nav else 1

    @property
    def first_rate(self) -> Optional[float]:
        return self.sub_fee_tiers[0][1] if self.sub_fee_tiers else None

    def row(self, fetched_at: str = "") -> Dict:
        d = asdict(self)
        d["sub_fee_tiers"] = json.dumps(self.sub_fee_tiers)
        return {**d, "sell_days": self.sell_days, "sell_days_basis": self.sell_days_basis, "nav_lag": self.nav_lag,
                "sub_fee_rate_1": self.first_rate, "source": SOURCE, "fetched_at": fetched_at}


def plain_text(page: str) -> str:
    """Tags stripped, entities decoded, whitespace collapsed."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text)


def _upper_bound(condition: str) -> Optional[float]:
    m = _UPPER.search(condition)
    if not m:
        return None
    return float(m.group(1)) * (10_000 if m.group(2) else 1)


def parse_fee_section(section: str) -> List[list]:
    """Rows of a 申购费率 table -> [[upper, rate, fixed], ...] in table order."""
    tiers = []
    for condition, charge in _TIER.findall(section):
        charge = charge.replace(" ", "")
        if charge.startswith("每笔"):
            rate, fixed = None, float(charge[2:-1])
        elif charge.endswith("%"):
            rate, fixed = round(float(charge[:-1]) / 100, 6), None
        else:
            continue
        tiers.append([_upper_bound(condition), rate, fixed])
    return tiers


def parse_fee_page(ticker: str, page: str) -> FundTerms:
    """Terms from a jjfl page; ``error`` says what could not be read."""
    text = plain_text(page)
    terms = FundTerms(ticker=str(ticker))
    m = (re.search(r"基金档案\s*>\s*([^>]+?)\s+手机访问", text)
         or re.search(r"(\S+)\s*\(" + re.escape(str(ticker)) + r"\)\s*立即购买", text))
    terms.name = m.group(1).strip() if m else ""
    m = re.search(r"类型：\s*(\S+)", text)
    terms.fund_type = m.group(1) if m else ""
    m = re.search(r"买入确认日\s*T\s*\+\s*(\d+)", text)
    terms.buy_confirm_days = int(m.group(1)) if m else None
    start = None
    for heading in ("申购费率（前端） 适用金额", "申购费率 适用金额"):
        i = text.find(heading)
        if i >= 0:
            start = i + len(heading)
            break
    errors = []
    if start is None:
        errors.append("no subscription fee table")
    else:
        end = min([j for j in (text.find(s, start) for s in ("友情提示", "申购费率（后端）", "赎回费率")) if j >= 0]
                  or [len(text)])
        terms.sub_fee_tiers = parse_fee_section(text[start:end])
        if not terms.sub_fee_tiers:
            errors.append("fee table has no rows")
        elif all(r == 0 for _, r, f in terms.sub_fee_tiers if f is None) and not terms.name.rstrip().endswith("C"):
            # C shares carry no front-end fee; a zero table on any other share is a placeholder on the page
            errors.append("zero fee on a non-C share (unverified)")
    terms.error = "; ".join(errors)
    return terms


def fetch_pages(tickers: Iterable[str], pages_dir: Path, refresh: bool = False, pause: float = 0.8,
                log=print) -> List[str]:
    """Download missing jjfl pages into ``pages_dir``; returns the tickers that failed."""
    import requests

    pages_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    todo = [t for t in tickers if refresh or not (pages_dir / f"jjfl_{t}.html").exists()]
    log(f"{len(todo)} pages to fetch")
    for n, t in enumerate(todo, 1):
        for attempt in range(3):
            try:
                r = requests.get(PAGE_URL.format(code=t), headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                r.raise_for_status()
                r.encoding = "utf-8"
                (pages_dir / f"jjfl_{t}.html").write_text(r.text, encoding="utf-8")
                break
            except Exception as e:  # network errors are retried, then reported
                if attempt == 2:
                    failed.append(t)
                    log(f"  {t}: {e}")
                time.sleep(pause * (attempt + 2))
        if n % 50 == 0:
            log(f"  {n}/{len(todo)}")
        time.sleep(pause)
    return failed


def build_terms(tickers: Iterable[str], pages_dir: Path) -> pd.DataFrame:
    """Parse cached pages into the fund_terms table (one row per ticker, errors kept)."""
    rows = []
    for t in tickers:
        path = pages_dir / f"jjfl_{t}.html"
        if not path.exists():
            rows.append(FundTerms(ticker=t, error="page not fetched").row())
            continue
        fetched = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        rows.append(parse_fee_page(t, path.read_text(encoding="utf-8")).row(fetched))
    return pd.DataFrame(rows)


def read_terms(path: Path) -> Dict[str, Dict]:
    """fund_terms.csv -> {ticker: row}, rows with a parse error dropped."""
    df = pd.read_csv(path, dtype={"ticker": str}, keep_default_na=False)
    out = {}
    for row in df.to_dict("records"):
        if row.get("error"):
            continue
        tiers = json.loads(row["sub_fee_tiers"])
        out[row["ticker"]] = {
            "sell_days": int(row["sell_days"]), "nav_lag": int(row["nav_lag"]),
            "sub_fee_tiers": [[math.inf if u is None else u, r, f] for u, r, f in tiers],
            "fund_type": row.get("fund_type", ""), "source": row.get("source", SOURCE),
        }
    return out


FEE_CHANGE = re.compile(r"(调低|调整|下调|降低|修改).{0,60}申购费|申购费率.{0,10}(调低|调整|下调|降低)")


def fee_change_notices(conn, start: str, end: str) -> pd.DataFrame:
    """Announcements in [start, end] whose title says a subscription fee was changed (not a promotion)."""
    rows = conn.execute("SELECT fund_code, announce_date, title FROM announcements "
                        "WHERE announce_date BETWEEN ? AND ? ORDER BY announce_date", (start, end)).fetchall()
    hits = [(c, d, t) for c, d, t in rows if FEE_CHANGE.search(t) and "优惠" not in t]
    return pd.DataFrame(hits, columns=["fund_code", "announce_date", "title"])
