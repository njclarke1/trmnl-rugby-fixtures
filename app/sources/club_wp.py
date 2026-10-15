"""Bristol Bears club feed (WordPress plugin namespace `afz/v1`).

Phase 1 decision (rugby/phase1-source-decision.md in the project): the club's
own feed is the only source that passed the coverage matrix — PREM, PREM
Rugby Cup and Champions Cup (incl. a knockout tie), past and upcoming — free
and keyless. A PREM play-off fixture has not yet been observed in it (Bristol
didn't reach the 2025/26 play-offs); see README. ESPN's rugby team-schedule endpoint is broken and it has no PREM Cup.

    {base}/fixtures/ical/{seasonId}/{category}   RFC 5545, Europe/London  ← CORE
    {base}/fixtures?seasonId=X&category=men      JSON, UTC                ← enrichment

KNOWN RISK (also in the README): this is an undocumented website plugin, not a
published API. Mitigations live here and in validate.py:
  1. The iCal feed is the core contract. It's the same route that serves the
     fans' "ADD ALL" calendar button (seasonId=upcoming), in a standard format,
     so the club can't reshape it without breaking subscribers' calendars.
  2. The JSON only adds crests, scores and status, plus any fixture missing from
     the calendar (additive). If it breaks, crests fall back to initials and every
     fixture still shows.
  3. Every fetch is shape-checked; a failure keeps the last good list and raises
     the panel's DATA CHECK flag (main.py).

The JSON endpoint silently ignores `season=` and `per_page=`; only `seasonId`
and `category` filter. The unfiltered call returns ~500 fixtures back to 2017.
"""
import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests

from .. import config, ical, validate
from ..errors import ShapeError, SourceUnavailable
from ..model import Fixture, Team, is_ours, parse_utc, synthetic_id

log = logging.getLogger(__name__)

SUMMARY_RE = re.compile(r"^(?P<home>.+?)\s+(?:vs?\.?)\s+(?P<away>.+?)(?:\s+-\s+(?P<comp>[^-].*))?$",
                        re.IGNORECASE)
PLACEHOLDER_VENUES = {"", "tbd", "tbc", "tba", "to be confirmed"}


@dataclass
class FetchResult:
    fixtures: list[Fixture]
    counts: dict[str, int]                      # parsed events per season
    season_status: dict[str, str]               # ok | missing
    warnings: list[str] = field(default_factory=list)
    enrich_ok: bool | None = None               # None = disabled


# --- season ids ------------------------------------------------------------

def season_ids(now: dt.datetime) -> list[str]:
    if config.SEASON_IDS:
        return list(config.SEASON_IDS)
    local = now.astimezone(ZoneInfo(config.TZ))
    start = local.year if local.month >= config.SEASON_CUTOVER_MONTH else local.year - 1
    return [f"{start}01", f"{start + 1}01"]


# --- transport ---------------------------------------------------------------

class _NotFound(Exception):
    pass


def _get(kind: str, season: str) -> str:
    cat = config.CLUB_FEED_CATEGORY
    if config.FIXTURES_SOURCE == "stub":
        name = f"ical_{season}_{cat}.ics" if kind == "ical" else f"fixtures_{season}_{cat}.json"
        path = os.path.join(config.STUB_DIR, name)
        if not os.path.exists(path):
            raise _NotFound(path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    if kind == "ical":
        url, params = f"{config.CLUB_FEED_BASE}/fixtures/ical/{season}/{cat}", None
    else:
        url, params = f"{config.CLUB_FEED_BASE}/fixtures", {"seasonId": season, "category": cat}
    try:
        r = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT,
                         headers={"User-Agent": config.USER_AGENT})
    except requests.RequestException as exc:
        raise SourceUnavailable(f"{kind} {season}: {exc}") from exc
    if r.status_code in (400, 404, 410):
        raise _NotFound(f"{kind} {season}: HTTP {r.status_code}")
    if r.status_code != 200:
        raise SourceUnavailable(f"{kind} {season}: HTTP {r.status_code}")
    return r.text


# --- parsing -----------------------------------------------------------------

def parse_summary(summary: str) -> tuple[str, str, str] | None:
    """'DHL Stormers vs Bristol Bears - European Cup' → (home, away, comp)."""
    m = SUMMARY_RE.match(summary.strip())
    if not m:
        return None
    return m["home"].strip(), m["away"].strip(), (m["comp"] or "").strip()


def _fixture_id(uid: str, start: dt.datetime, summary: str) -> int:
    head = uid.split("@", 1)[0]
    if head.isdigit():
        return int(head)
    return synthetic_id(start.isoformat(), summary)


def _venue(raw: str) -> str:
    return "" if raw.strip().casefold() in PLACEHOLDER_VENUES else raw.strip()


def fixtures_from_ical(text: str, season: str) -> tuple[list[Fixture], int, list[str]]:
    """Returns (fixtures, unparseable, warnings). Raises ical.ICalError."""
    events, bad = ical.parse_events(text)
    out, warnings = [], []
    for ev in events:
        parts = parse_summary(ev["summary"])
        if parts is None:
            bad += 1
            warnings.append(f"unparseable SUMMARY: {ev['summary']!r}")
            continue
        home, away, comp = parts
        if not (is_ours(home) or is_ours(away)):
            warnings.append(f"event without {config.TEAM_NAME}: {ev['summary']!r}")
            continue
        out.append(Fixture(
            id=_fixture_id(ev["uid"], ev["start_utc"], ev["summary"]),
            kickoff_utc=ev["start_utc"],
            all_day=ev["all_day"],
            home=Team(home), away=Team(away),
            competition_raw=comp,
            venue=_venue(ev["location"]),
            season_id=season,
        ))
    return out, bad, warnings


# --- enrichment ----------------------------------------------------------------

def _score(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def enrich(fixtures: list[Fixture], items: list, season: str) -> list[str]:
    """Add crest URLs, scores and status from the JSON feed; add any of our
    fixtures the calendar lacks (gap-filler, never overrides). Mutates
    `fixtures` in place. Raises ValueError if the JSON isn't the expected shape."""
    if not isinstance(items, list):
        raise ValueError("fixtures JSON is not a list")
    warnings: list[str] = []
    by_id = {f.id: f for f in fixtures}
    by_day = {(f.kickoff_utc.date(), f.home.name.casefold(), f.away.name.casefold()): f
              for f in fixtures}
    for it in items:
        if not isinstance(it, dict) or "gameId" not in it or "date" not in it:
            raise ValueError("fixtures JSON item missing gameId/date")
        if (it.get("category") or "") != config.CLUB_FEED_CATEGORY:
            continue
        h, a = it.get("homeTeam") or {}, it.get("awayTeam") or {}
        hn, an = (h.get("name") or "").strip(), (a.get("name") or "").strip()
        if not (is_ours(hn) or is_ours(an)):
            continue
        kick = parse_utc(it["date"])
        gid = int(it["gameId"]) if str(it["gameId"]).isdigit() else None
        fx = by_id.get(gid) or by_day.get((kick.date(), hn.casefold(), an.casefold()))

        if fx is None:
            # In the JSON, not in the calendar. Absence from the core feed is
            # not proof of no fixture: add it, flagged by source.
            fx = Fixture(id=gid or synthetic_id(it["date"], hn, an), kickoff_utc=kick,
                         all_day=False, home=Team(hn), away=Team(an),
                         competition_raw=(it.get("competition") or "").strip(),
                         venue=_venue(it.get("venue") or ""), season_id=season,
                         source="club_json")
            fixtures.append(fx)
            warnings.append(f"fixture only in JSON, added: {hn} v {an} {it['date']}")
        elif abs((fx.kickoff_utc - kick).total_seconds()) > 60 and not fx.all_day:
            warnings.append(f"kickoff differs ical {fx.kickoff_utc:%Y-%m-%d %H:%M}Z vs "
                            f"json {kick:%Y-%m-%d %H:%M}Z ({hn} v {an}); calendar kept")

        fx.status = (it.get("status") or fx.status).strip()
        fx.home.logo = h.get("logo") or fx.home.logo
        fx.away.logo = a.get("logo") or fx.away.logo
        fx.home.score, fx.away.score = _score(h.get("score")), _score(a.get("score"))
        fx.extra["json_round"] = (it.get("round") or "").strip()
    return warnings


# --- entry point ---------------------------------------------------------------

def fetch(now: dt.datetime, last_counts: dict[str, int]) -> FetchResult:
    """Fetch every configured season. Raises SourceUnavailable or ShapeError;
    otherwise returns validated fixtures (with warnings for anything odd)."""
    res = FetchResult(fixtures=[], counts={}, season_status={})
    outage: SourceUnavailable | None = None
    for sid in season_ids(now):
        required = last_counts.get(sid, 0) > 0
        try:
            text = _get("ical", sid)
        except _NotFound as exc:
            if required:
                raise ShapeError(f"season {sid} calendar has disappeared ({exc})") from exc
            res.season_status[sid] = "missing"       # not published yet: normal
            continue
        except SourceUnavailable as exc:
            if required:
                raise
            # An unpublished season may answer with an error rather than a 404;
            # never let it make the whole refresh stale.
            outage = exc
            res.season_status[sid] = "unavailable"
            continue
        try:
            fxs, bad, warns = fixtures_from_ical(text, sid)
        except ical.ICalError as exc:
            if required:
                raise ShapeError(f"season {sid}: {exc}") from exc
            res.season_status[sid] = "missing"
            continue
        validate.check_season(sid, parsed=len(fxs), unparseable=bad,
                              last_count=last_counts.get(sid, 0))
        res.fixtures.extend(fxs)
        res.counts[sid] = len(fxs)
        res.season_status[sid] = "ok"
        res.warnings.extend(warns)

    if not res.counts and outage is not None:
        raise outage
    if not res.counts and not any(last_counts.values()):
        raise ShapeError("no season calendar found for " + ",".join(season_ids(now)))

    unknown = sorted({f.competition_raw for f in res.fixtures
                      if f.competition_raw not in config.COMP_LABELS})
    for comp in unknown:
        res.warnings.append(f"unknown competition label {comp!r}: shown as-is")

    if config.ENABLE_ENRICH:
        res.enrich_ok = True
        for sid, status in res.season_status.items():
            if status != "ok":
                continue
            try:
                res.warnings.extend(enrich(res.fixtures, json.loads(_get("json", sid)), sid))
            except (SourceUnavailable, _NotFound, ValueError, KeyError) as exc:
                res.enrich_ok = False
                res.warnings.append(f"enrichment failed for {sid} (crests/scores only): {exc}")
    for w in res.warnings:
        log.warning(w)
    return res
