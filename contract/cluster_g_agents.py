"""Cluster G — 에이전트 · 실행 (docs/04 §1-G, §4).

Execution provenance for reproducibility (SEC-007).
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import TIWModel, utc_now
from datetime import datetime


class PromptVersion(TIWModel):
    prompt_version_id: str
    name: str
    version: str
    content_hash: Optional[str] = None


class ModelVersion(TIWModel):
    model_version_id: str
    provider: str = "anthropic"
    model_name: str = "claude-opus-4-8"  # default LLM (docs/07)
    version: Optional[str] = None


class AgentRun(TIWModel):
    agent_run_id: str
    source_answer_id: str
    prompt_version_id: str
    model_version_id: str
    started_at: datetime = Field(default_factory=utc_now)


class ToolCall(TIWModel):
    tool_call_id: str
    agent_run_id: str
    tool_name: str       # korean_law_mcp|tavily|brave|dart|ocr|...
    request_hash: Optional[str] = None
    response_snapshot_id: Optional[str] = None  # recorded SourceSnapshot for replay
