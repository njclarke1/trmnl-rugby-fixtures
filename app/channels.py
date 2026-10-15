"""Channel string → subscription family, owned filtering and rail short names.

Data, not logic: broadcasters rename constantly (BT Sport → TNT Sports in three
years; TNT's streaming moved from discovery+ to HBO Max on 26 Mar 2026). Add a
prefix here, don't touch code.
"""
from . import config

# Longest-prefix-first. Lowercased match against the start of the channel name.
FAMILY_PREFIXES: list[tuple[str, str]] = [
    ("sky sports", "sky"),
    ("sky ", "sky"),
    ("tnt sports", "tnt"),
    ("bt sport", "tnt"),               # legacy name, same subscription
    ("discovery+", "tnt"),             # TNT's streaming home until 26 Mar 2026
    ("hbo max", "hbomax"),             # TNT's streaming home since 26 Mar 2026
    ("bbc", "bbc"),
    ("itv", "itv"),
    ("stv", "itv"),
    ("channel 4", "channel4"),
    ("e4", "channel4"),
    ("channel 5", "channel5"),
    ("5action", "channel5"),
    ("s4c", "s4c"),
    ("premier sports", "premiersports"),
    ("viaplay", "premiersports"),
    ("epcr tv", "epcrtv"),
    ("amazon", "amazon"),
    ("prime video", "amazon"),
    ("dazn", "dazn"),
    ("youtube", "youtube"),
]

SHORT_NAMES: list[tuple[str, str]] = [
    ("tnt sports ultimate", "TNT Ult"),
    ("tnt sports 1", "TNT 1"),
    ("tnt sports 2", "TNT 2"),
    ("tnt sports 3", "TNT 3"),
    ("tnt sports 4", "TNT 4"),
    ("tnt sports", "TNT"),
    ("hbo max", "HBO Max"),
    ("premier sports 1", "Prem Sp 1"),
    ("premier sports 2", "Prem Sp 2"),
    ("premier sports", "Prem Sp"),
    ("sky sports main event", "Sky ME"),
    ("sky sports action", "Sky Act"),
    ("bbc one", "BBC One"),
    ("bbc two", "BBC Two"),
    ("bbc iplayer", "iPlayer"),
    ("itv1", "ITV1"),
    ("itv4", "ITV4"),
    ("itvx", "ITVX"),
    ("channel 4", "Ch4"),
    ("channel 5", "Ch5"),
]


def family_of(channel: str) -> str | None:
    c = channel.strip().lower()
    for prefix, fam in FAMILY_PREFIXES:
        if c.startswith(prefix):
            return fam
    return None


def is_owned(channel: str) -> bool:
    fam = family_of(channel)
    return fam is not None and fam in config.OWNED_CHANNELS


def short_name(channel: str) -> str:
    c = channel.strip().lower()
    for prefix, short in SHORT_NAMES:
        if c.startswith(prefix):
            return short
    return channel if len(channel) <= 12 else channel[:11] + "…"
