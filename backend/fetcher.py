# backend/fetcher.py
from __future__ import annotations

import os
import datetime as dt
from typing import Iterable, List, Tuple, Optional

import requests
import pytz

from backend.store import connect

# ---------------------------------------------------------------------
# Environment / constants
# ---------------------------------------------------------------------
API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Riyadh"))

# Optional season (only needed for some discover endpoints, not used here)
SEASON = os.getenv("SEASON")  # e.g., "2024"


def _parse_int_list(env_val: str | None) -> list[int]:
    out: list[int] = []
    for x in (env_val or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            # ignore non-integers
            pass
    return out


# From .env
DEFAULT_LEAGUE_IDS: list[int] = _parse_int_list(os.getenv("LEAGUE_IDS"))
DEFAULT_TEAM_IDS: list[int] = _parse_int_list(os.getenv("TEAM_IDS"))  # optional


# ---------------------------------------------------------------------
# Core fetcher
# ---------------------------------------------------------------------
def _request(
    endpoint: str,
    params: List[Tuple[str, str | int]],
    timeout: int = 30,
) -> dict:
    """Small helper to call API-Football with basic error handling."""
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
        # Rate limit
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


def _upsert_fixtures(rows: list[dict]) -> int:
    """Insert/update fixtures into SQLite."""
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


def run_daily_fetch(
    date: str | None = None,
    league_ids: Optional[Iterable[int]] = None,
    team_ids: Optional[Iterable[int]] = None,
    timeout: int = 30,
) -> int:
    """
    Fetch fixtures for a given date (defaults to 'today' in TIMEZONE) and save into SQLite.

    - You can filter by league_ids (LEAGUE_IDS in .env).
    - You can also filter by team_ids (TEAM_IDS in .env) to always include clubs
      like Al Ahli even when they play in other competitions (Asia/King's/Etc).

    API-Football allows combining date with repeated 'league' and 'team' params.
    We call it once with all filters.

    Returns:
        int: number of fixtures saved.
    """
    # Resolve date (local TZ -> ISO date)
    if not date:
        date = dt.datetime.now(TZ).date().isoformat()

    # Resolve filters (fall back to .env defaults)
    lid_list = list(league_ids) if league_ids is not None else list(DEFAULT_LEAGUE_IDS)
    tid_list = list(team_ids) if team_ids is not None else list(DEFAULT_TEAM_IDS)

    # Build params
    params: list[tuple[str, str | int]] = [("date", date)]
    for lid in lid_list:
        params.append(("league", lid))
    for tid in tid_list:
        params.append(("team", tid))

    data = _request("/fixtures", params=params, timeout=timeout)
    fixtures = data.get("response", []) or []

    saved = _upsert_fixtures(fixtures)
    print(f"✅ Saved {saved} matches from API for {date}")
    return saved


# ---------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------
def run_fetch_range(
    start_date: str,
    end_date: str,
    league_ids: Optional[Iterable[int]] = None,
    team_ids: Optional[Iterable[int]] = None,
    timeout: int = 30,
) -> int:
    """
    Fetch a range of dates inclusive (YYYY-MM-DD -> YYYY-MM-DD).
    Useful if you want to backfill a few days.
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


if __name__ == "__main__":
    # Default: fetch "today" with LEAGUE_IDS/TEAM_IDS from .env
    run_daily_fetch()