"""src/internal_rag.py — internal RAG pipeline (channel ②, docs/05).

The 10-step pipeline (docs/05 §2) made concrete:
  ① 수집 → ② 분류 → ③ 구조분할(src.chunking) → ④ 메타추출 → ⑤ 임베딩(CachedEmbedder
  → local model2vec) → ⑥ 적재(ChromaVectorStore: 테넌트 격리 색인, SEC-003) →
  ⑦ 하이브리드 회수(dense + BM25 키워드, RRF + 시점필터 RAG-005) → (⑧ rerank: parent
  확장) → ⑨ 인용근거 답변(slice① 생성기 재사용 — 회수된 PUBLIC 조문에만 grounding) →
  ⑩ RetrievalRun 로깅(RAG-013 재현성).

ISOLATION: the index is ``ChromaVectorStore`` — client material lives in physically
separate tenant collections; the retriever adds NO masking filter that could hide a
leak (docs/06⑥ lesson). Both the dense (Chroma collections) and the sparse (BM25
over ``scoped_item_ids``) sides go through the store's single candidate chokepoint,
so a broken store leaks BOTH and the harness catches it.

SEND-BOUNDARY (SEC / API-005): the citation-grounded answer grounds ONLY on the
retrieved PUBLIC (L0) 조문 text + the user's question — the client memo is used for
retrieval/isolation but is NEVER sent to the external LLM.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from contract.base import BasisKind, IndexScope, SourceType
from contract.cluster_f_qa import RetrievalRun
from src.ai.chroma_backend import ChromaVectorStore
from src.ai.law_data_source import ProvisionLookupResult
from src.ai.llm_client import LLMClient
from src.chunking import RagChunk
from src.isolation import TenantScope
from src.legal_research import ResearchLiteAnswer, generate_research_answer
from src.retrieval import RetrievedHit, count_cross_tenant_leakage
from src.source_registry import SourceRegistry

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_RRF_K = 60


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _rrf(ranked_lists: list[list[str]], k: int = _RRF_K) -> list[str]:
    """Reciprocal Rank Fusion (docs/05 §9): merge dense + sparse rankings.
    score(id) = Σ 1/(k + rank). Higher = better. Stable tie-break by id."""
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked):
            scores[item_id] += 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


# --------------------------------------------------------------------------- #
# Retrieval value objects
# --------------------------------------------------------------------------- #
@dataclass
class RetrievedChunk:
    chunk_id: str
    owner_client_id: Optional[str]
    scope: IndexScope
    score: float
    chunk: RagChunk

    def as_hit(self) -> RetrievedHit:
        return RetrievedHit(
            doc_id=self.chunk_id,
            owner_client_id=self.owner_client_id,
            scope=self.scope,
            score=self.score,
        )


@dataclass
class RagAnswer:
    retrieved: list[RetrievedChunk]
    retrieval_run: RetrievalRun
    candidate_ids: list[str]
    grounded: bool
    answer: Optional[ResearchLiteAnswer] = None
    grounding_lookup: Optional[ProvisionLookupResult] = None
    registry: SourceRegistry = field(default_factory=SourceRegistry)


# --------------------------------------------------------------------------- #
# The index + hybrid retriever
# --------------------------------------------------------------------------- #
class InternalRagIndex:
    """Tenant-isolated hybrid index over ``RagChunk``s."""

    def __init__(self, store: Optional[ChromaVectorStore] = None) -> None:
        self._store = store or ChromaVectorStore()
        self._chunks: dict[str, RagChunk] = {}

    @property
    def store(self) -> ChromaVectorStore:
        return self._store

    # -- ingest (③④⑤⑥) ---------------------------------------------------- #
    def ingest(self, chunks: list[RagChunk]) -> None:
        _assign_temporal_windows(chunks)
        for ch in chunks:
            self._store.add(
                ch.chunk_id,
                ch.text,
                ch.confidentiality_level,
                ch.client_id,
                effective_from=ch.effective_from,
                effective_to=ch.effective_to,
                doc_type=ch.doc_type,
                parent_id=ch.parent_id,
            )
            self._chunks[ch.chunk_id] = ch

    # -- hybrid retrieval (⑦⑧) ------------------------------------------- #
    def retrieve(
        self, scope: TenantScope, query: str, as_of: date, top_k: int = 5
    ) -> tuple[list[RetrievedChunk], list[str]]:
        pool = max(top_k * 3, top_k + 4)
        dense = self._store.search(scope, query, top_k=pool, as_of=as_of)
        dense_ids = [s.item_id for s in dense]
        meta = {s.item_id: s for s in dense}

        scoped_ids = self._store.scoped_item_ids(scope, as_of)
        sparse_ids = self._bm25(query, scoped_ids, top_k=pool)

        fused = _rrf([dense_ids, sparse_ids])
        candidate_ids = list(fused)

        # parent expansion (docs/05 §5): a child hit pulls in its parent 조문; we
        # then dedupe to the retrieval UNIT (parent for law, self for memos).
        seen: list[str] = []
        for cid in fused:
            ch = self._chunks.get(cid)
            unit_id = ch.parent_id if (ch and ch.parent_id) else cid
            if unit_id not in seen:
                seen.append(unit_id)

        hits: list[RetrievedChunk] = []
        for uid in seen[:top_k]:
            ch = self._chunks.get(uid)
            if ch is None:
                continue
            owner = ch.client_id
            scope_kind = IndexScope.TENANT if ch.client_id else IndexScope.SHARED
            score = meta[uid].score if uid in meta else 0.0
            hits.append(RetrievedChunk(uid, owner, scope_kind, score, ch))
        return hits, candidate_ids

    def _bm25(self, query: str, scoped_ids: set[str], top_k: int) -> list[str]:
        docs = [(cid, _tokenize(self._chunks[cid].text)) for cid in scoped_ids if cid in self._chunks]
        if not docs:
            return []
        n = len(docs)
        avgdl = sum(len(toks) for _, toks in docs) / n
        df: dict[str, int] = defaultdict(int)
        for _, toks in docs:
            for t in set(toks):
                df[t] += 1
        q_terms = set(_tokenize(query))
        k1, b = 1.5, 0.75
        scores: list[tuple[str, float]] = []
        for cid, toks in docs:
            if not toks:
                scores.append((cid, 0.0))
                continue
            tf: dict[str, int] = defaultdict(int)
            for t in toks:
                tf[t] += 1
            dl = len(toks)
            s = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                s += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
            scores.append((cid, s))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return [cid for cid, sc in scores if sc > 0][:top_k]

    # -- citation-grounded answer (⑨⑩) ---------------------------------- #
    def answer(
        self,
        *,
        question_text: str,
        scope: TenantScope,
        as_of: date,
        basis_kind: BasisKind = BasisKind.FISCAL_YEAR,
        source_answer_id: str,
        answer_run_id: str,
        run_id: str,
        high_risk: bool = False,
        source_type_label: str = "법률",
        top_k: int = 5,
        llm_client: Optional[LLMClient] = None,
        registry: Optional[SourceRegistry] = None,
    ) -> RagAnswer:
        hits, candidate_ids = self.retrieve(scope, question_text, as_of, top_k=top_k)
        run = RetrievalRun(
            run_id=run_id,
            source_answer_id=source_answer_id,
            client_id=scope.client_id,                 # isolation key propagated
            subqueries=[question_text],
            filters={
                "tenant_scope": scope.client_id,        # SEC-002: always present
                "include_shared": scope.include_shared,
                "as_of_date": as_of.isoformat(),        # RAG-005 시점 필터
                "top_k": top_k,
                "hybrid": "dense(model2vec)+bm25(rrf)",
            },
            candidate_chunk_ids=candidate_ids,
            selected_chunk_ids=[h.chunk_id for h in hits],
        )
        reg = registry or SourceRegistry()

        # ground on the top retrieved PUBLIC 조문 (parent law chunk with a lookup)
        law_hit = next(
            (h for h in hits if h.chunk.is_law and h.chunk.is_parent and h.chunk.lookup),
            None,
        )
        if law_hit is None:
            # no groundable provision retrieved → abstain (no fabricated citation)
            return RagAnswer(
                retrieved=hits, retrieval_run=run, candidate_ids=candidate_ids,
                grounded=False, registry=reg,
            )

        lookup = law_hit.chunk.lookup
        # The generator SELF-VERIFIES against its own bundle (registry=None); the
        # harness/caller registry is populated AFTER, for tamper/verification checks
        # — passing an empty registry in would falsely flag the real citation.
        answer = generate_research_answer(
            lookup=lookup,
            question_text=question_text,
            client_id=scope.client_id,
            answer_run_id=answer_run_id,
            source_answer_id=source_answer_id,
            source_type_label=source_type_label,
            high_risk=high_risk,
            answer_source_type=SourceType.INTERNAL_RAG,   # channel ② (docs/05 §11)
            channel_label="②",
            retrieval_run_id=run.run_id,
            basis_kind=basis_kind,
            llm_client=llm_client,
        )
        reg.register_all(answer.bundle.source_objects)
        return RagAnswer(
            retrieved=hits, retrieval_run=run, candidate_ids=candidate_ids,
            grounded=True, answer=answer, grounding_lookup=lookup, registry=reg,
        )

    # -- leakage metric (reuses slice⑥ pure function) -------------------- #
    @staticmethod
    def leakage(scope: TenantScope, hits: list[RetrievedChunk], forbidden: list[str]) -> int:
        return count_cross_tenant_leakage(scope, [h.as_hit() for h in hits], forbidden)


# --------------------------------------------------------------------------- #
# Temporal window assignment (RAG-005): same 조문, 다른 시행일 버전 → 닫힌 구간
# --------------------------------------------------------------------------- #
def _assign_temporal_windows(chunks: list[RagChunk]) -> None:
    """For overlapping versions of the same 조문, set each version's
    ``effective_to`` to the NEXT version's ``effective_from`` (exclusive), so the
    temporal filter selects exactly the version in force at the as-of date."""
    by_article: dict[tuple, list[RagChunk]] = defaultdict(list)
    for ch in chunks:
        if ch.is_law and ch.effective_from is not None:
            by_article[(ch.law_name, ch.article_label)].append(ch)

    for _, group in by_article.items():
        # distinct effective_from values, sorted
        efs = sorted({c.effective_from for c in group})
        if len(efs) < 2:
            continue
        nxt = {efs[i]: efs[i + 1] for i in range(len(efs) - 1)}
        for ch in group:
            successor = nxt.get(ch.effective_from)
            if successor is not None and (
                ch.effective_to is None or ch.effective_to > successor
            ):
                ch.effective_to = successor
