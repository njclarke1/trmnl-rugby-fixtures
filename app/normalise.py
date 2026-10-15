"""Build the flat, pre-formatted /fixtures payload.

All date maths lives here, in Python with zoneinfo. Liquid does presentation
only: no arithmetic, no date parsing (LaraPaper's `"now" | date` is unreliable).
"""
import datetime as dt
from zoneinfo import ZoneInfo

from . import broadcast, config, crests, dormant, rounds
from .model import Fixture, Team, is_ours
from .shortnames import badge, display_name, initials, is_long, rail_name

LONDON = ZoneInfo(config.TZ)


def _d(d: dt.datetime) -> str:
    return f"{d.day} {d:%b}"                       # "16 Oct" (no platform %-d)


def _end_of_hold(fx: Fixture) -> dt.datetime:
    if fx.extra.get("hold_until"):
        # Adapter-set span, e.g. a finals-weekend placeholder held Fri–Sun.
        return dt.datetime.fromisoformat(fx.extra["hold_until"])
    if fx.all_day:
        # Time unknown: hold for the whole local day rather than guess.
        local = fx.kickoff_utc.astimezone(LONDON)
        nxt = dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time(0, 0),
                                  tzinfo=LONDON)
        return nxt.astimezone(dt.timezone.utc)
    return fx.kickoff_utc + dt.timedelta(minutes=config.HOLD_PAST_KICKOFF_MIN)


def is_provisional(fx: Fixture, now: dt.datetime) -> bool:
    """15:00 weekend placeholder further out than the horizon. Self-clearing."""
    if fx.all_day or fx.status == "Result":
        return False
    k = fx.kickoff_utc.astimezone(LONDON)
    days = (k.date() - now.astimezone(LONDON).date()).days
    return (days > config.TBC_HORIZON_DAYS
            and k.strftime("%a") in config.TBC_PLACEHOLDER_DAYS
            and k.strftime("%H:%M") in config.TBC_PLACEHOLDER_TIMES)


def _countdown(fx: Fixture, now: dt.datetime) -> str:
    if not fx.all_day and now >= fx.kickoff_utc:
        return "Kicked off"
    days = (fx.kickoff_utc.astimezone(LONDON).date() - now.astimezone(LONDON).date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"In {days} days"


def _venue(fx: Fixture) -> str:
    return fx.venue or "Venue TBC"


def _team(t: Team, ours: bool, abbr: str = "") -> dict:
    return {
        "name": t.name,
        "display": display_name(t.name),
        "short": rail_name(t.name),
        "long": is_long(t.name),
        # Source abbreviation (World Rugby: "NZL") beats derived initials.
        "initials": abbr or initials(t.name),
        "ours": ours,
        # Set only once the processed 1-bit oval exists; else the template shows
        # initials. `crest_inv` is the white-on-black variant (mock `.crest.inv`).
        "crest": crests.url_for(t.logo, t.name),
        "crest_inv": crests.url_for(t.logo, t.name, inverted=True),
    }


def _is_home(fx: Fixture) -> bool:
    return is_ours(fx.home.name)


def _venue_tag(fx: Fixture, home: bool) -> str:
    """Home/Away from team order; Neutral when the source gives a venue country
    that isn't the listed home side's (Fiji v England at Liverpool; every RWC
    game in Australia). Only national-side adapters set `venue_country`."""
    country = (fx.extra.get("venue_country") or "").casefold()
    if country and country != fx.home.name.casefold():
        return "Neutral"
    return "Home" if home else "Away"


def build_payload(fixtures: list[Fixture], now: dt.datetime | None = None, *,
                  stale: bool = False, data_check: str | None = None,
                  sources: dict | None = None, overrides: dict | None = None,
                  extras: dict | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    now_local = now.astimezone(LONDON)
    round_of = rounds.label_rounds(fixtures)

    upcoming = sorted((f for f in fixtures if _end_of_hold(f) > now),
                      key=lambda f: f.kickoff_utc)

    payload = {
        "generated_display": f"{_d(now_local)}, {now_local:%H:%M}",
        "sources": sources or {},
        "stale": stale,
        "data_check": data_check is not None,
        "data_check_reason": data_check,
        "team": config.TEAM_NAME,
        "team_badge": config.TEAM_BADGE or badge(config.TEAM_NAME),
        "next": None,
        "on_deck": [],
    }
    if config.DORMANT_MODE:
        held = bool(upcoming) and not upcoming[0].all_day and now >= upcoming[0].kickoff_utc
        payload.update(dormant.resolve(fixtures, upcoming, now, round_of, extras, held))
        if upcoming and payload["display_mode"] == "fixture":
            win = {f.id for f in dormant.window_of(fixtures, upcoming[0])}
            upcoming = [upcoming[0]] + [f for f in upcoming[1:] if f.id in win]
        else:
            upcoming = upcoming[:1]                      # dormant: no rail

    if not upcoming:
        return payload

    fx = upcoming[0]
    key, comp, comp_short = rounds.comp_info(fx.competition_raw)
    k = fx.kickoff_utc.astimezone(LONDON)
    home = _is_home(fx)
    provisional = is_provisional(fx, now)
    payload["next"] = {
        "id": fx.id,
        "competition": comp,
        "competition_short": comp_short,
        "competition_key": key,
        "is_friendly": key == "friendly",
        "round": round_of.get(fx.id, ""),
        "is_home": home,
        "venue_tag": _venue_tag(fx, home),
        "home": _team(fx.home, home, fx.extra.get("home_abbr", "")),
        "away": _team(fx.away, not home, fx.extra.get("away_abbr", "")),
        "day": k.strftime("%A"),
        "date": _d(k),
        "time": "TBC" if fx.all_day else k.strftime("%H:%M"),
        "tbc": fx.all_day or provisional,
        "provisional": provisional,
        "venue": _venue(fx),
        "countdown": _countdown(fx, now),
        "kicked_off": not fx.all_day and now >= fx.kickoff_utc,
        "source": fx.source,
        "broadcast": broadcast.resolve(fx, key, overrides),
    }
    if fx.extra.get("placeholder"):
        # Derived final round (e.g. NC finals weekend): day and opponent unknown.
        payload["next"].update(placeholder=True, opponent_tbc=True, day="Finals weekend",
                               venue_tag="TBC",
                               date=fx.extra.get("span") or payload["next"]["date"])

    for fx in upcoming[1:1 + config.ON_DECK_COUNT]:
        key, comp, comp_short = rounds.comp_info(fx.competition_raw)
        k = fx.kickoff_utc.astimezone(LONDON)
        home = _is_home(fx)
        provisional = is_provisional(fx, now)
        b = broadcast.resolve(fx, key, overrides)
        if b["state"] in ("available", "unavailable"):
            chan = b["primary_short"]
        elif b["state"] == "none":
            chan = "No TV"
        else:
            chan = "TBC"
        time = "TBC" if fx.all_day else k.strftime("%H:%M") + (" TBC" if provisional else "")
        when = (fx.extra["span"] if fx.extra.get("placeholder") and fx.extra.get("span")
                else f"{k:%a} {_d(k)} · {time}")
        payload["on_deck"].append({
            "id": fx.id,
            "when": when,
            "tbc": fx.all_day or provisional,
            "opponent": rail_name((fx.away if home else fx.home).name),
            "ha": "H" if home else "A",
            "competition": comp,
            "competition_short": comp_short,
            "competition_key": key,
            "round": round_of.get(fx.id, ""),
            "channel_short": chan,
            "owned": b["owned"],
        })
    return payload
