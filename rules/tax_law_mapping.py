"""rules/tax_law_mapping.py — ORCH-015 다세목(multi-tax) 쟁점→법령 매핑 로더.

``rules/tax_law_mapping.yaml`` 을 읽어 (issue_key → :class:`IssueMapping`) 으로
평탄화한다. 법인세 한 세목에 고정하지 않고 소득세·부가세·상증세 등을 *동일 구조*
로 확장한다(변경①). 매핑이 코드 하드코딩이 아니라 데이터 레지스트리이므로, 새 세목·
쟁점은 코드 변경 없이 YAML 등록만으로 추가된다.

미등록 세목/쟁점은 이 로더가 ``None`` 을 돌려주고, 호출측(orchestrator)이 **fail-closed**
한다(임의 법령 추정 금지, ORCH-015).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

_YAML_PATH = Path(__file__).with_name("tax_law_mapping.yaml")


@dataclass(frozen=True)
class IssueMapping:
    """한 쟁점키의 세목·법령·조문 매핑 (레지스트리 1행)."""

    tax_type: str        # 세목 (법인세·소득세 …)
    law_name: str        # 법령명 (법인세법·소득세법 …)
    issue_key: str       # 쟁점 키 (기업업무추진비 …)
    article: str         # 조문 라벨 (제25조)
    article_title: str   # 조문 제목 (기업업무추진비의 손금불산입)
    title: str           # 검토패키지 표시 제목


class TaxLawMappingError(RuntimeError):
    """레지스트리 로드/형식 오류."""


@lru_cache(maxsize=1)
def load_mapping() -> dict[str, IssueMapping]:
    """YAML 레지스트리 → {issue_key: IssueMapping}. 1회 로드 후 캐시."""
    try:
        data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # pragma: no cover - 형식 오류는 fail-closed
        raise TaxLawMappingError(f"세목 매핑 레지스트리 로드 실패: {exc}") from exc

    out: dict[str, IssueMapping] = {}
    for tax_type, block in data.items():
        law_name = (block or {}).get("law_name")
        if not law_name:
            raise TaxLawMappingError(f"세목 '{tax_type}' 에 law_name 누락")
        for issue_key, m in ((block or {}).get("issues") or {}).items():
            if issue_key in out:
                raise TaxLawMappingError(f"중복 쟁점 키: {issue_key}")
            try:
                out[issue_key] = IssueMapping(
                    tax_type=tax_type, law_name=law_name, issue_key=issue_key,
                    article=m["article"], article_title=m["article_title"],
                    title=m["title"],
                )
            except (KeyError, TypeError) as exc:
                raise TaxLawMappingError(
                    f"쟁점 '{issue_key}' 매핑 필드 누락(article/article_title/title): {exc}"
                ) from exc
    return out


def article_by_issue() -> dict[str, tuple[str, str, str]]:
    """orchestrator 기존 ``_ARTICLE_BY_ISSUE`` 호환 형태 (article, article_title, title).

    법인세 항목은 기존 하드코딩과 문자 단위 동일(회귀 0)."""
    return {k: (v.article, v.article_title, v.title) for k, v in load_mapping().items()}


def law_name_for(issue_key: str, *, default: Optional[str] = None) -> Optional[str]:
    """쟁점키의 법령명(법인세법·소득세법 …). 미등록이면 ``default``(보통 None → fail-closed)."""
    m = load_mapping().get(issue_key)
    return m.law_name if m is not None else default


def tax_type_for(issue_key: str) -> Optional[str]:
    m = load_mapping().get(issue_key)
    return m.tax_type if m is not None else None
