"""Ensure the Workpaper-2120 repo root is importable even without `pip install -e .`
(so `contract`, `src`, `rules`, `tiw` resolve when running `pytest` directly)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(autouse=True)
def _chroma_isolation_teardown():
    """Deterministically tear down every Chroma store created during a test.

    Each ``ChromaVectorStore`` defaults to its OWN temp-dir PersistentClient (a
    separate Rust system), so no in-memory/system state can survive into the next
    test — this kills the order-dependent, flaky ``InternalError: Error finding id``
    that came from chromadb's process-global EphemeralClient singleton. Stores
    self-register; we stop + delete them all here, after every test."""
    yield
    try:
        from src.ai.chroma_backend import ChromaVectorStore
    except Exception:  # noqa: BLE001 - chromadb not installed → nothing to clean
        return
    ChromaVectorStore.close_all()
