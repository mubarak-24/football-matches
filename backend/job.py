# backend/job.py
import os
import datetime as dt
import pytz

# استيرادات مطلقة لتفادي مشاكل التشغيل
from backend.store import init_db, connect
from backend.fetcher import run_daily_fetch
from backend.scorer import pick_top_matches
from backend.summarizer import short_ar, short_en
from backend.emailer import send_email
from backend.news import format_news_bulletin, format_yesterday_news_bulletin

# المنطقة الزمنية + الدوريات من المتغيرات البيئية
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
    # يرجّع كل صف كقاموس بدلاً من tuple
    return {cursor.description[i][0]: row[i] for i in range(len(row))}


def build_prev_results() -> str:
    """نتائج أمس + Top 3 وملخص EN/AR لأفضل مباراة إن وُجد."""
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

    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i}) {r['home_team']} {r['home_goals']}-{r['away_goals']} {r['away_team']} "
            f"— {r['league_name']}"
        )

    # Top 3 (إن كان عندنا IDs)
    top = pick_top_matches(y.isoformat(), LEAGUE_IDS, limit=3) if LEAGUE_IDS else []
    if top:
        lines.append("\n⭐ Top 3 Matches of Yesterday")
        for i, m in enumerate(top, 1):
            lines.append(
                f"{i}. {m['home_team']} {m['home_goals']}-{m['away_goals']} {m['away_team']} "
                f"— {m['league_name']}"
            )
        motd = top[0]
        lines.append("\n— EN Recap —\n" + short_en(motd))
        lines.append("\n— AR ملخص —\n" + short_ar(motd))

    return "\n".join(lines)


def build_news(max_items: int = 8) -> str:
    """آخر أخبار كرة القدم (24 ساعة مفلترة)."""
    return format_news_bulletin(max_items=max_items)


def build_yesterday_news(max_items: int = 6) -> str:
    """أخبار أمس المهمة فقط (مفلترة بالكلمات + الفرق المفضلة)."""
    return format_yesterday_news_bulletin(
        max_items=max_items, tz=os.getenv("TIMEZONE", "Asia/Riyadh")
    )


def build_today_matches() -> str:
    """مباريات اليوم (حسب ما هو مخزّن في SQLite)."""
    t = dt.datetime.now(TZ).date()
    with connect() as con:
        con.row_factory = _dict_row_factory
        rows = con.execute(
            "SELECT * FROM matches "
            "WHERE status IN ('NS','TBD') AND date(date_utc)=?",
            (t.isoformat(),),
        ).fetchall()

    lines: list[str] = [f"⏰ Today's Fixtures ({t}):"]
    if not rows:
        lines.append("- لا توجد مباريات.")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        lines.append(f"{i}) {r['home_team']} vs {r['away_team']} — {r['league_name']}")
    return "\n".join(lines)


def build_tomorrow_matches() -> str:
    """مباريات الغد (حسب ما هو مخزّن في SQLite)."""
    tm = dt.datetime.now(TZ).date() + dt.timedelta(days=1)
    with connect() as con:
        con.row_factory = _dict_row_factory
        rows = con.execute(
            "SELECT * FROM matches "
            "WHERE status IN ('NS','TBD') AND date(date_utc)=?",
            (tm.isoformat(),),
        ).fetchall()

    lines: list[str] = [f"📅 Tomorrow's Fixtures ({tm}):"]
    if not rows:
        lines.append("- لا توجد مباريات.")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        lines.append(f"{i}) {r['home_team']} vs {r['away_team']} — {r['league_name']}")
    return "\n".join(lines)


def run_once(part: str) -> None:
    """يبني الرسالة المطلوبة ويرسلها بالبريد."""
    init_db()

    # نجلب من API فقط للرسائل التي تحتاج مباريات
    needs_api = part in {"prev", "today", "tomorrow", "digest"}
    if needs_api:
        try:
            # fetch daily fixtures (implementation currently fetches 'today' only)
            run_daily_fetch()
        except Exception as e:
            print("⚠️ Skipping API fetch:", e)

    if part == "prev":
        subject = "Football Digest — Yesterday's Results"
        body = build_prev_results()
    elif part == "news":
        subject = "Football Digest — Football News"
        body = build_news()
    elif part == "news_yday":
        subject = "Football Digest — Yesterday's Top News"
        body = build_yesterday_news()
    elif part == "today":
        subject = "Football Digest — Today's Fixtures"
        body = build_today_matches()
    elif part == "tomorrow":
        subject = "Football Digest — Tomorrow's Fixtures"
        body = build_tomorrow_matches()
    elif part == "digest":
        subject = "Football Digest — Daily Digest"
        body = "\n\n".join(
            [
                build_prev_results(),
                build_yesterday_news(),
                build_today_matches(),
                build_tomorrow_matches(),
            ]
        )
    else:
        subject = "Football Digest — Error"
        body = "Invalid part. Use: prev | news | news_yday | today | tomorrow | digest"

    send_email(subject, body)
    print("✅ Sent:", subject)


if __name__ == "__main__":
    import sys

    part = sys.argv[1] if len(sys.argv) > 1 else "prev"
    run_once(part)