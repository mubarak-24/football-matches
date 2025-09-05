# backend/app.py
from __future__ import annotations

import json
import sys
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

# ── Load .env from project root (one level above /backend) ──────────────
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Import AFTER .env is loaded
from backend.job import run_once  # noqa: E402
from backend.store import connect  # noqa: E402

VALID_PARTS = {"prev", "news", "news_yday", "today", "tomorrow", "digest", "api"}


def _print_usage() -> None:
    print(
        "Usage:\n"
        "  python -m backend.app <part>\n\n"
        "Parts:\n"
        "  prev        Yesterday's results (Top 3 + EN/AR recap)\n"
        "  news        Latest football news (last 24h, filtered)\n"
        "  news_yday   Yesterday-only top news (filtered)\n"
        "  today       Today's fixtures\n"
        "  tomorrow    Tomorrow's fixtures\n"
        "  digest      All of the above in one email\n"
        "  api         Start a tiny JSON API for the PWA (http://127.0.0.1:8000)\n\n"
        "Examples:\n"
        "  python -m backend.app prev\n"
        "  python -m backend.app news_yday\n"
        "  python -m backend.app digest\n"
        "  python -m backend.app api\n"
    )


# =============================================================================
# Tiny HTTP API (no external deps)
# =============================================================================

def _rows_for_date(date_iso: str) -> List[Dict[str, Any]]:
    """Return list of match dicts for a given ISO date (YYYY-MM-DD)."""
    with connect() as con:
        cur = con.execute(
            """
            SELECT id, date_utc, league_id, league_name,
                   home_team, away_team, home_goals, away_goals, status
            FROM matches
            WHERE date(date_utc) = ?
            ORDER BY datetime(date_utc) ASC
            """,
            (date_iso,),
        )
        cols = [c[0] for c in cur.description]
        out: List[Dict[str, Any]] = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            out.append(item)
        return out


class _Handler(BaseHTTPRequestHandler):
    # Silence default noisy logging
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        return

    # Common CORS/headers
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path or "/")
            path = parsed.path or "/"
            qs = parse_qs(parsed.query or "")

            if path == "/health":
                return self._send_json({"ok": True})

            if path == "/api/matches/today":
                today = dt.date.today().isoformat()
                rows = _rows_for_date(today)
                return self._send_json({"date": today, "matches": rows})

            if path == "/api/matches/date":
                d = (qs.get("d") or [""])[0]
                # Basic validation
                try:
                    _ = dt.date.fromisoformat(d)
                except Exception:
                    return self._send_json({"error": "invalid date"}, status=400)
                rows = _rows_for_date(d)
                return self._send_json({"date": d, "matches": rows})

            # Fallback
            return self._send_json({"error": "not found"}, status=404)

        except Exception as exc:  # defensive guard; keep server alive
            return self._send_json({"error": f"internal error: {exc!r}"}, status=500)


def _run_api_server(host: str = "127.0.0.1", port: int = 8000) -> int:
    srv = HTTPServer((host, port), _Handler)
    print(f"Serving API on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        srv.server_close()
    return 0


# =============================================================================
# CLI entry
# =============================================================================

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        _print_usage()
        return 0

    part = argv[1].strip().lower()
    if part not in VALID_PARTS:
        print(f"Error: unknown part '{part}'.\n")
        _print_usage()
        return 2

    if part == "api":
        return _run_api_server()

    run_once(part)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())