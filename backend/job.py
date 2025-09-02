import os
import datetime as dt
import pytz
from pathlib import Path

# ── Load .env defensively (works with: python -m backend.job prev) ─────────────
try:
    from dotenv import load_dotenv  # type: ignore
    ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# ── Absolute imports (avoid relative import surprises) ─────────────────────────
from backend.store import init_db, connect
from backend.fetcher import run_daily_fetch
from backend.scorer import pick_top_matches
from backend.summarizer import short_ar, short_en
from backend.emailer import send_email

# ── Import news formatters (normal + yesterday-only if available) ──────────────
try:
    from backend.news import (
        format_news_bulletin,
        format_yesterday_news_bulletin as _format_yday_news,
    )
    _HAS_YDAY_NEWS = True
except Exception:
    from backend.news import format_news_bulletin

    _HAS_YDAY_NEWS = False

    def _format_yday_news(max_items: int = 6, **_kwargs) -> str:
        # fallback: extend hours_back so it looks like "yesterday news"
        return format_news_bulletin(max_items=max_items, hours_back=36)


# ── Settings from environment ─────────────────────────────────────────────────
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Riyadh"))


def _parse_league_ids(env_val: str) -> list[int]:
    ids: list[int] = []
    for x in (env_val or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            ids.append(int(x))
        except ValueError:
            pass
    return ids


LEAGUE_IDS = _parse_league_ids(os.getenv("LEAGUE_IDS", ""))


def _dict_row_factory(cursor, row):
    """Return each SQLite row as a dict instead of tuple."""
    return {cursor.description[i][0]: row[i] for i in range(len(row))}


# ── Builders (results / news / fixtures) ──────────────────────────────────────
def build_prev_results() -> str:
    """Yesterday's results + Top 3 matches + EN/AR recap."""
    today = dt.datetime.now(TZ).date()
    y = today - dt.timedelta(days=1)

    with connect() as con:
        con.row_factory = _dict_row_factory
        rows = con.execute(
            "SELECT * FROM matches WHERE status='FT' AND date(date_utc)=?",
            (y.isoformat(),),
        ).fetchall()

    lines: list[str] = [f"🔁 Yesterday's Results ({y}):"]
    if not rows:
        lines.append("- لا توجد نتائج.")
        return "\n".join(lines)

    # List all finished matches
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i}) {r['home_team']} {r['home_goals']}-{r['away_goals']} "
            f"{r['away_team']} — {r['league_name']}"
        )

    # Highlight Top 3 matches (if LEAGUE_IDS configured)
    top = pick_top_matches(y.isoformat(), LEAGUE_IDS, limit=3) if LEAGUE_IDS else []
    if top:
        lines.append("\n⭐ Top 3 Matches of Yesterday")
        for i, m in enumerate(top, 1):
            lines.append(
                f"{i}. {m['home_team']} {m['home_goals']}-{m['away_goals']} "
                f"{m['away_team']} — {m['league_name']}"
            )
        motd = top[0]
        lines.append("\n— EN Recap —\n" + short_en(motd))
        lines.append("\n— AR ملخص —\n" + short_ar(motd))

    return "\n".join(lines)


def build_news(max_items: int = 8) -> str:
    """Latest football news (last 24h, filtered)."""
    return format_news_bulletin(max_items=max_items)


def build_yesterday_news(max_items: int = 6) -> str:
    """Important news from yesterday only (filtered)."""
    return _format_yday_news(
        max_items=max_items, tz=os.getenv("TIMEZONE", "Asia/Riyadh")
    )


def _build_fixtures_for_date(d: dt.date, title_emoji: str, title_text: str) -> str:
    """Helper to build fixtures for a given date."""
    with connect() as con:
        con.row_factory = _dict_row_factory
        rows = con.execute(
            "SELECT * FROM matches "
            "WHERE status IN ('NS','TBD') AND date(date_utc)=?",
            (d.isoformat(),),
        ).fetchall()

    header = f"{title_emoji} {title_text} ({d}):"
    lines: list[str] = [header]
    if not rows:
        lines.append("- لا توجد مباريات.")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        lines.append(f"{i}) {r['home_team']} vs {r['away_team']} — {r['league_name']}")
    return "\n".join(lines)


def build_today_matches() -> str:
    """Today's fixtures (from DB)."""
    return _build_fixtures_for_date(dt.datetime.now(TZ).date(), "⏰", "Today's Fixtures")


def build_tomorrow_matches() -> str:
    """Tomorrow's fixtures (from DB)."""
    tm = dt.datetime.now(TZ).date() + dt.timedelta(days=1)
    return _build_fixtures_for_date(tm, "📅", "Tomorrow's Fixtures")


# ── Runner ───────────────────────────────────────────────────────────────────
def run_once(part: str) -> str:
    """
    Build the requested section and send it by email.
    Returns the message body (so a PWA/frontend can also reuse it).
    """
    init_db()

    # Only call API if we need matches data
    if part in {"prev", "today", "tomorrow", "digest"}:
        try:
            run_daily_fetch()
        except Exception as e:
            print("⚠️ Skipping API fetch:", e)

    if part == "prev":
        subject, body = "Football Digest — Yesterday's Results", build_prev_results()
    elif part == "news":
        subject, body = "Football Digest — Football News", build_news()
    elif part == "news_yday":
        subject, body = "Football Digest — Yesterday's Top News", build_yesterday_news()
    elif part == "today":
        subject, body = "Football Digest — Today's Fixtures", build_today_matches()
    elif part == "tomorrow":
        subject, body = "Football Digest — Tomorrow's Fixtures", build_tomorrow_matches()
    elif part == "digest":
        subject = "Football Digest — Daily Digest"
        body = "\n\n".join(
            [build_prev_results(), build_yesterday_news(), build_today_matches(), build_tomorrow_matches()]
        )
    else:
        subject, body = "Football Digest — Error", "Invalid part."

    send_email(subject, body)
    print("✅ Sent:", subject)

    return body  # 👈 useful for frontend/PWA


if __name__ == "__main__":
    import sys
    run_once(sys.argv[1] if len(sys.argv) > 1 else "prev")