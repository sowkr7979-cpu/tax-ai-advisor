"""src/tax_charts.py — Tax Plan 도표(그림) 생성. matplotlib + 한글(Noto Sans KR).

회계사 가독성을 위해 지분구조도·시나리오 세부담 비교·증여세 절감 워터폴·실행 타임라인을 PNG로
그린다. 라벨은 모두 한국어(영어 0). 색은 구글 톤(블루/그레이/그린/오렌지)을 사용한다.

차트는 표시용 그림이므로 바이트 결정성은 요구하지 않는다(테스트는 파일 생성·크기만 확인).
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager, rcParams  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402

# 한글 폰트 — 라벨 한국어. env(KOREAN_FONT_PATH) 우선, Windows(로컬)·Linux(컨테이너) 폴백.
_FONT_CANDIDATES = [
    os.environ.get("KOREAN_FONT_PATH", ""),
    r"C:\Windows\Fonts\NotoSansKR-Regular.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
]
_BLUE, _GREEN, _ORANGE, _GREY, _RED = "#1A73E8", "#188038", "#E8710A", "#5F6368", "#D93025"


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


def _eok(v: float) -> str:
    return f"{v:,.0f}억"


def _box(ax, x, y, w, h, text, *, fc="#E8F0FE", ec=_BLUE, fs=11, bold=True):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02",
        linewidth=1.4, edgecolor=ec, facecolor=fc, mutation_scale=8))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", color="#202124")


def _arrow(ax, x1, y1, x2, y2, label="", color=_GREY):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.6))
    if label:
        ax.text((x1 + x2) / 2 + 0.04, (y1 + y2) / 2, label, fontsize=9.5,
                color=color, ha="left", va="center")


def save_ownership_diagram(holdings_before, holdings_after, out_path: str | Path) -> Path:
    """지분구조도(정리 전/후) — 박스+화살표(지분율)."""
    _setup_font()
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.3))
    for ax, title, hs, after in (
        (axes[0], "정리 전", holdings_before, False),
        (axes[1], "정리 후(가업승계)", holdings_after, True),
    ):
        ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
        ax.set_title(title, fontsize=12.5, fontweight="bold", color=_BLUE, pad=6)
        owner = "자녀(승계인)" if after else "창업주(오너)"
        _box(ax, 5, 8.6, 4.2, 1.1, owner, fc="#FCE8E6" if after else "#FEF7E0",
             ec=_GREEN if after else _ORANGE)
        _box(ax, 5, 5.2, 4.2, 1.1, "한맥홀딩스(주)\n(지주회사)")
        _box(ax, 5, 1.7, 4.2, 1.1, "한맥정밀(주)\n(사업회사)", fc="#E6F4EA", ec=_GREEN)
        # 화살표(지분율)
        pct_h = next((h.pct for h in hs if "홀딩스" in h.target), None)
        pct_p = next((h.pct for h in hs if "정밀" in h.target and "홀딩스" in h.holder), None)
        pct_o = next((h.pct for h in hs if "정밀" in h.target and "오너" in h.holder
                      or ("정밀" in h.target and "창업주" in h.holder)), None)
        if pct_h:
            _arrow(ax, 5, 8.0, 5, 5.8, f"{pct_h:.0f}%", _ORANGE if not after else _GREEN)
        if pct_p:
            _arrow(ax, 5, 4.6, 5, 2.3, f"{pct_p:.0f}%", _BLUE)
        if pct_o and not after:
            _arrow(ax, 6.9, 8.2, 6.9, 2.1, f"{pct_o:.0f}% 직접", _GREY)
    fig.suptitle("그림 1. 그룹 지분구조(정리 전 → 정리 후)", fontsize=13,
                 fontweight="bold", color="#202124", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_scenario_bar(scenarios, out_path: str | Path) -> Path:
    """시나리오별 추가 세부담 비교(막대) — 권고안 강조."""
    _setup_font()
    labels = [f"{s.key}. {s.label.split('(')[0].strip()}" for s in scenarios]
    vals = [s.tax_burden_eok for s in scenarios]
    colors = [_GREEN if s.recommended else _BLUE for s in scenarios]
    fig, ax = plt.subplots(figsize=(8.4, 3.9))
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    for b, s in zip(bars, scenarios):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.12,
                _eok(s.tax_burden_eok) + ("  ◀ 권고" if s.recommended else ""),
                ha="center", va="bottom", fontsize=10.5,
                fontweight="bold" if s.recommended else "normal",
                color=_GREEN if s.recommended else "#202124")
    ax.set_ylabel("추가 세부담(억원)", fontsize=10.5)
    ax.set_title("그림 3. 잉여금 환원 시나리오별 추가 세부담 비교", fontsize=12.5,
                 fontweight="bold", color="#202124", pad=8)
    ax.set_ylim(0, max(vals + [1]) * 1.35)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_gift_waterfall(steps, before: float, after: float, out_path: str | Path) -> Path:
    """가업승계 증여세 베이스(평가액) 절감 워터폴."""
    _setup_font()
    fig, ax = plt.subplots(figsize=(8.8, 4.1))
    x = range(len(steps))
    cum = 0.0
    for i, st in enumerate(steps):
        if st.is_total:
            ax.bar(i, st.delta_eok, color=_BLUE, width=0.6)
            ax.text(i, st.delta_eok + 4, _eok(st.delta_eok), ha="center", fontsize=10,
                    fontweight="bold", color=_BLUE)
            cum = st.delta_eok
        else:
            bottom = cum + min(st.delta_eok, 0)
            ax.bar(i, abs(st.delta_eok), bottom=bottom,
                   color=_GREEN if st.delta_eok < 0 else _GREY, width=0.6)
            if st.delta_eok != 0:
                ax.text(i, bottom + abs(st.delta_eok) + 4,
                        f"{st.delta_eok:+,.0f}억", ha="center", fontsize=9.5, color=_GREEN)
            cum += st.delta_eok
    ax.set_xticks(list(x))
    ax.set_xticklabels([st.label for st in steps], fontsize=9, rotation=12, ha="right")
    ax.set_ylabel("가업주식 평가액(억원)", fontsize=10.5)
    ax.set_title("그림 4. 가업주식 평가액 인하 → 증여세 절감", fontsize=12.5,
                 fontweight="bold", color="#202124", pad=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_strategy_screening(cards, out_path: str | Path) -> Path:
    """카테고리별 절세전략 스크리닝 맵(적용·조건부 / 미해당) — 가로 누적 막대."""
    _setup_font()
    cats: list[str] = []
    for c in cards:
        if c.category not in cats:
            cats.append(c.category)
    applied = [sum(1 for c in cards if c.category == cat and c.applies) for cat in cats]
    notapp = [sum(1 for c in cards if c.category == cat and not c.applies) for cat in cats]
    fig, ax = plt.subplots(figsize=(9.2, 0.66 * len(cats) + 1.6))
    y = list(range(len(cats)))
    ax.barh(y, applied, color=_GREEN, label="적용·조건부", height=0.55)
    ax.barh(y, notapp, left=applied, color="#BDC1C6", label="미해당", height=0.55)
    for i, (a, nn) in enumerate(zip(applied, notapp)):
        if a:
            ax.text(a / 2, i, str(a), ha="center", va="center", color="white",
                    fontsize=10.5, fontweight="bold")
        if nn:
            ax.text(a + nn / 2, i, str(nn), ha="center", va="center", color="#202124", fontsize=10)
    ax.set_yticks(y); ax.set_yticklabels(cats, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlabel("전략 수", fontsize=10.5)
    ax.set_title("그림 1. 카테고리별 절세전략 스크리닝(적용·조건부 / 미해당)", fontsize=12.5,
                 fontweight="bold", color="#202124", pad=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.legend(loc="lower right", fontsize=9.5, frameon=False)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_strategy_effect_tier(cards, out_path: str | Path) -> Path:
    """적용 전략별 기대 절세효과(정성 등급: 높음/중간/낮음) — 가로 막대."""
    _setup_font()
    order = {"높음": 3, "중간": 2, "낮음": 1, "정성": 1}
    applied = sorted([c for c in cards if c.applies],
                     key=lambda c: (-order.get(c.effect_tier, 1), c.priority))
    labels = [c.title for c in applied]
    vals = [order.get(c.effect_tier, 1) for c in applied]
    colors = [_GREEN if v == 3 else (_BLUE if v == 2 else _GREY) for v in vals]
    fig, ax = plt.subplots(figsize=(9.6, 0.5 * len(applied) + 1.4))
    y = list(range(len(applied)))
    ax.barh(y, vals, color=colors, height=0.6)
    for i, c in enumerate(applied):
        ax.text(vals[i] + 0.04, i, c.effect_tier, va="center", fontsize=9, color="#202124")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xticks([1, 2, 3]); ax.set_xticklabels(["낮음", "중간", "높음"], fontsize=9.5)
    ax.set_xlim(0, 3.5)
    ax.set_title("그림 2. 적용 전략별 기대 절세효과(정성 등급 — 금액 아님)", fontsize=12.5,
                 fontweight="bold", color="#202124", pad=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path


def save_timeline(steps, out_path: str | Path) -> Path:
    """실행 타임라인(단계·일자·행위·세무효과) 도식."""
    _setup_font()
    n = len(steps)
    fig, ax = plt.subplots(figsize=(9.6, 0.95 * n + 1.1))
    ax.set_xlim(0, 10); ax.set_ylim(0, n + 0.5); ax.axis("off")
    ax.plot([1.0, 1.0], [0.4, n + 0.1], color=_BLUE, lw=2.2, zorder=1)
    for idx, st in enumerate(steps):
        y = n - idx
        ax.scatter([1.0], [y], s=130, color=_BLUE, zorder=3)
        ax.text(1.0, y, str(st.seq), color="white", ha="center", va="center",
                fontsize=9, fontweight="bold", zorder=4)
        ax.text(1.5, y + 0.16, f"{st.date_label}  ·  {st.action}", fontsize=10.5,
                fontweight="bold", color="#202124", va="center")
        ax.text(1.5, y - 0.22, f"→ {st.tax_effect}", fontsize=9.3, color=_GREY, va="center")
    ax.set_title("그림 2. 실행 타임라인(시점 최적화)", fontsize=12.5, fontweight="bold",
                 color="#202124", loc="left", pad=6)
    fig.tight_layout()
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return out_path
