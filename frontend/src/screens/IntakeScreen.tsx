// 화면① Intake 자료수집 챗 (§4-1-1 / INTK) — 인터뷰 루프 + 마감 정리.
import type { Intake } from "../types";

function statusClass(status: string): string {
  switch (status) {
    case "수집":
      return "st st-collected";
    case "없음":
      return "st st-none";
    case "모름":
      return "st st-unknown";
    case "결손":
      return "st st-deficit";
    default:
      return "st";
  }
}

export function IntakeScreen({ intake }: { intake: Intake }) {
  return (
    <section className="screen" data-testid="screen-intake">
      <h1>① Intake 자료수집 챗</h1>
      <p className="goal" data-testid="intake-goal">
        검토 목적: {intake.goal}
      </p>

      <div className="chat" data-testid="intake-chat">
        {intake.turns.map((t, i) => (
          <div key={i} className={"bubble " + t.role} data-role={t.role}>
            <span className="who">{t.role === "bot" ? "Intake Agent" : "사용자"}</span>
            <span className="msg">{t.text}</span>
            {t.status ? <span className={statusClass(t.status)}>{t.status}</span> : null}
          </div>
        ))}
        {intake.early_stopped ? (
          <div className="early-stop" data-testid="intake-early-stop">
            ※ 조기 종료: 사용자 "여기까지만 입력" 선언 → 인터뷰 루프 탈출
          </div>
        ) : null}
      </div>

      <h2>필수자료 체크리스트 (수집/없음/모름/결손 상태)</h2>
      <table className="grid" data-testid="intake-checklist">
        <thead>
          <tr>
            <th>자료</th>
            <th>상태</th>
            <th>기밀등급</th>
          </tr>
        </thead>
        <tbody>
          {intake.checklist.map((m, i) => (
            <tr key={i}>
              <td>{m.name}</td>
              <td>
                <span className={statusClass(m.status)}>{m.status}</span>
              </td>
              <td>{m.confidentiality}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="closing" data-testid="intake-closing">
        <h2>마감 정리 — 검토 가능 범위 · 결손 · 한계 고지</h2>
        <p className="scope">{intake.closing_scope}</p>
        <h3>부족 자료(결손)</h3>
        <ul>
          {intake.deficits.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
        <h3>전제 · 한계 고지 (자료한계 꼬리표)</h3>
        <ul>
          {intake.limits.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
