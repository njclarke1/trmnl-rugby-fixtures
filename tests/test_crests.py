"""Crest pipeline on synthetic images (the club's real crests are trademarks and
aren't committed; check those by eye on /crests after deploying)."""
import datetime as dt

import pytest
from PIL import Image, ImageDraw

from app import config, crests, main, normalise
from app.sources import club_wp

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)
W, H = config.CREST_W, config.CREST_H


def shield(fg=(2, 2, 59, 255), bg=(0, 0, 0, 0), size=(257, 300), emblem=True):
    """Navy shield with a light-blue emblem on a transparent canvas (Bristol-ish)."""
    img = Image.new("RGBA", size, bg)
    d = ImageDraw.Draw(img)
    w, h = size
    d.polygon([(20, 20), (w - 20, 20), (w - 20, h * 0.55), (w / 2, h - 15), (20, h * 0.55)], fill=fg)
    if emblem:
        d.ellipse((w * 0.3, h * 0.25, w * 0.7, h * 0.6), fill=(0, 168, 225, 255))
    return img


def black_frac(img, box=None):
    region = img.crop(box) if box else img
    return 1 - region.convert("L").histogram()[255] / (region.width * region.height)


def test_output_size_mode_and_oval_mask():
    normal, inverted, thr = crests.process(shield())
    assert normal.size == inverted.size == (W, H)
    assert normal.mode == inverted.mode == "1"
    for corner in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
        assert normal.getpixel(corner) == 255          # outside the oval: paper
        assert inverted.getpixel(corner) == 0          # .inv: solid black oval
    assert isinstance(thr, int) and 0 < thr < 255


def test_shield_reads_dark_on_white_and_inverts():
    normal, inverted, _ = crests.process(shield())
    centre = (W // 2 - 15, H // 2 - 10, W // 2 + 15, H // 2 + 10)
    assert 0.05 < black_frac(normal) < 0.6
    # The two variants are photographic negatives inside the oval.
    assert abs(black_frac(normal, centre) + black_frac(inverted, centre) - 1) < 0.01


def test_opaque_dark_background_is_flipped_inside_crest_box_only():
    # Opaque black square with a small white emblem (no transparency).
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 255))
    ImageDraw.Draw(img).rectangle((120, 120, 180, 180), fill=(255, 255, 255, 255))
    normal, _, _ = crests.process(img)
    assert normal.getpixel((W // 2, H // 2)) == 0          # emblem now dark
    assert normal.getpixel((W // 2 - 20, H // 2)) == 255   # background now paper
    assert normal.getpixel((3, H // 2)) == 255             # padding untouched


def test_dark_shield_on_transparency_is_not_flipped():
    normal, _, _ = crests.process(shield(emblem=False))
    assert normal.getpixel((W // 2, H // 2)) == 0          # shield stays dark
    assert normal.getpixel((6, H // 2)) == 255             # paper around it


def test_mid_tone_shield_stays_dark_with_light_emblem():
    # Red shield (L≈81) with light-blue emblem (L≈124): sharpening halos must
    # not pull the threshold under the shield's own tone.
    normal, _, thr = crests.process(shield(fg=(200, 30, 30, 255)))
    assert 81 <= thr < 124
    assert normal.getpixel((W // 2, 12)) == 0              # shield body, above emblem: dark
    assert normal.getpixel((W // 2, 28)) == 255            # emblem centre: light
    assert normal.getpixel((W // 2, 46)) == 0              # shield body, below emblem: dark


def test_pale_crest_keeps_detail_and_outline():
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 290, 290), fill=(255, 215, 0, 255))     # gold disc
    d.rectangle((120, 60, 180, 240), fill=(0, 0, 0, 255))      # black bar
    normal, _, _ = crests.process(img)
    assert normal.getpixel((W // 2, H // 2)) == 0          # bar: dark
    assert normal.getpixel((W // 2 - 15, H // 2)) == 255   # gold: paper, not solid black
    assert black_frac(normal) < 0.4


def test_small_crest_on_big_canvas_is_trimmed_to_fill():
    img = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    img.paste(shield(size=(100, 120)), (450, 440))
    normal, _, _ = crests.process(img)
    assert black_frac(normal) > 0.08                   # not a speck in the middle


def test_dither_mode_and_cache_key(monkeypatch):
    plain_key = crests.key_for("https://x/a.png", "Saracens")
    monkeypatch.setattr(config, "CREST_DITHER", ["Saracens"])
    assert crests.mode_for("saracens") == "dither"
    assert crests.key_for("https://x/a.png", "Saracens") != plain_key
    normal, _, thr = crests.process(shield(), "dither")
    assert thr is None and normal.size == (W, H)


@pytest.fixture
def crest_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(crests, "CREST_DIR", str(tmp_path))
    monkeypatch.setattr(crests, "REGISTRY", {})
    return tmp_path


def test_ensure_caches_and_payload_uses_crest(monkeypatch, crest_dir):
    calls = []
    monkeypatch.setattr(crests, "_fetch", lambda url: calls.append(url) or shield())
    fixtures = club_wp.fetch(NOW, {}).fixtures
    teams = main._crest_teams(fixtures)
    assert len(teams) >= 10
    monkeypatch.setattr(config, "FIXTURES_SOURCE", "club_wp")
    assert crests.prewarm(teams) == {"ok": len(teams), "failed": 0}
    crests.prewarm(teams)
    assert len(calls) == len(teams)                    # second pass is all cache hits

    n = normalise.build_payload(fixtures, NOW)["next"]
    ours = n["away"]                                   # Stormers v Bristol
    assert ours["crest"].startswith(config.PUBLIC_BASE_URL + "/crest/")
    assert ours["crest_inv"].endswith("-inv.png")


def test_failed_fetch_falls_back_to_initials(monkeypatch, crest_dir):
    def boom(url):
        raise OSError("connection refused")
    monkeypatch.setattr(crests, "_fetch", boom)
    assert crests.ensure("https://x/missing.png", "Bath Rugby") is False
    assert crests.url_for("https://x/missing.png", "Bath Rugby") is None
    n = normalise.build_payload(club_wp.fetch(NOW, {}).fixtures, NOW)["next"]
    assert n["home"]["crest"] is None and n["home"]["initials"] == "STO"


def test_crest_routes(monkeypatch, crest_dir):
    monkeypatch.setattr(crests, "_fetch", lambda url: shield())
    crests.ensure("https://x/b.png", "<script>Bath</script>")
    key = crests.key_for("https://x/b.png", "<script>Bath</script>")
    client = main.app.test_client()
    r = client.get(f"/crest/{key}.png")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert client.get(f"/crest/{key}-inv.png").status_code == 200
    assert client.get("/crest/../../etc/passwd.png").status_code == 404
    assert client.get(f"/crest/{key}-x.png").status_code == 404
    page = client.get("/crests").get_data(as_text=True)
    assert "&lt;script&gt;Bath" in page and "<script>Bath" not in page
