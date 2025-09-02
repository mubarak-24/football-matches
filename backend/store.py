# backend/store.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator, Optional, Callable, Any, Dict

# ---------- Paths ----------
# Resolve .../project_root/data/football.db no matter where it's called from
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "football.db"

# ---------- Schema ----------
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS matches (
  id           INTEGER PRIMARY KEY,
  date_utc     TEXT,          -- ISO timestamp from API
  league_id    INTEGER,
  league_name  TEXT,
  home_team    TEXT,
  away_team    TEXT,
  home_goals   INTEGER,
  away_goals   INTEGER,
  status       TEXT,          -- e.g. NS, TBD, FT, etc.
  xg_home      REAL,
  xg_away      REAL,
  cards_home   INTEGER,
  cards_away   INTEGER,
  upset        INTEGER DEFAULT 0,
  late_drama   INTEGER DEFAULT 0,
  lead_changes INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date_local TEXT,        -- YYYY-MM-DD (local tz)
  motd_match_id  INTEGER,
  email_sent     INTEGER DEFAULT 0
);

-- Helpful indexes for common queries
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date(date_utc));
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id);
"""

# ---------- Connection helpers ----------
def connect(readonly: bool = False) -> sqlite3.Connection:
    """
    Open a SQLite connection with sensible defaults.
    - Ensures data directory exists
    - WAL mode for better concurrency
    - Busy timeout to avoid 'database is locked'
    - Normal synchronous (good balance for WAL)
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if readonly:
        # SQLite URI for read-only access
        uri = f"file:{DB_PATH.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    else:
        con = sqlite3.connect(DB_PATH.as_posix())

    # Performance / reliability PRAGMAs
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")  # 5s

    return con


def init_db() -> None:
    """
    Create tables & indexes if they don't exist.
    Safe to call many times.
    """
    with connect() as con:
        con.executescript(SCHEMA)


# Optional utility: quick dict row factory you can reuse
def dict_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> Dict[str, Any]:
    return {cursor.description[i][0]: row[i] for i in range(len(row))}


if __name__ == "__main__":
    init_db()
    print(f"✅ Database initialized at {DB_PATH}")