"""Fixtures source dispatcher, keyed on FIXTURES_SOURCE.

Every adapter exposes the same contract:
    fetch(now, last_counts) -> FetchResult(fixtures, counts, season_status,
                                           warnings, enrich_ok)
    SOURCE_LABEL: str              shown as payload["sources"]["fixtures"]
and raises errors.SourceUnavailable (outage → stale) or errors.ShapeError
(feed changed → DATA CHECK). Nothing source-specific leaks past model.Fixture.
"""
from .. import config
from . import club_wp, world_rugby

ADAPTERS = {
    "club_wp": club_wp,
    "stub": club_wp,              # legacy alias: club_wp + stub mode
    "world_rugby": world_rugby,
}


def adapter():
    try:
        return ADAPTERS[config.FIXTURES_SOURCE]
    except KeyError:
        raise RuntimeError(f"unknown FIXTURES_SOURCE {config.FIXTURES_SOURCE!r}; "
                           f"expected one of {sorted(ADAPTERS)}") from None
