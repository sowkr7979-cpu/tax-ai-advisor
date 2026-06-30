// 화면③ DOCX 검토패키지 미리보기 — 13목차(+§8 채널별·§10 추론도식) + 근거 인용 링크.
import { citationIndex } from "../data";
import type { Draft, ReasoningStep } from "../types";

// OUT-008(변경③): 추론 트레이스를 Mermaid flowchart 정의로(하이브리드: 프론트 인터랙티브).
function mermaidFlow(steps: ReasoningStep[]): string {
  const nodes = steps.map((s) => `  n${s.seq}["${s.seq}. ${s.stage}"]`);
  const edges = steps.slice(1).map((s, i) => `  n${steps[i].seq} --> n${s.seq}`);
  return ["flowchart LR", ...nodes, ...edges].join("\n");
}

function CiteLinks({ ids }: { ids: string[] }) {
  if (!ids.length) return null;
  return (
    <span className="cites">
      {ids.map((cid) => {
        const c = citationIndex[cid];
        return c ? (
          <a key={cid} className="cite-link" href={c.href} target="_blank" rel="noreferrer">
            {c.label}
          </a>
        ) : null;
      })}
    </span>
  );
}

export function DraftScreen({ draft }: { draft: Draft }) {
  return (
    <section className="screen docx" data-testid="screen-draft">
      <h1>③ DOCX 검토패키지 미리보기 (13목차)</h1>
      <p className="goal">
        {draft.company_name} {draft.fiscal_year} 세무 검토패키지 초안 · 기준일 {draft.as_of_date}
        {draft.high_risk ? <span className="badge-risk"> 고위험</span> : null}
      </p>
      {draft.data_limits.length ? (
        <div className="limit-tag" data-testid="draft-data-limits">
          자료한계: {draft.data_limits.join(" / ")}
        </div>
      ) : null}

      {/* 11목차 네비게이션 */}
      <ol className="toc" data-testid="draft-toc">
        {draft.sections.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>

      <article className="paper">
        {/* 1 */}
        <h2 data-section="1">1. Executive Summary</h2>
        <p>{draft.executive_summary}</p>

        {/* 2 */}
        <h2 data-section="2">2. 회사 개요·검토 범위</h2>
        <p>
          회사: {draft.company_name} (거래처 {draft.client_id}, 사건 {draft.matter_id})
        </p>
        <p>검토 범위: {draft.review_scope}</p>

        {/* 3 */}
        <h2 data-section="3">3. 입력 자료 목록</h2>
        <table className="grid">
          <thead>
            <tr>
              <th>자료</th>
              <th>상태</th>
              <th>기밀등급</th>
            </tr>
          </thead>
          <tbody>
            {draft.input_materials.map((m, i) => (
              <tr key={i}>
                <td>{m.name}</td>
                <td>{m.status}</td>
                <td>{m.confidentiality}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* 4 */}
        <h2 data-section="4">4. 주요 세무 리스크</h2>
        <ul>
          {draft.risks.map((r, i) => (
            <li key={i}>
              <strong>[{r.severity}]</strong> {r.title} — {r.description}
              <CiteLinks ids={r.citation_ids} />
            </li>
          ))}
        </ul>

        {/* 5 */}
        <h2 data-section="5">5. 절세 기회</h2>
        <ul>
          {draft.opportunities.map((o, i) => (
            <li key={i}>
              {o.title} — {o.description}
              <CiteLinks ids={o.citation_ids} />
            </li>
          ))}
        </ul>

        {/* 6 */}
        <h2 data-section="6">6. 선택지별 세부담·리스크 비교표</h2>
        <table className="grid">
          <thead>
            <tr>
              <th>선택지</th>
              <th>예상 세부담</th>
              <th>과세논리</th>
              <th>방어논리</th>
            </tr>
          </thead>
          <tbody>
            {draft.strategy_options.map((o) => (
              <tr key={o.option_key}>
                <th scope="row">{o.label}</th>
                <td>{o.expected_tax_burden}</td>
                <td>{o.tax_risk}</td>
                <td>{o.defensibility}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* 7 */}
        <h2 data-section="7">7. 쟁점별 검토 메모</h2>
        {draft.issue_memos.map((m, i) => (
          <div key={i} className="memo">
            <h3>{m.topic}</h3>
            <p>
              {m.analysis}
              <CiteLinks ids={m.citation_ids} />
            </p>
            {m.escalation ? <p className="esc">escalation: {m.escalation}</p> : null}
          </div>
        ))}

        {/* 8 — OUT-007(변경②): 종합 전 채널별 독립 결과(①②③ 병렬, SILENT 정직표기) */}
        <h2 data-section="8">8. 출처 채널별 독립 결과</h2>
        <p className="note">
          종합의견으로 합치기 전, 각 출처 채널의 독립 답변입니다(채널 원본 ⟂ 종합). 답하지 못한
          채널은 SILENT로 정직하게 표기합니다.
        </p>
        <table className="grid" data-testid="draft-channels">
          <thead>
            <tr>
              <th>채널</th>
              <th>출처</th>
              <th>상태</th>
              <th>답변 요지</th>
              <th>인용</th>
            </tr>
          </thead>
          <tbody>
            {draft.channel_results.map((cr) => (
              <tr key={cr.channel} data-testid={`channel-${cr.channel}`}>
                <th scope="row">{cr.channel}</th>
                <td>{cr.source_label}</td>
                <td>
                  <span className={cr.answered ? "ok" : "silent"}>
                    {cr.status}
                    {cr.answered ? "" : " (커버리지 갭)"}
                  </span>
                </td>
                <td>{cr.answer_excerpt || (cr.answered ? "—" : "(근거 없음)")}</td>
                <td>{cr.citation_locators.join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* 9 — 관련 법령·근거 자료 */}
        <h2 data-section="9">9. 관련 법령·근거 자료</h2>
        <ul className="cite-list" data-testid="draft-citations">
          {draft.citations.map((c) => (
            <li key={c.citation_id}>
              <a className="cite-link" href={c.href} target="_blank" rel="noreferrer">
                {c.label}
              </a>{" "}
              <span className="meta">
                · 적용시점 {c.as_of}({c.basis_kind}) · 권위 {c.authority_rank}
              </span>
              <blockquote>“{c.quote.slice(0, 120)}”</blockquote>
            </li>
          ))}
        </ul>

        {/* 10 — OUT-008/HALU-015(변경③): 법령 추적 + 추론 도식(하이브리드: Mermaid) */}
        <h2 data-section="10">10. 법령 추적 경로 + 추론 과정 도식</h2>
        {draft.reasoning_trace ? (
          <>
            <h3>10-1. 추론 과정 (ReasoningTrace · Mermaid)</h3>
            <pre className="mermaid" data-testid="reasoning-mermaid">
              {mermaidFlow(draft.reasoning_trace.steps)}
            </pre>
            <table className="grid" data-testid="reasoning-steps">
              <thead>
                <tr>
                  <th>#</th>
                  <th>단계</th>
                  <th>판단·근거</th>
                  <th>인용</th>
                </tr>
              </thead>
              <tbody>
                {draft.reasoning_trace.steps.map((s) => (
                  <tr key={s.seq}>
                    <td>{s.seq}</td>
                    <td>{s.stage}</td>
                    <td>{s.decision}</td>
                    <td>{s.citation_locators.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>10-2. 법령 추적 경로 (law-tracing)</h3>
            <table className="grid" data-testid="law-trace">
              <thead>
                <tr>
                  <th>쟁점</th>
                  <th>법령·조문</th>
                  <th>적용시점</th>
                  <th>pinpoint</th>
                </tr>
              </thead>
              <tbody>
                {draft.reasoning_trace.law_trace.map((e, i) => (
                  <tr key={i}>
                    <td>{e.issue}</td>
                    <td>
                      {e.law_name} {e.article}
                    </td>
                    <td>
                      {e.as_of}
                      {e.basis_kind ? `(${e.basis_kind})` : ""}
                    </td>
                    <td>{e.locator}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}

        {/* 11 — 추가 요청 자료 */}
        <h2 data-section="11">11. 추가 요청 자료</h2>
        <ul>
          {draft.additional_requests.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>

        {/* 12 — 회계사 검토 필요사항 */}
        <h2 data-section="12">12. 회계사 검토 필요사항</h2>
        <ul data-testid="draft-review-items">
          {draft.review_items.map((it) => (
            <li key={it.item_id}>
              <code>
                [{it.gate ?? "-"}/{it.category}/{it.severity}]
              </code>{" "}
              {it.requires_warning ? <span className="warn">⚠검토경고</span> : null} {it.description}
            </li>
          ))}
        </ul>

        {/* 13 — 결론 초안·추천 검토 순서 */}
        <h2 data-section="13">13. 결론 초안·추천 검토 순서</h2>
        <p>{draft.conclusion}</p>
        <ol>
          {draft.recommended_order.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </article>
    </section>
  );
}
