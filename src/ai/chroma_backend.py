"""src/ai/chroma_backend.py — Chroma vector backend with PHYSICAL tenant isolation.

Real wiring of the slice-⑥ isolation contract onto chromadb (SEC-003 / RAG-007,
codex slice⑥ P2-1):

  * each TENANT ``client_id`` → its OWN collection (``tenant_<id>``);
  * SHARED reference knowledge → a SEPARATE collection (``shared_reference``);
  * a query for scope A iterates ONLY {A's tenant collection} ∪ {SHARED?} — B's
    collection is a different physical collection that is never named, so a B
    document cannot be returned to A.

ISOLATION IS STRUCTURAL, NOT A QUERY FLAG (SEC-002): ``search`` REQUIRES a
``TenantScope`` and the candidate-collection set is the single chokepoint
(``_candidate_collections``) that BOTH dense search and the sparse-candidate
helper go through. There is no overload that searches across all tenants. The
filter cannot be turned off; the routing on ingest reuses the SAME pure rules as
the deterministic store (``src.isolation.classify_target_scope``).

ON-PREM EMBEDDING: vectors are computed by the injected ``Embedder``
(``CachedEmbedder`` → local model2vec) and passed to Chroma EXPLICITLY — Chroma's
own (external-ish) default embedder is never used, so L3/L4 client text is never
embedded by anything but the local model (SEC).

persist_dir defaults to ``.chroma`` (gitignored runtime data). For determinism the
harness gives EACH store its OWN throwaway PersistentClient (a unique temp dir →
a unique Rust system), instead of chromadb's process-GLOBAL EphemeralClient whose
shared in-memory system accumulated state across cases and corrupted its segment
cache ("Error finding id") depending on test order. ``close()`` stops the system
and deletes the dir, so there is zero cross-case residue (see ``__init__``).
"""

from __future__ import annotations

import atexit
import gc
import shutil
import sys
import tempfile
import uuid
from datetime import date
from typing import Optional

from contract.base import ConfidentialityLevel, IndexScope
from src.ai.base import Embedder
from src.ai.embedding_client import default_rag_embedder
from src.isolation import IngestTarget, IsolationError, TenantScope, classify_target_scope
from src.vector_store import ScoredItem

_OPEN_EF = 99991231
_SHARED_OWNER = "__shared__"


def _raise_file_handle_limit() -> None:
    """Give chromadb's Rust HNSW backend file-handle headroom (the OTHER half of
    the flaky-isolation fix).

    chromadb sizes its per-collection HNSW file-handle cache as
    ``_getmaxstdio() // 5`` on Windows and opens several files per collection.
    Across a test run the harness churns through many short-lived collections;
    with the C-runtime default of 512 stdio handles, leaked/slow-released handles
    accumulate and the next segment open fails non-deterministically with
    ``InternalError: Error creating hnsw segment read`` / ``Error finding id`` —
    the order-dependent flake. Raise the per-process stdio limit ONCE, as high as
    this CRT accepts (2048 is the practical cap; 4096/8192 are rejected → -1).
    Best-effort and Windows-only; a no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        msvcrt = ctypes.CDLL("msvcrt")
        for target in (8192, 4096, 2048):
            if msvcrt._getmaxstdio() >= target:
                return
            if msvcrt._setmaxstdio(target) == target:
                return
    except Exception:  # noqa: BLE001 - never fail import over a tuning knob
        pass


_raise_file_handle_limit()


class ChromaVectorStore:
    """Chroma-backed, isolation-preserving vector store (mirrors
    ``DeterministicVectorStore``'s interface so ``IsolatedRetriever`` works
    unchanged)."""

    # Auto-created (temp-dir) stores register here so a test teardown / atexit can
    # deterministically stop their Rust systems and delete their dirs. Because each
    # such store owns a SEPARATE system, nothing survives a case → no cross-order
    # state can leak (the root cause of the flaky "Error finding id").
    _AUTO_STORES: "list[ChromaVectorStore]" = []

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        *,
        persist_dir: Optional[str] = None,
        client: Optional[object] = None,
        shared_collection: str = "shared_reference",
        tenant_prefix: str = "tenant_",
        namespace: Optional[str] = None,
    ) -> None:
        # NB: use `is not None` (not `or`) — a fresh CachedEmbedder is empty and
        # therefore falsy via __len__, which would wrongly swap in the default.
        self._embedder = embedder if embedder is not None else default_rag_embedder()
        # A per-instance collection ``namespace`` (uuid by default) keeps each
        # store's collections uniquely named — defence-in-depth that preserves the
        # SHARED ⟂ tenant_<id> contract under ANY client.
        ns = namespace if namespace is not None else f"ns_{uuid.uuid4().hex[:8]}_"
        self._shared_name = f"{ns}{shared_collection}"
        self._tenant_prefix = f"{ns}{tenant_prefix}"
        self._space = {"hnsw:space": "cosine"}
        self._temp_dir: Optional[str] = None
        self._closed = False
        if client is not None:
            # caller-managed client — its lifecycle is the caller's responsibility.
            self._client = client
        elif persist_dir is not None:
            self._client = self._build_client(persist_dir)
        else:
            # DEFAULT — and the FIX for the flaky cross-case "Error finding id":
            # chromadb's EphemeralClient is a PROCESS-GLOBAL singleton — its system
            # identifier is the constant "ephemeral", so every in-memory client
            # shares ONE Rust system (see chromadb shared_system_client). State from
            # earlier stores/cases accumulated there and corrupted its segment cache
            # depending on test order. A PersistentClient's system identifier is its
            # PATH, so a UNIQUE throwaway temp dir gives each store its OWN, fully
            # isolated Rust system + sqlite. ``close()`` stops that system and deletes
            # the dir — zero residue, deterministic across any order/repeat.
            self._temp_dir = tempfile.mkdtemp(prefix="chroma_tiw_")
            self._client = self._build_client(self._temp_dir)
            ChromaVectorStore._AUTO_STORES.append(self)

    @staticmethod
    def _build_client(persist_dir: str):
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover - adapters extra
            from .base import AdapterConfigError

            raise AdapterConfigError(
                "chromadb not installed (pip install 'tiw[adapters]')."
            ) from exc
        # allow_reset → close() may wipe defensively; telemetry off for hermetic runs.
        return chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(allow_reset=True, anonymized_telemetry=False),
        )

    # -- lifecycle / deterministic teardown -------------------------------- #
    def close(self) -> None:
        """Stop this store's Chroma system and delete its temp dir (idempotent).

        Only auto-created (temp-dir) clients are torn down here; an injected
        ``client`` or explicit ``persist_dir`` is left to the caller."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        if getattr(self, "_temp_dir", None) is not None:
            close = getattr(getattr(self, "_client", None), "close", None)
            if callable(close):
                try:
                    close()  # decrements refcount → stops the per-path Rust system
                except Exception:  # noqa: BLE001 - teardown must never raise
                    pass
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        try:
            ChromaVectorStore._AUTO_STORES.remove(self)
        except ValueError:
            pass

    @classmethod
    def close_all(cls) -> None:
        """Tear down every still-open auto-created store (test teardown / atexit).

        The trailing ``gc.collect()`` is load-bearing: ``client.close()`` stops the
        system, but the Rust ``Bindings`` (which holds the open HNSW segment file
        handles) is only dropped when its Python wrapper is collected. chromadb's
        objects form reference cycles, so a refcount drop alone won't free them —
        forcing a collection here releases the handles PROMPTLY instead of letting
        them pile up across cases until a segment open fails."""
        for store in list(cls._AUTO_STORES):
            store.close()
        cls._AUTO_STORES.clear()
        gc.collect()

    def __del__(self):  # best-effort safety net if close() was never called
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # -- collection naming ------------------------------------------------- #
    def _tenant_name(self, client_id: str) -> str:
        return f"{self._tenant_prefix}{client_id}"

    def _get_or_create(self, name: str):
        return self._client.get_or_create_collection(name=name, metadata=self._space)

    def _get_existing(self, name: str):
        try:
            return self._client.get_collection(name=name)
        except Exception:  # noqa: BLE001 - collection absent
            return None

    # -- ingestion --------------------------------------------------------- #
    def add(
        self,
        item_id: str,
        text: str,
        confidentiality_level: ConfidentialityLevel,
        client_id: Optional[str] = None,
        *,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        doc_type: str = "",
        parent_id: Optional[str] = None,
        embedding: Optional[list[float]] = None,
    ) -> IngestTarget:
        """Route an item to its physically-separate collection (SEC-003). Raises
        ``IsolationError`` on a NULL isolation key for client material (SEC-001)."""
        target = classify_target_scope(confidentiality_level, client_id)
        if target.scope is IndexScope.TENANT:
            assert target.client_id is not None
            col = self._get_or_create(self._tenant_name(target.client_id))
            owner = target.client_id
        else:
            col = self._get_or_create(self._shared_name)
            owner = _SHARED_OWNER
        meta = {
            "scope": target.scope.value,
            "owner": owner,
            "ef_from": int(effective_from.strftime("%Y%m%d")) if effective_from else 0,
            "ef_to": int(effective_to.strftime("%Y%m%d")) if effective_to else _OPEN_EF,
            "doc_type": doc_type or "",
            "parent_id": parent_id or "",
        }
        vec = embedding if embedding is not None else self._embedder.embed(text)
        col.add(ids=[item_id], embeddings=[vec], documents=[text], metadatas=[meta])
        return target

    # -- the single isolation chokepoint ----------------------------------- #
    def _candidate_collections(self, scope: TenantScope) -> list:
        """The ONLY collections a query may see (SEC-003). Overridable ONLY for an
        adversarial test that simulates a 'forgotten filter' — production never
        widens this. A different client's collection is never returned here."""
        cols = []
        tenant = self._get_existing(self._tenant_name(scope.client_id))
        if tenant is not None:
            cols.append(tenant)
        if scope.include_shared:
            shared = self._get_existing(self._shared_name)
            if shared is not None:
                cols.append(shared)
        return cols

    @staticmethod
    def _temporal_where(as_of: Optional[date]) -> Optional[dict]:
        """RAG-005: restrict the SEARCH SPACE to versions valid at ``as_of`` (a
        candidate-generation filter, not a post-rerank one)."""
        if as_of is None:
            return None
        a = int(as_of.strftime("%Y%m%d"))
        return {"$and": [{"ef_from": {"$lte": a}}, {"ef_to": {"$gt": a}}]}

    @staticmethod
    def _to_scope(value: str) -> IndexScope:
        return IndexScope.SHARED if value == IndexScope.SHARED.value else IndexScope.TENANT

    @staticmethod
    def _owner(meta: dict) -> Optional[str]:
        owner = meta.get("owner")
        return None if owner == _SHARED_OWNER else owner

    # -- retrieval (dense) ------------------------------------------------- #
    def search(
        self,
        scope: TenantScope,
        query: str,
        top_k: int = 5,
        *,
        as_of: Optional[date] = None,
        query_embedding: Optional[list[float]] = None,
    ) -> list[ScoredItem]:
        # SEC-002 격리필터 비활성 불가 — scope는 필수이며 타입을 우회할 수 없다.
        if not isinstance(scope, TenantScope):
            raise IsolationError(
                "SEC-002: search requires a TenantScope (filter cannot be omitted)"
            )
        qv = query_embedding if query_embedding is not None else self._embedder.embed(query)
        where = self._temporal_where(as_of)
        scored: list[ScoredItem] = []
        for col in self._candidate_collections(scope):
            n = min(top_k, col.count()) or 1
            res = col.query(query_embeddings=[qv], n_results=n, where=where)
            ids = (res.get("ids") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            for i, item_id in enumerate(ids):
                meta = metas[i] or {}
                scored.append(
                    ScoredItem(
                        item_id=item_id,
                        score=1.0 - float(dists[i]),     # cosine similarity
                        scope=self._to_scope(meta.get("scope", IndexScope.SHARED.value)),
                        owner_client_id=self._owner(meta),
                        text=docs[i] if i < len(docs) else "",
                    )
                )
        scored.sort(key=lambda s: (-s.score, s.item_id))
        return scored[:top_k]

    # -- scoped corpus for the sparse (BM25) side -------------------------- #
    def scoped_item_ids(self, scope: TenantScope, as_of: Optional[date] = None) -> set[str]:
        """Ids visible to ``scope`` (+ temporally valid) — for the keyword index.
        Goes through the SAME ``_candidate_collections`` chokepoint, so a leaky
        override leaks BOTH dense and sparse (the harness then catches it)."""
        if not isinstance(scope, TenantScope):
            raise IsolationError("SEC-002: scoped_item_ids requires a TenantScope")
        where = self._temporal_where(as_of)
        ids: set[str] = set()
        for col in self._candidate_collections(scope):
            got = col.get(where=where) if where else col.get()
            ids.update(got.get("ids") or [])
        return ids

    # -- introspection (tests / parity with DeterministicVectorStore) ------ #
    def tenant_ids(self) -> list[str]:
        out = []
        for c in self._client.list_collections():
            if c.name.startswith(self._tenant_prefix):
                out.append(c.name[len(self._tenant_prefix):])
        return sorted(out)

    def shared_count(self) -> int:
        shared = self._get_existing(self._shared_name)
        return shared.count() if shared is not None else 0


# Safety net: if the process exits without explicit teardown, stop any lingering
# auto-created systems and delete their temp dirs (no leaked sqlite/handles).
atexit.register(ChromaVectorStore.close_all)
