"""Render plugin/full.liquid for every demo state → HTML (+ PNG if Playwright
is installed). Doubles as a Liquid syntax check. Run from the repo root:

    pip install python-liquid playwright   # playwright optional
    python plugin/demo/render_demo.py

PNGs are 960×540 1-bit-ish previews in Chromium. LaraPaper's renderer is the
final word: check on the panel with /demo/<state>.json (README, Phase 5).
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("FIXTURES_SOURCE", "stub")
os.environ.setdefault("STUB_DIR", "tests/fixtures")
os.environ.setdefault("CACHE_DIR", "/tmp/trf-demo-cache")

from liquid import Environment  # noqa: E402

from app import demo  # noqa: E402

OUT = os.environ.get("DEMO_OUT", "plugin/demo/out")
tpl = Environment().from_string(open("plugin/full.liquid", encoding="utf-8").read())


def render_all() -> dict[str, str]:
    os.makedirs(OUT, exist_ok=True)
    pages = {}
    for state in demo.STATES:
        payload = demo.build(state)
        if state == "provisional" and payload["next"]:
            payload["next"]["provisional"] = True        # show the main-panel chip too
        html = ('<!doctype html><meta charset="utf-8"><body style="margin:0">'
                + tpl.render(**payload) + "</body>")
        path = os.path.join(OUT, f"{state}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        pages[state] = path
    return pages


def screenshot(pages: dict[str, str]) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed: HTML only")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 960, "height": 540})
        for state, path in pages.items():
            page.goto("file://" + os.path.abspath(path))
            page.screenshot(path=os.path.join(OUT, f"{state}.png"))
        browser.close()


if __name__ == "__main__":
    pages = render_all()
    screenshot(pages)
    for s, p in pages.items():
        print(f"{s:12} {p}")
