# backend/news.py
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Iterable
from urllib.parse import urlparse

import feedparser
import pytz

# --------------------------- Feeds (يمكنك الإضافة) ----------------------------
FEEDS = [
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.theguardian.com/football/rss",
    "https://www.skysports.com/rss/12040",
]

# --------------------------- إعدادات قابلة للضبط -----------------------------
# تقدر تغيّرها من .env
NEWS_MAX = int(os.getenv("NEWS_MAX", "8"))
NEWS_HOURS = int(os.getenv("NEWS_HOURS", "24"))           # للنافذة العامة
NEWS_MIN_SCORE = float(os.getenv("NEWS_MIN_SCORE", "2.5"))  # الحد الأدنى للعرض
DEFAULT_TZ = os.getenv("TIMEZONE", "Asia/Riyadh")

# أندية وكيوردز نهتم بها (EN/AR)
CLUBS = {
    # Spain
    "real madrid": ["real madrid", "madrid", "ريال مدريد"],
    "barcelona": ["barcelona", "barça", "barca", "برشلونة"],
    # Italy
    "ac milan": ["ac milan", "milan", "ميلان"],
    # England
    "manchester united": ["man united", "man utd", "manchester united", "يونايتد"],
    "manchester city": ["man city", "manchester city", "السيتي"],
    "arsenal": ["arsenal", "آرسنال", "ارسنال"],
    "chelsea": ["chelsea", "تشيلسي"],
    # Saudi
    "al ahli": ["al ahli", "al-ahli", "alahli", "الأهلي", "الأهلي جدة", "أهلي جدة"],
}

LEAGUE_KEYWORDS = [
    "saudi pro league", "spl", "الدوري السعودي", "دوري روشن", "روشن السعودي",
]

# كلمات إيجابية (تعطي وزن أعلى للخبر المهم)
POS_WORDS = [
    "official", "confirmed", "statement", "signs", "suspended", "injury", "out",
    "return", "deal", "transfer", "joins", "sold", "loan", "sack", "appointed",
    "wins", "beats", "draw", "fixtures", "result", "deadline",
    "رسمي", "تعاقد", "انتقال", "إيقاف", "إصابة", "غياب", "عودة", "مدرب", "فوز", "خسارة", "تعادل",
]

# أنماط أخبار ضعيفة/إشاعات لخفض الوزن
NEG_PATTERNS = [
    r"\brumou?r\b", r"\brumou?rs\b", r"\bgossip\b", r"\btalk\b", r"\blinked\b",
    r"\bset to\b", r"\breportedly\b", r"\bconsidering\b", r"\bclose to\b",
    r"مصدر|إشاعة|تقارير|مرشح|قد|يرتبط|محتمل",
]
NEG_RX = [re.compile(p, re.I) for p in NEG_PATTERNS]


# ------------------------------- Helpers --------------------------------------
def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _source_weight(source_lc: str) -> float:
    # Boost بسيط لبعض المصادر
    if "bbc" in source_lc:
        return 1.15
    if "guardian" in source_lc:
        return 1.1
    if "skysports" in source_lc:
        return 1.05
    if "espn" in source_lc:
        return 1.0
    return 1.0


def _club_hit_score(title_lc: str, src_lc: str) -> float:
    score = 0.0
    for aliases in CLUBS.values():
        for a in aliases:
            a_lc = a.lower()
            if a_lc and (a_lc in title_lc or a_lc in src_lc):
                score += 2.0  # Boost قوي لذكر النادي
                break
    return score


def _league_hit_score(title_lc: str, src_lc: str) -> float:
    score = 0.0
    for kw in LEAGUE_KEYWORDS:
        kw_lc = kw.lower()
        if kw_lc in title_lc or kw_lc in src_lc:
            score += 1.5
    return score


def _pos_words_score(title_lc: str) -> float:
    hits = sum(1 for w in POS_WORDS if w.lower() in title_lc)
    return min(hits, 3) * 0.6  # عوائد متناقصة


def _neg_words_penalty(title_lc: str) -> float:
    penalty = 0.0
    for rx in NEG_RX:
        if rx.search(title_lc):
            penalty += 0.8
    return penalty


def _score_item(title: str, source: str) -> float:
    t = _norm(title)
    s = _norm(source)
    base = 0.0
    base += _club_hit_score(t, s)
    base += _league_hit_score(t, s)
    base += _pos_words_score(t)
    base -= _neg_words_penalty(t)
    base *= _source_weight(s)
    return base


def _within_local_day(dt_utc: dt.datetime, tzname: str, target_day: dt.date) -> bool:
    """
    تحوّل زمن UTC لـ timezone المحدد وتتحقق إن الخبر داخل نفس تاريخ target_day (محليًا).
    """
    tz = pytz.timezone(tzname)
    local_dt = dt_utc.astimezone(tz)
    return local_dt.date() == target_day


def _iter_feeds(feeds: Iterable[str]) -> Iterable[tuple[str, list]]:
    """
    Generator يرجّع (source_title, entries) لكل فيد.
    """
    for url in feeds:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        meta = getattr(feed, "feed", {}) or {}
        fallback = urlparse(url).netloc
        source = meta.get("title") or fallback
        entries = getattr(feed, "entries", []) or []
        yield source, entries


# ------------------------------ Core fetchers ---------------------------------
def fetch_news(
    max_items: int | None = None,
    hours_back: int | None = None,
) -> list[dict]:
    """
    يجلب الأخبار ضمن نافذة زمنية محددة (افتراضي 24 ساعة):
    يعيد قائمة بعناصر: [{title, source, link, published, score}]
    """
    max_items = max_items or NEWS_MAX
    hours_back = hours_back or NEWS_HOURS

    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours_back)

    items: list[dict] = []
    for source, entries in _iter_feeds(FEEDS):
        src_lc = _norm(source)
        for e in entries:
            # parse published time (UTC-naive→make it UTC-aware)
            published = None
            if getattr(e, "published_parsed", None):
                published = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc)
            elif getattr(e, "updated_parsed", None):
                published = dt.datetime(*e.updated_parsed[:6], tzinfo=dt.timezone.utc)

            if published and published < cutoff:
                continue

            title = (e.get("title") or "").strip()
            link = e.get("link") or ""
            if not title:
                continue

            score = _score_item(title, source)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source,
                    "published": published.isoformat() if published else "",
                    "score": round(score, 3),
                }
            )

    # de-dup by normalized title
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        key = _norm(it["title"])
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)

    # filter by score
    filtered = [it for it in deduped if it["score"] >= NEWS_MIN_SCORE]

    # sort by (score desc, published desc)
    filtered.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)

    # fallback: لو مافي شيء فوق العتبة، رجّع أعلى 3 عالأقل
    if not filtered:
        deduped.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)
        filtered = deduped[: min(3, max_items)]

    return filtered[:max_items]


def fetch_yesterday_news(
    max_items: int | None = None,
    tz: str | None = None,
) -> list[dict]:
    """
    يجلب الأخبار التي نشرت خلال "أمس" فقط (حسب timezone الممرّر).
    يحوّل وقت النشر لـ timezone محلي ويتحقق من تاريخ أمس المحلي.
    """
    max_items = max_items or NEWS_MAX
    tz = tz or DEFAULT_TZ
    tzinfo = pytz.timezone(tz)

    # حدّد يوم "أمس" المحلي
    now_local = dt.datetime.now(tzinfo)
    yday_local_date = (now_local - dt.timedelta(days=1)).date()

    items: list[dict] = []
    for source, entries in _iter_feeds(FEEDS):
        for e in entries:
            published_utc = None
            if getattr(e, "published_parsed", None):
                published_utc = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc)
            elif getattr(e, "updated_parsed", None):
                published_utc = dt.datetime(*e.updated_parsed[:6], tzinfo=dt.timezone.utc)

            # لو ما عرفنا وقت النشر، تجاهل (حتى لا نخاطر)
            if not published_utc:
                continue

            if not _within_local_day(published_utc, tz, yday_local_date):
                continue

            title = (e.get("title") or "").strip()
            if not title:
                continue

            link = e.get("link") or ""
            score = _score_item(title, source)

            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source,
                    "published": published_utc.isoformat(),
                    "score": round(score, 3),
                }
            )

    # de-dup + filter + sort
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        key = _norm(it["title"])
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)

    filtered = [it for it in deduped if it["score"] >= NEWS_MIN_SCORE]
    filtered.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)

    if not filtered:
        # fallback: رجّع أعلى 3 من أمس (حتى لو تحت العتبة) عشان ما تطلع فارغة
        deduped.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)
        filtered = deduped[: min(3, max_items)]

    return filtered[:max_items]


# ----------------------------- Formatters (strings) ---------------------------
def format_news_bulletin(max_items: int | None = None, hours_back: int | None = None) -> str:
    """
    نشرة أخبار لآخر N ساعة (افتراضي 24h).
    """
    items = fetch_news(max_items=max_items, hours_back=hours_back)
    if not items:
        return "📰 Football News (last 24h)\n- لا توجد عناوين مهمة الآن."
    lines = ["📰 Football News (last 24h — filtered)"]
    for it in items:
        lines.append(f"- [{it['source']}] {it['title']}  (score: {it['score']})\n  {it['link']}")
    return "\n".join(lines)


def format_yesterday_news_bulletin(max_items: int | None = None, tz: str | None = None) -> str:
    """
    نشرة أخبار لأمس فقط (حسب التوقيت المحلي).
    """
    tz = tz or DEFAULT_TZ
    tzinfo = pytz.timezone(tz)
    yday = (dt.datetime.now(tzinfo) - dt.timedelta(days=1)).date()

    items = fetch_yesterday_news(max_items=max_items, tz=tz)
    if not items:
        return f"📰 Yesterday's Football News ({yday})\n- لا توجد عناوين مهمة ليوم أمس."

    lines = [f"📰 Yesterday's Football News ({yday} — filtered)"]
    for it in items:
        lines.append(f"- [{it['source']}] {it['title']}  (score: {it['score']})\n  {it['link']}")
    return "\n".join(lines)


# ----------------------------- Manual test runner -----------------------------
if __name__ == "__main__":
    print(format_news_bulletin())
    # or:
    # print(format_yesterday_news_bulletin(tz="Asia/Riyadh"))