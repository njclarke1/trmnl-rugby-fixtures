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

England (national side; world_rugby adapter), verified 15 Oct 2026 against:
  Six Nations  ITV press centre, 14 Mar 2025 — BBC/ITV four-year deal 2026–2029:
               ITV ten live games a season "including every England fixture",
               on ITV1, ITVX, STV and STV Player. BBC: Scotland/Wales home games.
               itv.com/presscentre/node/44016
  Nations Ch.  ITV press centre, 26 Jan 2026 — ITV and STV exclusive free-to-air
               home of the 2026 and 2028 editions (every fixture); also the 2027
               Summer Nations Series and 2029 July/Autumn Nations Series, to 2029.
               itv.com/presscentre/node/54366
  RWC 2027     World Rugby, Jul 2026 — ITV exclusive UK broadcaster, all 52
               matches live, on ITV and ITVX (ITV1 vs ITV4 per match not stated).
               world.rugby/news/1045829
STV is ITV's Scottish licensee (same family in channels.py); it is left out of
the displayed channel lists because the panel is in England.

NOT encoded: the 2027 Summer Nations Series and 2029 July/Autumn series. Their
World Rugby competition names are unknown until listed, so they resolve to
`tbc`; add an entry (or overrides) once the label is seen. ITV per the release.
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
    # --- England (free-to-air: the panel says "Free to air", not "You have this")
    "sixnations": {
        "channels": ["ITV1", "ITVX"],
        "coverage": "all",                    # every England fixture (see above)
        "free_to_air": True,
        "valid_until": dt.date(2029, 3, 31),
    },
    "nations": {
        "channels": ["ITV1", "ITVX"],
        "coverage": "all",
        "free_to_air": True,
        # 2026 and 2028 editions. There is no 2027 edition (Summer Nations Series).
        "valid_until": dt.date(2028, 11, 30),
    },
    "rwc": {
        "channels": ["ITV", "ITVX"],
        "coverage": "all",
        "free_to_air": True,
        "note": "ITV1 or ITV4: confirmed nearer the match",
        "valid_until": dt.date(2027, 11, 13),
    },
    "friendly": {
        "channels": [],
        "coverage": "unknown",
        "note": "Friendly: check the club's own stream",
    },
}
