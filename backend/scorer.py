# backend/scorer.py
from __future__ import annotations

from typing import Iterable, List, Dict, Any, Sequence, Tuple
from backend.store import connect


# أوزان الخوارزمية (لو حبيت تعدّل بسهولة)
W_GOALS = 3.0
W_DRAW = 2.0
W_LEAD = 1.5
W_XG = 1.2
W_CARDS = 0.8
W_UPSET = 2.0
W_LATE = 0.5


def _num(x: Any, default: float = 0.0) -> float:
    """يحاول تحويل القيمة إلى رقم؛ يرجع default لو ما ينفع."""
    try:
        if isinstance(x, bool):
            return float(int(x))
        return float(x)
    except (TypeError, ValueError):
        return default


def compute_score(row: Dict[str, Any]) -> float:
    """
    يحسب نقاط المباراة حسب الصيغة المتفق عليها.
    المتغيرات الاختيارية (xG/carts/upset/late_drama/lead_changes) لو غير موجودة تُحتسب 0.
    """
    hg = _num(row.get("home_goals"))
    ag = _num(row.get("away_goals"))
    total_goals = hg + ag

    draw_bonus = 1.0 if (row.get("home_goals") is not None and row.get("home_goals") == row.get("away_goals")) else 0.0
    lead_changes = _num(row.get("lead_changes"))
    xg_total = _num(row.get("xg_home")) + _num(row.get("xg_away"))
    cards = _num(row.get("cards_home")) + _num(row.get("cards_away"))
    upset = _num(row.get("upset"))
    late_drama = _num(row.get("late_drama"))

    return (
        W_GOALS * total_goals
        + W_DRAW * draw_bonus
        + W_LEAD * lead_changes
        + W_XG * xg_total
        + W_CARDS * cards
        + W_UPSET * upset
        + W_LATE * late_drama
    )


def _to_int_list(values: Iterable[Any]) -> List[int]:
    out: List[int] = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def pick_top_matches(target_date: str, league_ids: Iterable[int] | None, limit: int = 5) -> List[Dict[str, Any]]:
    """
    يرجّع أفضل المباريات (حسب compute_score) ليوم معيّن (YYYY-MM-DD).
    - لو league_ids موجودة، يفلتر الدوري عليها.
    - يرجّع قائمة من قواميس صفوف SQLite.
    """
    sql = "SELECT * FROM matches WHERE status='FT' AND date(date_utc)=?"
    params: List[Any] = [target_date]

    lids = _to_int_list(list(league_ids or []))
    if lids:
        placeholders = ",".join("?" for _ in lids)
        sql += f" AND league_id IN ({placeholders})"
        params.extend(lids)

    with connect() as con:
        con.row_factory = lambda c, r: {c.description[i][0]: r[i] for i in range(len(r))}
        rows: List[Dict[str, Any]] = con.execute(sql, params).fetchall()

    if not rows:
        return []

    def sort_key(row: Dict[str, Any]) -> Tuple[float, float, float, int]:
        total_goals = _num(row.get("home_goals")) + _num(row.get("away_goals"))
        late = _num(row.get("late_drama"))
        # لو id مفقود/غلط، خليه 0
        try:
            neg_id = -int(row.get("id", 0) or 0)
        except (TypeError, ValueError):
            neg_id = 0
        return (compute_score(row), total_goals, late, neg_id)

    lim = max(1, int(limit or 1))
    return sorted(rows, key=sort_key, reverse=True)[:lim]