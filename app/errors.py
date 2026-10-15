"""Failure classes shared by source adapters, the shape checks and main.py."""


class SourceUnavailable(RuntimeError):
    """Network or upstream outage: keep last good, set `stale`."""


class ShapeError(RuntimeError):
    """The feed answered but no longer looks like the feed: keep last good and
    set `data_check`, so the change is visible on the panel."""
