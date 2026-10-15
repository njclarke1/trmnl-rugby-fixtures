"""Crest pipeline: club logo → 1-bit oval for the 960×540 e-ink panel.

  fetch PNG (URL from the club feed's JSON) → RGBA → composite on white → L
  → fit inside the oval (LANCZOS) → UnsharpMask → 1-bit (Otsu threshold by
  default; Floyd–Steinberg dither per team via CREST_DITHER) → polarity check
  → oval mask → two variants: normal (black on white) and inverted (white on
  black, the mock's `.crest.inv` for our own side) → disk cache.

Output is CREST_W×CREST_H (90×68): the inside of the mock's 96×74 oval with its
3px CSS border, so the image sits inside the border, never over it.

Crests are processed during the upstream refresh, not on the render path. The
payload names a crest only once its file exists; until then (or if a fetch
fails) the template shows initials, which the mock already treats as a
deliberate look. Club crests are trademarks: the cache is git-ignored.
"""
import hashlib
import io
import logging
import os
import threading

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import config

log = logging.getLogger(__name__)

PIPELINE_VERSION = "1"          # bump to re-render every cached crest
CREST_DIR = os.path.join(config.CACHE_DIR, "crests")
MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()
# key → {"url", "name", "mode", "threshold", "ok", "error"}; feeds /crests.
REGISTRY: dict[str, dict] = {}


def mode_for(name: str) -> str:
    wanted = {n.casefold() for n in config.CREST_DITHER}
    return "dither" if name.casefold() in wanted else "threshold"


def key_for(url: str, name: str = "") -> str:
    """Pipeline version and render mode are part of the key, so changing either
    re-renders instead of serving a stale cached file."""
    raw = f"{PIPELINE_VERSION}|{mode_for(name)}|{url}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def path_for(key: str, inverted: bool = False) -> str:
    return os.path.join(CREST_DIR, f"{key}{'-inv' if inverted else ''}.png")


def url_for(logo: str | None, name: str, inverted: bool = False) -> str | None:
    """Public crest URL if the processed file exists, else None (→ initials)."""
    if not logo:
        return None
    key = key_for(logo, name)
    if not os.path.exists(path_for(key, inverted)):
        return None
    return f"{config.PUBLIC_BASE_URL}/crest/{key}{'-inv' if inverted else ''}.png"


# --- image processing (pure, unit-tested) ------------------------------------

def otsu(hist: list[int]) -> int:
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * n for i, n in enumerate(hist))
    sum_b, w_b, best, thresh = 0.0, 0, 0.0, 128
    for i, n in enumerate(hist):
        w_b += n
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * n
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thresh = var, i
    return thresh


def _oval_mask(size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    return mask


def process(src: Image.Image, mode: str = "threshold") -> tuple[Image.Image, Image.Image, int | None]:
    """Return (normal, inverted, threshold_used). Both are mode '1', CREST_W×CREST_H."""
    size = (config.CREST_W, config.CREST_H)
    rgba = src.convert("RGBA")
    alpha = rgba.getchannel("A")
    has_alpha = alpha.getextrema()[0] < 250
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    grey = Image.alpha_composite(white, rgba).convert("L")

    # Trim margins so small crests on big canvases still fill the oval. With
    # transparency, the alpha channel defines the crest (a white crest on a
    # transparent canvas has no dark pixels to find a box from).
    bbox = alpha.point(lambda a: 255 if a > 32 else 0).getbbox() if has_alpha \
        else ImageOps.invert(grey).getbbox()
    if bbox:
        grey, alpha = grey.crop(bbox), alpha.crop(bbox)

    # The largest box inside an ellipse is a/√2 × b/√2; shields tolerate a little
    # more because their corners are cut. Fit to 78% of each axis.
    fit = (round(size[0] * 0.78), round(size[1] * 0.78))
    grey = ImageOps.contain(grey, fit, Image.LANCZOS)
    alpha = alpha.resize(grey.size, Image.LANCZOS)
    canvas = Image.new("L", size, 255)
    off = ((size[0] - grey.width) // 2, (size[1] - grey.height) // 2)
    canvas.paste(grey, off)
    # Otsu reads the clean pixels; sharpening first adds dark halos at the
    # crest's edge that Otsu then splits off as their own class.
    clean = canvas
    canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.5, percent=180, threshold=3))

    threshold = None
    if mode == "dither":
        mono = canvas.convert("1")                                   # Floyd–Steinberg
    else:
        area = clean.crop((off[0], off[1], off[0] + grey.width, off[1] + grey.height))
        # Otsu over the crest's own pixels only: transparent margins count as
        # white and would drag the split up until a pale crest goes solid black.
        hist = area.histogram(mask=alpha.point(lambda a: 255 if a > 128 else 0)) \
            if has_alpha else area.histogram()
        threshold = config.CREST_THRESHOLD or otsu(hist)
        mono = canvas.point(lambda p: 255 if p > threshold else 0).convert("1")
        # Polarity: e-ink wants dark marks on white. Flip only artwork that sits
        # on its own opaque dark background — all four corners of the crest box
        # black. A dark shield on a transparent canvas keeps its cut-away corners
        # white and is left alone (a "mostly black → invert" rule flips it).
        if not has_alpha:
            x0, y0 = off
            x1, y1 = x0 + grey.width - 1, y0 + grey.height - 1
            if all(mono.getpixel(p) == 0 for p in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
                box = (x0, y0, x1 + 1, y1 + 1)
                flipped = ImageOps.invert(mono.convert("L").crop(box))
                mono = mono.convert("L")
                mono.paste(flipped, box[:2])
                mono = mono.convert("1")

    if has_alpha:
        # Silhouette outline from the alpha channel, so a white or pale crest
        # still shows its shape on white paper. Invisible on dark crests.
        sil = Image.new("L", size, 0)
        sil.paste(alpha.point(lambda a: 255 if a > 128 else 0), off)
        edge = ImageChops.subtract(sil, sil.filter(ImageFilter.MinFilter(3)))
        mono = Image.composite(Image.new("L", size, 0), mono.convert("L"), edge).convert("1")

    mask = _oval_mask(size)
    normal = Image.composite(mono.convert("L"), Image.new("L", size, 255), mask).convert("1")
    inv_src = ImageOps.invert(mono.convert("L"))
    inverted = Image.composite(inv_src, Image.new("L", size, 0), mask).convert("1")
    return normal, inverted, threshold


# --- fetch + cache ---------------------------------------------------------

def _fetch(url: str) -> Image.Image:
    r = requests.get(url, timeout=config.HTTP_TIMEOUT, stream=True,
                     headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("crest image larger than 5 MB")
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def ensure(url: str, name: str) -> bool:
    """Process a crest if it isn't cached. Never raises; returns success."""
    key, mode = key_for(url, name), mode_for(name)
    entry = REGISTRY.setdefault(key, {"url": url, "name": name, "mode": mode})
    if os.path.exists(path_for(key)) and os.path.exists(path_for(key, True)):
        entry.update(ok=True)
        return True
    try:
        normal, inverted, thr = process(_fetch(url), mode)
        os.makedirs(CREST_DIR, exist_ok=True)
        normal.save(path_for(key))
        inverted.save(path_for(key, True))
        entry.update(ok=True, error=None, threshold=thr)
        return True
    except Exception as exc:  # noqa: BLE001 — a crest is garnish; initials stand in
        log.warning("crest %s (%s) failed: %s", name, url, exc)
        entry.update(ok=False, error=str(exc))
        return False


def prewarm(teams: dict[str, str]) -> dict[str, int]:
    """teams: {logo url: team name}. Called after a successful refresh."""
    if config.stub_mode():
        return {"ok": 0, "failed": 0}
    done = {"ok": 0, "failed": 0}
    with _lock:
        for url, name in teams.items():
            done["ok" if ensure(url, name) else "failed"] += 1
    return done
