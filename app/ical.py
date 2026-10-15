"""Minimal RFC 5545 reader: enough for a fixtures calendar, nothing more.

Handles line unfolding, CRLF/LF, TEXT unescaping, and DTSTART in its three
forms (TZID local, UTC "Z", and all-day VALUE=DATE). Times are returned as
aware UTC datetimes; all maths downstream uses zoneinfo.

Kept in-house rather than pulling in a library so that every behaviour the
display depends on is pinned by tests against the club's real feed.
"""
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ICalError(ValueError):
    """The document is not a parseable VCALENDAR."""


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [ln for ln in lines if ln]


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _split(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID=Europe/London:20261017T151500' → (name, params, value)."""
    head, sep, value = line.partition(":")
    if not sep:
        return line.upper(), {}, ""
    name, *params = head.split(";")
    pdict = {}
    for p in params:
        k, _, v = p.partition("=")
        pdict[k.upper()] = v.strip('"')
    return name.upper(), pdict, value


def parse_dtstart(params: dict[str, str], value: str) -> tuple[dt.datetime, bool]:
    """Return (start in UTC, all_day)."""
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        d = dt.datetime.strptime(value[:8], "%Y%m%d").date()
        # All-day: anchor at local noon so the calendar date survives conversion.
        tz = ZoneInfo(params.get("TZID", "Europe/London"))
        return dt.datetime.combine(d, dt.time(12, 0), tzinfo=tz).astimezone(dt.timezone.utc), True
    if value.endswith("Z"):
        naive = dt.datetime.strptime(value[:-1], "%Y%m%dT%H%M%S")
        return naive.replace(tzinfo=dt.timezone.utc), False
    naive = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if not tzid:
        raise ValueError(f"floating DTSTART without TZID: {value}")
    try:
        tz = ZoneInfo(tzid)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown TZID {tzid}") from exc
    return naive.replace(tzinfo=tz).astimezone(dt.timezone.utc), False


def parse_events(text: str) -> tuple[list[dict], int]:
    """Parse VEVENTs. Returns (events, unparseable_count).

    Each event: {uid, start_utc, all_day, summary, location, url}.
    Raises ICalError if the document is not a VCALENDAR at all.
    """
    lines = _unfold(text)
    if not lines or lines[0].strip().upper() != "BEGIN:VCALENDAR":
        raise ICalError("not a VCALENDAR document")

    events: list[dict] = []
    bad = 0
    cur: dict | None = None
    depth = 0          # nested components inside a VEVENT (VALARM) are skipped
    for line in lines:
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur, depth = {"_params": {}}, 0
            continue
        if cur is None:
            continue
        if name == "BEGIN":
            depth += 1
            continue
        if name == "END" and value.upper() != "VEVENT":
            depth -= 1
            continue
        if name == "END":
            try:
                start, all_day = parse_dtstart(cur["_params"].get("DTSTART", {}),
                                               cur["DTSTART"])
                events.append({
                    "uid": cur.get("UID", ""),
                    "start_utc": start,
                    "all_day": all_day,
                    "summary": _unescape(cur.get("SUMMARY", "")).strip(),
                    "location": _unescape(cur.get("LOCATION", "")).strip(),
                    "url": cur.get("URL", ""),
                })
            except (KeyError, ValueError):
                bad += 1
            cur = None
            continue
        if depth == 0 and name not in cur:
            cur[name] = value
            cur["_params"][name] = params
    return events, bad
