"""src/scenario_flowchart.py — '경우의 수' 의사결정 플로우차트(PNG) 렌더.

``scenario_planner.Scenario`` 의 게이트(순차 분기)를 **세로 의사결정 spine + 옆으로 빠지는
리스크 분기**로 그린다. 마름모=판단(분기), 빨강=세무리스크 결과, 초록=정상 종결, 파랑=시작.
라벨은 모두 한국어(영어 0). matplotlib(Agg) + Noto Sans KR.

플로우차트는 표시용 그림이므로 바이트 결정성은 요구하지 않는다(테스트는 생성·크기만 확인).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager, rcParams  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSansKR-Regular.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
]
_BLUE, _GREEN, _ORANGE, _GREY, _RED = "#1A73E8", "#188038", "#E8710A", "#5F6368", "#D93025"
_FILL = {"start": "#E8F0FE", "decision": "#FEF7E0", "risk": "#FCE8E6", "safe": "#E6F4EA"}
_EDGE = {"start": _BLUE, "decision": _ORANGE, "risk": _RED, "safe": _GREEN}


def _setup_font() -> None:
    for fp in _FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                font_manager.fontManager.addfont(fp)
                rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
                break
            except Exception:  # pragma: no cover
                continue
    rcParams["axes.unicode_minus"] = False


def _wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width)) or text


def _round_box(ax, cx, cy, w, h, text, kind, *, fs=10):
    ax.add_patch(mpatches.FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.04",
        linewidth=1.6, edgecolor=_EDGE[kind], facecolor=_FILL[kind], mutation_scale=10, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color="#202124", zorder=3)


def _diamond(ax, cx, cy, w, h, text, *, fs=9.5):
    pts = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
    ax.add_patch(mpatches.Polygon(pts, closed=True, linewidth=1.7,
                                  edgecolor=_EDGE["decision"], facecolor=_FILL["decision"], zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color="#202124", zorder=3)


def _arrow(ax, x1, y1, x2, y2, label="", color=_GREY, *, label_dx=0.12, label_color=None):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.7), zorder=1)
    if label:
        ax.text((x1 + x2) / 2 + label_dx, (y1 + y2) / 2, label, fontsize=9,
                color=label_color or color, ha="left", va="center", fontweight="bold", zorder=4)


def save_scenario_flowchart(scenario, out_path: str | Path) -> Path:
    """시나리오의 게이트 분기를 세로 의사결정 플로우차트로 그린다."""
    _setup_font()
    gates = scenario.gates
    n = len(gates)
    if n < 1:                       # 분기 없는 시나리오는 의사결정 플로우차트를 그릴 수 없음
        raise ValueError(f"[{scenario.key}] 게이트가 없어 플로우차트를 그릴 수 없습니다(분기 필요).")
    spine_x, risk_x = 3.4, 9.0
    dy = 2.05
    top_y = (n + 1) * dy + 0.6
    fig_h = top_y + 1.3

    fig, ax = plt.subplots(figsize=(11.0, fig_h + 0.8))
    ax.set_xlim(0, 12); ax.set_ylim(-0.85, fig_h); ax.axis("off")

    # 시작 노드
    start_y = top_y
    _round_box(ax, spine_x, start_y, 4.0, 1.1,
               f"[사실관계]\n{_wrap(scenario.title, 16)}", "start", fs=10.5)

    # 게이트(마름모) + 리스크 분기(빨강) 세로 배치
    dec_y = []
    for i, g in enumerate(gates):
        cy = top_y - (i + 1) * dy
        dec_y.append(cy)
        _diamond(ax, spine_x, cy, 3.7, 1.78, f"{g.key}. {_wrap(g.question, 15)}")
        # 리스크 분기 박스
        _round_box(ax, risk_x, cy, 4.4, 1.5,
                   f"⚠ {g.risk_title}\n{_wrap(g.risk_detail, 24)}", "risk", fs=8.6)
        # 마름모 오른쪽 → 리스크
        _arrow(ax, spine_x + 3.7 / 2, cy, risk_x - 4.4 / 2, cy,
               g.risk_label, _RED, label_color=_RED)

    # 정상 종결(초록)
    safe_y = top_y - (n + 1) * dy
    _round_box(ax, spine_x, safe_y, 4.4, 1.25,
               f"✓ {scenario.safe_title}\n{_wrap(scenario.safe_detail, 24)}", "safe", fs=8.8)

    # 세로(통과) 화살표: 시작→D1→…→safe
    _arrow(ax, spine_x, start_y - 1.1 / 2, spine_x, dec_y[0] + 1.78 / 2, "", _BLUE)
    for i in range(n):
        y_top = dec_y[i] - 1.78 / 2
        y_bot = (dec_y[i + 1] + 1.78 / 2) if i + 1 < n else (safe_y + 1.25 / 2)
        _arrow(ax, spine_x, y_top, spine_x, y_bot, gates[i].pass_label, _GREEN,
               label_dx=0.18, label_color=_GREEN)

    # 범례
    handles = [
        mpatches.Patch(facecolor=_FILL["decision"], edgecolor=_EDGE["decision"], label="판단(분기)"),
        mpatches.Patch(facecolor=_FILL["risk"], edgecolor=_EDGE["risk"], label="세무리스크(과세·부인·추징)"),
        mpatches.Patch(facecolor=_FILL["safe"], edgecolor=_EDGE["safe"], label="정상 종결(절세·안전)"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8.6, frameon=False,
              bbox_to_anchor=(1.0, 0.0))
    fig.suptitle(f"[{scenario.key}] {scenario.title} — 경우의 수 의사결정 플로우차트",
                 fontsize=13, fontweight="bold", color="#202124", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_burden_bar(scenario, out_path: str | Path) -> Path:
    """Tax Plan 대안별 추가세부담(억) 비교 막대 — 권고 대안 강조(가정 금액)."""
    _setup_font()
    alts = list(scenario.alternatives)
    if not alts:
        raise ValueError(f"[{scenario.key}] 대안(alternatives)이 없어 비교 막대를 그릴 수 없습니다.")
    labels = [f"{a.key}\n{a.label}" for a in alts]
    vals = [a.burden_eok for a in alts]
    colors = [_GREEN if a.recommended else _BLUE for a in alts]
    fig, ax = plt.subplots(figsize=(8.6, 4.0))
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    for b, a in zip(bars, alts):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(vals) * 0.02,
                f"{a.burden_eok:,.0f}억" + ("  ◀ 권고" if a.recommended else ""),
                ha="center", va="bottom", fontsize=10,
                fontweight="bold" if a.recommended else "normal",
                color=_GREEN if a.recommended else "#202124")
    ax.set_ylabel("추가 세부담(억원, 가정)", fontsize=10.5)
    ax.set_title(f"[{scenario.key}] 대안별 추가 세부담 비교 (절세 대안)", fontsize=12.5,
                 fontweight="bold", color="#202124", pad=8)
    ax.set_ylim(0, max(max(vals) * 1.3, 1.0))   # 전부 0이어도 y축 붕괴 방지(codex note)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_plan_timeline(scenario, out_path: str | Path) -> Path:
    """실행 타임라인(시점 최적화) — 단계별 시점·행위·세무효과 세로 도식."""
    _setup_font()
    steps = list(scenario.plan)
    n = len(steps)
    if n == 0:
        raise ValueError(f"[{scenario.key}] 실행계획(plan)이 없어 타임라인을 그릴 수 없습니다.")
    fig, ax = plt.subplots(figsize=(9.6, 0.98 * n + 1.1))
    ax.set_xlim(0, 10); ax.set_ylim(0, n + 0.5); ax.axis("off")
    ax.plot([1.0, 1.0], [0.4, n + 0.1], color=_BLUE, lw=2.2, zorder=1)
    for idx, st in enumerate(steps):
        y = n - idx
        ax.scatter([1.0], [y], s=130, color=_BLUE, zorder=3)
        ax.text(1.0, y, str(idx + 1), color="white", ha="center", va="center",
                fontsize=9, fontweight="bold", zorder=4)
        ax.text(1.5, y + 0.17, f"{st.when}  ·  {st.what}", fontsize=10.3,
                fontweight="bold", color="#202124", va="center")
        ax.text(1.5, y - 0.2, f"→ {st.effect}", fontsize=9.2, color=_GREY, va="center")
    ax.set_title(f"[{scenario.key}] 실행 타임라인 (시점 최적화)", fontsize=12.5,
                 fontweight="bold", color="#202124", loc="left", pad=6)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_case_matrix(scenario, out_path: str | Path) -> Path:
    """경우의 수 × (위험등급·세무리스크·관리) 매트릭스를 색상 표 이미지로."""
    _setup_font()
    leaves = scenario.leaves
    risk_color = {"안전": _GREEN, "주의": _ORANGE, "위험": _RED}
    fig, ax = plt.subplots(figsize=(11.0, 0.92 * len(leaves) + 1.4))
    ax.set_xlim(0, 12); ax.set_ylim(0, len(leaves) + 1); ax.axis("off")
    ax.text(0.1, len(leaves) + 0.5, "경우의 수", fontsize=10.5, fontweight="bold", color=_BLUE)
    ax.text(3.2, len(leaves) + 0.5, "위험", fontsize=10.5, fontweight="bold", color=_BLUE)
    ax.text(4.4, len(leaves) + 0.5, "세무리스크", fontsize=10.5, fontweight="bold", color=_BLUE)
    ax.text(8.2, len(leaves) + 0.5, "절세전략·리스크관리", fontsize=10.5, fontweight="bold", color=_BLUE)
    for i, lf in enumerate(leaves):
        y = len(leaves) - i - 0.5
        col = risk_color.get(lf.risk_level, _GREY)
        ax.text(0.1, y, f"{lf.case_label}\n{_wrap(lf.path, 12)}", fontsize=8.6,
                va="center", color="#202124")
        ax.add_patch(mpatches.FancyBboxPatch((3.0, y - 0.28), 1.0, 0.56,
                     boxstyle="round,pad=0.02", facecolor=col, edgecolor=col, zorder=2))
        ax.text(3.5, y, lf.risk_level, fontsize=9, ha="center", va="center",
                color="white", fontweight="bold", zorder=3)
        ax.text(4.4, y, _wrap(lf.tax_risk, 30), fontsize=8.3, va="center", color="#202124")
        ax.text(8.2, y, _wrap(lf.management, 30), fontsize=8.3, va="center", color="#202124")
        ax.axhline(y - 0.5, color="#E0E0E0", lw=0.6)
    ax.set_title(f"[{scenario.key}] 경우의 수별 결론 매트릭스", fontsize=12.5,
                 fontweight="bold", color="#202124", loc="left", pad=8)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path
