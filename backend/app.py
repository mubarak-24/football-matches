from __future__ import annotations

import sys
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env from project root (one level above /backend) ──────────────
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Import AFTER .env is loaded
from backend.job import run_once  # noqa: E402

VALID_PARTS = {"prev", "news", "news_yday", "today", "tomorrow", "digest"}


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
        "  digest      All of the above in one email\n\n"
        "Examples:\n"
        "  python -m backend.app prev\n"
        "  python -m backend.app news_yday\n"
        "  python -m backend.app digest\n"
    )


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

    run_once(part)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())