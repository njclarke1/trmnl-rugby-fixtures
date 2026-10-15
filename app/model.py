"""Neutral internal fixture shape. Source adapters produce these; normalise.py
consumes them. No source's schema leaks past the adapter."""
import datetime as dt
import zlib
from dataclasses import asdict, dataclass, field

from . import config


@dataclass
class Team:
    name: str
    logo: str | None = None          # source crest URL (enrichment)
    score: int | None = None


@dataclass
class Fixture:
    id: int
    kickoff_utc: dt.datetime
    all_day: bool                    # date known, time not
    home: Team
    away: Team
    competition_raw: str
    venue: str
    season_id: str
    status: str = "Fixture"          # "Fixture" | "Result" | anything unknown
    source: str = "club_ical"
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        d["kickoff_utc"] = self.kickoff_utc.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Fixture":
        d = dict(d)
        d["kickoff_utc"] = dt.datetime.fromisoformat(d["kickoff_utc"])
        d["home"] = Team(**d["home"])
        d["away"] = Team(**d["away"])
        return cls(**d)


def parse_utc(s: str) -> dt.datetime:
    """'2026-10-10T16:30:00Z' / '2026-09-15T19:00Z' → aware UTC datetime."""
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def synthetic_id(*parts: str) -> int:
    """Stable negative id from a natural key.

    crc32, not hash(): hash() is salted per process, so ids would change on
    every restart. Parenthesised deliberately: `-x % n` parses as `(-x) % n`,
    which is NON-negative — the football build shipped exactly that bug.
    """
    key = "|".join(parts).encode()
    return -((zlib.crc32(key) % 10 ** 9) + 1)


def is_ours(name: str) -> bool:
    """Is this side the configured team? Exact or contained, case-insensitive."""
    n, ours = name.casefold().strip(), config.TEAM_NAME.casefold().strip()
    return bool(n) and (n == ours or ours in n)
