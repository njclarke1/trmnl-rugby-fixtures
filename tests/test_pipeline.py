"""Pipeline tests against the club feed's real responses.

Covers: the Phase 1 coverage matrix, iCal parsing (TZID, UTC, all-day,
folding), JSON enrichment and gap-fill, round derivation, the hold window,
the BST→GMT boundary, provisional kickoffs, friendlies, season rollover, an
empty season, shape checks, and outage → last-good → recovery.
"""
import datetime as dt
import os
import zlib

import pytest

from app import config, ical, main, normalise, rounds
from app.errors import ShapeError, SourceUnavailable
from app.model import synthetic_id
from app.sources import club_wp

UTC = dt.timezone.utc
FIX = os.environ["STUB_DIR"]
NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)       # Thu 15 Oct 2026, 18:00 BST


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def _fetch(now=NOW, counts=None):
    return club_wp.fetch(now, counts or {})


def _by_date(fixtures, iso_date):
    return [f for f in fixtures
            if f.kickoff_utc.astimezone(normalise.LONDON).date().isoformat() == iso_date]


@pytest.fixture
def both_seasons(monkeypatch):
    monkeypatch.setattr(config, "SEASON_IDS", ["202501", "202601"])
    return _fetch().fixtures


# --- Phase 1 coverage matrix, pinned -----------------------------------------

@pytest.mark.parametrize("date,opponent,comp", [
    ("2026-06-06", "Sale Sharks", "Gallagher Premiership"),     # PREM Round 18 (past)
    ("2026-05-29", "Bath Rugby", "Gallagher Premiership"),      # PREM (past)
    ("2026-10-24", "Exeter Chiefs", "Gallagher Premiership"),   # PREM (upcoming)
    ("2026-02-28", "Sale Sharks", "Prem Rugby Cup"),            # PREM Cup (past)
    ("2026-11-06", "Sale Sharks", "Prem Rugby Cup"),            # PREM Cup (upcoming)
    ("2026-04-04", "Toulouse", "European Cup"),                 # Champions Cup R16 (past)
    ("2026-10-17", "DHL Stormers", "European Cup"),             # Champions Cup (upcoming)
    ("2026-12-12", "Munster Rugby", "European Cup"),
])
def test_coverage_matrix(both_seasons, date, opponent, comp):
    hits = [f for f in _by_date(both_seasons, date)
            if opponent in (f.home.name, f.away.name) and f.competition_raw == comp]
    assert len(hits) == 1


def test_counts_match_feed():
    res = _fetch()
    assert res.counts == {"202601": 30}
    assert res.season_status == {"202601": "ok", "202701": "missing"}
    assert res.enrich_ok is True
    assert not [w for w in res.warnings if "differs" in w or "only in JSON" in w]


# --- iCal parsing ----------------------------------------------------------------

def test_ical_tzid_bst_and_gmt():
    events, bad = ical.parse_events(_read("ical_202601_men.ics"))
    assert bad == 0 and len(events) == 30
    by_uid = {e["uid"].split("@")[0]: e for e in events}
    # Stormers: 15:15 BST → 14:15Z.  Munster: 20:00 GMT → 20:00Z.
    assert by_uid["293322"]["start_utc"] == dt.datetime(2026, 10, 17, 14, 15, tzinfo=UTC)
    munster = next(e for e in events if "Munster" in e["summary"])
    assert munster["start_utc"] == dt.datetime(2026, 12, 12, 20, 0, tzinfo=UTC)


def test_ical_unfolds_long_lines():
    events, _ = ical.parse_events(_read("ical_202601_men.ics"))
    assert all(e["url"].startswith("https://www.bristolbearsrugby.com/match-centre/")
               and " " not in e["url"] for e in events)


def test_ical_utc_allday_escapes_and_bad_events():
    doc = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "BEGIN:VEVENT", "UID:1@x", "DTSTART:20261024T163000Z",
        "SUMMARY:Bristol Bears vs Exeter Chiefs - Gallagher Premiership",
        "LOCATION:Ashton Gate\\, Bristol", "END:VEVENT",
        "BEGIN:VEVENT", "UID:2@x", "DTSTART;VALUE=DATE:20270320",
        "SUMMARY:Bristol Bears vs Sale Sharks - Gallagher Premiership", "END:VEVENT",
        "BEGIN:VEVENT", "UID:3@x", "SUMMARY:no start", "END:VEVENT",
        "END:VCALENDAR"])
    events, bad = ical.parse_events(doc)
    assert bad == 1
    assert events[0]["start_utc"] == dt.datetime(2026, 10, 24, 16, 30, tzinfo=UTC)
    assert events[0]["location"] == "Ashton Gate, Bristol"
    assert events[1]["all_day"] is True
    assert events[1]["start_utc"].astimezone(normalise.LONDON).date() == dt.date(2027, 3, 20)


def test_ical_rejects_non_calendar():
    with pytest.raises(ical.ICalError):
        ical.parse_events("<html><body>Not found</body></html>")


@pytest.mark.parametrize("summary,expected", [
    ("Bristol Bears vs Bordeaux-Begles - European Cup",
     ("Bristol Bears", "Bordeaux-Begles", "European Cup")),
    ("DHL Stormers vs Bristol Bears - European Cup",
     ("DHL Stormers", "Bristol Bears", "European Cup")),
    ("Bristol Bears vs Argentina XV - Exhibition", ("Bristol Bears", "Argentina XV", "Exhibition")),
    ("Bristol Bears v Bath Rugby", ("Bristol Bears", "Bath Rugby", "")),
])
def test_parse_summary(summary, expected):
    assert club_wp.parse_summary(summary) == expected


# --- enrichment --------------------------------------------------------------------

def test_enrichment_joins_on_game_id():
    fx = {f.id: f for f in _fetch().fixtures}
    sara = fx[294920]                                  # Saracens 30-7 Bristol, 10 Oct
    assert sara.status == "Result" and (sara.home.score, sara.away.score) == (30, 7)
    assert sara.home.logo and sara.home.logo.startswith("https://www.bristolbearsrugby.com/")
    assert fx[293322].status == "Fixture" and fx[293322].home.score is None


def test_enrichment_failure_keeps_every_fixture(monkeypatch):
    real = club_wp._get

    def broken(kind, season):
        if kind == "json":
            return '{"code": "rest_no_route"}'
        return real(kind, season)
    monkeypatch.setattr(club_wp, "_get", broken)
    res = _fetch()
    assert res.enrich_ok is False and len(res.fixtures) == 30
    assert all(f.home.logo is None for f in res.fixtures)


def test_json_only_fixture_is_added_not_lost(monkeypatch):
    real = club_wp._get

    def drop_one(kind, season):
        text = real(kind, season)
        if kind == "ical":                             # remove the Leicester event
            start = text.index("UID:294928")
            b = text.rfind("BEGIN:VEVENT", 0, start)
            e = text.index("END:VEVENT", start) + len("END:VEVENT\r\n")
            text = text[:b] + text[e:]
        return text
    monkeypatch.setattr(club_wp, "_get", drop_one)
    res = _fetch()
    lei = [f for f in res.fixtures if "Leicester" in f.away.name]
    assert len(lei) == 1 and lei[0].source == "club_json" and lei[0].id == 294928
    assert any("only in JSON" in w for w in res.warnings)


def test_kickoff_mismatch_warns_and_calendar_wins(monkeypatch):
    real = club_wp._get

    def shift(kind, season):
        text = real(kind, season)
        return text.replace('"date":"2026-10-24T16:30:00Z"', '"date":"2026-10-24T14:00:00Z"') \
            if kind == "json" else text
    monkeypatch.setattr(club_wp, "_get", shift)
    res = _fetch()
    exe = next(f for f in res.fixtures if f.id == 294926)
    assert exe.kickoff_utc == dt.datetime(2026, 10, 24, 16, 30, tzinfo=UTC)
    assert any("kickoff differs" in w for w in res.warnings)


# --- rounds ---------------------------------------------------------------------

def test_rounds_current_season():
    fxs = _fetch().fixtures
    lab = rounds.label_rounds(fxs)
    by = {f.id: lab[f.id] for f in fxs}
    assert by[293322] == "Pool · R1"                   # Stormers
    assert by[294926] == "Round 4"                     # Exeter, PREM
    assert by[294862] == "Pool game 3"                 # Sale, PREM Cup
    prem = sorted((f for f in fxs if f.competition_raw == "Gallagher Premiership"),
                  key=lambda f: f.kickoff_utc)
    assert len(prem) == 18 and lab[prem[-1].id] == "Round 18"


def test_rounds_last_season_knockouts_and_friendly(both_seasons):
    lab = rounds.label_rounds(both_seasons)
    r18 = _by_date(both_seasons, "2026-06-06")[0]       # 18 played: regular season
    tou = _by_date(both_seasons, "2026-04-04")[0]
    arg = _by_date(both_seasons, "2025-11-07")[0]
    assert lab[r18.id] == "Round 18"
    assert lab[tou.id] == "Round of 16"
    assert lab[arg.id] == "Exhibition"


def test_rounds_prem_play_offs_synthetic():
    # No Bristol play-off exists in the real data yet: pin the rule on a
    # synthetic 19th/20th league game.
    fxs = _fetch().fixtures
    last = max(fxs, key=lambda f: f.kickoff_utc)
    extra = []
    for i, day in enumerate((12, 19)):
        f = club_wp.fixtures_from_ical(_read("ical_202601_men.ics"), "202601")[0][-1]
        f.id, f.kickoff_utc = -100 - i, last.kickoff_utc.replace(day=day)
        extra.append(f)
    lab = rounds.label_rounds(fxs + extra)
    assert (lab[-100], lab[-101]) == ("Semi-final", "Final")


# --- payload: next, hold window, countdown ----------------------------------------

def test_payload_next_and_rail():
    p = normalise.build_payload(_fetch().fixtures, NOW)
    n = p["next"]
    assert (n["competition"], n["round"], n["venue_tag"]) == ("Champions Cup", "Pool · R1", "Away")
    assert (n["day"], n["date"], n["time"], n["countdown"]) == ("Saturday", "17 Oct", "15:15", "In 2 days")
    assert n["home"]["display"] == "Stormers" and n["home"]["initials"] == "STO"
    assert n["away"]["ours"] and n["away"]["initials"] == "BRI"
    assert p["team_badge"] == "BB"
    assert [d["opponent"] for d in p["on_deck"]] == ["Exeter", "Leicester", "Sale"]
    assert [d["ha"] for d in p["on_deck"]] == ["H", "H", "A"]
    assert p["on_deck"][2]["competition_short"] == "PREM Cup"


@pytest.mark.parametrize("minutes,expect_id,countdown", [
    (-1, 293322, "Today"),
    (0, 293322, "Kicked off"),
    (149, 293322, "Kicked off"),
    (151, 294926, "In 7 days"),
])
def test_hold_window_150_minutes(minutes, expect_id, countdown):
    kick = dt.datetime(2026, 10, 17, 14, 15, tzinfo=UTC)
    p = normalise.build_payload(_fetch().fixtures, kick + dt.timedelta(minutes=minutes))
    assert p["next"]["id"] == expect_id and p["next"]["countdown"] == countdown


def test_bst_to_gmt_boundary():
    # Clocks go back 01:00 GMT Sun 25 Oct 2026.
    fxs = _fetch().fixtures
    exe = next(f for f in fxs if f.id == 294926)
    lei = next(f for f in fxs if f.id == 294928)
    assert exe.kickoff_utc == dt.datetime(2026, 10, 24, 16, 30, tzinfo=UTC)   # 17:30 BST
    assert lei.kickoff_utc == dt.datetime(2026, 10, 30, 19, 45, tzinfo=UTC)   # 19:45 GMT
    # Late Saturday BST, after the Exeter hold has expired: Leicester is next,
    # shown in GMT local time, six calendar days away across the change.
    now = dt.datetime(2026, 10, 24, 22, 30, tzinfo=UTC)                        # 23:30 BST
    n = normalise.build_payload(fxs, now)["next"]
    assert (n["id"], n["time"], n["countdown"]) == (294928, "19:45", "In 6 days")
    # And just after the change, 00:30 GMT Sunday.
    now = dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert normalise.build_payload(fxs, now)["next"]["countdown"] == "In 5 days"


# --- provisional kickoff times ---------------------------------------------------

def test_provisional_placeholder_rule():
    fxs = {f.id: f for f in _fetch().fixtures}
    quins = next(f for f in fxs.values() if f.home.name == "Bristol Bears"
                 and f.away.name == "Harlequins")                            # Sun 20 Dec 15:00
    assert normalise.is_provisional(quins, NOW) is True                       # 66 days out
    assert normalise.is_provisional(quins, dt.datetime(2026, 12, 1, tzinfo=UTC)) is False
    assert normalise.is_provisional(fxs[294928], NOW) is False                # Fri 19:45
    newc = next(f for f in fxs.values() if "Newcastle" in f.away.name)        # Sat 15:05
    assert normalise.is_provisional(newc, NOW) is False


def test_provisional_shown_in_rail():
    now = dt.datetime(2026, 12, 14, 12, 0, tzinfo=UTC)          # after Munster
    p = normalise.build_payload(_fetch().fixtures, now)
    assert p["next"]["away"]["name"] == "Harlequins"
    assert p["next"]["provisional"] is False                    # 6 days out: inside horizon
    later = normalise.build_payload(_fetch().fixtures, dt.datetime(2027, 1, 17, tzinfo=UTC))
    assert later["next"]["time"] == "15:00" and later["next"]["provisional"] is False
    assert later["on_deck"][0]["when"] == "Sat 30 Jan · 15:00"  # 13 days: confirmed
    far = normalise.build_payload(_fetch().fixtures, dt.datetime(2027, 1, 31, tzinfo=UTC))
    assert far["on_deck"][1]["when"] == "Sat 27 Feb · 15:00"          # 27 days
    assert far["on_deck"][2]["when"] == "Sat 20 Mar · 15:00 TBC"      # 48 days
    assert far["on_deck"][2]["tbc"] is True


def test_all_day_event_renders_tbc_and_holds_all_day():
    doc = "\r\n".join(["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:9@x",
                       "DTSTART;VALUE=DATE:20270320",
                       "SUMMARY:Bristol Bears vs Sale Sharks - Gallagher Premiership",
                       "LOCATION:TBD", "END:VEVENT", "END:VCALENDAR"])
    fxs, bad, _ = club_wp.fixtures_from_ical(doc, "202601")
    late = dt.datetime(2027, 3, 20, 22, 0, tzinfo=UTC)
    n = normalise.build_payload(fxs, late)["next"]
    assert (n["time"], n["tbc"], n["venue"], n["countdown"]) == ("TBC", True, "Venue TBC", "Today")


# --- friendlies ------------------------------------------------------------------

def test_exhibition_is_friendly(both_seasons):
    now = dt.datetime(2025, 11, 1, 12, 0, tzinfo=UTC)
    p = normalise.build_payload(both_seasons, now)
    n = p["next"]
    assert (n["competition"], n["round"], n["is_friendly"]) == ("Friendly", "Exhibition", True)
    assert n["away"]["name"] == "Argentina XV" and n["broadcast"]["state"] == "tbc"
    assert n["broadcast"]["also"] == "Friendly: check the club's own stream"


# --- seasons, rollover, empty ------------------------------------------------------

@pytest.mark.parametrize("now,ids", [
    (dt.datetime(2026, 10, 15, tzinfo=UTC), ["202601", "202701"]),
    (dt.datetime(2027, 6, 30, 12, tzinfo=UTC), ["202601", "202701"]),
    (dt.datetime(2027, 7, 1, 12, tzinfo=UTC), ["202701", "202801"]),
])
def test_season_ids(monkeypatch, now, ids):
    monkeypatch.setattr(config, "SEASON_IDS", [])
    assert club_wp.season_ids(now) == ids


def test_rollover_summer_shows_next_season():
    # 20 Jun 2026: 2025/26 is over (semi 6 Jun); 2026/27 is published.
    now = dt.datetime(2026, 6, 20, 12, tzinfo=UTC)
    res = club_wp.fetch(now, {})
    assert set(res.counts) == {"202501", "202601"}
    n = normalise.build_payload(res.fixtures, now)["next"]
    assert n["away"]["name"] == "Gloucester Rugby" and n["date"] == "5 Sep"
    assert n["round"] == "Pool game 1"


def test_empty_season():
    after = dt.datetime(2027, 6, 10, tzinfo=UTC)
    p = normalise.build_payload(_fetch().fixtures, after)
    assert p["next"] is None and p["on_deck"] == []


def test_unpublished_next_season_erroring_is_not_an_outage(monkeypatch):
    real = club_wp._get

    def next_season_500(kind, season):
        if season == "202701":
            raise SourceUnavailable("HTTP 500")
        return real(kind, season)
    monkeypatch.setattr(club_wp, "_get", next_season_500)
    res = _fetch()
    assert res.counts == {"202601": 30} and res.season_status["202701"] == "unavailable"


def test_first_run_outage_is_stale_not_data_check(monkeypatch):
    monkeypatch.setattr(club_wp, "_get", lambda k, s: (_ for _ in ()).throw(
        SourceUnavailable("dns")))
    with pytest.raises(SourceUnavailable):
        _fetch()


def test_no_calendar_at_all_is_a_shape_error(monkeypatch):
    monkeypatch.setattr(config, "SEASON_IDS", ["199901"])
    with pytest.raises(ShapeError):
        _fetch()


# --- shape checks (protection 2) --------------------------------------------------

def test_sharp_drop_is_refused():
    # 41 → 30 is an 11-fixture drop; allowed is max(3, 25% of 41 = 10).
    with pytest.raises(ShapeError, match="was 41"):
        _fetch(counts={"202601": 41})


def test_small_drop_is_accepted():
    assert _fetch(counts={"202601": 32}).counts["202601"] == 30     # e.g. 2 cancellations


def test_known_season_disappearing_is_a_shape_error(monkeypatch):
    monkeypatch.setattr(club_wp, "_get", lambda kind, season: (_ for _ in ()).throw(
        club_wp._NotFound("404")))
    with pytest.raises(ShapeError, match="disappeared"):
        _fetch(counts={"202601": 30})


def test_html_instead_of_calendar_for_known_season(monkeypatch):
    monkeypatch.setattr(club_wp, "_get", lambda kind, season: "<html>maintenance</html>")
    with pytest.raises(ShapeError):
        _fetch(counts={"202601": 30})


def test_reworded_summaries_are_refused(monkeypatch):
    real = club_wp._get
    monkeypatch.setattr(club_wp, "_get", lambda k, s: real(k, s).replace(" vs ", " – ")
                        if k == "ical" else real(k, s))
    with pytest.raises(ShapeError, match="unparseable"):
        _fetch()


# --- outage, data check, last good, recovery (end to end through Flask) ------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LAST_GOOD_FILE", str(tmp_path / "last_good.json"))
    monkeypatch.setattr(main, "_state", main._blank_state())
    return main.app.test_client()


def _get_fixtures(client):
    return client.get("/fixtures?now=2026-10-15T17:00:00Z")


def test_outage_serves_last_good_then_recovers(client, monkeypatch):
    ok = _get_fixtures(client).get_json()
    assert ok["stale"] is False and ok["next"]["id"] == 293322
    assert ok["sources"] == {"fixtures": "stub", "enrich": "club-json", "broadcast": "rights-map"}

    def down(kind, season):
        raise SourceUnavailable("connection reset")
    real = club_wp._get
    monkeypatch.setattr(club_wp, "_get", down)
    main.refresh_if_due(force=True)
    out = _get_fixtures(client).get_json()
    assert out["stale"] is True and out["data_check"] is False
    assert out["next"]["id"] == 293322                      # fixture survives the outage

    monkeypatch.setattr(club_wp, "_get", real)
    main.refresh_if_due(force=True)
    back = _get_fixtures(client).get_json()
    assert back["stale"] is False and back["next"]["id"] == 293322


def test_restart_during_outage_uses_persisted_last_good(client, monkeypatch):
    _get_fixtures(client)                                    # good fetch, persisted
    monkeypatch.setattr(main, "_state", main._blank_state())  # simulate restart
    monkeypatch.setattr(club_wp, "_get", lambda k, s: (_ for _ in ()).throw(
        SourceUnavailable("dns")))
    out = _get_fixtures(client).get_json()
    assert out["stale"] is True and out["next"]["id"] == 293322


def test_shape_change_raises_data_check_and_keeps_last_good(client, monkeypatch):
    _get_fixtures(client)
    monkeypatch.setattr(club_wp, "_get", lambda k, s: "<html>new site</html>")
    main.refresh_if_due(force=True)
    out = _get_fixtures(client).get_json()
    assert out["data_check"] is True and "202601" in out["data_check_reason"]
    assert out["stale"] is True and out["next"]["id"] == 293322
    h = client.get("/healthz").get_json()
    assert h["ok"] is False and h["data_check"]


def test_no_data_ever_returns_503(client, monkeypatch):
    monkeypatch.setattr(club_wp, "_get", lambda k, s: (_ for _ in ()).throw(
        SourceUnavailable("down")))
    r = _get_fixtures(client)
    assert r.status_code == 503 and r.get_json()["next"] is None


def test_healthz_is_populated_from_cold(client):
    h = client.get("/healthz").get_json()
    assert h["ok"] is True and h["fixtures_cached"] == 30
    assert h["season_status"] == {"202601": "ok", "202701": "missing"}


# --- ids ------------------------------------------------------------------------

def test_synthetic_ids_negative_and_stable():
    ids = [synthetic_id("2026-10-24", f"team{i}") for i in range(500)]
    assert all(i < 0 for i in ids)
    expected = -((zlib.crc32(b"a|b") % 10 ** 9) + 1)
    assert synthetic_id("a", "b") == synthetic_id("a", "b") == expected
