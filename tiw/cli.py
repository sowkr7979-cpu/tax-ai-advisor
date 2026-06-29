"""tiw/cli.py — TIW orchestrator CLI (``python -m tiw run ...``).

새 질문 → 검토패키지 DOCX 를 한 명령으로:

    python -m tiw run --company tests/fixtures/company/A제조_2026.json \
        --question "A제조 2026 기업업무추진비 손금한도 검토" \
        --out scratchpad/검토패키지.docx [--live|--replay] [--internal|--client] [--approve-demo]

기본값은 ``--replay --internal`` (결정적·내부본). ``--live`` 는 실제 LLM/임베딩 호출을
하고 응답을 fixture 로 녹화한다. ``--client`` 는 HITL 승인 proof 가 필요하다(없으면 내부본만
+ 안내). ``python -m tiw.eval`` 는 그대로 유지된다(이 CLI 와 독립).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.orchestrator import DEFAULT_COMPANY_FIXTURE, CompanyProfile, Orchestrator


def _reconfig_utf8() -> None:
    # Windows consoles default to cp949 — force UTF-8 so Korean output never crashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tiw",
        description="TIW — 법인세 검토패키지 오케스트레이터 (새 질문 → 11목차 DOCX).",
        epilog="평가 하버스는 별도: `python -m tiw.eval [--slice N]`.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="회사 자료 + 질문 → 검토패키지 DOCX 생성(§4-1 흐름)")
    run.add_argument("--company", default=str(DEFAULT_COMPANY_FIXTURE),
                     help="회사 자료 fixture(JSON) 경로 (기본: A제조_2026)")
    run.add_argument("--question", default=None,
                     help="검토 질문 (생략 시 fixture 의 default_question)")
    run.add_argument("--out", default=None, help="출력 DOCX 경로")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--replay", dest="mode", action="store_const", const="replay",
                      help="결정적 replay (기본) — 녹화 fixture 재생, 네트워크/키 0")
    mode.add_argument("--live", dest="mode", action="store_const", const="live",
                      help="실제 LLM/임베딩 호출 + fixture 녹화")
    run.set_defaults(mode="replay")
    aud = run.add_mutually_exclusive_group()
    aud.add_argument("--internal", dest="audience", action="store_const", const="internal",
                     help="내부 검토본 (기본) — 11목차 전체")
    aud.add_argument("--client", dest="audience", action="store_const", const="client",
                     help="고객 전달본 — HITL 승인 proof 필요(내부 전략메모·검토항목 제외)")
    run.set_defaults(audience="internal")
    run.add_argument("--approve-demo", action="store_true",
                     help="(데모) Reviewer 가 H4·H5 를 승인해 고객 전달본 proof 구성")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    company = CompanyProfile.from_fixture(args.company)
    question = args.question or company.default_question
    out = Path(args.out) if args.out else None

    print(f"▶ TIW run — {company.company_name} {company.fiscal_year} "
          f"[{args.mode} · {args.audience}]")
    print(f"  질문: {question}")
    if args.mode == "live":
        print("  (live) 실제 LLM/임베딩 호출 + fixture 녹화 — 네트워크/키 사용")

    orch = Orchestrator(mode=args.mode)
    result = orch.run(
        company=company, question=question, out_path=out,
        audience=args.audience, approve_demo=args.approve_demo,
        write_docx=out is not None,
    )

    print("\n── 진행 로그(§4-1 단계·소스·인용) ──")
    for line in result.log:
        print(f"  {line}")

    pkg = result.package
    n_cit = len(pkg.citations)
    n_opt = len(pkg.strategy_options)
    n_rev = len(pkg.review_items)
    print("\n── 산출 요약 ──")
    print(f"  섹션: 11목차 / 인용(버전객체): {n_cit} / 선택지: {n_opt}(보수·중립·적극) / "
          f"검토항목: {n_rev}")
    print(f"  종합: {'합의(AGREE)' if result.synthesis and not result.synthesis.abstained else '보류'} · "
          f"전략 grounding: {'OK' if result.strategy and result.strategy.entailment_supported else '부분'}")
    if result.docx_path is not None:
        kind = "고객 전달본" if result.is_client_deliverable else "내부 검토본"
        print(f"  DOCX({kind}): {result.docx_path}")
    elif out is not None:
        print("  DOCX: (미생성)")
    else:
        print("  DOCX: --out 미지정(생성 생략)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfig_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
