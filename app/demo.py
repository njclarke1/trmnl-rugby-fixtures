"""Canned payloads for every screen state, built from the real stub responses
bundled in the image. They are used to force states on the panel during Phase 5:
point the LaraPaper plugin's polling URL at /demo/<state>.json, render,
then point it back at /fixtures. They are also used by plugin/demo/render_demo.py.

Read-only and independent of the live cache, so safe to leave enabled.
"""
import datetime as dt
import json
import os

from . import config, normalise
from .sources import club_wp

U = dt.timezone.utc
SOURCES = {"fixtures": "demo", "enrich": "club-json", "broadcast": "rights-map"}

# state → (now, extra kwargs). Dates chosen against the 2025/26 + 2026/27 stubs.
STATES: dict[str, tuple[dt.datetime, dict]] = {
    "available":   (dt.datetime(2026, 10, 18, 12, 0, tzinfo=U), {}),   # v Exeter, PREM, TNT
    "unavailable": (dt.datetime(2026, 10, 15, 17, 0, tzinfo=U), {}),   # @ Stormers, Premier Sports
    "tbc":         (dt.datetime(2026, 11, 1, 12, 0, tzinfo=U), {}),    # @ Sale, PREM Cup
    "none":        (dt.datetime(2026, 11, 1, 12, 0, tzinfo=U),
                    {"overrides": {"294862": {"channels": []}}}),
    "itv":         (dt.datetime(2026, 10, 25, 12, 0, tzinfo=U),         # v Leicester, ITV pick
                    {"overrides": {"294928": {"channels": ["ITV1", "ITVX", "TNT Sports 1"]}}}),
    "provisional": (dt.datetime(2027, 1, 31, 12, 0, tzinfo=U), {}),    # rail: 20 Mar 15:00 TBC
    "long_name":   (dt.datetime(2026, 12, 21, 12, 0, tzinfo=U), {}),   # v Newcastle Red Bulls
    "kicked_off":  (dt.datetime(2026, 10, 17, 15, 30, tzinfo=U), {}),
    "friendly":    (dt.datetime(2025, 11, 1, 12, 0, tzinfo=U), {}),    # v Argentina XV
    "data_check":  (dt.datetime(2026, 10, 15, 17, 0, tzinfo=U),
                    {"stale": True, "data_check": "season 202601: 9 fixtures, was 30 (drop > 7)"}),
    "empty":       (dt.datetime(2027, 6, 10, 12, 0, tzinfo=U), {}),
}


def _load_fixtures() -> list:
    out = []
    for season in ("202501", "202601"):
        base = os.path.join(config.STUB_DIR, f"ical_{season}_{config.CLUB_FEED_CATEGORY}.ics")
        with open(base, encoding="utf-8") as fh:
            fxs, _, _ = club_wp.fixtures_from_ical(fh.read(), season)
        jpath = os.path.join(config.STUB_DIR, f"fixtures_{season}_{config.CLUB_FEED_CATEGORY}.json")
        if os.path.exists(jpath):
            with open(jpath, encoding="utf-8") as fh:
                club_wp.enrich(fxs, json.load(fh), season)
        out.extend(fxs)
    return out


def build(state: str) -> dict | None:
    if state not in STATES:
        return None
    now, kw = STATES[state]
    payload = normalise.build_payload(_load_fixtures(), now, sources=SOURCES, **kw)
    payload["demo_state"] = state
    return payload
