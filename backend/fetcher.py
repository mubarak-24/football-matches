# backend/fetcher.py
from __future__ import annotations

import os
import datetime as dt
import requests
import pytz

from backend.store import connect

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Riyadh"))


def _parse_league_ids(env_val: str) -> list[int]:
    out: list[int] = []
    for x in (env_val or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            # ignore non-numeric pieces
            pass
    return out


DEFAULT_LEAGUE_IDS = _parse_league_ids(os.getenv("LEAGUE_IDS", ""))


def run_daily_fetch(
    date: str | None = None,
    league_ids: list[int] | None = None,
    timeout: int = 30,
) -> int:
    """
    Fetch fixtures for a given date (default: today in TIMEZONE) and save into SQLite.

    Args:
        date: ISO date string (YYYY-MM-DD). If None, uses "today" in TZ.
        league_ids: Optional list of league IDs to filter results.
        timeout: HTTP timeout in seconds.

    Returns:
        int: number of matches saved (inserted/replaced) into SQLite.

    Raises:
        RuntimeError: if API key is missing or the API returns an error.
    """
    if not API_KEY:
        raise RuntimeError("⚠️ API_FOOTBALL_KEY not found in .env")

    if not date:
        date = dt.datetime.now(TZ).date().isoformat()

    if league_ids is None:
        league_ids = DEFAULT_LEAGUE_IDS

    headers = {
        "x-apisports-key": API_KEY,
        "User-Agent": "football-digest/1.0 (+https://example.local)",
        "Accept": "application/json",
    }

    # Use params dict; API-Football allows multiple 'league' params.
    params: list[tuple[str, str | int]] = [("date", date)]
    for lid in league_ids or []:
        params.append(("league", lid))

    try:
        resp = requests.get(f"{BASE_URL}/fixtures", headers=headers, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Network error calling API-Football: {exc}") from exc

    if resp.status_code == 429:
        # Rate limit: show the small response if any (usually includes 'message')
        detail = ""
        try:
            detail = resp.json().get("message") or ""
        except Exception:
            detail = resp.text[:200]
        raise RuntimeError(f"API rate limit (429). {detail}".strip())

    if resp.status_code != 200:
        # Keep error succinct but useful
        snippet = resp.text[:300]
        raise RuntimeError(f"API error {resp.status_code}: {snippet}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("Invalid JSON from API-Football") from exc

    matches = data.get("response", []) or []

    saved = 0
    with connect() as con:
        for m in matches:
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

    print(f"✅ Saved {saved} matches from API for {date}")
    return saved


if __name__ == "__main__":
    run_daily_fetch()