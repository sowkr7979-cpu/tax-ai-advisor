"""src/ai/chroma_backend.py — local embedded Chroma vector backend (docs/07).

This is the ADAPTER seam for a real vector DB. The deterministic isolation logic
lives in src/vector_store.py (a pure-Python store) so slice-⑥ tests never need
Chroma. A Chroma-backed store MUST preserve the SAME isolation contract:
SHARED ⟂ TENANT physical separation + mandatory tenant filter (SEC-002/003).
"""

from __future__ import annotations

from typing import Optional

from .base import AdapterConfigError


class ChromaBackend:
    """# TODO(API-vectordb / SEC-003): wire chromadb PersistentClient.
    # Map each TENANT client_id to its OWN collection (namespace) and SHARED
    # reference knowledge to a SEPARATE read-only collection. Path/settings from
    # infra/config/vendors.yaml. The isolation contract is identical to
    # src.vector_store.DeterministicVectorStore — see that module for the rules.
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self.persist_dir = persist_dir

    def _client(self):  # pragma: no cover - real wiring
        try:
            import chromadb  # noqa: F401
        except ImportError as exc:
            raise AdapterConfigError(
                "chromadb not installed (pip install 'tiw[adapters]'). "
                "Slice ⑥ uses src.vector_store.DeterministicVectorStore instead."
            ) from exc
        raise AdapterConfigError("ChromaBackend not yet wired (SEC-003 namespace map TODO).")
