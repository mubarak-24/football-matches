# backend/scorer.py
from __future__ import annotations

from typing import Iterable, List, Dict, Any
from backend.store import connect


def compute_score(row: Dict[str, Any]) -> float:
    total_goals = (row.get("home_goals") or 0) + (row.get("away_goals") or 0)
    draw_bonus = 1 if (
        row.get("home_goals") is not None and row.get("home_goals") == row.get("away_goals")
    ) else 0
    lead_changes = row.get("lead_changes") or 0
    xg_total = sum(x for x in (row.get("xg_home"), row.get("xg_away")) if isinstance(x, (int, float)))
    cards = sum(x for x in (row.get("cards_home"), row.get("cards_away")) if isinstance(x, (int, float)))
    upset = row.get("upset") or 0
    late_drama = row.get("late_drama") or 0
    return (
        3 * total_goals
        + 2 * draw_bonus
        + 1.5 * lead_changes
        + 1.2 * xg_total
        + 0.8 * cards
        + 2 * upset
        + 0.5 * late_drama
    )


def pick_top_matches(target_date: str, league_ids: Iterable[int] | None, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Return top matches (by our heuristic) for a given ISO date (YYYY-MM-DD).
    If league_ids is provided, results are filtered to those leagues.
    """
    sql = "SELECT * FROM matches WHERE status='FT' AND date(date_utc)=?"
    params: List[Any] = [target_date]

    lids = list(league_ids or [])
    if lids:
        placeholders = ",".join("?" for _ in lids)
        sql += f" AND league_id IN ({placeholders})"
        params.extend(lids)

    with connect() as con:
        con.row_factory = lambda c, r: {c.description[i][0]: r[i] for i in range(len(r))}
        rows: List[Dict[str, Any]] = con.execute(sql, params).fetchall()

    if not rows:
        return []

    def key(row: Dict[str, Any]):
        total_goals = (row.get("home_goals") or 0) + (row.get("away_goals") or 0)
        # If id is missing/unexpected, fallback to 0 so sort key is stable
        try:
            neg_id = -int(row.get("id", 0) or 0)
        except (TypeError, ValueError):
            neg_id = 0
        return (compute_score(row), total_goals, (row.get("late_drama") or 0), neg_id)

    return sorted(rows, key=key, reverse=True)[:max(1, int(limit))]