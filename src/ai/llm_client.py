"""src/ai/llm_client.py — LLM adapter (docs/07). Default model: claude-opus-4-8.

Interface + real wiring point. Deterministic tests do NOT call an LLM (slice ⑥ is
fully deterministic). Synthesis/judge slices will wire this later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import AdapterConfigError


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"   # docs/07 default LLM
    max_tokens: int = 4096
    temperature: float = 0.0


class LLMClient:
    """Anthropic-by-default LLM client.

    # TODO(API-001 LLM): wire `anthropic` SDK. Read model from
    # infra/config/vendors.yaml; key from env (ANTHROPIC_API_KEY), never code.
    # Enforce docs/01 §8 (non-training, masking, confidentiality_level gating)
    # BEFORE sending any L3/L4 context.
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig()

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - real wiring
        raise AdapterConfigError(
            "LLMClient is not wired (no key/config). Slice ⑥ does not require an LLM."
        )
