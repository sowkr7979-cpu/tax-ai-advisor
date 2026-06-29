"""src/ai/embedding_client.py — embedding adapter (docs/07 API; RAG embeddings).

DeterministicFakeEmbedder: a hash-based bag-of-words embedder. It needs NO API key
and is fully deterministic, so the slice-⑥ isolation harness can verify the
ISOLATION logic (which docs go in which index, which are retrievable) without
depending on any real embedding provider.

Real LOCAL on-prem embedder (slice ②): ``Model2VecEmbedder`` wraps a static
multilingual model (model2vec, default ``minishlab/potion-multilingual-128M``).
It is **on-prem** (the model weights are downloaded once and run locally with NO
external API call — so L3/L4 client chunks are NEVER sent to a third party, SEC),
torch-free, and deterministic. e5/sentence-transformers was the first choice but
torch has no wheel for this interpreter; model2vec is the sanctioned static
fallback (PROMPT.md 임베딩 §). The model name lives in infra/config/vendors.yaml.

CI DETERMINISM (record/replay): ``CachedEmbedder`` records every vector it computes
to ``tests/fixtures/embeddings/`` and REPLAYS from there with NO model and NO
torch. A missing key or a tampered cache is FAIL-CLOSED (``EmbeddingUnavailable`` /
``EmbeddingNotReproducible``) — never a silent zero-vector (docs/09 §6, PROMPT.md).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Optional

from .base import AdapterConfigError, Embedder

# repo root = .../src/ai/embedding_client.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EMB_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "embeddings"

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)  # \w includes Hangul under re.UNICODE


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class DeterministicFakeEmbedder:
    """Hashing bag-of-words → fixed-dim L2-normalized vector.

    Deterministic across runs/processes (uses a stable hash, not Python's salted
    hash). Two texts that share tokens get higher cosine similarity — enough to
    exercise retrieval/recall in the isolation harness without a real model.
    """

    model_name = "fake-deterministic-bow-v1"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    @staticmethod
    def _stable_hash(token: str) -> int:
        # FNV-1a (stable, unsalted) — reproducible across processes.
        h = 0x811C9DC5
        for ch in token.encode("utf-8"):
            h ^= ch
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for tok in _tokenize(text):
            idx = self._stable_hash(tok) % self.dimension
            sign = 1.0 if (self._stable_hash(tok + "#sign") & 1) else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


# --------------------------------------------------------------------------- #
# Embedding config (infra/config/vendors.yaml: embedding.*)
# --------------------------------------------------------------------------- #
def load_embedding_config(path: Optional[Path] = None) -> dict:
    """Load embedding.* from vendors.yaml (model name never hardcoded in code)."""
    path = path or (_REPO_ROOT / "infra" / "config" / "vendors.yaml")
    defaults = {
        "provider": "model2vec",
        "model": "minishlab/potion-multilingual-128M",
        "dimension": 256,
    }
    try:
        import yaml  # lazy: pyyaml is a core dep
    except ImportError:  # pragma: no cover
        return defaults
    if not path.exists():  # pragma: no cover
        return defaults
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("embedding", {})
    return {**defaults, **{k: v for k, v in data.items() if v not in (None, "TODO")}}


# --------------------------------------------------------------------------- #
# Errors (fail-closed surface)
# --------------------------------------------------------------------------- #
class EmbeddingUnavailable(RuntimeError):
    """Real model not available / vector not recorded → fail-closed (not a pass)."""


class EmbeddingNotReproducible(RuntimeError):
    """Recorded embedding cache no longer hashes to its stored value (tamper)."""


# --------------------------------------------------------------------------- #
# Real LOCAL on-prem embedder (model2vec static multilingual)
# --------------------------------------------------------------------------- #
class Model2VecEmbedder:
    """Static multilingual sentence embedder (model2vec) — LOCAL, torch-free.

    Runs entirely on-prem: weights are fetched once to the local HF cache and all
    inference is in-process (no API). L3/L4 client text can therefore be embedded
    WITHOUT leaving the machine (SEC). Deterministic (static lookup + pooling), so
    a recorded vector replays bit-identically.

    Heavy import (model2vec) is lazy — only the one-time RECORD path pays for it;
    tests/CI use ``CachedEmbedder`` replay and never import model2vec."""

    def __init__(self, model_name: Optional[str] = None, dimension: Optional[int] = None) -> None:
        cfg = load_embedding_config()
        self.model_name = model_name or cfg["model"]
        self.dimension = int(dimension or cfg["dimension"])
        self._model = None

    def _load(self):  # pragma: no cover - heavy, record-time only
        if self._model is None:
            try:
                from model2vec import StaticModel
            except ImportError as exc:
                raise EmbeddingUnavailable(
                    "model2vec not installed (pip install 'tiw[adapters]'); needed only "
                    "to RECORD embedding fixtures — tests replay from tests/fixtures/embeddings/."
                ) from exc
            self._model = StaticModel.from_pretrained(self.model_name)
            self.dimension = int(self._model.dim)
        return self._model

    def embed(self, text: str) -> list[float]:  # pragma: no cover - record-time only
        model = self._load()
        vec = model.encode([text])[0]
        return _l2_normalize([float(x) for x in vec.tolist()])


# --------------------------------------------------------------------------- #
# Record / replay cache (CI determinism without torch/model)
# --------------------------------------------------------------------------- #
_EMB_ROUND = 6  # decimals — keeps the committed cache small + reproducible


class CachedEmbedder:
    """Record/replay wrapper around a real embedder (mirrors law/LLM fixtures).

    * REPLAY (default): resolves each text → its recorded vector from
      ``tests/fixtures/embeddings/manifest.json`` (NO model, NO torch). A text
      with no recorded vector raises ``EmbeddingUnavailable`` and a tampered cache
      raises ``EmbeddingNotReproducible`` — both FAIL-CLOSED (never a silent
      zero-vector that would fake retrieval signal).
    * RECORD: computes via the real ``backend`` (Model2VecEmbedder) and appends to
      the cache. Used once by scripts/record_rag_fixtures.py.

    Key = sha256(model_name \\x00 text) so the SAME text deterministically resolves
    to the SAME vector. Satisfies the ``Embedder`` protocol (dimension/model_name/
    embed) so it is a drop-in for the vector store + Chroma backend."""

    def __init__(
        self,
        fixtures_dir: Path = DEFAULT_EMB_FIXTURES_DIR,
        backend: Optional[Embedder] = None,
        record: bool = False,
    ) -> None:
        self._dir = Path(fixtures_dir)
        self._manifest_path = self._dir / "manifest.json"
        self._record = record
        self._backend = backend
        cfg = load_embedding_config()
        self.model_name = cfg["model"]
        self.dimension = int(cfg["dimension"])
        self._vectors: dict[str, list[float]] = {}
        if self._manifest_path.exists():
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            self.model_name = data.get("model", self.model_name)
            self.dimension = int(data.get("dimension", self.dimension))
            stored = data.get("vectors", {})
            digest = _vectors_hash(self.model_name, self.dimension, stored)
            if digest != data.get("content_hash"):
                raise EmbeddingNotReproducible(
                    f"embedding cache {self._manifest_path.name} hash mismatch — "
                    f"refusing tampered replay (fail-closed)"
                )
            self._vectors = {k: list(map(float, v)) for k, v in stored.items()}
        elif not record:
            # No cache at all → replay cannot proceed (fail-closed, not silent pass).
            pass

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_name}\x00{text}".encode("utf-8")).hexdigest()

    def embed(self, text: str) -> list[float]:
        key = self._key(text)
        cached = self._vectors.get(key)
        if cached is not None:
            return cached
        if not self._record:
            raise EmbeddingUnavailable(
                f"no recorded embedding for text key {key[:12]}… "
                f"(run scripts/record_rag_fixtures.py once to record it). Fail-closed."
            )
        if self._backend is None:  # pragma: no cover - guarded by record path
            raise EmbeddingUnavailable("record mode requires a real backend embedder")
        vec = [round(float(x), _EMB_ROUND) for x in self._backend.embed(text)]  # pragma: no cover
        self.dimension = len(vec)  # pragma: no cover
        self._vectors[key] = vec  # pragma: no cover
        return vec  # pragma: no cover

    def save(self) -> None:  # pragma: no cover - record-time only
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model_name,
            "dimension": self.dimension,
            "vectors": self._vectors,
            "content_hash": _vectors_hash(self.model_name, self.dimension, self._vectors),
        }
        self._manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._vectors)


def _vectors_hash(model: str, dimension: int, vectors: dict) -> str:
    body = json.dumps(
        {"model": model, "dimension": dimension, "vectors": vectors},
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class RealEmbeddingClient(Model2VecEmbedder):
    """Back-compat alias for the real local embedder (was a TODO stub).

    The wiring is now real: a local static multilingual model (model2vec). Tests
    never touch it — they replay ``CachedEmbedder`` fixtures."""


def default_embedder() -> Embedder:
    """Hermetic default for the slice-⑥ isolation harness (no model/torch)."""
    return DeterministicFakeEmbedder()


def default_rag_embedder(fixtures_dir: Path = DEFAULT_EMB_FIXTURES_DIR) -> CachedEmbedder:
    """Hermetic REAL-embedding replay client for slice ② (fail-closed on miss)."""
    return CachedEmbedder(fixtures_dir=fixtures_dir, record=False)
