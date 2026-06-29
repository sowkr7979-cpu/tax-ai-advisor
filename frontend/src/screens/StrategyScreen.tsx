// 화면② 선택지 비교표 (§3-5) — 보수/중립/적극 × (세부담·과세리스크·방어가능성·증빙·검토포인트).
import { citationIndex } from "../data";
import type { Draft } from "../types";

export function StrategyScreen({ draft }: { draft: Draft }) {
  return (
    <section className="screen" data-testid="screen-strategy">
      <h1>② 선택지 비교표 — 과세논리 vs 방어논리</h1>
      <p className="goal">
        {draft.company_name} · {draft.fiscal_year} · 기준일 {draft.as_of_date}
      </p>

      <table className="grid strategy" data-testid="strategy-table">
        <thead>
          <tr>
            <th>선택지</th>
            <th>예상 세부담</th>
            <th>세무 리스크(과세논리)</th>
            <th>방어 가능성(방어논리)</th>
            <th>필요 증빙</th>
            <th>회계사 검토 포인트</th>
            <th>근거</th>
          </tr>
        </thead>
        <tbody>
          {draft.strategy_options.map((o) => (
            <tr key={o.option_key} data-testid={`strategy-row-${o.option_key}`}>
              <th scope="row">{o.label}</th>
              <td className="num" data-testid={`burden-${o.option_key}`}>
                {o.expected_tax_burden}
              </td>
              <td>{o.tax_risk}</td>
              <td>{o.defensibility}</td>
              <td>{o.required_evidence}</td>
              <td>{o.cpa_review_point}</td>
              <td className="cite-cell">
                {o.citation_ids.map((cid) => {
                  const c = citationIndex[cid];
                  return c ? (
                    <a key={cid} className="cite-link" href={c.href} target="_blank" rel="noreferrer">
                      {c.label}
                    </a>
                  ) : null;
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="callout" data-testid="strategy-guardrail">
        적극 선택지 가드레일(AGT-008): 과세논리·방어논리 양면 적시 + 회계사(Reviewer) 승인
        없이는 고객 전달본 포함 금지. 미해소 충돌·시점 가정은 단정하지 않고 회계사 검토로 승격.
      </div>
    </section>
  );
}
