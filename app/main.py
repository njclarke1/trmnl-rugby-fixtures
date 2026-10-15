"""trmnl-rugby-fixtures sidecar.

GET /fixtures   → flat payload for the LaraPaper plugin (6 h upstream cache)
GET /healthz    → cache, feed and shape-check state (refreshes if due, so it
                  is never empty after a restart; the football build's was)

Failure handling, all fail-soft:
  network/HTTP outage  → keep last good, `stale: true`, retry in 10 min
  feed shape changed   → keep last good, `data_check: true` + reason, retry in 10 min
  enrichment failure   → fixtures unaffected; crests fall back to initials
"""
import datetime as dt
import json
import logging
import os
import threading
import time

from flask import Flask, jsonify, request

from . import config, normalise
from .errors import ShapeError, SourceUnavailable
from .model import Fixture
from .sources import club_wp

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

app = Flask(__name__)

LAST_GOOD_FILE = os.path.join(config.CACHE_DIR, "last_good.json")
_lock = threading.Lock()


def _blank_state() -> dict:
    return {"fixtures": None, "counts": {}, "fetched_at": 0.0, "good_at": 0.0,
            "season_status": {}, "warnings": [], "enrich_ok": None,
            "stale": False, "data_check": None, "last_error": None, "loaded": False}


_state = _blank_state()


def _load_last_good() -> None:
    try:
        with open(LAST_GOOD_FILE) as fh:
            d = json.load(fh)
        _state["fixtures"] = [Fixture.from_json(x) for x in d["fixtures"]]
        _state["counts"] = d.get("counts", {})
        _state["good_at"] = d.get("saved_at", 0.0)
        log.info("loaded last good: %d fixtures", len(_state["fixtures"]))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("last-good file unreadable, ignoring: %s", exc)


def _save_last_good() -> None:
    try:
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        tmp = LAST_GOOD_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"saved_at": _state["good_at"], "counts": _state["counts"],
                       "fixtures": [f.to_json() for f in _state["fixtures"]]}, fh)
        os.replace(tmp, LAST_GOOD_FILE)
    except OSError as exc:
        log.warning("could not persist last-good fixtures: %s", exc)


def refresh_if_due(now: dt.datetime | None = None, force: bool = False) -> None:
    with _lock:
        if not _state["loaded"]:
            _load_last_good()
            _state["loaded"] = True
        age = time.time() - _state["fetched_at"]
        if not force and _state["fetched_at"] and age < config.CACHE_TTL:
            return
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            res = club_wp.fetch(now, _state["counts"])
        except SourceUnavailable as exc:
            log.error("source unavailable, serving last good: %s", exc)
            _state.update(stale=True, last_error=str(exc))
            _state["fetched_at"] = time.time() - config.CACHE_TTL + config.RETRY_AFTER_FAIL
            return
        except ShapeError as exc:
            log.error("DATA CHECK — feed shape changed, serving last good: %s", exc)
            _state.update(data_check=str(exc), last_error=str(exc))
            _state["fetched_at"] = time.time() - config.CACHE_TTL + config.RETRY_AFTER_FAIL
            return
        except Exception as exc:  # noqa: BLE001 — a parser bug must not blank the wall
            log.exception("unexpected failure parsing the feed")
            _state.update(data_check=f"unexpected: {exc}", last_error=repr(exc))
            _state["fetched_at"] = time.time() - config.CACHE_TTL + config.RETRY_AFTER_FAIL
            return

        _state.update(fixtures=res.fixtures, counts=res.counts,
                      season_status=res.season_status, warnings=res.warnings,
                      enrich_ok=res.enrich_ok, stale=False, data_check=None,
                      last_error=None, fetched_at=time.time(), good_at=time.time())
        _save_last_good()


def _sources() -> dict:
    return {
        "fixtures": "stub" if config.FIXTURES_SOURCE == "stub" else "club-ical",
        "enrich": {True: "club-json", False: "failed", None: "off"}[_state["enrich_ok"]],
        "broadcast": "rights-map",
    }


def _now_override() -> dt.datetime | None:
    """?now=2026-10-24T15:00:00Z — stub mode only, for forcing states."""
    raw = request.args.get("now")
    if not raw or config.FIXTURES_SOURCE != "stub":
        return None
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


@app.get("/fixtures")
def fixtures():
    now = _now_override()
    refresh_if_due(now)
    if _state["fixtures"] is None:
        return jsonify({"stale": True, "data_check": _state["data_check"] is not None,
                        "data_check_reason": _state["data_check"], "next": None,
                        "on_deck": [], "error": "no fixture data available yet",
                        "last_error": _state["last_error"]}), 503
    too_old = _state["good_at"] and time.time() - _state["good_at"] > config.CACHE_TTL * 2
    payload = normalise.build_payload(
        _state["fixtures"], now,
        stale=_state["stale"] or _state["data_check"] is not None or bool(too_old),
        data_check=_state["data_check"], sources=_sources())
    return jsonify(payload)


@app.get("/healthz")
def healthz():
    refresh_if_due()
    fx = _state["fixtures"]
    return jsonify({
        "ok": fx is not None and _state["data_check"] is None,
        "fixtures_cached": None if fx is None else len(fx),
        "last_good_age_s": int(time.time() - _state["good_at"]) if _state["good_at"] else None,
        "stale": _state["stale"],
        "data_check": _state["data_check"],
        "last_error": _state["last_error"],
        "season_counts": _state["counts"],
        "season_status": _state["season_status"],
        "enrich": _sources()["enrich"],
        "warnings": _state["warnings"][-20:],
        "source": config.FIXTURES_SOURCE,
        "team": config.TEAM_NAME,
        "euro_tier": config.EURO_TIER,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "3459")))
