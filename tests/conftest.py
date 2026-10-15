"""Stub-driven test setup. Stubs in tests/fixtures/ are REAL responses saved
from the NAS on 14–15 Oct 2026 (Phase 1). Run: python -m pytest -q"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ["FIXTURES_SOURCE"] = "stub"
os.environ["STUB_DIR"] = os.path.join(HERE, "fixtures")
os.environ["CACHE_DIR"] = tempfile.mkdtemp(prefix="trf-cache-")
os.environ.setdefault("TEAM_NAME", "Bristol Bears")
os.environ.setdefault("EURO_TIER", "champions")
