"""Broadcast states against the 2026/27 rights map (verified 15 Oct 2026).
All four states are reproducible; a Champions Cup fixture renders `unavailable`."""
import datetime as dt

import pytest

from app import broadcast, config, normalise, rounds
from app.sources import club_wp

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)


def _fx(fid):
    return next(f for f in club_wp.fetch(NOW, {}).fixtures if f.id == fid)


def _resolve(fid):
    f = _fx(fid)
    return broadcast.resolve(f, rounds.comp_info(f.competition_raw)[0])


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    monkeypatch.setattr(broadcast, "OVERRIDES", {})


def test_prem_available_on_tnt():
    b = _resolve(294926)                                   # Bristol v Exeter, PREM
    assert (b["state"], b["primary"], b["owned"]) == ("available", "TNT Sports", True)
    assert b["others"] == ["HBO Max"] and b["also"] == "Also: HBO Max"
    assert b["status_label"] == "You have this" and b["confidence"] == "rights-map"


def test_champions_cup_unavailable_premier_sports():
    b = _resolve(293322)                                   # Stormers v Bristol
    assert (b["state"], b["primary"], b["owned"]) == ("unavailable", "Premier Sports", False)
    assert b["status_label"] == "Not on your TV"
    assert b["also"] == "Not in your Sky / TNT / terrestrial package"
    assert b["primary_short"] == "Prem Sp"


def test_prem_cup_selected_games_tbc():
    b = _resolve(294862)                                   # Sale v Bristol, PREM Cup
    assert (b["state"], b["primary"]) == ("tbc", None)
    assert b["also"] == "TNT Sports shows selected PREM Cup games"


def test_override_none_means_not_televised(monkeypatch):
    monkeypatch.setattr(broadcast, "OVERRIDES", {"294862": {"channels": []}})
    b = _resolve(294862)
    assert (b["state"], b["status_label"], b["confidence"]) == ("none", "Not televised", "override")


def test_override_itv_free_to_air_pick(monkeypatch):
    monkeypatch.setattr(broadcast, "OVERRIDES", {
        "294928": {"channels": ["ITV1", "ITVX", "TNT Sports 1"], "note": "ITV pick"}})
    b = _resolve(294928)                                   # Bristol v Leicester
    assert (b["state"], b["primary"], b["primary_short"]) == ("available", "ITV1", "ITV1")
    assert b["others"] == ["ITVX", "TNT Sports 1"] and b["also"] == "Also: ITVX · TNT Sports 1"


def test_override_televises_prem_cup_game(monkeypatch):
    monkeypatch.setattr(broadcast, "OVERRIDES", {"294862": {"channels": ["TNT Sports 2", "HBO Max"]}})
    b = _resolve(294862)
    assert (b["state"], b["primary_short"]) == ("available", "TNT 2")


def test_rights_expire_to_tbc_not_stale_assumption(monkeypatch):
    monkeypatch.setitem(broadcast.RIGHTS["prem"], "valid_until", dt.date(2026, 12, 31))
    later = next(f for f in club_wp.fetch(NOW, {}).fixtures
                 if f.competition_raw == "Gallagher Premiership"
                 and f.kickoff_utc.date() > dt.date(2027, 1, 1))
    b = broadcast.resolve(later, "prem")
    assert (b["state"], b["confidence"]) == ("tbc", "expired")
    assert b["also"] == "Rights after Dec 2026 not yet verified"


def test_without_tnt_prem_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "OWNED_CHANNELS", ["sky", "bbc", "itv"])
    b = _resolve(294926)
    assert (b["state"], b["primary"]) == ("unavailable", "TNT Sports")


def test_challenge_cup_tier(monkeypatch):
    b = broadcast.resolve(_fx(293322), "challenge")
    assert (b["state"], b["primary"], b["note"]) == (
        "unavailable", "Premier Sports", "Premier Sports shows selected games")
    monkeypatch.setattr(config, "OWNED_CHANNELS", config.OWNED_CHANNELS + ["premiersports"])
    assert broadcast.resolve(_fx(293322), "challenge")["state"] == "tbc"


def test_unknown_competition_tbc():
    assert broadcast.resolve(_fx(293322), "other")["state"] == "tbc"


def test_rail_channels_and_chips():
    p = normalise.build_payload(club_wp.fetch(NOW, {}).fixtures, NOW)
    assert p["next"]["broadcast"]["state"] == "unavailable"           # Champions Cup night
    rail = [(d["opponent"], d["channel_short"], d["owned"]) for d in p["on_deck"]]
    assert rail == [("Exeter", "TNT", True), ("Leicester", "TNT", True), ("Sale", "TBC", False)]


def test_shipped_overrides_file_is_valid():
    data = broadcast._load_overrides()
    for key, ov in data.items():
        assert key.lstrip("-").isdigit()
        assert isinstance(ov.get("channels"), list)
