"""rules/ — decision rules (docs/README §2): 세무 한도·source-priority·conflict·
web policy·hard gates. Frozen rubric constants live in rules.hard_gates."""

from __future__ import annotations

from .hard_gates import (  # noqa: F401
    COMPLETION_THRESHOLD,
    DIMENSION_WEIGHTS,
    HARD_GATES,
    SCORE_BUCKETS,
    HardGate,
    tightest_cap,
)
