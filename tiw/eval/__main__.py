"""python -m tiw.eval [--slice N] [--json] [--strict]

Runs the evaluation harness and prints per-slice RubricResults + hard-gate flags.
This output is the ground truth PROMPT.md §5 reads to judge completion.
"""

from __future__ import annotations

import argparse
import json
import sys

from contract.cluster_i_eval import Visibility
from tiw.eval.runner import SliceReport, implemented_slices, run_all, run_slice


def _fmt_dims(result) -> str:
    parts = []
    for s in result.dimension_scores:
        if s.applicable and s.score is not None:
            parts.append(f"{s.dimension}={int(s.score)}")
    return " ".join(parts)


_CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}


def _fmt_pending(result) -> str:
    pend = [s.dimension for s in result.dimension_scores if s.applicable and s.score is None]
    return (" pending(judge)=" + ",".join(pend)) if pend else ""


def _print_report(report: SliceReport) -> None:
    if report.pending:
        status = "PENDING_JUDGE (미완료 — 결정적 차원만 채점)"
    elif report.passed:
        status = "PASS"
    else:
        status = "FAIL"
    gate = "HARD-GATE 위반" if report.hard_gate_hit else "하드게이트 0"
    glyph = _CIRCLED.get(report.slice_no, str(report.slice_no))
    print(f"\n=== slice {glyph} '{report.name}' (slice {report.slice_no}) ===")
    headline = "결정적 소계" if report.pending else "headline=min"
    print(
        f"  점수({headline}): {report.score:.1f}/100  |  mean: {report.mean_total:.1f}  "
        f"|  완료게이트(≥{report.threshold}): {status}  |  {gate}"
    )
    if report.pending:
        print(f"  PENDING_JUDGE 차원(보류, 만점 아님): {', '.join(report.pending_dimensions)}")
    print(f"  케이스: public={report.public_count} hidden={report.hidden_count}")
    for r in report.case_results:
        vis = "H" if r.visibility == Visibility.HIDDEN else "P"
        flags = ",".join(f.code for f in r.failure_modes) or "-"
        cap = f" cap={r.cap}" if r.cap is not None else ""
        extra = []
        for key in ("leakage_count", "recall", "shared_recall", "citation_grounding",
                    "temporal_error", "reproducible", "entailment"):
            if key in r.metrics:
                extra.append(f"{key}={r.metrics.get(key)}")
        print(
            f"    [{vis}] {r.case_id:<14} total={r.total:>5.1f}{cap}  "
            f"{'  '.join(extra)}  gate=[{flags}]"
        )
        print(f"         dims: {_fmt_dims(r)}{_fmt_pending(r)}")


def _report_to_dict(report: SliceReport) -> dict:
    return {
        "slice": report.slice_no,
        "name": report.name,
        # Headline separation (codex P2-B): a PENDING slice has NO completion
        # score — expose the judge-free `deterministic_subtotal` separately and
        # null out `completion_score` so a reader of the JSON cannot mistake the
        # subtotal for a ≥90 completion. (`score` retained for back-compat = the
        # deterministic subtotal/min.)
        "completion_score": report.completion_score,
        "deterministic_subtotal": report.deterministic_subtotal,
        "score": report.score,
        "mean_total": report.mean_total,
        "hard_gate_hit": report.hard_gate_hit,
        "pending": report.pending,
        "pending_dimensions": report.pending_dimensions,
        "passed": report.passed,
        "public_count": report.public_count,
        "hidden_count": report.hidden_count,
        "cases": [r.model_dump(mode="json") for r in report.case_results],
    }


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp949 — force UTF-8 so Korean output never crashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    parser = argparse.ArgumentParser(prog="tiw.eval", description="TIW evaluation harness")
    parser.add_argument("--slice", type=int, default=None, help="run a single slice (e.g. 6)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero if any slice fails the 90 gate"
    )
    args = parser.parse_args(argv)

    if args.slice is not None and args.slice not in implemented_slices():
        print(
            f"slice {args.slice} 미구현. 구현된 슬라이스: {implemented_slices()}",
            file=sys.stderr,
        )
        return 2

    reports = [run_slice(args.slice)] if args.slice is not None else run_all()

    if args.json:
        print(json.dumps([_report_to_dict(r) for r in reports], ensure_ascii=False, indent=2))
    else:
        for report in reports:
            _print_report(report)
        passed = sum(r.passed for r in reports)
        print(
            f"\n요약: {passed}/{len(reports)} 슬라이스 완료게이트 통과 "
            f"(구현된 슬라이스만 평가; 전체 6 중 {len(implemented_slices())} 구현)."
        )

    if args.strict and not all(r.passed for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
