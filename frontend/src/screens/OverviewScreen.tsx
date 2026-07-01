/**
 * OverviewScreen — 프로젝트 소개(랜딩) 화면.
 * 목업 3화면 위에 '이 시스템이 무엇이고 왜 신뢰 가능한가'를 한눈에 보여주는 진입 화면.
 * 이력서/포트폴리오 링크의 첫 인상이 되도록 핵심 지표·파이프라인·산출물·안전장치를 요약한다.
 */
const METRICS: { value: string; label: string }[] = [
  { value: "전 세목", label: "법인세→소득세 등 확장(규칙 데이터화)" },
  { value: "31 PDF · 1만+", label: "내부 실무자료 OCR 임베딩 청크" },
  { value: "4대 거래", label: "자기주식·임원보수·가지급금·R&D" },
  { value: "3중 검증", label: "법령·내부자료·판례 교차검증" },
];

const PIPELINE: { step: string; title: string; desc: string }[] = [
  { step: "①", title: "거래·사건", desc: "자기주식·임원보수·가지급금·R&D" },
  { step: "②", title: "판단 게이트", desc: "재원·시가·균등 등 순차 분기 추론" },
  { step: "③", title: "경우의 수", desc: "안전 / 주의 / 위험 + 세무리스크" },
  { step: "④", title: "권고·실행계획", desc: "권고 경로·시점·분개·증빙 예시" },
  { step: "⑤", title: "근거 3중검증", desc: "법령·내부자료·판례 인용 강제" },
];

const SAFEGUARDS: { k: string; title: string; desc: string }[] = [
  { k: "A", title: "근거 인용 강제", desc: "결론·경우의 수에 근거(법령) 필수 — 미입력 시 검증 실패." },
  { k: "B", title: "실값 / 가상 분리", desc: "DART 실재무는 실값, 분개·증빙은 가상 예시(dummy)로 명시." },
  { k: "C", title: "fail-closed", desc: "근거 조회 불가 시 생략+정직 고지. 없는 근거를 지어내지 않음." },
  { k: "D", title: "HITL(사람 검토)", desc: "전 산출물 '인공지능 추론 초안' — 최종 판단·서명은 회계사." },
];

export function OverviewScreen() {
  return (
    <section className="screen" data-testid="screen-overview" aria-labelledby="ov-title">
      <div className="ov-hero">
        <div className="ov-eyebrow">Tax Advisory AI · Decision Report Generator</div>
        <h1 id="ov-title" className="ov-h1">
          AI 세무자문 의사결정 보고서 생성 시스템
        </h1>
        <p className="ov-lead">
          하나의 거래를 <b>판단 게이트</b>로 분해해 <b>'경우의 수(안전·주의·위험)'</b>와
          경우별 세무리스크·절세전략을, <b>법령·내부자료·판례 근거</b>와 함께 회계사 검토용
          보고서(DOCX)로 자동 작성합니다. 최종 판단과 서명은 회계사가 하는 검토 보조 시스템입니다.
        </p>
        <div className="ov-metrics" data-testid="overview-metrics">
          {METRICS.map((m) => (
            <div className="ov-metric" key={m.value}>
              <b>{m.value}</b>
              <span>{m.label}</span>
            </div>
          ))}
        </div>
      </div>

      <h2 className="ov-h2">작동 방식 — 거래를 '경우의 수'로 분해</h2>
      <ol className="ov-pipeline" data-testid="overview-pipeline">
        {PIPELINE.map((p) => (
          <li className="ov-step" key={p.step}>
            <div className="ov-step-no">{p.step}</div>
            <div className="ov-step-title">{p.title}</div>
            <div className="ov-step-desc">{p.desc}</div>
          </li>
        ))}
      </ol>

      <h2 className="ov-h2">대표 산출물 2종</h2>
      <div className="ov-cards">
        <article className="ov-card">
          <h3>가나다정밀 (데모)</h3>
          <p>가상 회사 기준 3대 거래 — 자기주식·임원 보수/퇴직금·가지급금. 교육·검토용 표준 형식.</p>
          <div className="ov-card-meta">시나리오 3 · 표 14 · 분개장/원장 부록</div>
        </article>
        <article className="ov-card teal">
          <h3>한미반도체 (DART 실재무)</h3>
          <p>전자공시(DART) 실재무 그라운딩 + 위 3대 거래 + 연구·인력개발 세액공제까지 4대 쟁점.</p>
          <div className="ov-card-meta">시나리오 4 · 표 21 · 회사개요·종합세무검토·증빙 부록</div>
        </article>
      </div>

      <h2 className="ov-h2">환각방지·정직성 설계</h2>
      <div className="ov-safe">
        {SAFEGUARDS.map((s) => (
          <div className="ov-safe-item" key={s.k}>
            <span className="ov-safe-k">{s.k}</span>
            <div>
              <b>{s.title}</b>
              <p>{s.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <p className="ov-cta">
        아래 탭에서 실제 작업 흐름(①자료수집 → ②선택지 비교 → ③DOCX 검토패키지)을 확인할 수 있습니다.
      </p>
    </section>
  );
}
