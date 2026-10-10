"""Evidence sources: fixtures loader and the GitHub code-search live source."""

from __future__ import annotations

import json
from pathlib import Path

from hunter.models import Fixtures


def load_fixtures(path: str | Path = "data/fixtures.json") -> Fixtures:
    with open(path) as f:
        raw = json.load(f)
    return Fixtures.model_validate(raw)
