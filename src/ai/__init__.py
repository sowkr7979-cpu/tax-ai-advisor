"""src/ai/ — external adapters (CLIENTS ONLY). docs/README §2 boundary rule.

No RAG orchestration or isolation logic here — that lives in src/ (deterministic).
Every adapter ships a deterministic fallback or a TODO real-wiring point so the
slice-⑥ harness runs with NO API keys.
"""

from __future__ import annotations

from .base import AdapterConfigError, Embedder  # noqa: F401
from .embedding_client import (  # noqa: F401
    DeterministicFakeEmbedder,
    RealEmbeddingClient,
    default_embedder,
)
from .llm_client import LLMClient, LLMConfig  # noqa: F401
from .reranker_client import RerankerClient  # noqa: F401
from .korean_law_mcp_client import KoreanLawMCPClient  # noqa: F401
from .tavily_client import TavilyClient  # noqa: F401
from .brave_client import BraveClient  # noqa: F401
from .dart_client import DartClient  # noqa: F401
from .ocr_client import OcrClient  # noqa: F401
from .docx_client import DocxClient  # noqa: F401
from .chroma_backend import ChromaBackend  # noqa: F401
