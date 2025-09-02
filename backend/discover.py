# backend/discover.py
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

# Load .env from project root so this module works via: python -m backend.discover ...
try:
    from dotenv import load_dotenv  # type: ignore
    ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(ROOT / ".env")
except Exception:
    pass

BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.getenv("API_FOOTBALL_KEY")


def _headers() -> dict[str, str]:
    if not API_KEY:
        print("⚠️  API_FOOTBALL_KEY missing in .env", file=sys.stderr)
        sys.exit(2)
    return {
        "x-apisports-key": API_KEY,
        "User-Agent": "football-digest/1.0",
        "Accept": "application/json",
    }


def _get(path: str, **params: Any) -> dict:
    r = requests.get(f"{BASE_URL}/{path.lstrip('/')}", headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ----------------- commands -----------------

def cmd_leagues(args: argparse.Namespace) -> None:
    """
    Examples:
      python -m backend.discover leagues --country "Saudi Arabia" --season 2024
      python -m backend.discover leagues --search "Premier" --season 2024
    """
    q: dict[str, Any] = {}
    if args.country:
        q["country"] = args.country
    if args.search:
        q["search"] = args.search
    if args.season:
        q["season"] = args.season

    data = _get("leagues", **q).get("response", [])
    if not data:
        print("No leagues found.")
        return

    print(f"Found {len(data)} leagues:")
    for item in data:
        lg = item.get("league", {}) or {}
        cn = item.get("country", {}) or {}
        name = lg.get("name")
        lid = lg.get("id")
        ctry = cn.get("name")
        typ = lg.get("type")  # League/Cup
        print(f"- id={lid:<5}  name={name}  type={typ}  country={ctry}")


def cmd_team(args: argparse.Namespace) -> None:
    """
    Examples:
      python -m backend.discover team --search "Al Ahli"
      python -m backend.discover team --search "Al Ahli Jeddah"
    """
    if not args.search:
        print("--search is required")
        return
    data = _get("teams", search=args.search).get("response", [])
    if not data:
        print("No teams found.")
        return

    print(f"Found {len(data)} teams:")
    for item in data:
        tm = item.get("team", {}) or {}
        vn = item.get("venue", {}) or {}
        print(f"- id={tm.get('id')}  name={tm.get('name')}  country={tm.get('country')}  "
              f"city={vn.get('city')}  code={tm.get('code')}")


def cmd_team_comps(args: argparse.Namespace) -> None:
    """
    Show which competitions a team plays in for a given season.
    Examples:
      python -m backend.discover team-comps --team 152 --season 2024
    """
    if not args.team:
        print("--team is required (numeric team id)")
        return
    if not args.season:
        print("--season is required (e.g., 2024)")
        return

    # API: /leagues?team=<id>&season=<year>
    data = _get("leagues", team=args.team, season=args.season).get("response", [])
    if not data:
        print("No leagues for that team/season.")
        return

    print(f"Team {args.team} leagues in season {args.season}:")
    for item in data:
        lg = item.get("league", {}) or {}
        cn = item.get("country", {}) or {}
        print(f"- id={lg.get('id'):<5}  name={lg.get('name')}  type={lg.get('type')}  country={cn.get('name')}")


# ----------------- parser -----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend.discover", description="API-Football discover helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("leagues", help="search leagues")
    p1.add_argument("--country", type=str, help='Country name, e.g. "Saudi Arabia"')
    p1.add_argument("--search", type=str, help='Search text, e.g. "Premier" / "La Liga"')
    p1.add_argument("--season", type=int, help="Season year, e.g. 2024")
    p1.set_defaults(func=cmd_leagues)

    p2 = sub.add_parser("team", help="search teams by name")
    p2.add_argument("--search", type=str, required=True, help='Team name fragment, e.g. "Al Ahli Jeddah"')
    p2.set_defaults(func=cmd_team)

    p3 = sub.add_parser("team-comps", help="leagues a team plays in for a season")
    p3.add_argument("--team", type=int, required=True, help="Team ID (numeric)")
    p3.add_argument("--season", type=int, required=True, help="Season year, e.g. 2024")
    p3.set_defaults(func=cmd_team_comps)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())