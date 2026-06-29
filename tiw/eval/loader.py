"""tiw/eval/loader.py — gold-set loading (docs/09 §6, §8; EVAL-004).

hidden freeze set / public practice set are loaded by SEPARATE functions from
SEPARATE directories. The implementation under src/ NEVER imports this module —
only the eval harness does — so implementation code cannot peek at gold answers
(anti-gaming: docs/09 §6, PROMPT.md §4).
"""

from __future__ import annotations

import json
from pathlib import Path

from contract.cluster_i_eval import EvaluationCase, Visibility

# repo root = .../tiw/eval/loader.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_DIR = _REPO_ROOT / "tests" / "golden" / "public"
_HIDDEN_DIR = _REPO_ROOT / "tests" / "golden" / "hidden"


def _load_dir(directory: Path, slice_no: int | None, visibility: Visibility) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    if not directory.exists():
        return cases
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        case = EvaluationCase.model_validate(raw)
        # defense: directory determines visibility (a file cannot mislabel itself)
        if case.visibility != visibility:
            raise ValueError(
                f"{path.name}: visibility {case.visibility} does not match its directory "
                f"({visibility}); freeze-set integrity (EVAL-004) requires dir==visibility"
            )
        if slice_no is None or case.slice == slice_no:
            cases.append(case)
    return cases


def load_public_cases(slice_no: int | None = None) -> list[EvaluationCase]:
    """Public practice set (rotating). Safe for implementers to inspect."""
    return _load_dir(_PUBLIC_DIR, slice_no, Visibility.PUBLIC)


def load_hidden_cases(slice_no: int | None = None) -> list[EvaluationCase]:
    """Hidden freeze set. Loaded ONLY by the harness at eval time; not imported by
    any src/ implementation module."""
    return _load_dir(_HIDDEN_DIR, slice_no, Visibility.HIDDEN)
