"""Dormant mode: what a national side's screen shows between windows.

England play ~11 matches a year in three clusters, so for ~7 months there is
no fixture worth a countdown. With DORMANT_MODE=1 the payload gains
`display_mode` (fixture | dormant) and a `dormant` block; Liquid only branches.
All date maths here, in Europe/London (zoneinfo), never in Liquid.

    fixture   next fixture within IMMINENT_DAYS (or kicked off and held)
    dormant   state = between_windows   next window is further away
                      awaiting_draw     inside a competition we are still in,
                                        with no fixture listed yet (RWC after
                                        the pool, before a quarter-final is set)
                      none_scheduled    nothing listed at all

A "window" is a cluster of our fixtures no more than WINDOW_GAP_DAYS apart:
NC July and NC November are two windows of one competition. The window name is
the next fixture's competition, never hard-coded.
"""
import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import config, rounds
from .model import Fixture, is_ours

LONDON = ZoneInfo(config.TZ)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _local(d: dt.datetime) -> dt.datetime:
    return d.astimezone(LONDON)


def _d(d) -> str:
    return f"{d.day} {d:%b}"


def _ord(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _date_extra(fx: Fixture, key: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(fx.extra.get(key) or "")
    except ValueError:
        return None


def _days_until(fx: Fixture, now: dt.datetime) -> int:
    return (_local(fx.kickoff_utc).date() - _local(now).date()).days


def _real(fixtures: list[Fixture]) -> list[Fixture]:
    return [f for f in fixtures if not f.extra.get("placeholder")]


# --- final round (positional play-offs) --------------------------------------------

def final_round_span(fx: Fixture) -> tuple[dt.date, dt.date] | None:
    if fx.competition_raw not in config.WR_FINAL_ROUND_COMPS:
        return None
    end = _date_extra(fx, "wr_event_end")
    if end is None:
        return None
    return end - dt.timedelta(days=config.WR_FINAL_ROUND_SPAN_DAYS - 1), end


def is_final_round(fx: Fixture) -> bool:
    span = final_round_span(fx)
    return bool(span) and span[0] <= _local(fx.kickoff_utc).date() <= span[1]


# --- competitions -------------------------------------------------------------------

@dataclass
class CompInfo:
    season_id: str             # "Six Nations 2026"
    label: str                 # "2026 Six Nations"
    key: str                   # rounds key: sixnations | nations | rwc | …
    display: str
    event_id: str
    phase: str                 # our last match's phase ("Pool F") for the table name
    completed: int
    accept_records: set        # {(played, won, drawn, lost)}: with and without finals
    ended: bool
    final_round_pending: bool
    event_end: dt.date | None


def _record(results: list[Fixture]) -> tuple[int, int, int, int]:
    r = [_result_block(f, {})["result"] for f in results]
    return len(r), r.count("W"), r.count("D"), r.count("L")


def last_result(fixtures: list[Fixture], now: dt.datetime) -> Fixture | None:
    done = [f for f in _real(fixtures) if f.status == "Result" and f.kickoff_utc <= now
            and f.home.score is not None and f.away.score is not None]
    return max(done, key=lambda f: f.kickoff_utc) if done else None


def comp_info(fixtures: list[Fixture], season_id: str, now: dt.datetime,
              phase: str = "") -> CompInfo | None:
    fxs = [f for f in fixtures if f.season_id == season_id]
    if not fxs:
        return None
    ref = fxs[0]
    key, display, _ = rounds.comp_info(ref.competition_raw)
    m = YEAR_RE.search(season_id)
    label = f"{m.group()} {display}" if m else display
    done = [f for f in _real(fxs) if f.status == "Result"
            and f.home.score is not None and f.away.score is not None]
    non_final = [f for f in done if not is_final_round(f)]
    end = next((d for d in (_date_extra(f, "wr_event_end") for f in fxs) if d), None)
    today = _local(now).date()
    pending = any(is_final_round(f) or f.extra.get("placeholder")
                  for f in fxs if f.status != "Result")
    upcoming_here = [f for f in fxs if f.status != "Result" and f.kickoff_utc > now]
    ended = end < today if end else not upcoming_here
    return CompInfo(season_id=season_id, label=label, key=key, display=display,
                    event_id=ref.extra.get("wr_event_id", ""), phase=phase,
                    completed=len(done),
                    accept_records={_record(done), _record(non_final)},
                    ended=ended, final_round_pending=pending, event_end=end)


def last_result_comp(fixtures: list[Fixture], now: dt.datetime) -> CompInfo | None:
    lr = last_result(fixtures, now)
    if lr is None:
        return None
    return comp_info(fixtures, lr.season_id, now, phase=lr.extra.get("phase", ""))


# --- windows ------------------------------------------------------------------------

def windows(fixtures: list[Fixture]) -> list[list[Fixture]]:
    out: list[list[Fixture]] = []
    for f in sorted(fixtures, key=lambda f: f.kickoff_utc):
        if out and (_local(f.kickoff_utc).date()
                    - _local(out[-1][-1].kickoff_utc).date()).days > config.WINDOW_GAP_DAYS:
            out.append([f])
        elif out:
            out[-1].append(f)
        else:
            out.append([f])
    return out


def window_of(fixtures: list[Fixture], fx: Fixture) -> list[Fixture]:
    for w in windows(fixtures):
        if any(f.id == fx.id for f in w):
            return w
    return [fx]


def _range(a: dt.date, b: dt.date) -> str:
    if a == b:
        return f"{_d(a)} {a.year}"
    if (a.month, a.year) == (b.month, b.year):
        return f"{a.day}–{b.day} {b:%b} {b.year}"
    if a.year == b.year:
        return f"{_d(a)} – {_d(b)} {b.year}"
    return f"{_d(a)} {a.year} – {_d(b)} {b.year}"


def _window_when(w: list[Fixture]) -> str:
    first = _local(w[0].kickoff_utc).date()
    last_fx = w[-1]
    last = (_date_extra(last_fx, "wr_event_end") if last_fx.extra.get("placeholder")
            else None) or _local(last_fx.kickoff_utc).date()
    n = len(w)
    text = f"{_range(first, last)} · {n} match{'es' if n != 1 else ''}"
    ph = next((f for f in w if f.extra.get("placeholder")), None)
    if ph:
        text += f" incl. finals {ph.extra.get('span', '')}".rstrip()
    return text


# --- payload blocks -------------------------------------------------------------------

def _result_block(fx: Fixture, round_of: dict) -> dict:
    hs, as_ = fx.home.score, fx.away.score
    ours, theirs = (hs, as_) if is_ours(fx.home.name) else (as_, hs)
    if ours > theirs:
        res, outcome = "W", f"Won by {ours - theirs}"
    elif ours < theirs:
        res, outcome = "L", f"Lost by {theirs - ours}"
    else:
        res, outcome = "D", "Drawn"
    _, display, _ = rounds.comp_info(fx.competition_raw)
    k = _local(fx.kickoff_utc)
    detail = " · ".join(p for p in (display, round_of.get(fx.id, ""), _d(k)) if p)
    return {"line": f"{fx.home.name} {hs}–{as_} {fx.away.name}", "detail": detail,
            "result": res, "outcome": outcome, "date": _d(k)}


def _standing_block(fixtures: list[Fixture], comp: CompInfo, rec: dict | None,
                    now: dt.datetime) -> dict | None:
    if not rec or rec.get("pos") is None:
        return None
    label = comp.label
    if rec.get("sections", 1) > 1 and rec.get("section"):
        label += f" · {rec['section']}"
    wdl = f"W{rec['won']}" + (f" D{rec['drawn']}" if rec.get("drawn") else "") + f" L{rec['lost']}"
    pd = rec.get("pd")
    pd_txt = "" if pd is None else f" · {pd:+d} points difference"
    block = {"label": label, "line": f"{_ord(rec['pos'])} · {rec['points']} pts",
             "detail": wdl + pd_txt, "historic": bool(rec.get("final")) or comp.ended,
             "source": rec.get("source", "")}

    # Positional play-offs: table position p, final-round win → 2p-1, loss → 2p.
    finals = [f for f in _real(fixtures) if f.season_id == comp.season_id
              and is_final_round(f) and f.status == "Result"
              and f.home.score is not None and f.away.score is not None]
    if finals:
        f = finals[-1]
        p = rec.get("pre_final_pos") or rec["pos"]
        r = _result_block(f, {})["result"]
        placing = {"W": _ord(2 * p - 1), "L": _ord(2 * p), "D": f"{_ord(2 * p - 1)}="}[r]
        opp = f.away.name if is_ours(f.home.name) else f.home.name
        verb = {"W": "beat", "L": "lost to", "D": "drew with"}[r]
        block.update(line=f"Finished {placing}",
                     detail=f"{_ord(p)} in table · {verb} {opp} in finals",
                     placing=placing)
    if block["historic"]:
        block["label"] += " · final"
    return block


def _ranking_block(rank: dict | None) -> dict | None:
    if not rank or not rank.get("pos"):
        return None
    pts = rank.get("points")
    return {"line": f"{_ord(rank['pos'])} in world rankings",
            "detail": f"{pts:.2f} ranking points" if isinstance(pts, (int, float)) else ""}


def resolve(fixtures: list[Fixture], upcoming: list[Fixture], now: dt.datetime,
            round_of: dict, extras: dict | None, held: bool) -> dict:
    """→ {"display_mode", "rail_label", "dormant"} for the payload."""
    extras = extras or {}
    nxt = upcoming[0] if upcoming else None
    out = {"display_mode": "fixture", "rail_label": "Rest of window", "dormant": None}
    if nxt is not None and (held or _days_until(nxt, now) <= config.IMMINENT_DAYS):
        return out

    lr = last_result(fixtures, now)
    comp = last_result_comp(fixtures, now)
    today = _local(now).date()
    awaiting = (comp is not None and comp.event_end is not None and comp.event_end >= today
                and not any(f.season_id == comp.season_id for f in upcoming))

    d: dict = {"spine": config.DORMANT_SPINE or f"{config.TEAM_NAME} Rugby",
               "window_name": None, "window_when": "", "countdown": "",
               "opener": "", "opener_venue": ""}
    if awaiting:
        d.update(state="awaiting_draw", headline="Awaiting the draw",
                 spine_round="Awaiting draw", window_name=comp.display,
                 window_when=f"Next fixture not yet set · final {_d(comp.event_end)} "
                             f"{comp.event_end.year}")
    elif nxt is not None:
        _, display, _ = rounds.comp_info(nxt.competition_raw)
        k = _local(nxt.kickoff_utc)
        days = _days_until(nxt, now)
        opener = (f"{nxt.home.name} v {nxt.away.name} · {k:%a} {_d(k)}"
                  + ("" if nxt.all_day else f", {k:%H:%M}"))
        d.update(state="between_windows", headline="Next window opens",
                 spine_round="Off window", window_name=display,
                 window_when=_window_when(window_of(fixtures, nxt)),
                 countdown=f"In {days} days", opener=opener,
                 opener_venue=nxt.venue or "Venue TBC")
    else:
        d.update(state="none_scheduled", headline="No fixtures scheduled",
                 spine_round="Off window")

    d["last_result"] = _result_block(lr, round_of) if lr else None
    d["standing"] = (_standing_block(fixtures, comp, (extras.get("standings") or {})
                                     .get(comp.season_id), now) if comp else None)
    d["ranking"] = _ranking_block(extras.get("ranking"))
    out.update(display_mode="dormant", dormant=d)
    return out
