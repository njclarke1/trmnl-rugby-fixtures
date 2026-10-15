"""full.liquid against every demo state (Liquid syntax + content), and the
/demo endpoints used to force states on the panel."""
import os

import pytest

from app import demo, main

liquid = pytest.importorskip("liquid")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = liquid.Environment().from_string(
    open(os.path.join(ROOT, "plugin", "full.liquid"), encoding="utf-8").read())


def render(state):
    return TPL.render(**demo.build(state))


@pytest.mark.parametrize("state,expect,absent", [
    ("available", ["Gallagher PREM", "Round 4",
                   "tv-primary\">TNT Sports", "Also: HBO Max", "You have<br>this",
                   "Exeter Chiefs", "Home", "In 6 days"], ["tv-primary out", "Data check"]),
    ("unavailable", ["Champions Cup", "Pool · R1", "tv-primary out\">Premier Sports",
                     "Not on<br>your TV", "Not in your Sky / TNT / terrestrial package",
                     "Stormers", "Away"], ["You have<br>this"]),
    ("tbc", ["PREM Rugby Cup", "Pool game 3", "To be confirmed",
             "TNT Sports shows selected PREM Cup games"], ['class="tv-primary']),
    ("none", ["Not televised", "No<br>coverage"], ['class="tv-primary', 'class="tv-also']),
    ("itv", ["tv-primary\">ITV1", "Also: ITVX · TNT Sports 1"], []),
    ("provisional", ["Sat 20 Mar · 15:00 TBC"], ['class="tbc-chip']),   # main: 6 days out
    ("long_name", ["club long\">Newcastle Red Bulls"], []),
    ("kicked_off", ["Kicked off"], []),
    ("friendly", ["Friendly", "Exhibition", "Argentina XV", "check the club"], []),
    ("data_check", ["strip-tag alert\">Data check"], ["Cached"]),
    ("empty", ["To be announced", "Off<br>season", "Bristol Bears", "Fixtures: demo"],
     ["Watch<br>on"]),
])
def test_template_states(state, expect, absent):
    html = render(state)
    for s in expect:
        assert s in html, (state, s)
    for s in absent:
        assert s not in html, (state, s)


def test_ours_uses_inverted_crest_class():
    html = render("available")
    assert html.count('class="crest inv"') == 1 and html.count('class="crest"') == 1


def test_no_grid_and_self_contained_style():
    src = open(os.path.join(ROOT, "plugin", "full.liquid"), encoding="utf-8").read()
    assert "display:grid" not in src.replace(" ", "")
    assert "class=\"layout\"" not in src and "title_bar" not in src


def test_layout_pinned_to_viewport_origin():
    # Regression: LaraPaper's page margin/wrapper padding offset the layout.
    src = open(os.path.join(ROOT, "plugin", "full.liquid"), encoding="utf-8").read()
    compact = src.replace(" ", "")
    assert "html,body{margin:0!important;padding:0!important" in compact
    assert ".rg{position:fixed;top:0;left:0" in compact


def test_demo_endpoints():
    c = main.app.test_client()
    assert sorted(c.get("/demo").get_json()["states"]) == sorted(demo.STATES)
    p = c.get("/demo/unavailable.json").get_json()
    assert p["demo_state"] == "unavailable" and p["next"]["broadcast"]["state"] == "unavailable"
    assert c.get("/demo/nope.json").status_code == 404
