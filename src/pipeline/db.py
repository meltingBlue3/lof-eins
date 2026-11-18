"""
Schema and connection for the v2 state database.

v2 状态库的表结构与连接。表 1~3 属于阶段 B；state_assertions 与 anomalies 属于阶段 C；daily_status 在阶段 D 加入。
"""

import sqlite3
from pathlib import Path
from typing import Union

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "real_all_lof" / "config" / "subscription_state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
  id            INTEGER PRIMARY KEY,
  fund_code     TEXT NOT NULL,
  announce_date DATE NOT NULL,
  title         TEXT NOT NULL,
  rel_path      TEXT NOT NULL UNIQUE,
  sha256        TEXT NOT NULL,
  size_bytes    INTEGER NOT NULL,
  triage        TEXT CHECK (triage IN ('relevant','irrelevant','unsure')),
  triage_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_announcements_sha ON announcements(sha256);
CREATE INDEX IF NOT EXISTS idx_announcements_fund ON announcements(fund_code, announce_date);

CREATE TABLE IF NOT EXISTS pdf_texts (
  sha256     TEXT PRIMARY KEY,
  extractor  TEXT NOT NULL,
  text       TEXT NOT NULL,
  tables     TEXT NOT NULL DEFAULT '[]',
  n_pages    INTEGER,
  is_empty   INTEGER NOT NULL DEFAULT 0,
  error      TEXT
);

CREATE TABLE IF NOT EXISTS extractions (
  id              INTEGER PRIMARY KEY,
  sha256          TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  model           TEXT NOT NULL,
  raw_response    TEXT,
  status          TEXT NOT NULL CHECK (status IN ('ok','schema_error','api_error')),
  error           TEXT,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (sha256, prompt_version, model)
);
CREATE TABLE IF NOT EXISTS state_assertions (
  id             INTEGER PRIMARY KEY,
  extraction_id  INTEGER NOT NULL REFERENCES extractions(id),
  sha256         TEXT NOT NULL,
  fund_code      TEXT NOT NULL,
  share_codes    TEXT NOT NULL,
  channel        TEXT NOT NULL CHECK (channel IN ('all','exchange','agency','direct','specific')),
  businesses     TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('open','limited','closed')),
  amount         REAL,
  currency       TEXT NOT NULL DEFAULT 'CNY',
  valid_from     DATE NOT NULL,
  valid_to       DATE,
  layer          TEXT NOT NULL CHECK (layer IN ('baseline','overlay')),
  kind           TEXT NOT NULL CHECK (kind IN ('change','restatement')),
  observed_on    DATE NOT NULL,
  prior_status   TEXT CHECK (prior_status IN ('open','limited','closed')),
  evidence       TEXT NOT NULL,
  evidence_ok    INTEGER NOT NULL,
  CHECK (layer = 'overlay' OR valid_to IS NULL),
  CHECK (layer = 'baseline' OR valid_to IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_assertions_fund ON state_assertions(fund_code, valid_from);
CREATE TABLE IF NOT EXISTS anomalies (
  id INTEGER PRIMARY KEY, fund_code TEXT NOT NULL, date_from DATE, date_to DATE,
  kind TEXT NOT NULL, detail TEXT, assertion_ids TEXT, sha256 TEXT,
  resolved INTEGER NOT NULL DEFAULT 0, resolution TEXT
);
"""


def connect(path: Union[str, Path] = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and create if needed) the state database with the schema applied."""
    in_memory = str(path) == ":memory:"
    if not in_memory:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    if not in_memory:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
