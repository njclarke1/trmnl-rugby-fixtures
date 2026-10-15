"""World Rugby data API (Pulselive) — national sides. England men's XV = 34.

Phase 1 decision (rugby/phase1-england-source-decision.md in the project): the
governing body's own API is the only source that passed the coverage matrix for
England — Six Nations 2026 and 2027, Nations Championship July and November,
RWC 2027 pool — in ONE keyless call. ESPN has no 2027 Six Nations.

    {base}/match?teams=<id>&startDate=…&endDate=…&sort=asc&pageSize=100&page=N

KNOWN RISKS (also in the README): undocumented, it is the API behind
world.rugby, not a published one. Mitigations here and in main.py:
  1. `teamId=` is silently IGNORED (returns 100 unrelated matches); only
     `teams=` filters. Every match must contain our team, else ShapeError: an
     ignored filter is caught, never rendered.
  2. Per-competition counts are shape-checked like the club feed's seasons; a
     competition only "may vanish" once its last match has aged out of the
     query window.
  3. Last good list persisted; outage → stale, shape change → DATA CHECK.

Data notes, all observed in the 15 Oct 2026 probe:
  * time.millis is UTC. time.label is the VENUE-LOCAL date: never display it.
  * status: C complete, U upcoming. events[].eventStatus is unreliable (the
    finished 2026 Six Nations says "Scheduled"): only the match status is used.
  * outcome: A first-listed team won, B second, N not played.
  * city can carry a dual name ("Brisbane | Meeanjin"): first part kept.
  * no crest URLs; no round number for 6N/NC ("Match 15"); RWC has eventPhase.
  * the Nations Championship finals weekend is not listed until pairings are
    known (after round 6): see _final_round_placeholders.
"""
import datetime as dt
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests

from .. import config, validate
from ..errors import ShapeError, SourceUnavailable
from ..model import Fixture, Team, synthetic_id

log = logging.getLogger(__name__)

SOURCE_LABEL = "world-rugby"
STATUS = {"C": "Result", "U": "Fixture"}
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
MAX_PAGES = 5
LAST_SUFFIX = "|last_day"          # counts key carrying a competition's last match day


@dataclass
class FetchResult:
    fixtures: list[Fixture]
    counts: dict[str, int]
    season_status: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    enrich_ok: bool | None = None


# --- helpers -------------------------------------------------------------------

def comp_name(label: str) -> str:
    """'Six Nations 2026' / '2026 Six Nations' → 'Six Nations'."""
    return re.sub(r"\s{2,}", " ", YEAR_RE.sub("", label or "")).strip()


def city(raw: str | None) -> str:
    return (raw or "").split(" | ", 1)[0].strip()


def _day(d: dt.datetime) -> int:
    return d.date().toordinal()


def window(now: dt.datetime) -> tuple[dt.date, dt.date]:
    d = now.astimezone(dt.timezone.utc).date()
    return d - dt.timedelta(days=config.WR_DAYS_BACK), d + dt.timedelta(days=config.WR_DAYS_FORWARD)


# --- transport -------------------------------------------------------------------

def _get_page(start: dt.date, end: dt.date, page: int) -> dict:
    if config.stub_mode():
        path = os.path.join(config.STUB_DIR, "england", f"wr_match_{config.WR_TEAM_ID}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError as exc:
            raise SourceUnavailable(f"stub missing: {path}") from exc
    params = {"teams": config.WR_TEAM_ID, "startDate": start.isoformat(),
              "endDate": end.isoformat(), "sort": "asc", "pageSize": 100, "page": page}
    try:
        r = requests.get(f"{config.WR_API_BASE}/match", params=params,
                         timeout=config.HTTP_TIMEOUT,
                         headers={"User-Agent": config.USER_AGENT})
    except requests.RequestException as exc:
        raise SourceUnavailable(f"world rugby: {exc}") from exc
    if r.status_code != 200:
        raise SourceUnavailable(f"world rugby: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as exc:
        raise ShapeError("world rugby: response is not JSON") from exc


def _get_all(start: dt.date, end: dt.date) -> list:
    out, page = [], 0
    while True:
        doc = _get_page(start, end, page)
        if not isinstance(doc, dict) or not isinstance(doc.get("content"), list):
            raise ShapeError("world rugby: no `content` list in match response")
        out.extend(doc["content"])
        pages = (doc.get("pageInfo") or {}).get("numPages") or 1
        page += 1
        if page >= pages or page >= MAX_PAGES or config.stub_mode():
            return out


# --- parsing -----------------------------------------------------------------------

def _venue(name: str, town: str) -> str:
    """'Allianz Stadium' + 'London' → 'Allianz Stadium, London' (mock style)."""
    if not town or town.casefold() in name.casefold():
        return name
    return f"{name}, {town}" if name else town


def _team(t: dict, score, played: bool) -> Team:
    return Team(name=(t.get("name") or "").strip(),
                score=int(score) if played and isinstance(score, (int, float)) else None)


def to_fixture(m: dict) -> Fixture:
    """One WR match → Fixture. Raises (KeyError, TypeError, ValueError) if unusable."""
    teams = m["teams"]
    if len(teams) != 2 or not all(t.get("name") for t in teams):
        raise ValueError("match without two named teams")
    kick = dt.datetime.fromtimestamp(m["time"]["millis"] / 1000, dt.timezone.utc)
    status = STATUS.get(m.get("status") or "", m.get("status") or "Fixture")
    played = status == "Result"
    scores = m.get("scores") or [None, None]
    venue = m.get("venue") or {}
    vname, vcity = (venue.get("name") or "").strip(), city(venue.get("city"))
    event = (m.get("events") or [{}])[0] or {}
    label = (m.get("competition") or event.get("label") or "").strip()
    end = (event.get("end") or {}).get("label") or ""
    return Fixture(
        id=synthetic_id("wr", m["matchId"]),
        kickoff_utc=kick,
        all_day=False,
        home=_team(teams[0], scores[0] if len(scores) > 0 else None, played),
        away=_team(teams[1], scores[1] if len(scores) > 1 else None, played),
        competition_raw=comp_name(label),
        venue=_venue(vname, vcity),
        season_id=label,
        status=status,
        source="world_rugby",
        extra={
            "wr_match_id": m["matchId"],
            "wr_event_id": event.get("id") or "",
            "wr_event_end": end,
            "competition_label": label,
            "phase": (m.get("eventPhase") or "").strip(),
            "venue_country": (venue.get("country") or "").strip(),
            "home_abbr": (teams[0].get("abbreviation") or "").strip(),
            "away_abbr": (teams[1].get("abbreviation") or "").strip(),
            "outcome": m.get("outcome") or "",
        },
    )


def _final_round_placeholders(fixtures: list[Fixture], now: dt.datetime) -> list[Fixture]:
    """Approved option (b). In a competition where every team plays the final
    round (Nations Championship finals weekend: positional play-offs), the last
    fixture is certain but unlisted until pairings are known. If the
    competition's end date is after our last listed match in it and no listed
    match falls in the final-round span, add an all-day 'Opponent TBC' fixture
    held for the whole span. The real fixture supersedes it once listed."""
    tz = ZoneInfo(config.TZ)
    by_event: dict[str, list[Fixture]] = defaultdict(list)
    for f in fixtures:
        if f.competition_raw in config.WR_FINAL_ROUND_COMPS and f.extra.get("wr_event_end"):
            by_event[f.extra["wr_event_id"] or f.season_id].append(f)
    out = []
    for key, fxs in by_event.items():
        try:
            end = dt.date.fromisoformat(fxs[0].extra["wr_event_end"])
        except ValueError:
            continue
        start = end - dt.timedelta(days=config.WR_FINAL_ROUND_SPAN_DAYS - 1)
        last = max(f.kickoff_utc.astimezone(tz).date() for f in fxs)
        if last >= start or end < now.astimezone(tz).date():
            continue                                  # listed already, or over
        begin = dt.datetime.combine(start, dt.time(0, 0), tzinfo=tz)
        hold = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0, 0), tzinfo=tz)
        ref = fxs[0]
        out.append(Fixture(
            id=synthetic_id("wr-final-round", key),
            kickoff_utc=begin.astimezone(dt.timezone.utc),
            all_day=True,
            home=Team(config.TEAM_NAME), away=Team("Opponent TBC"),
            competition_raw=ref.competition_raw,
            venue="",
            season_id=ref.season_id,
            source="world_rugby_placeholder",
            extra={"placeholder": True, "phase": "Finals weekend",
                   "competition_label": ref.extra.get("competition_label", ""),
                   "wr_event_id": ref.extra.get("wr_event_id", ""),
                   "span": f"{start.day}–{end.day} {end:%b}" if start.month == end.month
                           else f"{start.day} {start:%b}–{end.day} {end:%b}",
                   "hold_until": hold.astimezone(dt.timezone.utc).isoformat()},
        ))
    return out


# --- entry point -----------------------------------------------------------------

def fetch(now: dt.datetime, last_counts: dict[str, int]) -> FetchResult:
    if not config.WR_TEAM_ID:
        raise ShapeError("WR_TEAM_ID is not set (pin the team id in the stack env)")
    start, end = window(now)
    matches = _get_all(start, end)
    res = FetchResult(fixtures=[], counts={}, season_status={})

    bad = 0
    for m in matches:
        ids = {str(t.get("id")) for t in (m.get("teams") or []) if isinstance(t, dict)}
        if config.WR_TEAM_ID not in ids:
            # The filter param was ignored or changed: the whole response is suspect.
            raise ShapeError(f"world rugby: match without team {config.WR_TEAM_ID} "
                             "(team filter ignored?)")
        try:
            fx = to_fixture(m)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            bad += 1
            res.warnings.append(f"unparseable match {m.get('matchId')}: {exc}")
            continue
        if not start <= fx.kickoff_utc.date() <= end:
            continue                                   # stub mode, or a lax server
        res.fixtures.append(fx)

    total = len(res.fixtures) + bad
    if total and bad / total > config.MAX_UNPARSEABLE_FRAC:
        raise ShapeError(f"world rugby: {bad}/{total} matches unparseable")
    if not res.fixtures and not any(v for k, v in last_counts.items() if LAST_SUFFIX not in k):
        raise ShapeError(f"world rugby: no matches for team {config.WR_TEAM_ID} "
                         f"between {start} and {end}")

    by_comp: dict[str, list[Fixture]] = defaultdict(list)
    for f in res.fixtures:
        by_comp[f.season_id].append(f)
    for comp, fxs in by_comp.items():
        res.counts[comp] = len(fxs)
        res.counts[comp + LAST_SUFFIX] = max(_day(f.kickoff_utc) for f in fxs)
        res.season_status[comp] = "ok"

    # Shape-check every competition we knew about, unless it has legitimately
    # aged out of the window (its last match is now before the window start).
    for comp, n in last_counts.items():
        if LAST_SUFFIX in comp:
            continue
        last_day = last_counts.get(comp + LAST_SUFFIX, 0)
        if comp not in res.counts and last_day and last_day < start.toordinal():
            res.season_status[comp] = "aged-out"
            continue
        validate.check_season(comp, parsed=res.counts.get(comp, 0), unparseable=0,
                              last_count=n)

    res.fixtures.extend(_final_round_placeholders(res.fixtures, now))

    unknown = sorted({f.competition_raw for f in res.fixtures
                      if f.competition_raw not in config.COMP_LABELS})
    for comp in unknown:
        res.warnings.append(f"unknown competition label {comp!r}: shown as-is")
    for w in res.warnings:
        log.warning(w)
    return res
