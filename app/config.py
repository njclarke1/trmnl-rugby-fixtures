"""Central configuration. Everything team- or stack-specific is env-driven.

One codebase serves several stacks (Bristol on :3459, England later on :3460):
the stack's env picks the fixtures source adapter, the team and its labels.
"""
import json
import os


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# --- team ------------------------------------------------------------------
TEAM_NAME = os.environ.get("TEAM_NAME", "Bristol Bears")
# Spine badge text (mock: "BB"). Blank = word initials of TEAM_NAME.
TEAM_BADGE = os.environ.get("TEAM_BADGE", "")

# --- fixtures source ------------------------------------------------------
# "club_wp"  — club WordPress feed (Bristol Bears), iCal core + JSON enrichment
# "stub"     — same adapter, reading tests/fixtures/ (offline dev, tests, demo)
FIXTURES_SOURCE = os.environ.get("FIXTURES_SOURCE", "club_wp")
STUB_DIR = os.environ.get("STUB_DIR", "/app/tests/fixtures")

CLUB_FEED_BASE = os.environ.get(
    "CLUB_FEED_BASE", "https://www.bristolbearsrugby.com/wp-json/afz/v1").rstrip("/")
CLUB_FEED_CATEGORY = os.environ.get("CLUB_FEED_CATEGORY", "men")
# JSON enrichment (crests, scores, result status). Optional garnish: a failure
# here never removes a fixture.
ENABLE_ENRICH = _bool("ENABLE_ENRICH", "1")

# Season ids. Blank = derive from the date: the club numbers men's seasons
# "<start year>01" (2026/27 → 202601). The current season and the next one are
# both fetched so the June–September rollover never empties the screen.
SEASON_IDS = _list("SEASON_IDS", "")
SEASON_CUTOVER_MONTH = int(os.environ.get("SEASON_CUTOVER_MONTH", "7"))

# Plain UA. Never put an email address in it (ESPN's edge 403s on one;
# no reason to find out whether anyone else does).
USER_AGENT = "trmnl-rugby-fixtures/1.0 (personal e-ink display)"
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20"))

# --- competitions -----------------------------------------------------------
# The club feed labels BOTH EPCR tiers "European Cup". Which one Bristol are in
# is set here once a season: "champions" or "challenge".
EURO_TIER = os.environ.get("EURO_TIER", "champions").strip().lower()

# Raw feed label → (key, display, short). Override/extend with COMP_LABELS as
# JSON, e.g. {"Some Cup": ["somecup", "Some Cup", "Some"]}.
_EURO = {"champions": ("champions", "Champions Cup", "Champions Cup"),
         "challenge": ("challenge", "Challenge Cup", "Challenge Cup")}
COMP_LABELS: dict[str, tuple[str, str, str]] = {
    "Gallagher Premiership": ("prem", "Gallagher PREM", "PREM"),
    "Gallagher PREM": ("prem", "Gallagher PREM", "PREM"),
    "Prem Rugby Cup": ("premcup", "PREM Rugby Cup", "PREM Cup"),
    "PREM Rugby Cup": ("premcup", "PREM Rugby Cup", "PREM Cup"),
    "European Cup": _EURO.get(EURO_TIER, _EURO["champions"]),
    "Exhibition": ("friendly", "Friendly", "Friendly"),
}
COMP_LABELS.update({k: tuple(v) for k, v in json.loads(os.environ.get("COMP_LABELS") or "{}").items()})

# Round derivation (the feed carries no round). Ordinal of our fixture within
# the competition this season → label. See app/rounds.py.
PREM_REGULAR_ROUNDS = int(os.environ.get("PREM_REGULAR_ROUNDS", "18"))
EURO_POOL_ROUNDS = int(os.environ.get("EURO_POOL_ROUNDS", "4"))
PREMCUP_POOL_GAMES = int(os.environ.get("PREMCUP_POOL_GAMES", "8"))

# --- provisional kickoff times ----------------------------------------------
# The feed has no TBC flag; unconfirmed PREM kickoffs sit at a 15:00 weekend
# placeholder until broadcasters pick. A kickoff matching a placeholder slot and
# further out than the horizon is shown as provisional. Self-clearing: the club
# edits the time, or the fixture comes inside the horizon.
TBC_HORIZON_DAYS = int(os.environ.get("TBC_HORIZON_DAYS", "42"))
TBC_PLACEHOLDER_TIMES = _list("TBC_PLACEHOLDER_TIMES", "15:00")
TBC_PLACEHOLDER_DAYS = [d[:3].title() for d in _list("TBC_PLACEHOLDER_DAYS", "Sat,Sun")]

# --- feed shape checks (protection 2) ----------------------------------------
# A season's event count may only fall by this much against the last good
# fetch before the new data is refused and the last good list kept.
MAX_DROP_ABS = int(os.environ.get("MAX_DROP_ABS", "3"))
MAX_DROP_FRAC = float(os.environ.get("MAX_DROP_FRAC", "0.25"))
MAX_UNPARSEABLE_FRAC = float(os.environ.get("MAX_UNPARSEABLE_FRAC", "0.2"))

# --- owned channels (app/broadcast.py, app/rights.py) ----------------------
OWNED_CHANNELS = [c.lower() for c in _list(
    "OWNED_CHANNELS", "sky,tnt,bbc,itv,channel4,channel5,s4c")]
# Wording for the `unavailable` band: "Not in your <OWNED_LABEL> package".
OWNED_LABEL = os.environ.get("OWNED_LABEL", "Sky / TNT / terrestrial")

# --- behaviour -------------------------------------------------------------
TZ = os.environ.get("DISPLAY_TZ", "Europe/London")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "21600"))        # 6 h
RETRY_AFTER_FAIL = int(os.environ.get("RETRY_AFTER_FAIL", "600"))
HOLD_PAST_KICKOFF_MIN = int(os.environ.get("HOLD_PAST_KICKOFF_MIN", "150"))
ON_DECK_COUNT = int(os.environ.get("ON_DECK_COUNT", "3"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/app/cache")

# Absolute base for crest URLs in the payload (LaraPaper's renderer must reach
# it: use the NAS LAN address, not localhost). Crests arrive in Phase 4.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://192.168.68.111:3459").rstrip("/")
