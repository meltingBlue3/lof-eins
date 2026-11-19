"""
LOF market data and NAV downloader on AKShare.

LOF 行情和净值下载器（数据源：AKShare）。

What comes from where / 数据来源：
- Daily bars (source="sina", the default): ak.fund_etf_hist_sina, unadjusted, volume in shares.
  Against the JoinQuant files it replaced (410 funds, 2021-2024) the close and the NAV match on
  every day both have; volume matches except 28 fund-days where Sina shows 0.
  日线（默认新浪）：ak.fund_etf_hist_sina，不复权，成交量单位为份。与原聚宽数据对比，收盘价和净值逐日一致，
  成交量只有 28 个基金日新浪为 0。
- Daily bars (source="eastmoney"): ak.fund_lof_hist_em, unadjusted. Eastmoney reports volume in
  lots of 100; it is stored in shares (x100, so it carries the rounding of the lots).
  日线（东方财富）：ak.fund_lof_hist_em，不复权；成交量单位是手，保存时换算成份（x100，带取整误差）。
- Neither source has a row on a day without trades (JoinQuant filled those with the previous
  close and volume 0), so nothing can be traded on such a day.
  两个来源在无成交的日子都没有记录（聚宽会用前收盘价和零成交量补齐），所以这些日子不能交易。
- Unit NAV: ak.fund_open_fund_info_em(indicator="单位净值走势").  单位净值：ak.fund_open_fund_info_em。
- LOF list (when no codes are given): the funds trading today, from Sina's list plus Eastmoney's
  board; a fund that has delisted is on neither, so to rebuild a historical universe pass its tickers.
  LOF 名单（未指定代码时）：新浪列表并上东方财富板块，只含当前在交易的基金；重建历史样本时要显式传入代码。

Eastmoney's push2 quote servers (its LOF board and daily bars) close the connection on a request
with the default python-requests User-Agent, and refuse an IP for minutes, after repeated triggers
for over an hour, after a burst of requests. For Eastmoney the downloader sends a browser
User-Agent, looks each fund's exchange up once for the whole run (fund_lof_hist_em would fetch the
full LOF board again for every fund), keeps a gap between requests and waits out a refusal. Each
fund is written as soon as it is fetched, and a rerun skips the funds already on disk.
东方财富 push2 行情服务器会断开默认 python-requests User-Agent 的请求，短时间请求过多会封 IP
（反复触发可超过一小时）。用东方财富时，下载器使用浏览器 User-Agent，整次运行只查一次交易所映射，
请求之间留间隔，被封时等待后继续。每只基金抓完立即写盘，重跑时跳过已有的基金。

Output layout (what DataLoader reads) / 输出目录：
- market/{ticker}.parquet: date, ticker, open, high, low, close, volume (shares), volume_ma5
- nav/{ticker}.parquet: date, ticker, nav
- config/: created empty; subscription_state.db and fund_terms.csv come from
  scripts/build_corpus.py ... build_timeline.py and scripts/fund_terms.py
- download_report.csv: one row per fund (rows, first and last date, status)
"""

from __future__ import annotations

import contextlib
import random
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    import akshare as ak
    import requests.sessions
    from akshare.fund import fund_lof_em as _lof_em
    from akshare.utils.http import Push2RateLimitError

    AK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without akshare installed
    AK_AVAILABLE = False

    class Push2RateLimitError(Exception):  # type: ignore[no-redef]
        """Placeholder so the module imports without akshare."""


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
MARKET_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "volume_ma5"]
NAV_COLUMNS = ["date", "ticker", "nav"]
SHARES_PER_LOT = 100
# Waits after Eastmoney refuses the IP, in seconds; the first refusal usually lifts in about
# five minutes, repeated ones take longer.  被封后的等待时间（秒）。
BAN_WAITS = (360, 720, 1500, 3000)
SOURCES = ("eastmoney", "sina")


def exchange_id(ticker: str) -> int:
    """Eastmoney market id of a fund code: 1 Shanghai (5xxxxx), 0 Shenzhen (1xxxxx).
    基金代码对应的东方财富市场标识：1 上海，0 深圳。"""
    return 1 if str(ticker).startswith("5") else 0


class ExchangeMap(dict):
    """Ticker -> market id; a ticker missing from the live LOF board (delisted) falls back to its
    code prefix, so fund_lof_hist_em can still ask for its history.
    代码到市场标识的映射；不在当前 LOF 板块的代码（已退市）按代码前缀推断。"""

    def __missing__(self, ticker: str) -> int:
        return exchange_id(ticker)


@contextlib.contextmanager
def eastmoney_session(code_map: Optional[Dict[str, int]] = None):
    """Send a browser User-Agent on every requests session and, if given, serve fund_lof_hist_em
    a fixed exchange map. Both are restored on exit.
    在上下文内给 requests 会话加浏览器 User-Agent，并让 fund_lof_hist_em 使用固定的交易所映射。"""
    original_headers = requests.sessions.default_headers
    original_map = _lof_em._fund_lof_code_id_map_em

    def browser_headers():
        headers = original_headers()
        headers["User-Agent"] = BROWSER_UA
        return headers

    requests.sessions.default_headers = browser_headers
    if code_map is not None:
        _lof_em._fund_lof_code_id_map_em = lambda: code_map
    try:
        yield
    finally:
        requests.sessions.default_headers = original_headers
        _lof_em._fund_lof_code_id_map_em = original_map


def list_lofs() -> Dict[str, int]:
    """Codes on Eastmoney's LOF board today, with their market ids.
    东方财富 LOF 板块当前的基金代码及市场标识。"""
    with eastmoney_session():
        return {str(k): int(v) for k, v in _lof_em._fund_lof_code_id_map_em().items()}


def list_lofs_sina() -> Dict[str, int]:
    """Codes on Sina's LOF list today, with Eastmoney-style market ids (1 Shanghai, 0 Shenzhen).
    新浪 LOF 列表当前的基金代码及市场标识。"""
    df = ak.fund_etf_category_sina(symbol="LOF基金")
    return {c[2:]: 1 if c.startswith("sh") else 0 for c in df["代码"].astype(str)}


def market_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """fund_lof_hist_em output -> the market parquet layout (volume in shares).
    把 fund_lof_hist_em 的结果转成行情文件格式（成交量换算为份）。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=MARKET_COLUMNS)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["日期"]),
        "ticker": ticker,
        "open": pd.to_numeric(raw["开盘"], errors="coerce"),
        "high": pd.to_numeric(raw["最高"], errors="coerce"),
        "low": pd.to_numeric(raw["最低"], errors="coerce"),
        "close": pd.to_numeric(raw["收盘"], errors="coerce"),
        "volume": pd.to_numeric(raw["成交量"], errors="coerce").astype(float) * SHARES_PER_LOT,
    })
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df["volume_ma5"] = df["volume"].rolling(window=5).mean().fillna(df["volume"])
    return df[MARKET_COLUMNS]


def sina_symbol(ticker: str) -> str:
    """Sina's symbol for a fund code: sh501018, sz161226.  新浪的代码格式。"""
    return ("sh" if exchange_id(ticker) == 1 else "sz") + str(ticker)


def sina_frame(raw: pd.DataFrame, ticker: str, start: str, end: str) -> pd.DataFrame:
    """fund_etf_hist_sina output (full history, volume in shares) -> the market parquet layout,
    cut to [start, end]. The moving average is taken after the cut, as for Eastmoney's bars.
    把 fund_etf_hist_sina 的结果（全部历史，成交量单位为份）转成行情文件格式并截取到区间内。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=MARKET_COLUMNS)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["date"]),
        "ticker": ticker,
        **{c: pd.to_numeric(raw[c], errors="coerce") for c in ("open", "high", "low", "close")},
        "volume": pd.to_numeric(raw["volume"], errors="coerce").astype(float),
    })
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df["volume_ma5"] = df["volume"].rolling(window=5).mean().fillna(df["volume"])
    return df[MARKET_COLUMNS]


def nav_frame(raw: pd.DataFrame, ticker: str, start: str, end: str) -> pd.DataFrame:
    """fund_open_fund_info_em output -> the NAV parquet layout, cut to [start, end].
    把 fund_open_fund_info_em 的结果转成净值文件格式，并截取到区间内。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=NAV_COLUMNS)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["净值日期"]),
        "ticker": ticker,
        "nav": pd.to_numeric(raw["单位净值"], errors="coerce"),
    })
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return df[NAV_COLUMNS]


class RealDataDownloader:
    """Downloads LOF daily bars and unit NAV from AKShare into the DataLoader layout.
    从 AKShare 下载 LOF 日线和单位净值，写成 DataLoader 读取的目录结构。

    Attributes:
        output_dir: Root directory for downloaded data.  # 下载数据的根目录
        source: Daily bars from "eastmoney" (fund_lof_hist_em) or "sina" (fund_etf_hist_sina).
            日线来源。
        pause: Minimum seconds between two quote requests to Eastmoney.  # 两次东方财富行情请求的最小间隔
        sina_pause: Minimum seconds between two requests to Sina.  # 两次新浪请求的最小间隔
        nav_pause: Minimum seconds between two NAV requests.  # 两次净值请求的最小间隔
        ban_waits: Seconds to wait after each successive refusal.  # 连续被封时依次等待的秒数
        max_errors_in_row: Stop after this many funds in a row fail (the source is likely
            refusing requests).  # 连续这么多只基金出错就停止（数据源多半在拒绝请求）
    """

    def __init__(self, output_dir: str = "./data/real_all_lof", source: str = "sina",
                 pause: float = 5.0, sina_pause: float = 1.5, nav_pause: float = 0.5,
                 ban_waits: Iterable[float] = BAN_WAITS, max_pause: float = 30.0,
                 max_errors_in_row: int = 5, sleep: Callable[[float], None] = time.sleep):
        if not AK_AVAILABLE:
            raise ImportError("akshare is required for RealDataDownloader: pip install akshare")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        self.source = source
        self.sina_pause = sina_pause
        self.max_errors_in_row = max_errors_in_row
        self.output_dir = Path(output_dir)
        self.market_dir = self.output_dir / "market"
        self.nav_dir = self.output_dir / "nav"
        self.config_dir = self.output_dir / "config"
        self.pause = pause
        self.nav_pause = nav_pause
        self.ban_waits = tuple(ban_waits)
        self.max_pause = max_pause
        self._sleep = sleep
        self._last: Dict[str, float] = {}
        self._strikes = 0   # refusals since the last request that went through

    def _setup_directories(self) -> None:
        for d in (self.market_dir, self.nav_dir, self.config_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _wait(self, kind: str, gap: float) -> None:
        """Keep at least `gap` seconds (plus jitter) since the last request of this kind."""
        last = self._last.get(kind)
        if last is not None:
            remaining = gap + random.uniform(0, gap / 2) - (time.monotonic() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[kind] = time.monotonic()

    def _with_ban_waits(self, call: Callable, what: str):
        """Run a push2 request. When Eastmoney refuses the IP, wait (longer each time in a row),
        slow the pace by half and retry; give up after len(ban_waits) refusals in a row.
        执行一次 push2 请求；被封时等待（连续被封则越等越久）、放慢节奏后重试，连续被封超过次数则放弃。"""
        while True:
            try:
                result = call()
            except Push2RateLimitError:
                if self._strikes >= len(self.ban_waits):
                    raise
                wait = self.ban_waits[self._strikes]
                self._strikes += 1
                self.pause = min(self.pause * 1.5, self.max_pause)
                print(f"    [WAIT] Eastmoney refused the IP at {what}; retrying in {wait / 60:.0f} min, "
                      f"then {self.pause:.1f}s between requests")
                self._sleep(wait)
                self._last.pop("quote", None)
                continue
            self._strikes = 0
            return result

    def _quote(self, call: Callable, what: str):
        """A paced push2 request with ban waits."""
        def paced():
            self._wait("quote", self.pause)
            return call()
        return self._with_ban_waits(paced, what)

    def fetch_market(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        if self.source == "sina":
            self._wait("sina", self.sina_pause)
            return sina_frame(ak.fund_etf_hist_sina(symbol=sina_symbol(ticker)), ticker, start, end)
        raw = self._quote(lambda: ak.fund_lof_hist_em(
            symbol=ticker, period="daily", start_date=start.replace("-", ""),
            end_date=end.replace("-", ""), adjust=""), ticker)
        return market_frame(raw, ticker)

    def fetch_nav(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self._wait("nav", self.nav_pause)
        return nav_frame(ak.fund_open_fund_info_em(symbol=ticker, indicator="单位净值走势"), ticker, start, end)

    def fetch_all_lof_codes(self) -> Dict[str, int]:
        """LOF codes trading today with their market ids; delisted funds are not included.
        With Sina as the source: Sina's list plus Eastmoney's board when Eastmoney answers (each
        list misses funds the other has). With Eastmoney: its board.
        当前在交易的 LOF 代码及市场标识（不含已退市基金）。新浪来源：新浪列表并上东方财富板块
        （东方财富可用时；两份列表各缺一些基金）；东方财富来源：东方财富板块。"""
        if self.source == "eastmoney":
            return self._quote(list_lofs, "the LOF list")
        self._wait("sina", self.sina_pause)
        board = list_lofs_sina()
        try:
            extra = {k: v for k, v in list_lofs().items() if k not in board}
            board.update(extra)
            print(f"    LOF list: {len(board) - len(extra)} from Sina, {len(extra)} more from Eastmoney")
        except Exception as exc:  # Eastmoney refusing the IP must not stop a Sina download
            print(f"    LOF list: {len(board)} from Sina; Eastmoney's board unavailable ({type(exc).__name__})")
        return board

    def download(self, start_date: str, end_date: str, codes: Optional[List[str]] = None,
                 refresh: bool = False) -> Tuple[int, List[str]]:
        """Download bars and NAV for [start_date, end_date] (YYYY-MM-DD).
        下载区间内的日线和净值。

        Args:
            codes: Fund codes; None downloads every fund on today's LOF board.
                基金代码；为 None 时下载当前 LOF 板块的全部基金。
            refresh: Fetch again funds whose files already exist.  # 已有文件的基金也重新下载

        Returns:
            (count, tickers) of funds that have both a market and a NAV file.
            同时有行情和净值文件的基金数量及代码。
        """
        self._setup_directories()
        if codes is None:
            board = ExchangeMap(self.fetch_all_lof_codes())
            codes = sorted(board)
        else:
            # The exchange follows from the code, so a given list needs no request for the board.
            board = ExchangeMap()
        codes = [str(c).split(".")[0] for c in codes]
        print(f">>> {len(codes)} funds, {start_date} ~ {end_date}, daily bars from {self.source}")

        report = []
        errors_in_row = 0
        with eastmoney_session(board):
            for i, ticker in enumerate(codes, 1):
                market_path = self.market_dir / f"{ticker}.parquet"
                nav_path = self.nav_dir / f"{ticker}.parquet"
                row = {"ticker": ticker, "source": self.source}
                if not refresh and market_path.exists() and nav_path.exists():
                    row.update(_file_summary(market_path, nav_path), status="kept")
                    report.append(row)
                    continue
                try:
                    market = self.fetch_market(ticker, start_date, end_date)
                    nav = self.fetch_nav(ticker, start_date, end_date)
                except Push2RateLimitError:
                    print(f"[STOP] Eastmoney still refuses the IP after {len(self.ban_waits)} waits; "
                          f"rerun later to continue from {ticker}")
                    report.append({**row, "status": "stopped: rate limited"})
                    break
                except Exception as exc:  # one bad fund must not stop the run
                    print(f"  [{i}/{len(codes)}] {ticker}: error {exc!r}")
                    report.append({**row, "status": f"error: {type(exc).__name__}: {exc}"[:200]})
                    errors_in_row += 1
                    if errors_in_row >= self.max_errors_in_row:
                        print(f"[STOP] {errors_in_row} funds in a row failed; the source is probably refusing "
                              f"requests. Rerun later to continue from {ticker}")
                        break
                    continue
                errors_in_row = 0
                if not market.empty:
                    market.to_parquet(market_path, index=False)
                if not nav.empty:
                    nav.to_parquet(nav_path, index=False)
                status = "ok" if not market.empty and not nav.empty else (
                    "no market data" if market.empty and not nav.empty else
                    "no NAV" if not market.empty else "no data")
                row.update(market_rows=len(market), nav_rows=len(nav),
                           first_date=_day(market["date"].min()) if len(market) else None,
                           last_date=_day(market["date"].max()) if len(market) else None, status=status)
                report.append(row)
                print(f"  [{i}/{len(codes)}] {ticker}: {len(market)} bars, {len(nav)} NAV  {status}")

        pd.DataFrame(report).to_csv(self.output_dir / "download_report.csv", index=False, encoding="utf-8-sig")
        done = [r["ticker"] for r in report if r.get("status") in ("ok", "kept")]
        print(f">>> {len(done)} funds with bars and NAV in {self.output_dir} (report: download_report.csv)")
        return len(done), done


def _day(ts) -> Optional[str]:
    return None if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _file_summary(market_path: Path, nav_path: Path) -> dict:
    dates = pd.read_parquet(market_path, columns=["date"])["date"]
    return {"market_rows": len(dates), "nav_rows": len(pd.read_parquet(nav_path, columns=["date"])),
            "first_date": _day(dates.min()), "last_date": _day(dates.max())}


def download_all_lof(start_date: str, end_date: str, output_dir: str = "./data/real_all_lof",
                     codes: Optional[List[str]] = None) -> Tuple[int, List[str]]:
    """Download bars and NAV for every fund on today's LOF board (or `codes`).
    下载当前 LOF 板块全部基金（或指定代码）的日线和净值。"""
    return RealDataDownloader(output_dir=output_dir).download(start_date, end_date, codes=codes)
