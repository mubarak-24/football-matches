# backend/fetcher.py
from __future__ import annotations

import os
import datetime as dt
from typing import Iterable, List, Tuple, Optional, Dict

import requests
import pytz

from backend.store import connect
from dotenv import load_dotenv
load_dotenv()

# =============================================================================
# Environment / constants
# =============================================================================
API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Riyadh"))

# Optional season (occasionally useful for discovery utilities; not used here)
SEASON = os.getenv("SEASON")  # e.g., "2024"

# writeafter: We centralize env + constants so the rest of the file can assume
# stable configuration. Keeping TIMEZONE and API key here prevents duplicated
# env lookups across functions and makes testing easier.


# =============================================================================
# Utilities
# =============================================================================
def _parse_int_list(env_val: str | None) -> list[int]:
    """Parse a comma-separated list of ints like '39,140,135' into [39, 140, 135]."""
    out: list[int] = []
    for x in (env_val or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            # ignore non-integers silently (robust to user typos)
            pass
    return out

# writeafter: This helper lets us accept friendly comma-separated env values
# in .env (LEAGUE_IDS / TEAM_IDS). It’s safer than failing on a single typo.


# Defaults from .env (can be overridden at runtime by function params)
DEFAULT_LEAGUE_IDS: list[int] = _parse_int_list(os.getenv("LEAGUE_IDS"))
DEFAULT_TEAM_IDS: list[int] = _parse_int_list(os.getenv("TEAM_IDS"))

# writeafter: Using .env defaults means you can run the fetcher with zero args
# in cron or manual runs, while still allowing per-call overrides in code/tests.


# =============================================================================
# HTTP core
# =============================================================================
def _request(
    endpoint: str,
    params: List[Tuple[str, str | int]],
    timeout: int = 30,
) -> dict:
    """
    Thin wrapper over requests.get with consistent headers + error handling.
    """
    if not API_KEY:
        raise RuntimeError("⚠️ API_FOOTBALL_KEY not found in .env")

    headers = {
        "x-apisports-key": API_KEY,
        "User-Agent": "football-digest/1.0",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if resp.status_code == 429:
        detail = ""
        try:
            detail = resp.json().get("message") or ""
        except Exception:
            detail = resp.text[:200]
        raise RuntimeError(f"API rate limit (429). {detail}".strip())

    if resp.status_code != 200:
        snippet = resp.text[:300]
        raise RuntimeError(f"API error {resp.status_code}: {snippet}")

    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError("Invalid JSON from API-Football") from exc

# writeafter: A single HTTP entry point makes retries/logging uniform and keeps
# the fetcher functions tiny. We also surface meaningful errors for CI/cron.


# =============================================================================
# SQLite upsert
# =============================================================================
def _upsert_fixtures(rows: list[dict]) -> int:
    """
    Insert/update fixtures into SQLite.

    Expects API-Football fixture objects in `rows`. We only store the fields
    the rest of the app needs (id/date/league/teams/goals/status).
    """
    saved = 0
    with connect() as con:
        for m in rows:
            fixture = m.get("fixture", {}) or {}
            league = m.get("league", {}) or {}
            teams = m.get("teams", {}) or {}
            goals = m.get("goals", {}) or {}
            status = (fixture.get("status") or {}).get("short")

            con.execute(
                """
                INSERT OR REPLACE INTO matches
                (id, date_utc, league_id, league_name,
                 home_team, away_team, home_goals, away_goals, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fixture.get("id"),
                    fixture.get("date"),
                    league.get("id"),
                    league.get("name"),
                    (teams.get("home") or {}).get("name"),
                    (teams.get("away") or {}).get("name"),
                    goals.get("home"),
                    goals.get("away"),
                    status,
                ),
            )
            saved += 1
        con.commit()
    return saved

# writeafter: We normalize and upsert into SQLite so downstream code (emails,
# PWA API) reads a stable schema. INSERT OR REPLACE prevents duplicate rows if
# we refetch the same day or backfill ranges.


# =============================================================================
# Internal fetch modes (team-first, then league)
# =============================================================================
def _fetch_by_teams(date: str, team_ids: list[int], timeout: int) -> list[dict]:
    """
    Fetch fixtures for given date by iterating teams (one call per team) and merge.
    """
    merged: Dict[int, dict] = {}
    for tid in team_ids:
        params: list[tuple[str, str | int]] = [("date", date), ("team", tid)]
        data = _request("/fixtures", params=params, timeout=timeout)
        for item in data.get("response", []) or []:
            fid = (item.get("fixture") or {}).get("id")
            if fid is not None:
                merged[fid] = item
    return list(merged.values())

def _fetch_by_leagues(date: str, league_ids: list[int], timeout: int) -> list[dict]:
    """
    Fetch fixtures for given date by iterating leagues (one call per league) and merge.
    """
    merged: Dict[int, dict] = {}
    for lid in league_ids:
        params: list[tuple[str, str | int]] = [("date", date), ("league", lid)]
        data = _request("/fixtures", params=params, timeout=timeout)
        for item in data.get("response", []) or []:
            fid = (item.get("fixture") or {}).get("id")
            if fid is not None:
                merged[fid] = item
    return list(merged.values())

# writeafter: We intentionally split into per-team/per-league calls. Passing both
# `league` and `team` in a single request acts like AND at API-Football, which can
# hide club games in other competitions. Looping and merging by fixture id ensures
# we never miss Al-Ahli (or any configured club), while keeping results deduplicated.


# =============================================================================
# Public fetchers
# =============================================================================
def run_daily_fetch(
    date: str | None = None,
    league_ids: Optional[Iterable[int]] = None,
    team_ids: Optional[Iterable[int]] = None,
    timeout: int = 30,
) -> int:
    """
    Fetch fixtures for a single date and save into SQLite.

    Filters:
      - league_ids: restrict to specific competitions (e.g., SPL, LaLiga).
      - team_ids:   ALWAYS include specific clubs (e.g., Al-Ahli) regardless
                    of which competition they’re playing in that day.

    Behavior:
      - If team_ids present → fetch **by team(s)** only (club-first).
      - Else if league_ids present → fetch **by league(s)**.
      - Else → fetch everything for the date (not recommended: heavy).

    Returns:
        Number of fixtures upserted.
    """
    # Resolve date (local TZ -> ISO date string)
    if not date:
        date = dt.datetime.now(TZ).date().isoformat()

    # Resolve filters (fallback to .env if not provided)
    lid_list = list(league_ids) if league_ids is not None else list(DEFAULT_LEAGUE_IDS)
    tid_list = list(team_ids) if team_ids is not None else list(DEFAULT_TEAM_IDS)

    # Decide mode (club-first)
    if tid_list:
        fixtures = _fetch_by_teams(date, tid_list, timeout=timeout)
    elif lid_list:
        fixtures = _fetch_by_leagues(date, lid_list, timeout=timeout)
    else:
        # Last resort: fetch all fixtures of the day (expensive).
        data = _request("/fixtures", params=[("date", date)], timeout=timeout)
        fixtures = data.get("response", []) or []

    saved = _upsert_fixtures(fixtures)
    print(f"✅ Saved {saved} matches from API for {date}")
    return saved

# writeafter: This is the main entry you’ll call from jobs. Prioritizing teams
# guarantees your “clubs-first” workflow (e.g., Al-Ahli in SPL, AFC, King’s Cup).
# We avoid AND-filter pitfalls and dedupe merged results by fixture id.


def run_fetch_range(
    start_date: str,
    end_date: str,
    league_ids: Optional[Iterable[int]] = None,
    team_ids: Optional[Iterable[int]] = None,
    timeout: int = 30,
) -> int:
    """
    Backfill a date range inclusive (YYYY-MM-DD → YYYY-MM-DD).

    Example:
        run_fetch_range("2025-09-01", "2025-09-07", team_ids=[2929])
    """
    s = dt.date.fromisoformat(start_date)
    e = dt.date.fromisoformat(end_date)
    if e < s:
        s, e = e, s

    total = 0
    cur = s
    while cur <= e:
        total += run_daily_fetch(
            date=cur.isoformat(),
            league_ids=league_ids,
            team_ids=team_ids,
            timeout=timeout,
        )
        cur += dt.timedelta(days=1)
    return total

# writeafter: Useful for first-run seeding or when the API had a hiccup. The
# same single-day function is reused to keep logic identical across paths.


# =============================================================================
# CLI dev convenience
# =============================================================================
if __name__ == "__main__":
    # Default: fetch "today" using LEAGUE_IDS/TEAM_IDS from .env
    run_daily_fetch()

# writeafter: Allow `python backend/fetcher.py` to work during local dev/testing
# without needing the module launcher. Mirrors the cron behavior with .env
# defaults, which is exactly what we want in quick smoke tests.