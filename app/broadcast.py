"""Broadcast resolution. PHASE 3 placeholder.

Rugby rights are held per competition, not per match, so Phase 3 adds a static
rights map (re-verified against the rights holders' own announcements) plus
owned-channel filtering. Until then every fixture reports `tbc`.

Four states only. There is no `blackout` in rugby (the 3pm closed period is
football-only): available | unavailable | tbc | none.
"""
from .model import Fixture

STATES = ("available", "unavailable", "tbc", "none")


def resolve(fx: Fixture, comp_key: str) -> dict:  # noqa: ARG001 — Phase 3
    return {"state": "tbc", "primary": None, "others": [], "owned": False,
            "status_label": None, "confidence": "none"}
