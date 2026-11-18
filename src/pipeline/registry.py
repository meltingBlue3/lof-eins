"""
Register every announcement PDF, without any title filter.

登记全部公告 PDF（不做标题过滤），以 sha256 标识内容。

Layout on disk: <root>/<fund_code>/<YYYY-MM-DD>_<title>.pdf
"""

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Union

NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)\.pdf$", re.IGNORECASE)


@dataclass(frozen=True)
class FileEntry:
    fund_code: str
    announce_date: str
    title: str
    rel_path: str
    sha256: str
    size_bytes: int


def parse_name(name: str) -> Optional[tuple]:
    """Split '<date>_<title>.pdf' into (date, title); None if the name does not follow the layout."""
    m = NAME_RE.match(name)
    return (m.group(1), m.group(2)) if m else None


def sha256_of(path: Union[str, Path], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def scan(root: Union[str, Path]) -> Iterator[Union[FileEntry, str]]:
    """Yield a FileEntry per PDF, or the relative path (str) of a file whose name does not parse."""
    root = Path(root)
    for fund_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for entry in sorted(os.scandir(fund_dir), key=lambda e: e.name):
            if not entry.is_file():
                continue
            rel = f"{fund_dir.name}/{entry.name}"
            parsed = parse_name(entry.name)
            if parsed is None:
                yield rel
                continue
            yield FileEntry(fund_dir.name, parsed[0], parsed[1], rel, sha256_of(entry.path), entry.stat().st_size)


def register(conn: sqlite3.Connection, root: Union[str, Path]) -> dict:
    """
    Upsert every PDF under root into `announcements`.

    A file whose content changed (new sha256) loses its triage, so it is triaged again.
    Rows whose file disappeared are deleted. Returns counts and the names that did not parse.
    """
    seen, bad = set(), []
    counts = {"inserted": 0, "changed": 0, "unchanged": 0, "removed": 0}
    existing = {r["rel_path"]: r["sha256"] for r in conn.execute("SELECT rel_path, sha256 FROM announcements")}
    with conn:
        for item in scan(root):
            if isinstance(item, str):
                bad.append(item)
                continue
            seen.add(item.rel_path)
            old = existing.get(item.rel_path)
            if old is None:
                counts["inserted"] += 1
                conn.execute(
                    "INSERT INTO announcements (fund_code, announce_date, title, rel_path, sha256, size_bytes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (item.fund_code, item.announce_date, item.title, item.rel_path, item.sha256, item.size_bytes),
                )
            elif old != item.sha256:
                counts["changed"] += 1
                conn.execute(
                    "UPDATE announcements SET sha256 = ?, size_bytes = ?, triage = NULL, triage_by = NULL "
                    "WHERE rel_path = ?",
                    (item.sha256, item.size_bytes, item.rel_path),
                )
            else:
                counts["unchanged"] += 1
        gone: List[str] = [p for p in existing if p not in seen]
        conn.executemany("DELETE FROM announcements WHERE rel_path = ?", [(p,) for p in gone])
        counts["removed"] = len(gone)
    counts["unparsed"] = bad
    return counts
