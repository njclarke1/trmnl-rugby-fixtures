"""Broadcast resolution: rights map + per-fixture overrides + owned filtering.

Four states. There is no `blackout` in rugby (the 3pm closed period is
football-only):
  available    a channel you have carries it
  unavailable  it's televised, but not on anything you have (every European
               night for Bristol: Premier Sports). A first-class state, not an error.
  tbc          not known: selected-games competition without a pick yet, a
               friendly, an unknown competition, or rights past `valid_until`
  none         confirmed not televised (override with "channels": [])

Absence of a channel never removes or hides a fixture: broadcast is a join.
"""
import json
import logging
import os

from . import config
from .channels import is_owned, short_name
from .model import Fixture
from .rights import RIGHTS

log = logging.getLogger(__name__)

STATES = ("available", "unavailable", "tbc", "none")
OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "broadcast_overrides.json")


def _load_overrides() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        with open(OVERRIDES_FILE) as fh:
            out.update(json.load(fh))
    except (OSError, ValueError) as exc:
        log.warning("broadcast overrides file unreadable: %s", exc)
    try:
        out.update(json.loads(os.environ.get("BROADCAST_OVERRIDES") or "{}"))
    except ValueError as exc:
        log.warning("BROADCAST_OVERRIDES env is not JSON, ignored: %s", exc)
    return {k: v for k, v in out.items() if not k.startswith("_")}


OVERRIDES = _load_overrides()


def _result(state: str, channels: list[str], note: str | None, confidence: str) -> dict:
    owned = [c for c in channels if is_owned(c)]
    ordered = owned + [c for c in channels if c not in owned]
    primary = ordered[0] if ordered else None
    others = ordered[1:]
    if state == "available":
        status, also = "You have this", ("Also: " + " · ".join(others)) if others else (note or "")
    elif state == "unavailable":
        status, also = "Not on your TV", note or f"Not in your {config.OWNED_LABEL} package"
    elif state == "none":
        status, also = "Not televised", note or "Not televised"
    else:
        status, also = "To be confirmed", note or "Channel not yet announced"
    return {
        "state": state,
        "primary": primary,
        "primary_short": short_name(primary) if primary else None,
        "others": others,
        "owned": bool(owned),
        "status_label": status,
        "also": also,
        "note": note,
        "confidence": confidence,
    }


def resolve(fx: Fixture, comp_key: str, overrides: dict | None = None) -> dict:
    ov = (OVERRIDES if overrides is None else overrides).get(str(fx.id))
    if ov is not None:
        chans = list(ov.get("channels") or [])
        if not chans:
            return _result("none", [], ov.get("note"), "override")
        state = "available" if any(is_owned(c) for c in chans) else "unavailable"
        return _result(state, chans, ov.get("note"), "override")

    entry = RIGHTS.get(comp_key)
    if entry is None:
        return _result("tbc", [], None, "none")
    until = entry.get("valid_until")
    if until and fx.kickoff_utc.date() > until:
        return _result("tbc", [], f"Rights after {until:%b %Y} not yet verified", "expired")

    chans = list(entry["channels"])
    coverage = entry.get("coverage", "all")
    if not chans or coverage in ("selected", "unknown"):
        return _result("tbc", [], entry.get("note"), "rights-map")
    owned = any(is_owned(c) for c in chans)
    if coverage == "selected-same-holder":
        # Every televised game is on this holder, but not every game is
        # televised: certain only for someone who doesn't have the holder.
        if owned:
            return _result("tbc", [], entry.get("note"), "rights-map")
        return _result("unavailable", chans, entry.get("note"), "rights-map")
    return _result("available" if owned else "unavailable", chans, entry.get("note"), "rights-map")
