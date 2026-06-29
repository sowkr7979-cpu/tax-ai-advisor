// 화면③ DOCX 검토패키지 미리보기 — 11목차 구조 + 근거(법령/예규) 인용 링크.
import { citationIndex } from "../data";
import type { Draft } from "../types";

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
      <h1>③ DOCX 검토패키지 미리보기 (11목차)</h1>
      <p className="goal">
        {draft.company_name} {draft.fiscal_year} 법인세 검토패키지 초안 · 기준일 {draft.as_of_date}
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

        {/* 8 */}
        <h2 data-section="8">8. 관련 법령·근거 자료</h2>
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

        {/* 9 */}
        <h2 data-section="9">9. 추가 요청 자료</h2>
        <ul>
          {draft.additional_requests.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>

        {/* 10 */}
        <h2 data-section="10">10. 회계사 검토 필요사항</h2>
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

        {/* 11 */}
        <h2 data-section="11">11. 결론 초안·추천 검토 순서</h2>
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
