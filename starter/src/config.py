"""Shared paths and settings for the Day 06 pipeline."""
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"
BENCHMARK = ROOT / "benchmark"
RESULTS = ROOT / "results"
