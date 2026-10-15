"""Derive round labels. The club feed carries none (`round` is always empty).

Method: the ordinal of our fixture within a competition this season.
  PREM       — 10 teams, no byes, so our nth league game IS Round n.
               After PREM_REGULAR_ROUNDS: Semi-final, then Final.
  Champions/Challenge — n ≤ EURO_POOL_ROUNDS: "Pool · Rn"; then
               Round of 16, Quarter-final, Semi-final, Final.
  PREM Cup   — two pools of five, home and away over ten rounds, so each team
               has byes and our nth game is NOT round n: "Pool game n" for
               n ≤ PREMCUP_POOL_GAMES (8), then Semi-final, Final.
  Friendly   — "Exhibition".

Known limitation (README): a postponed game re-staged out of order shifts the
labels of the games around it until it has been played. Rare, and the date,
opponent and competition are still right.
"""
from . import config
from .model import Fixture

EURO_KO = ["Round of 16", "Quarter-final", "Semi-final", "Final"]
PREM_KO = ["Semi-final", "Final"]


def comp_info(raw: str) -> tuple[str, str, str]:
    """Raw feed label → (key, display, short). Unknown labels pass through."""
    if raw in config.COMP_LABELS:
        return config.COMP_LABELS[raw]
    return ("other", raw or "Fixture", raw or "Fixture")


def _label(key: str, n: int) -> str:
    if key == "prem":
        if n <= config.PREM_REGULAR_ROUNDS:
            return f"Round {n}"
        i = n - config.PREM_REGULAR_ROUNDS - 1
        return PREM_KO[i] if i < len(PREM_KO) else ""
    if key in ("champions", "challenge"):
        if n <= config.EURO_POOL_ROUNDS:
            return f"Pool · R{n}"
        i = n - config.EURO_POOL_ROUNDS - 1
        return EURO_KO[i] if i < len(EURO_KO) else ""
    if key == "premcup":
        if n <= config.PREMCUP_POOL_GAMES:
            return f"Pool game {n}"
        i = n - config.PREMCUP_POOL_GAMES - 1
        return PREM_KO[i] if i < len(PREM_KO) else ""
    if key == "friendly":
        return "Exhibition"
    return ""


def label_rounds(fixtures: list[Fixture]) -> dict[int, str]:
    """{fixture id: round label} over the whole season list (past included,
    which is why the season calendar, not the 'upcoming' one, is fetched)."""
    out: dict[int, str] = {}
    counters: dict[tuple[str, str], int] = {}
    for fx in sorted(fixtures, key=lambda f: f.kickoff_utc):
        key = comp_info(fx.competition_raw)[0]
        c = counters[(fx.season_id, key)] = counters.get((fx.season_id, key), 0) + 1
        out[fx.id] = _label(key, c)
    return out
