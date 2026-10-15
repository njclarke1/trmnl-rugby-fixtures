"""UK broadcast rights per competition: DATA, re-verified every summer.

Rugby rights are sold per competition, not per match, so a static map is close
to deterministic: no scraper. Each entry carries the rights holder's own
announcement and a `valid_until`; a fixture after that date resolves to `tbc`
("rights not yet verified") rather than silently trusting last season's deal.
Re-verify, then move the date: that is the whole of the annual maintenance.

Verified 15 Oct 2026 against:
  PREM      TNT Sports, 22 Sep 2026 — all 93 Gallagher PREM matches and 13 PREM
            Rugby Cup games; HBO Max is TNT's streaming home (first season on it).
            Some games are HBO Max-only (e.g. Harlequins v Bath, R1).
            tntsports.co.uk/rugby/tnt-rugby-season-prem-pwr_sto23339419
  ITV       ITV press centre, 22 Jan 2026 — 7 live PREM matches per season incl.
            the Final, 2026/27 and 2027/28, all simulcast on TNT Sports. Chosen
            per match → per-fixture overrides (broadcast_overrides.json).
            itv.com/presscentre/node/54251
  EPCR      Premier Sports deal (Aug 2024) to the end of 2026/27 — all 63
            Champions Cup matches; Challenge Cup: two pool games per round, two
            Round-of-16 ties, all QF/SF/Final. S4C carve-out (Welsh sides only).
            ITV had free-to-air rights to the 2026 finals weekend only.
            sportforbusiness.com/premier-sports-signs-three-year-deal-for-investec-champions-cup
            sportcal.com/media/itv-to-air-2026-champions-cup-challenge-cup-finals-weekend

NOT verified (Aug research, no rights-holder source found): "Challenge Cup —
selected games on the BBC". Not encoded.
"""
import datetime as dt

SEASON_END = dt.date(2027, 6, 30)

RIGHTS: dict[str, dict] = {
    "prem": {
        "channels": ["TNT Sports", "HBO Max"],
        "coverage": "all",
        "valid_until": SEASON_END,
    },
    "premcup": {
        # 13 of the cup's ~44 games are televised; which ones is announced
        # piecemeal. Unknown until an override names the game.
        "channels": ["TNT Sports", "HBO Max"],
        "coverage": "selected",
        "note": "TNT Sports shows selected PREM Cup games",
        "valid_until": SEASON_END,
    },
    "champions": {
        "channels": ["Premier Sports"],
        "coverage": "all",
        "valid_until": SEASON_END,
    },
    "challenge": {
        # Selected games only, but every televised one is on Premier Sports,
        # so for an owner without it the answer is the same: not on your TV.
        "channels": ["Premier Sports"],
        "coverage": "selected-same-holder",
        "note": "Premier Sports shows selected games",
        "valid_until": SEASON_END,
    },
    "friendly": {
        "channels": [],
        "coverage": "unknown",
        "note": "Friendly: check the club's own stream",
    },
}
