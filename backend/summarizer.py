# backend/summarizer.py
from __future__ import annotations
from typing import Dict, Any


def _describe_match(row: Dict[str, Any], lang: str = "en") -> str:
    """Generate a short recap sentence based on goals / status."""
    hg, ag = row.get("home_goals"), row.get("away_goals")
    home, away = row.get("home_team"), row.get("away_team")
    league = row.get("league_name", "")

    # Safety defaults
    hg = 0 if hg is None else hg
    ag = 0 if ag is None else ag

    # Determine drama type
    if hg == ag:
        if lang == "ar":
            desc = "انتهت بالتعادل بعد صراع قوي."
        else:
            desc = "ended in a hard-fought draw."
    else:
        winner = home if hg > ag else away
        loser = away if hg > ag else home
        margin = abs(hg - ag)
        if margin == 1:
            if lang == "ar":
                desc = f"حسمها {winner} بفارق هدف واحد فقط ضد {loser}."
            else:
                desc = f"{winner} edged past {loser} by a single goal."
        elif margin == 2:
            if lang == "ar":
                desc = f"{winner} فرض سيطرته على {loser} بفارق هدفين."
            else:
                desc = f"{winner} showed control with a two-goal margin over {loser}."
        else:
            if lang == "ar":
                desc = f"{winner} اكتسح {loser} بفوز كبير."
            else:
                desc = f"{winner} dominated {loser} with a big win."

    if lang == "ar":
        return (
            f"مباراة الأمس: {home} {hg}-{ag} {away}.\n"
            f"{desc}\n"
            f"الدوري: {league}."
        )
    else:
        return (
            f"Match of the Day: {home} {hg}-{ag} {away}.\n"
            f"The game {desc}\n"
            f"League: {league}."
        )


def short_ar(row: Dict[str, Any]) -> str:
    return _describe_match(row, lang="ar")


def short_en(row: Dict[str, Any]) -> str:
    return _describe_match(row, lang="en")