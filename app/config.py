"""Central configuration. Everything team- or stack-specific is env-driven.

One codebase serves several stacks (Bristol on :3459, England later on :3460):
the stack's env picks the fixtures source adapter, the team and its labels.
"""
import json
import os


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


_OFF = ("none", "off", "-")


def _list(name: str, default: str) -> list[str]:
    """Comma list. "none"/"off"/"-" mean an explicitly empty list: a sentinel,
    because an empty env value is easy to lose between Portainer and compose."""
    raw = os.environ.get(name, default)
    if raw.strip().lower() in _OFF:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


# --- team ------------------------------------------------------------------
TEAM_NAME = os.environ.get("TEAM_NAME", "Bristol Bears")
# Spine badge text (mock: "BB"). Blank = word initials of TEAM_NAME.
TEAM_BADGE = os.environ.get("TEAM_BADGE", "")

# --- fixtures source ------------------------------------------------------
# "club_wp"      — club WordPress feed (Bristol Bears), iCal core + JSON enrichment
# "world_rugby"  — World Rugby data API (national sides; England)
# "stub"         — legacy alias: club_wp reading tests/fixtures/
# SOURCE_STUB=1 makes any adapter read its saved responses from STUB_DIR instead
# of the network (offline dev, tests, demo). See app/sources/__init__.py.
FIXTURES_SOURCE = os.environ.get("FIXTURES_SOURCE", "club_wp")
SOURCE_STUB = _bool("SOURCE_STUB", "0")
STUB_DIR = os.environ.get("STUB_DIR", "/app/tests/fixtures")


def stub_mode() -> bool:
    return FIXTURES_SOURCE == "stub" or SOURCE_STUB


# --- World Rugby adapter (app/sources/world_rugby.py) -------------------------
WR_API_BASE = os.environ.get(
    "WR_API_BASE", "https://api.wr-rims-prod.pulselive.com/rugby/v3").rstrip("/")
# Pinned team id, never searched at runtime (England men's XV = 34; England
# Women / A / U20 have other ids). Required when FIXTURES_SOURCE=world_rugby.
WR_TEAM_ID = os.environ.get("WR_TEAM_ID", "").strip()
# Query window around now. Back far enough to keep the last completed Six
# Nations and the last result in view; forward past the next World Cup.
WR_DAYS_BACK = int(os.environ.get("WR_DAYS_BACK", "400"))
WR_DAYS_FORWARD = int(os.environ.get("WR_DAYS_FORWARD", "550"))
# Competitions in which every team plays the final round (positional
# play-offs), so an unlisted last fixture is certain, only its opponent unknown.
# A placeholder "Opponent TBC" is derived from the competition's end date.
WR_FINAL_ROUND_COMPS = _list("WR_FINAL_ROUND_COMPS", "Nations Championship")
WR_FINAL_ROUND_SPAN_DAYS = int(os.environ.get("WR_FINAL_ROUND_SPAN_DAYS", "3"))

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
    # National-side competitions (world_rugby adapter strips the year first).
    "Six Nations": ("sixnations", "Six Nations", "Six Nations"),
    "Nations Championship": ("nations", "Nations Championship", "Nations Ch'ship"),
    "Men's Rugby World Cup": ("rwc", "Rugby World Cup", "World Cup"),
    "Rugby World Cup": ("rwc", "Rugby World Cup", "World Cup"),
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
# it: use the NAS LAN address, not localhost).
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://192.168.68.111:3459").rstrip("/")

# --- crests (app/crests.py) ---------------------------------------------------
ENABLE_CRESTS = _bool("ENABLE_CRESTS", "1")
# Inside of the mock's 96×74 oval less its 3px border.
CREST_W = int(os.environ.get("CREST_W", "90"))
CREST_H = int(os.environ.get("CREST_H", "68"))
# Team names (as in the feed or as displayed) rendered with Floyd–Steinberg
# dither instead of a hard threshold — for crests with gradients or fine detail.
CREST_DITHER = _list("CREST_DITHER", "")
# Fixed threshold 1–254; 0 = Otsu per crest.
CREST_THRESHOLD = int(os.environ.get("CREST_THRESHOLD", "0"))
