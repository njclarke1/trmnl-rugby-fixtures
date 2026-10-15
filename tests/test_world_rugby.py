"""World Rugby adapter (England) against the real 15 Oct 2026 probe responses
in tests/fixtures/england/. Covers the Phase 1 coverage matrix, parsing quirks,
shape checks (ignored team filter, ageing out of the window), the derived
finals-weekend placeholder, the dispatcher and the RWC overnight boundary.
"""
import copy
import datetime as dt
import json
import os

import pytest

from app import config, main, normalise, sources
from app.errors import ShapeError, SourceUnavailable
from app.sources import world_rugby as wr

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)
ENG = os.path.join(os.environ["STUB_DIR"], "england")


def _stub(name):
    with open(os.path.join(ENG, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(autouse=True)
def england(monkeypatch):
    monkeypatch.setattr(config, "FIXTURES_SOURCE", "world_rugby")
    monkeypatch.setattr(config, "SOURCE_STUB", True)
    monkeypatch.setattr(config, "WR_TEAM_ID", "34")
    monkeypatch.setattr(config, "TEAM_NAME", "England")
    monkeypatch.setattr(config, "TBC_PLACEHOLDER_TIMES", [])


def _fetch(now=NOW, counts=None):
    return wr.fetch(now, counts or {})


def _real(fixtures):
    return [f for f in fixtures if not f.extra.get("placeholder")]


def _one(fixtures, iso_date, opponent):
    hits = [f for f in _real(fixtures)
            if f.kickoff_utc.astimezone(normalise.LONDON).date().isoformat() == iso_date
            and opponent in (f.home.name, f.away.name)]
    assert len(hits) == 1, (iso_date, opponent, hits)
    return hits[0]


def _with_matches(monkeypatch, edit):
    doc = copy.deepcopy(_stub("wr_match_34.json"))
    edit(doc)                                          # edits in place
    monkeypatch.setattr(wr, "_get_page", lambda s, e, p: doc)


# --- Phase 1 coverage matrix, pinned ------------------------------------------------

@pytest.mark.parametrize("date,opponent,comp,kick_utc", [
    ("2026-03-14", "France", "Six Nations", "2026-03-14T20:10"),         # Super Saturday
    ("2026-07-04", "South Africa", "Nations Championship", "2026-07-04T15:40"),
    ("2026-07-11", "Fiji", "Nations Championship", "2026-07-11T13:10"),
    ("2026-07-18", "Argentina", "Nations Championship", "2026-07-18T19:10"),
    ("2026-11-08", "Australia", "Nations Championship", "2026-11-08T15:10"),
    ("2026-11-21", "New Zealand", "Nations Championship", "2026-11-21T14:10"),
    ("2027-02-05", "Ireland", "Six Nations", "2027-02-05T20:10"),       # not in ESPN
    ("2027-03-13", "Scotland", "Six Nations", "2027-03-13T16:40"),
    ("2027-10-02", "Tonga", "Men's Rugby World Cup", "2027-10-02T10:15"),
    ("2027-10-16", "Wales", "Men's Rugby World Cup", "2027-10-16T08:45"),
])
def test_coverage_matrix(date, opponent, comp, kick_utc):
    f = _one(_fetch().fixtures, date, opponent)
    assert f.competition_raw == comp
    assert f.kickoff_utc.strftime("%Y-%m-%dT%H:%M") == kick_utc


def test_counts_and_status():
    res = _fetch()
    assert len(_real(res.fixtures)) == 19
    assert res.counts["Six Nations 2026"] == 5 and res.counts["Six Nations 2027"] == 5
    assert res.counts["Nations Championship 2026"] == 6
    assert res.counts["Men's Rugby World Cup 2027"] == 3
    assert set(res.season_status.values()) == {"ok"}


def test_results_carry_scores_and_upcoming_do_not():
    fx = _fetch().fixtures
    sat = _one(fx, "2026-03-14", "France")
    assert (sat.status, sat.home.name, sat.home.score, sat.away.score) == \
        ("Result", "France", 48, 46)
    assert sat.extra["outcome"] == "A"
    aus = _one(fx, "2026-11-08", "Australia")
    assert aus.status == "Fixture" and aus.home.score is None and aus.away.score is None


def test_venue_city_country_and_abbreviations():
    fx = _fetch().fixtures
    tonga = _one(fx, "2027-10-02", "Tonga")
    assert tonga.venue == "Brisbane Stadium"   # city already in name; "| Meeanjin" dropped
    assert tonga.extra["venue_country"] == "Australia" and tonga.extra["phase"] == "Pool F"
    fiji = _one(fx, "2026-07-11", "Fiji")
    assert fiji.home.name == "Fiji" and fiji.extra["venue_country"] == "England"
    assert (fiji.extra["home_abbr"], fiji.extra["away_abbr"]) == ("FIJ", "ENG")
    assert _one(fx, "2026-11-08", "Australia").venue == "Allianz Stadium, London"
    assert _one(fx, "2027-10-16", "Wales").venue == "Stadium Australia, Sydney"


@pytest.mark.parametrize("label,expected", [
    ("Six Nations 2026", "Six Nations"),
    ("2027 Six Nations", "Six Nations"),
    ("Men's Rugby World Cup 2027", "Men's Rugby World Cup"),
    ("Nations Championship 2026", "Nations Championship"),
])
def test_comp_name_strips_year(label, expected):
    assert wr.comp_name(label) == expected


def test_competition_labels_resolve():
    from app import rounds
    keys = {rounds.comp_info(f.competition_raw)[0] for f in _fetch().fixtures}
    assert keys == {"sixnations", "nations", "rwc"}


def test_ids_negative_and_stable():
    a, b = _fetch().fixtures, _fetch().fixtures
    assert [f.id for f in a] == [f.id for f in b]
    assert all(f.id < 0 for f in a) and len({f.id for f in a}) == len(a)


# --- shape checks -------------------------------------------------------------------

def test_ignored_team_filter_is_a_shape_error(monkeypatch):
    doc = _stub("wr_match_filter_ignored.json")        # real response to teamId=34
    monkeypatch.setattr(wr, "_get_page", lambda s, e, p: doc)
    with pytest.raises(ShapeError, match="team filter"):
        _fetch()


def test_missing_content_is_a_shape_error(monkeypatch):
    monkeypatch.setattr(wr, "_get_page", lambda s, e, p: {"error": "moved"})
    with pytest.raises(ShapeError):
        _fetch()


def test_team_id_unset_is_a_shape_error(monkeypatch):
    monkeypatch.setattr(config, "WR_TEAM_ID", "")
    with pytest.raises(ShapeError, match="WR_TEAM_ID"):
        _fetch()


def test_outage_propagates_as_source_unavailable(monkeypatch):
    def down(s, e, p):
        raise SourceUnavailable("timeout")
    monkeypatch.setattr(wr, "_get_page", down)
    with pytest.raises(SourceUnavailable):
        _fetch()


def test_competition_vanishing_inside_window_is_refused(monkeypatch):
    good = _fetch().counts
    _with_matches(monkeypatch, lambda d: d.update(content=[
        m for m in d["content"] if "Nations Championship" not in m["competition"]]))
    with pytest.raises(ShapeError, match="Nations Championship 2026"):
        _fetch(counts=good)


def test_competition_ageing_out_of_window_is_accepted():
    good = _fetch().counts
    later = dt.datetime(2027, 5, 1, 12, 0, tzinfo=UTC)   # window starts 2026-03-27
    res = _fetch(later, good)
    assert res.season_status["Six Nations 2026"] == "aged-out"
    assert "Six Nations 2026" not in res.counts


def test_mostly_unparseable_is_refused(monkeypatch):
    def edit(d):
        for m in d["content"][:10]:
            del m["time"]
    _with_matches(monkeypatch, edit)
    with pytest.raises(ShapeError, match="unparseable"):
        _fetch()


# --- finals-weekend placeholder (approved option b) ------------------------------------

def test_finals_weekend_placeholder_derived_from_event_end():
    ph = [f for f in _fetch().fixtures if f.extra.get("placeholder")]
    assert len(ph) == 1
    p = ph[0]
    assert p.all_day and p.away.name == "Opponent TBC" and p.home.name == "England"
    assert p.competition_raw == "Nations Championship"
    assert p.kickoff_utc.astimezone(normalise.LONDON).date() == dt.date(2026, 11, 27)
    assert p.extra["span"] == "27–29 Nov"
    assert p.id < 0 and p.id == [f for f in _fetch().fixtures if f.extra.get("placeholder")][0].id


def test_no_placeholder_once_final_round_is_listed(monkeypatch):
    def edit(d):
        final = copy.deepcopy(next(m for m in d["content"]
                                   if m["time"]["label"] == "2026-11-21"))
        final["matchId"] = "finals-weekend-test"
        final["teams"][1].update(id="36", name="Ireland", abbreviation="IRE")
        final["time"]["millis"] = int(dt.datetime(2026, 11, 28, 17, 40, tzinfo=UTC)
                                      .timestamp() * 1000)
        d["content"].append(final)
    _with_matches(monkeypatch, edit)
    fx = _fetch().fixtures
    assert not [f for f in fx if f.extra.get("placeholder")]
    assert _one(fx, "2026-11-28", "Ireland").competition_raw == "Nations Championship"


def test_no_placeholder_after_competition_ends():
    after = dt.datetime(2026, 11, 30, 9, 0, tzinfo=UTC)
    assert not [f for f in _fetch(after).fixtures if f.extra.get("placeholder")]


@pytest.mark.parametrize("now,expect", [
    (dt.datetime(2026, 11, 21, 16, 30, tzinfo=UTC), "New Zealand"),   # held 150 min
    (dt.datetime(2026, 11, 22, 12, 0, tzinfo=UTC), "Opponent TBC"),
    (dt.datetime(2026, 11, 29, 20, 0, tzinfo=UTC), "Opponent TBC"),   # held all weekend
    (dt.datetime(2026, 11, 30, 0, 30, tzinfo=UTC), "Ireland"),        # → Six Nations 2027
])
def test_placeholder_is_next_through_finals_weekend(now, expect):
    p = normalise.build_payload(_fetch(now).fixtures, now)["next"]
    assert expect in (p["home"]["name"], p["away"]["name"])


# --- time zones -----------------------------------------------------------------------

def test_rwc_countdown_from_london_kickoff_not_venue_date(monkeypatch):
    """Venue-local date (Sydney) is a day ahead of the UK date: the UK date wins."""
    def edit(d):
        m = next(m for m in d["content"] if m["time"]["label"] == "2027-10-16")
        m["time"].update(millis=int(dt.datetime(2027, 10, 15, 22, 0, tzinfo=UTC)
                                    .timestamp() * 1000), label="2027-10-16")
    _with_matches(monkeypatch, edit)
    now = dt.datetime(2027, 10, 14, 22, 0, tzinfo=UTC)          # Thu 23:00 BST
    p = normalise.build_payload(_fetch(now).fixtures, now)["next"]
    assert p["away"]["name"] == "Wales"
    assert (p["day"], p["date"], p["time"], p["countdown"]) == \
        ("Friday", "15 Oct", "23:00", "Tomorrow")


@pytest.mark.parametrize("now,countdown", [
    (dt.datetime(2027, 10, 1, 22, 30, tzinfo=UTC), "Tomorrow"),      # Fri 23:30 BST
    (dt.datetime(2027, 10, 1, 23, 30, tzinfo=UTC), "Today"),         # Sat 00:30 BST
])
def test_rwc_morning_kickoff_today_tomorrow_boundary(now, countdown):
    p = normalise.build_payload(_fetch(now).fixtures, now)["next"]
    assert p["away"]["name"] == "Tonga" and p["time"] == "11:15"
    assert p["countdown"] == countdown


def test_november_window_is_gmt():
    p = normalise.build_payload(_fetch().fixtures, NOW)["next"]
    assert (p["away"]["name"], p["date"], p["time"]) == ("Australia", "8 Nov", "15:10")


# --- dispatcher and end-to-end ---------------------------------------------------------

def test_dispatcher(monkeypatch):
    assert sources.adapter() is wr
    for name, mod in (("club_wp", sources.club_wp), ("stub", sources.club_wp)):
        monkeypatch.setattr(config, "FIXTURES_SOURCE", name)
        assert sources.adapter() is mod
    monkeypatch.setattr(config, "FIXTURES_SOURCE", "api_rugby")
    with pytest.raises(RuntimeError, match="unknown FIXTURES_SOURCE"):
        sources.adapter()


def test_end_to_end_through_flask(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LAST_GOOD_FILE", str(tmp_path / "last_good.json"))
    monkeypatch.setattr(main, "_state", main._blank_state())
    c = main.app.test_client()
    out = c.get("/fixtures?now=2026-10-15T17:00:00Z").get_json()
    assert out["team"] == "England" and out["stale"] is False
    assert out["sources"]["fixtures"] == "stub" and out["sources"]["enrich"] == "off"
    assert out["next"]["away"]["name"] == "Australia"
    assert out["next"]["venue"] == "Allianz Stadium, London"
    h = c.get("/healthz").get_json()
    assert h["ok"] is True and h["fixtures_cached"] == 20        # 19 + placeholder
