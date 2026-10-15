"""England rights map (verified 15 Oct 2026 against ITV press centre and World
Rugby). Every England fixture in the stub resolves; free-to-air wording;
expiry after valid_until; unknown competitions stay `tbc`; owned filtering."""
import dataclasses
import datetime as dt

import pytest

from app import broadcast, config, rounds
from app.sources import world_rugby as wr

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def england(monkeypatch):
    for k, v in {"FIXTURES_SOURCE": "world_rugby", "SOURCE_STUB": True, "WR_TEAM_ID": "34",
                 "TEAM_NAME": "England"}.items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(broadcast, "OVERRIDES", {})


def _fixtures():
    return [f for f in wr.fetch(NOW, {}).fixtures if f.kickoff_utc > NOW]


def _b(f):
    return broadcast.resolve(f, rounds.comp_info(f.competition_raw)[0])


@pytest.mark.parametrize("comp,primary", [
    ("Nations Championship", "ITV1"),
    ("Six Nations", "ITV1"),
    ("Men's Rugby World Cup", "ITV"),
])
def test_every_upcoming_england_fixture_is_free_to_air(comp, primary):
    fxs = [f for f in _fixtures() if f.competition_raw == comp]
    assert fxs
    for f in fxs:
        b = _b(f)
        assert (b["state"], b["primary"], b["owned"], b["status_label"]) == \
            ("available", primary, True, "Free to air")
        assert b["also"] == "Also: ITVX" and b["confidence"] == "rights-map"


def test_finals_placeholder_is_also_on_itv():
    ph = next(f for f in _fixtures() if f.extra.get("placeholder"))
    assert _b(ph)["primary"] == "ITV1"


def test_rights_expire_into_tbc():
    six = next(f for f in _fixtures() if f.competition_raw == "Six Nations")
    later = dataclasses.replace(six, kickoff_utc=dt.datetime(2030, 2, 2, 16, 40, tzinfo=UTC))
    b = _b(later)
    assert b["state"] == "tbc" and b["confidence"] == "expired"
    assert "not yet verified" in b["also"]


def test_unlisted_competition_is_tbc_not_guessed():
    six = next(f for f in _fixtures() if f.competition_raw == "Six Nations")
    tour = dataclasses.replace(six, competition_raw="Summer Nations Series")
    b = _b(tour)
    assert b["state"] == "tbc" and b["primary"] is None


def test_without_itv_it_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "OWNED_CHANNELS", ["sky", "tnt"])
    b = _b(_fixtures()[0])
    assert (b["state"], b["status_label"]) == ("unavailable", "Not on your TV")


def test_override_still_wins_for_england(monkeypatch):
    f = _fixtures()[0]
    monkeypatch.setattr(broadcast, "OVERRIDES", {str(f.id): {"channels": ["ITV4", "ITVX"]}})
    b = _b(f)
    assert (b["primary"], b["confidence"], b["status_label"]) == \
        ("ITV4", "override", "Free to air")
