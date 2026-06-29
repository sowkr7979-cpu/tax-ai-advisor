"""Ensure the Workpaper-2120 repo root is importable even without `pip install -e .`
(so `contract`, `src`, `rules`, `tiw` resolve when running `pytest` directly)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
