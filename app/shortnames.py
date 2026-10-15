"""Team display names for constrained widths.

DISPLAY strips sponsor prefixes the club feed carries ("DHL Stormers") so the
main panel shows the club. RAIL is the compact form for the next-up rail.
Extend via env TEAM_DISPLAY / TEAM_RAIL as JSON objects.
"""
import json
import os

DISPLAY = {
    "DHL Stormers": "Stormers",
    "Vodacom Bulls": "Bulls",
    "Hollywoodbets Sharks": "Sharks",
    "Emirates Lions": "Lions",
    "Bordeaux-Begles": "Bordeaux-Bègles",
}
DISPLAY.update(json.loads(os.environ.get("TEAM_DISPLAY") or "{}"))

RAIL = {
    "Newcastle Red Bulls": "Newcastle",
    "Northampton Saints": "Northampton",
    "Leicester Tigers": "Leicester",
    "Gloucester Rugby": "Gloucester",
    "Bath Rugby": "Bath",
    "Exeter Chiefs": "Exeter",
    "Sale Sharks": "Sale",
    "Munster Rugby": "Munster",
    "Leinster Rugby": "Leinster",
    "Ulster Rugby": "Ulster",
    "Connacht Rugby": "Connacht",
    "Bordeaux-Bègles": "Bordeaux",
    "Stade Toulousain": "Toulouse",
    "Glasgow Warriors": "Glasgow",
}
RAIL.update(json.loads(os.environ.get("TEAM_RAIL") or "{}"))

# Main panel (.club, 40px uppercase) steps down to .long above this length.
LONG_NAME_THRESHOLD = 14

INITIALS = {"Racing 92": "RAC"}


def display_name(name: str) -> str:
    return DISPLAY.get(name, name)


def rail_name(name: str) -> str:
    d = display_name(name)
    return RAIL.get(d, RAIL.get(name, d))


def is_long(name: str) -> bool:
    return len(display_name(name)) > LONG_NAME_THRESHOLD


def initials(name: str) -> str:
    """3-letter crest fallback, as in the mock: BRI, SAL, LEI."""
    d = display_name(name)
    if d in INITIALS:
        return INITIALS[d]
    letters = "".join(ch for ch in d.split()[0] if ch.isalpha()) if d.split() else ""
    return (letters[:3] or d[:3]).upper()


def badge(name: str) -> str:
    """Spine badge, word initials: 'Bristol Bears' → 'BB'."""
    words = [w for w in name.split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:3]).upper() or name[:3].upper()
