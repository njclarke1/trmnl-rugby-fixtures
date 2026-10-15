"""Dormant-mode extras: championship standings and world ranking.

Fetched on their own, longer TTL (EXTRAS_TTL, 24 h) and persisted to the cache
volume, so an outage or a restart never loses them. Every failure here is
swallowed: extras are garnish, the fixture list is the product.

Standings (approved Phase 1 decision):
  1. World Rugby  {WR}/event/{eventId}/standings   — empty for the Six Nations
  2. ESPN         {ESPN}/{slug}/standings           — CURRENT table only
                                                      (?season= is ignored)
Either source is accepted only if our row's played/won/drawn/lost matches our own
completed results in that competition (with or without a finals-weekend game).
That is what stops ESPN's table for the *next* Six Nations being shown as last
year's, and it is why a finished
competition's table is frozen ("final") once seen: it can't be re-fetched
after the source moves on.
"""
import json
import logging
import os
import re
import threading
import time

import requests

from . import config, dormant
from .errors import SourceUnavailable
from .model import Fixture

log = logging.getLogger("extras")

EXTRAS_FILE = lambda: os.path.join(config.CACHE_DIR, "extras.json")  # noqa: E731
_lock = threading.Lock()


def blank() -> dict:
    return {"standings": {}, "ranking": None, "checked": {}, "last_error": None}


# --- transport --------------------------------------------------------------------

def _get_json(url: str, stub_name: str):
    if config.stub_mode():
        path = os.path.join(config.STUB_DIR, "england", stub_name)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError as exc:
            raise SourceUnavailable(f"stub missing: {stub_name}") from exc
    try:
        r = requests.get(url, timeout=config.HTTP_TIMEOUT,
                         headers={"User-Agent": config.USER_AGENT})
    except requests.RequestException as exc:
        raise SourceUnavailable(str(exc)) from exc
    if r.status_code != 200:
        raise SourceUnavailable(f"HTTP {r.status_code} {url}")
    try:
        return r.json()
    except ValueError as exc:
        raise SourceUnavailable(f"not JSON: {url}") from exc


def _int(v) -> int | None:
    try:
        return int(float(str(v).replace("+", "")))
    except (TypeError, ValueError):
        return None


def _pos(label) -> int | None:
    m = re.search(r"\d+", str(label or ""))
    return int(m.group()) if m else None


# --- parsers: our row → neutral dict -------------------------------------------------

def parse_wr(doc: dict, phase: str = "") -> dict | None:
    tables = doc.get("tables") if isinstance(doc, dict) else None
    if not tables:
        return None
    for ti, t in enumerate(tables):
        for e in t.get("entries") or []:
            team = e.get("team") or {}
            if str(team.get("id")) == config.WR_TEAM_ID or team.get("name") == config.TEAM_NAME:
                pf, pa = _int(e.get("pointsFor")), _int(e.get("pointsAgainst"))
                return {
                    "pos": _pos(e.get("positionLabel")), "played": _int(e.get("played")),
                    "won": _int(e.get("won")), "drawn": _int(e.get("drawn")),
                    "lost": _int(e.get("lost")), "points": _int(e.get("points")),
                    "pd": None if pf is None or pa is None else pf - pa,
                    "table_size": len(t.get("entries") or []),
                    "section": (t.get("title") or phase or "").strip(),
                    "sections": len(tables),
                }
    return None


def parse_espn(doc: dict) -> dict | None:
    children = doc.get("children") if isinstance(doc, dict) else None
    for ch in children or []:
        entries = (ch.get("standings") or {}).get("entries") or []
        for e in entries:
            if (e.get("team") or {}).get("displayName") != config.TEAM_NAME:
                continue
            s = {x.get("name"): x.get("value", x.get("displayValue"))
                 for x in e.get("stats") or []}
            return {
                "pos": _int(s.get("rank")), "played": _int(s.get("gamesPlayed")),
                "won": _int(s.get("gamesWon")), "drawn": _int(s.get("gamesDrawn")),
                "lost": _int(s.get("gamesLost")), "points": _int(s.get("points")),
                "pd": _int(s.get("pointsDifference")),
                "table_size": len(entries),
                "section": (ch.get("name") or "") if len(children) > 1 else "",
                "sections": len([c for c in children
                                 if (c.get("standings") or {}).get("entries")]),
            }
    return None


# --- refresh ------------------------------------------------------------------------

def _due(cache: dict, key: str) -> bool:
    return time.time() - cache["checked"].get(key, 0) >= config.EXTRAS_TTL


def _standing_for(comp: dormant.CompInfo) -> tuple[dict | None, str, list[str]]:
    """Try WR then ESPN; return (row, source, reasons-for-rejections)."""
    notes = []
    candidates = []
    if comp.event_id:
        candidates.append(("world-rugby", lambda: parse_wr(_get_json(
            f"{config.WR_API_BASE}/event/{comp.event_id}/standings",
            f"wr_standings_{comp.event_id}.json"), comp.phase)))
    slug = config.ESPN_STANDINGS_SLUGS.get(comp.key)
    if slug:
        candidates.append(("espn", lambda: parse_espn(_get_json(
            f"{config.ESPN_SITE_BASE}/{slug}/standings", f"espn_standings_{slug}.json"))))
    for source, get in candidates:
        try:
            row = get()
        except SourceUnavailable as exc:
            notes.append(f"{source}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — a parser bug must not touch fixtures
            notes.append(f"{source}: unexpected {exc!r}")
            continue
        if row is None:
            notes.append(f"{source}: no table / not in table")
            continue
        # Must match OUR results in this competition, not just the count: a
        # stale or next-season table with the same number of games fails here.
        rec = (row["played"], row["won"], row["drawn"] or 0, row["lost"])
        if rec not in comp.accept_records:
            notes.append(f"{source}: P/W/D/L {rec} does not match our results "
                         f"{sorted(comp.accept_records)} (other season?)")
            continue
        return row, source, notes
    return None, "", notes


def refresh(cache: dict, fixtures: list[Fixture], now) -> dict:
    """Refresh what is due. Mutates and returns `cache`; never raises."""
    with _lock:
        before = json.dumps(cache, sort_keys=True, default=str)
        try:
            comp = dormant.last_result_comp(fixtures, now)
            if comp and not cache["standings"].get(comp.season_id, {}).get("final") \
                    and _due(cache, "standings:" + comp.season_id):
                cache["checked"]["standings:" + comp.season_id] = time.time()
                row, source, notes = _standing_for(comp)
                prev = cache["standings"].get(comp.season_id) or {}
                if row:
                    rec = {**row, "source": source, "label": comp.label,
                           "fetched_at": time.time(),
                           "final": comp.ended and row["played"] == comp.completed,
                           "pre_final_pos": prev.get("pre_final_pos")}
                    if comp.final_round_pending:
                        rec["pre_final_pos"] = row["pos"]
                    cache["standings"][comp.season_id] = rec
                    cache["last_error"] = None
                else:
                    # Retry sooner than the full TTL, as for fixtures.
                    cache["checked"]["standings:" + comp.season_id] = (
                        time.time() - config.EXTRAS_TTL + config.RETRY_AFTER_FAIL)
                    cache["last_error"] = "standings: " + "; ".join(notes)
                    log.warning("standings for %s unavailable, keeping cache: %s",
                                comp.season_id, notes)
            if config.ENABLE_RANKING and _due(cache, "ranking"):
                cache["checked"]["ranking"] = time.time()
                try:
                    doc = _get_json(f"{config.WR_API_BASE}/rankings/mru", "wr_rankings_mru.json")
                    for e in doc.get("entries") or []:
                        if str((e.get("team") or {}).get("id")) == config.WR_TEAM_ID:
                            cache["ranking"] = {"pos": _int(e.get("pos")),
                                                "points": e.get("pts"),
                                                "fetched_at": time.time()}
                            break
                except SourceUnavailable as exc:
                    cache["checked"]["ranking"] = (
                        time.time() - config.EXTRAS_TTL + config.RETRY_AFTER_FAIL)
                    log.warning("ranking unavailable, keeping cache: %s", exc)
        except Exception as exc:  # noqa: BLE001 — extras never break the payload
            log.exception("extras refresh failed")
            cache["last_error"] = f"unexpected: {exc!r}"
        if json.dumps(cache, sort_keys=True, default=str) != before:
            _save(cache)                  # only when something was attempted or changed
        return cache


# --- persistence ----------------------------------------------------------------------

def load() -> dict:
    try:
        with open(EXTRAS_FILE()) as fh:
            d = json.load(fh)
        out = blank()
        out.update({k: d[k] for k in out if k in d})
        return out
    except FileNotFoundError:
        return blank()
    except (OSError, ValueError) as exc:
        log.warning("extras file unreadable, starting empty: %s", exc)
        return blank()


def _save(cache: dict) -> None:
    try:
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        tmp = EXTRAS_FILE() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, EXTRAS_FILE())
    except OSError as exc:
        log.warning("could not persist extras: %s", exc)
