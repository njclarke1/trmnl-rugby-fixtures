"""Feed shape checks (protection 2).

A season's fixture list only ever grows or holds steady across a season: a
single postponement or cancellation removes one event, not a quarter of them.
A sudden drop, a pile of unparseable events, or an empty calendar that used to
be full means the feed has changed, not the fixtures. The caller keeps its last
good list and raises DATA CHECK on the panel instead of quietly showing less.
"""
from . import config
from .errors import ShapeError


def check_season(season: str, parsed: int, unparseable: int, last_count: int) -> None:
    total = parsed + unparseable
    if total and unparseable / total > config.MAX_UNPARSEABLE_FRAC:
        raise ShapeError(f"season {season}: {unparseable}/{total} events unparseable")
    if parsed == 0 and last_count > 0:
        raise ShapeError(f"season {season}: calendar now empty (was {last_count})")
    allowed = max(config.MAX_DROP_ABS, int(last_count * config.MAX_DROP_FRAC))
    if last_count - parsed > allowed:
        raise ShapeError(f"season {season}: {parsed} fixtures, was {last_count} "
                         f"(drop > {allowed})")
