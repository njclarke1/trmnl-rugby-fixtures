"""Dormant mode (England), driven by a FAKED CLOCK over the real World Rugby
stubs. Results after the 15 Oct 2026 probe are simulated by flipping stub
matches to complete, so every state of the year is reachable without waiting:
between windows, imminent, finals weekend, awaiting the draw, none scheduled.
Also: rest-of-window rail, standings source fallback and validation, final
placing, extras outage, neutral tag, round labels, Bristol untouched.
"""
import copy
import datetime as dt
import json
import os

import pytest

from app import config, dormant, extras, main, normalise
from app.errors import SourceUnavailable
from app.sources import world_rugby as wr

UTC = dt.timezone.utc
ENG = os.path.join(os.environ["STUB_DIR"], "england")


def T(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def _stub(name):
    with open(os.path.join(ENG, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(autouse=True)
def england(monkeypatch, tmp_path):
    for k, v in {"FIXTURES_SOURCE": "world_rugby", "SOURCE_STUB": True, "WR_TEAM_ID": "34",
                 "TEAM_NAME": "England", "TBC_PLACEHOLDER_TIMES": [], "DORMANT_MODE": True,
                 "EXTRAS_TTL": 0, "CACHE_DIR": str(tmp_path)}.items():
        monkeypatch.setattr(config, k, v)


def simulate(monkeypatch, upto, scores=None, extra=()):
    """Stub with every match before `upto` complete. England win 30–10 unless
    `scores` = {"YYYY-MM-DD": (ours, theirs)} says otherwise. `extra`: matches to add."""
    doc = copy.deepcopy(_stub("wr_match_34.json"))
    doc["content"].extend(copy.deepcopy(list(extra)))
    cut = upto.timestamp() * 1000
    for m in doc["content"]:
        if m["status"] == "U" and m["time"]["millis"] < cut:
            day = dt.datetime.fromtimestamp(m["time"]["millis"] / 1000, UTC).date().isoformat()
            ours, theirs = (scores or {}).get(day, (30, 10))
            first = m["teams"][0]["id"] == "34"
            m["status"] = "C"
            m["scores"] = [ours, theirs] if first else [theirs, ours]
            m["outcome"] = ("A" if first else "B") if ours > theirs else ("B" if first else "A")
    monkeypatch.setattr(wr, "_get_page", lambda s, e, p: doc)
    return doc


def finals_match(day=28, opponent=("36", "Ireland", "IRE")):
    m = copy.deepcopy(next(m for m in _stub("wr_match_34.json")["content"]
                           if m["time"]["label"] == "2026-11-21"))
    m["matchId"] = f"nc-finals-{day}"
    m["teams"][1].update(id=opponent[0], name=opponent[1], abbreviation=opponent[2])
    m["time"]["millis"] = int(dt.datetime(2026, 11, day, 17, 40, tzinfo=UTC).timestamp() * 1000)
    return m


def payload(now, cache=None):
    fx = wr.fetch(now, {}).fixtures
    cache = extras.refresh(cache if cache is not None else extras.blank(), fx, now)
    return normalise.build_payload(fx, now, extras=cache), cache


# --- the mode across the year --------------------------------------------------------

def test_today_is_dormant_with_nations_championship_next():
    p, _ = payload(T("2026-10-15T17:00"))
    d = p["dormant"]
    assert p["display_mode"] == "dormant" and p["on_deck"] == []
    assert (d["state"], d["headline"], d["window_name"], d["countdown"]) == \
        ("between_windows", "Next window opens", "Nations Championship", "In 24 days")
    assert d["window_when"] == "8–29 Nov 2026 · 4 matches incl. finals 27–29 Nov"
    assert d["opener"] == "England v Australia · Sun 8 Nov, 15:10"
    assert d["opener_venue"] == "Allianz Stadium, London"
    assert d["spine"] == "England Rugby" and d["spine_round"] == "Off window"
    assert d["last_result"] == {"line": "Argentina 24–31 England",
                                "detail": "Nations Championship · Round 3 · 18 Jul",
                                "result": "W", "outcome": "Won by 7", "date": "18 Jul"}
    assert d["standing"]["line"] == "3rd · 10 pts"
    assert d["standing"]["detail"] == "W2 L1 · +48 points difference"
    assert d["standing"]["source"] == "world-rugby" and d["standing"]["historic"] is False
    assert d["ranking"] == {"line": "5th in world rankings", "detail": "85.68 ranking points"}


@pytest.mark.parametrize("now,mode", [
    ("2026-10-17T22:30", "dormant"),     # Sat 17 Oct 23:30 BST: 22 days to 8 Nov
    ("2026-10-17T23:30", "fixture"),     # Sun 18 Oct 00:30 BST: 21 days
])
def test_imminent_threshold_counts_london_days(now, mode):
    assert payload(T(now))[0]["display_mode"] == mode


def test_fixture_mode_rail_is_rest_of_window_only():
    p, _ = payload(T("2026-10-18T12:00"))
    assert p["display_mode"] == "fixture" and p["dormant"] is None
    assert p["rail_label"] == "Rest of window"
    assert [(r["opponent"], r["round"]) for r in p["on_deck"]] == \
        [("Japan", "Round 5"), ("New Zealand", "Round 6"), ("Opponent TBC", "Finals weekend")]
    assert p["on_deck"][2]["when"] == "27–29 Nov"


def test_rail_never_reaches_into_the_next_window(monkeypatch):
    simulate(monkeypatch, T("2026-11-15T00:00"))
    p, _ = payload(T("2026-11-15T12:00"))
    assert p["next"]["away"]["name"] == "New Zealand"
    assert [r["opponent"] for r in p["on_deck"]] == ["Opponent TBC"]   # not Ireland in Feb


def test_finals_weekend_placeholder_screen(monkeypatch):
    simulate(monkeypatch, T("2026-11-22T00:00"))
    p, _ = payload(T("2026-11-22T12:00"))
    n = p["next"]
    assert p["display_mode"] == "fixture"
    assert (n["placeholder"], n["opponent_tbc"], n["day"], n["date"], n["time"]) == \
        (True, True, "Finals weekend", "27–29 Nov", "TBC")
    assert (n["venue_tag"], n["round"], n["countdown"]) == ("TBC", "Finals weekend", "In 5 days")


def test_after_november_dormant_until_six_nations(monkeypatch):
    simulate(monkeypatch, T("2026-11-30T00:00"), extra=[finals_match()])
    p, _ = payload(T("2026-12-01T12:00"))
    d = p["dormant"]
    assert (d["window_name"], d["countdown"]) == ("Six Nations", "In 66 days")
    assert d["window_when"] == "5 Feb – 13 Mar 2027 · 5 matches"
    assert d["opener"] == "Ireland v England · Fri 5 Feb, 20:10"
    assert d["last_result"]["line"] == "England 30–10 Ireland"
    assert d["last_result"]["detail"] == "Nations Championship · Finals weekend · 28 Nov"


def test_six_nations_window_is_fixture_mode_with_rest_of_window():
    p, _ = payload(T("2027-02-01T12:00"))
    assert p["display_mode"] == "fixture"
    assert p["next"]["venue_tag"] == "Away" and p["next"]["round"] == "Round 1"
    assert [r["opponent"] for r in p["on_deck"]] == ["France", "Italy", "Wales"]


def test_awaiting_draw_after_world_cup_pool(monkeypatch):
    simulate(monkeypatch, T("2027-10-17T00:00"))
    p, _ = payload(T("2027-10-17T12:00"))
    d = p["dormant"]
    assert p["display_mode"] == "dormant" and p["next"] is None
    assert (d["state"], d["headline"], d["spine_round"], d["window_name"]) == \
        ("awaiting_draw", "Awaiting the draw", "Awaiting draw", "Rugby World Cup")
    assert d["window_when"] == "Next fixture not yet set · final 13 Nov 2027"
    assert d["last_result"]["line"] == "England 30–10 Wales"
    assert d["last_result"]["detail"] == "Rugby World Cup · Pool F · 16 Oct"


def test_none_scheduled_after_world_cup_ends(monkeypatch):
    simulate(monkeypatch, T("2027-11-14T00:00"))
    d = payload(T("2027-11-14T12:00"))[0]["dormant"]
    assert d["state"] == "none_scheduled" and d["window_name"] is None
    assert d["last_result"]["line"] == "England 30–10 Wales"


# --- standings: source fallback, validation, final placing ------------------------------

def test_six_nations_table_falls_back_to_espn():
    d = payload(T("2026-04-01T12:00"))[0]["dormant"]
    assert d["last_result"]["line"] == "France 48–46 England"
    assert d["last_result"]["outcome"] == "Lost by 2"
    assert d["standing"] == {"label": "2026 Six Nations · final", "line": "5th · 8 pts",
                             "detail": "W1 L4 · +2 points difference", "historic": True,
                             "source": "espn"}


def test_table_that_does_not_match_our_results_is_refused(monkeypatch):
    """After a simulated grand slam in 2027, ESPN's (2026: W1 L4) table must not show."""
    simulate(monkeypatch, T("2027-03-14T00:00"))
    p, cache = payload(T("2027-03-20T12:00"))
    assert p["dormant"]["last_result"]["line"] == "England 30–10 Scotland"
    assert p["dormant"]["standing"] is None
    assert "does not match our results" in cache["last_error"]


def test_final_placing_from_pre_finals_table_position(monkeypatch):
    simulate(monkeypatch, T("2026-11-22T00:00"))
    nc = _stub("wr_standings_46294cf5-dee3-4234-957a-dbe1f08049f2.json")
    row = next(e for e in nc["tables"][0]["entries"] if e["team"]["name"] == "England")
    row.update(positionLabel="2", played=6, won=5, lost=1, points=24)
    real_get = extras._get_json
    monkeypatch.setattr(extras, "_get_json", lambda url, stub: nc if "46294cf5" in stub
                        else real_get(url, stub))
    _, cache = payload(T("2026-11-23T12:00"))                  # finals pending
    assert cache["standings"]["Nations Championship 2026"]["pre_final_pos"] == 2

    simulate(monkeypatch, T("2026-11-30T00:00"), extra=[finals_match()])
    row.update(positionLabel="1", played=7, won=6)            # table moved after finals
    d = payload(T("2026-12-01T12:00"), cache)[0]["dormant"]
    assert d["standing"]["line"] == "Finished 3rd"            # 2nd v 2nd, won → 3rd
    assert d["standing"]["detail"] == "2nd in table · beat Ireland in finals"
    assert d["standing"]["label"] == "2026 Nations Championship · final"


def test_extras_outage_keeps_cached_standing(monkeypatch):
    _, cache = payload(T("2026-10-15T17:00"))
    monkeypatch.setattr(extras, "_get_json", lambda url, stub: (_ for _ in ()).throw(
        SourceUnavailable("down")))
    p, cache = payload(T("2026-10-15T18:00"), cache)
    assert p["dormant"]["standing"]["line"] == "3rd · 10 pts"
    assert p["dormant"]["ranking"]["line"] == "5th in world rankings"
    assert "down" in cache["last_error"]


def test_extras_persist_across_restart():
    _, cache = payload(T("2026-10-15T17:00"))
    again = extras.load()
    assert again["standings"] == cache["standings"] and again["ranking"] == cache["ranking"]


# --- labels, tags, initials ------------------------------------------------------------

@pytest.mark.parametrize("now,opp,tag,rnd", [
    ("2026-11-01T12:00", "Australia", "Home", "Round 4"),
    ("2027-02-01T12:00", "Ireland", "Away", "Round 1"),
    ("2027-09-25T12:00", "Tonga", "Neutral", "Pool F"),
])
def test_venue_tag_and_round(now, opp, tag, rnd):
    n = normalise.build_payload(wr.fetch(T(now), {}).fixtures, T(now))["next"]
    assert opp in (n["home"]["name"], n["away"]["name"])
    assert (n["venue_tag"], n["round"]) == (tag, rnd)


def test_fiji_at_liverpool_is_neutral():
    fx = [f for f in wr.fetch(T("2026-07-01T12:00"), {}).fixtures if f.home.name == "Fiji"]
    n = normalise.build_payload(fx, T("2026-07-01T12:00"))["next"]
    assert n["venue_tag"] == "Neutral" and n["venue"] == "Hill Dickinson Stadium, Liverpool"


def test_initials_from_source_abbreviation():
    n = normalise.build_payload(wr.fetch(T("2026-11-18T12:00"), {}).fixtures,
                                T("2026-11-18T12:00"))["next"]
    assert (n["home"]["initials"], n["away"]["initials"]) == ("ENG", "NZL")


def test_ordinal():
    assert [dormant._ord(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]


# --- gating and end to end -------------------------------------------------------------

def test_dormant_mode_off_adds_nothing(monkeypatch):
    monkeypatch.setattr(config, "DORMANT_MODE", False)
    p = normalise.build_payload(wr.fetch(T("2026-10-15T17:00"), {}).fixtures,
                                T("2026-10-15T17:00"))
    assert not {"display_mode", "dormant", "rail_label"} & set(p)


def test_end_to_end_dormant_through_flask(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LAST_GOOD_FILE", str(tmp_path / "lg.json"))
    monkeypatch.setattr(main, "_state", main._blank_state())
    c = main.app.test_client()
    out = c.get("/fixtures?now=2026-10-15T17:00:00Z").get_json()
    assert out["display_mode"] == "dormant"
    assert out["dormant"]["standing"]["line"] == "3rd · 10 pts"
    h = c.get("/healthz").get_json()
    assert h["dormant_mode"] is True
    assert h["extras"]["standings"] == ["Nations Championship 2026"]
