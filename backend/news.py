# backend/news.py
from __future__ import annotations
import datetime as dt
from urllib.parse import urlparse
import os
import re
import feedparser

# ---------- Feeds (add more if you like) ----------
FEEDS = [
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.theguardian.com/football/rss",
    "https://www.skysports.com/rss/12040",
]

# ---------- Preferences / Tuning ----------
# You can override these from .env:
# NEWS_MAX=8
# NEWS_HOURS=24
# NEWS_MIN_SCORE=2.5

NEWS_MAX = int(os.getenv("NEWS_MAX", "8"))
NEWS_HOURS = int(os.getenv("NEWS_HOURS", "24"))
NEWS_MIN_SCORE = float(os.getenv("NEWS_MIN_SCORE", "2.5"))

# Your clubs & league (aliases in EN + AR)
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

# Saudi Pro League signals
LEAGUE_KEYWORDS = [
    "saudi pro league", "spl", "الدوري السعودي", "دوري روشن", "روشن السعودي",
]

# Positive signal words (newsier / important)
POS_WORDS = [
    "official", "confirmed", "statement", "signs", "suspended", "injury", "out",
    "return", "deal", "transfer", "joins", "sold", "loan", "sack", "appointed",
    "wins", "beats", "draw", "fixtures", "result", "deadline",
    "رسمي", "تعاقد", "انتقال", "إيقاف", "إصابة", "غياب", "عودة", "مدرب", "فوز", "خسارة", "تعادل",
]

# Negative / low-value patterns to down-weight
NEG_PATTERNS = [
    r"\brumou?r\b", r"\brumou?rs\b", r"\bgossip\b", r"\btalk\b", r"\blinked\b",
    r"\bset to\b", r"\breportedly\b", r"\bconsidering\b", r"\bclose to\b",
    r"مصدر|إشاعة|تقارير|مرشح|قد|يرتبط|محتمل",
]

NEG_RX = [re.compile(p, re.I) for p in NEG_PATTERNS]


def _tokens(s: str) -> str:
    s = (s or "").strip().lower()
    # normalize some unicode forms for Arabic/English mix
    return s


def _club_hit_score(title_lc: str, src_lc: str) -> float:
    score = 0.0
    for _, aliases in CLUBS.items():
        for a in aliases:
            a_lc = a.lower()
            if a_lc and (a_lc in title_lc or a_lc in src_lc):
                score += 2.0  # strong boost for club mention
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
    # diminishing returns
    return min(hits, 3) * 0.6


def _neg_words_penalty(title_lc: str) -> float:
    penalty = 0.0
    for rx in NEG_RX:
        if rx.search(title_lc):
            penalty += 0.8
    return penalty


def _source_weight(source_lc: str) -> float:
    # Nudge some sources a bit (tweak freely)
    if "bbc" in source_lc:
        return 1.15
    if "guardian" in source_lc:
        return 1.1
    if "skysports" in source_lc:
        return 1.05
    if "espn" in source_lc:
        return 1.0
    return 1.0


def _score_item(title: str, source: str) -> float:
    t = _tokens(title)
    s = _tokens(source)
    base = 0.0

    base += _club_hit_score(t, s)
    base += _league_hit_score(t, s)
    base += _pos_words_score(t)
    base -= _neg_words_penalty(t)

    # small source weight
    base *= _source_weight(s)
    return base


def fetch_news(max_items: int | None = None, hours_back: int | None = None) -> list[dict]:
    """
    Return top filtered items: [{title, source, link, published, score}]
    """
    max_items = max_items or NEWS_MAX
    hours_back = hours_back or NEWS_HOURS

    now = dt.datetime.utcnow()
    cutoff = now - dt.timedelta(hours=hours_back)
    items: list[dict] = []

    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        meta = getattr(feed, "feed", {}) or {}
        fallback = urlparse(url).netloc
        source = meta.get("title") or fallback

        for e in getattr(feed, "entries", []):
            published = None
            if getattr(e, "published_parsed", None):
                published = dt.datetime(*e.published_parsed[:6])
            elif getattr(e, "updated_parsed", None):
                published = dt.datetime(*e.updated_parsed[:6])

            if published and published < cutoff:
                continue

            title = (e.get("title") or "").strip()
            link = e.get("link") or ""
            if not title:
                continue

            score = _score_item(title, source)
            items.append({
                "title": title,
                "link": link,
                "source": source,
                "published": published.isoformat() if published else "",
                "score": round(score, 3),
            })

    # De-duplicate by normalized title
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        key = it["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)

    # Filter low-value items
    filtered = [it for it in deduped if it["score"] >= NEWS_MIN_SCORE]

    # Sort by (score desc, published desc)
    filtered.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)

    # If nothing passes, fallback to top 3 by score so the email isn’t empty
    if not filtered:
        deduped.sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)
        filtered = deduped[: min(3, max_items)]

    return filtered[:max_items]


def format_news_bulletin(max_items: int | None = None) -> str:
    items = fetch_news(max_items=max_items)
    if not items:
        return "📰 Football News (last 24h)\n- لا توجد عناوين مهمة الآن."

    lines = ["📰 Football News (last 24h — filtered)"]
    for it in items:
        lines.append(f"- [{it['source']}] {it['title']}  (score: {it['score']})\n  {it['link']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_news_bulletin())