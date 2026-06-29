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
        if s.applicable:
            parts.append(f"{s.dimension}={int(s.score)}")
    return " ".join(parts)


def _print_report(report: SliceReport) -> None:
    status = "PASS" if report.passed else "FAIL"
    gate = "HARD-GATE 위반" if report.hard_gate_hit else "하드게이트 0"
    print(f"\n=== slice ⑥ '{report.name}' (slice {report.slice_no}) ===")
    print(
        f"  점수(headline=min): {report.score:.1f}/100  |  mean: {report.mean_total:.1f}  "
        f"|  완료게이트(≥{report.threshold}): {status}  |  {gate}"
    )
    print(f"  케이스: public={report.public_count} hidden={report.hidden_count}")
    for r in report.case_results:
        vis = "H" if r.visibility == Visibility.HIDDEN else "P"
        flags = ",".join(f.code for f in r.failure_modes) or "-"
        cap = f" cap={r.cap}" if r.cap is not None else ""
        print(
            f"    [{vis}] {r.case_id:<14} total={r.total:>5.1f}{cap}  "
            f"leak={r.metrics.get('leakage_count')}  "
            f"recall={r.metrics.get('recall')}  shared={r.metrics.get('shared_recall')}  "
            f"null_rej={r.metrics.get('null_key_rejected')}  gate=[{flags}]"
        )
        print(f"         dims: {_fmt_dims(r)}")


def _report_to_dict(report: SliceReport) -> dict:
    return {
        "slice": report.slice_no,
        "name": report.name,
        "score": report.score,
        "mean_total": report.mean_total,
        "hard_gate_hit": report.hard_gate_hit,
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
