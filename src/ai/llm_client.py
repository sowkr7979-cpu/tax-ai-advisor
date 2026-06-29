"""src/ai/llm_client.py — Anthropic LLM adapter (docs/07, API-001/008).

Real Anthropic Messages API wiring (default model ``claude-opus-4-8``) behind a
RECORD/REPLAY transport seam, mirroring ``src/ai/law_data_source.py``:

  * ``ReplayLLMTransport``    — hermetic replay from ``tests/fixtures/llm/`` with
    NO network and NO API key. This is the DEFAULT used by tests/CI and by
    ``python -m tiw.eval``. A missing or hash-mismatched fixture is FAIL-CLOSED
    (``LLMUnavailable`` / ``LLMNotReproducible``) — never a silent pass
    (docs/09 §2, PROMPT.md §4-5).
  * ``RecordingLLMTransport`` — performs ONE live Anthropic call and records the
    response (text + ModelVersion + token usage + cost) to a fixture. Used only
    by ``scripts/record_llm_fixtures.py`` to seed fixtures
    (PROMPT.md: 라이브 호출은 녹화 목적 1회만).

ModelVersion / token / cost logging (docs/07 §2 observability): every
``LLMResponse`` carries the resolved ``model`` string the API actually served,
input/output token counts, and an estimated USD cost. Costs use the published
claude-opus-4-8 rate ($5 / $25 per 1M input/output tokens).

ZERO-RETENTION / confidentiality (docs/01 §8, API-005): the Anthropic API is
NOT zero-retention by default. Callers MUST enforce non-training / masking /
private-path policy BEFORE sending any L3/L4 (client-identifying) context. This
slice (① 법령 앵커) sends only L0 PUBLIC statute text + the user's legal
*question* — no client material — so the public path is policy-compliant here.
Do not route L3/L4 context through this default client without that gating.

API NOTE (claude-opus-4-8): the model REJECTS ``temperature``/``top_p``/``top_k``
(HTTP 400). Determinism for tests is provided by REPLAY of recorded fixtures, not
by a sampling temperature, so this adapter does not send a temperature. The
``temperature`` in ``infra/config/vendors.yaml`` records the *intended*
determinism and is carried on ``LLMConfig`` for provenance, but is not forwarded
to the Opus-family API.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import AdapterConfigError

# repo root = .../src/ai/llm_client.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LLM_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "llm"

# Published claude-opus-4-8 price (USD per 1M tokens) — used for cost logging
# only (docs/07 §4 cost observability). Recorded into fixtures for determinism.
_PRICE_PER_MTOK = {"input": 5.0, "output": 25.0}

# Models that REJECT sampling params (temperature/top_p/top_k) — Opus 4.6+ family.
_NO_SAMPLING_PREFIXES = ("claude-opus-4-", "claude-opus-4.", "claude-fable-", "claude-sonnet-4-6")


# --------------------------------------------------------------------------- #
# Errors (fail-closed surface)
# --------------------------------------------------------------------------- #
class LLMError(RuntimeError):
    """Base error for the LLM adapter layer."""


class LLMUnavailable(LLMError):
    """Backend not wired / fixture missing / key absent → fail-closed (not a pass)."""


class LLMNotReproducible(LLMError):
    """Recorded fixture hash does not match its bytes (replay integrity)."""


# --------------------------------------------------------------------------- #
# Config / value objects
# --------------------------------------------------------------------------- #
@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-opus-4-8"          # docs/07 default LLM
    max_tokens: int = 4096
    temperature: float = 0.0                # provenance only — NOT sent to Opus API
    api_key_env: str = "ANTHROPIC_API_KEY"

    @classmethod
    def from_vendors(cls, path: Optional[Path] = None) -> "LLMConfig":
        """Load llm.* from infra/config/vendors.yaml (model/keys never hardcoded)."""
        path = path or (_REPO_ROOT / "infra" / "config" / "vendors.yaml")
        try:
            import yaml  # lazy: pyyaml is a core dep
        except ImportError:  # pragma: no cover
            return cls()
        if not path.exists():  # pragma: no cover
            return cls()
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("llm", {})
        return cls(
            provider=data.get("provider", "anthropic"),
            model=data.get("model", "claude-opus-4-8"),
            max_tokens=int(data.get("max_tokens", 4096)),
            temperature=float(data.get("temperature", 0.0)),
            api_key_env=data.get("api_key_env", "ANTHROPIC_API_KEY"),
        )


@dataclass(frozen=True)
class LLMRequest:
    """A canonical, hashable LLM request. The key pins (model, max_tokens, system,
    user) so the SAME prompt deterministically resolves to the SAME fixture."""

    model: str
    max_tokens: int
    system: str
    user: str
    tag: str = "llm"

    def _canonical(self) -> str:
        return json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.system,
                "user": self.user,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @property
    def key(self) -> str:
        return hashlib.sha256(self._canonical().encode("utf-8")).hexdigest()

    @property
    def filename(self) -> str:
        return f"{self.tag}_{self.key[:16]}.json"


@dataclass
class LLMResponse:
    """One completion + ModelVersion/token/cost log (docs/07 §2)."""

    text: str
    model: str                  # the model string the API actually served
    input_tokens: int
    output_tokens: int
    stop_reason: Optional[str]
    origin: str                 # "fixture" | "live"
    cost_usd: float = 0.0
    recorded_at: Optional[str] = None

    @staticmethod
    def estimate_cost(input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1_000_000 * _PRICE_PER_MTOK["input"]
            + output_tokens / 1_000_000 * _PRICE_PER_MTOK["output"],
            6,
        )


def _content_hash(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
class ReplayLLMTransport:
    """Resolves an ``LLMRequest`` from a recorded fixture (NO network/key).

    Fail-closed: a request with no recorded fixture raises ``LLMUnavailable``; a
    fixture whose recorded fields no longer hash to the stored value raises
    ``LLMNotReproducible`` (tamper guard)."""

    def __init__(self, fixtures_dir: Path = DEFAULT_LLM_FIXTURES_DIR) -> None:
        self._dir = Path(fixtures_dir)
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def complete(self, req: LLMRequest) -> LLMResponse:
        entry = self._manifest.get(req.key)
        if entry is None:
            raise LLMUnavailable(
                f"no recorded LLM fixture for request '{req.tag}' (key {req.key[:12]}…) — "
                f"run scripts/record_llm_fixtures.py once to record it"
            )
        path = self._dir / entry["file"]
        if not path.exists():
            raise LLMUnavailable(f"LLM fixture file missing: {entry['file']}")
        record = json.loads(path.read_text(encoding="utf-8"))
        payload = record["response"]
        digest = _content_hash(payload)
        if digest != record.get("content_hash"):
            raise LLMNotReproducible(
                f"LLM fixture {entry['file']} hash mismatch — refusing tampered replay"
            )
        usage = payload.get("usage", {})
        return LLMResponse(
            text=payload["text"],
            model=payload["model"],
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            stop_reason=payload.get("stop_reason"),
            origin="fixture",
            cost_usd=LLMResponse.estimate_cost(
                int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            ),
            recorded_at=record.get("recorded_at"),
        )


class RecordingLLMTransport:  # pragma: no cover - live, one-time recording only
    """Performs the live Anthropic call and records the response to a fixture.

    Reads the key from env (``ANTHROPIC_API_KEY``) or ``.env`` — never hardcoded.
    Adaptive thinking is enabled (docs recommend it for reasoning tasks); the
    Opus family rejects ``temperature``, so none is sent."""

    def __init__(self, config: Optional[LLMConfig] = None,
                 fixtures_dir: Path = DEFAULT_LLM_FIXTURES_DIR) -> None:
        self.config = config or LLMConfig.from_vendors()
        self._dir = Path(fixtures_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        self._client = self._build_client()

    def _build_client(self):
        import os

        key = os.environ.get(self.config.api_key_env)
        if not key:
            env_path = _REPO_ROOT / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith(f"{self.config.api_key_env}="):
                        key = line.split("=", 1)[1].strip().strip('"').strip()
                        break
        if not key:
            raise LLMUnavailable(
                f"{self.config.api_key_env} not set (.env) — cannot record live LLM fixtures"
            )
        try:
            import anthropic
        except ImportError as exc:
            raise LLMUnavailable("anthropic SDK not installed (pip install -e .[adapters])") from exc
        return anthropic.Anthropic(api_key=key)

    def complete(self, req: LLMRequest) -> LLMResponse:
        kwargs = dict(
            model=req.model,
            max_tokens=req.max_tokens,
            system=req.system,
            messages=[{"role": "user", "content": req.user}],
            thinking={"type": "adaptive"},
        )
        # Opus 4.6+ family rejects sampling params; only send temperature on models
        # that accept it (none, in slice ① — kept for forward-compat).
        if not any(req.model.startswith(p) for p in _NO_SAMPLING_PREFIXES):
            kwargs["temperature"] = self.config.temperature
        msg = self._client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if msg.stop_reason == "max_tokens":
            raise LLMError(
                f"completion truncated (stop_reason=max_tokens) for '{req.tag}'; "
                f"raise max_tokens before recording"
            )
        payload = {
            "text": text,
            "model": msg.model,
            "stop_reason": msg.stop_reason,
            "usage": {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            },
        }
        record = {
            "request": {
                "tag": req.tag,
                "model": req.model,
                "max_tokens": req.max_tokens,
                "key": req.key,
            },
            "response": payload,
            "content_hash": _content_hash(payload),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._dir / req.filename
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        self._manifest[req.key] = {
            "file": req.filename,
            "tag": req.tag,
            "model": msg.model,
            "recorded_at": record["recorded_at"],
        }
        self._manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return LLMResponse(
            text=text,
            model=msg.model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            stop_reason=msg.stop_reason,
            origin="live",
            cost_usd=LLMResponse.estimate_cost(
                msg.usage.input_tokens, msg.usage.output_tokens
            ),
            recorded_at=record["recorded_at"],
        )


# --------------------------------------------------------------------------- #
# Client facade
# --------------------------------------------------------------------------- #
class LLMClient:
    """Anthropic-by-default LLM client over a record/replay transport.

    The DEFAULT transport is REPLAY (hermetic, no key) so the eval harness and
    tests are deterministic and offline. Pass a ``RecordingLLMTransport`` only
    from the one-time recording script."""

    def __init__(self, config: Optional[LLMConfig] = None, transport: Optional[object] = None) -> None:
        self.config = config or LLMConfig.from_vendors()
        self.transport = transport or ReplayLLMTransport()
        self.calls: list[LLMResponse] = []  # in-process usage log (docs/07 §2)

    def complete(self, *, system: str, user: str, tag: str = "llm",
                 max_tokens: Optional[int] = None) -> LLMResponse:
        req = LLMRequest(
            model=self.config.model,
            max_tokens=max_tokens or self.config.max_tokens,
            system=system,
            user=user,
            tag=tag,
        )
        resp = self.transport.complete(req)
        self.calls.append(resp)
        return resp

    @property
    def total_tokens(self) -> tuple[int, int]:
        return (sum(c.input_tokens for c in self.calls), sum(c.output_tokens for c in self.calls))

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)


def default_llm_client(fixtures_dir: Path = DEFAULT_LLM_FIXTURES_DIR) -> LLMClient:
    """Hermetic replay client (no key/network). Fail-closed on missing fixtures."""
    return LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(fixtures_dir))


# Back-compat: the old stub raised AdapterConfigError when "not wired". The wiring
# is now real (replay). Keep the symbol importable for any older reference.
__all__ = [
    "LLMConfig", "LLMRequest", "LLMResponse", "LLMClient",
    "ReplayLLMTransport", "RecordingLLMTransport",
    "LLMError", "LLMUnavailable", "LLMNotReproducible",
    "default_llm_client", "AdapterConfigError",
]
