"""tiw.eval — the evaluation harness (Ralph-loop fitness function, docs/09).

This harness IS the score. Run it via `python -m tiw.eval [--slice N]`.
"""

from __future__ import annotations

from .runner import SliceReport, implemented_slices, run_all, run_slice  # noqa: F401
from .scorer import build_rubric_result, snap_to_bucket  # noqa: F401
