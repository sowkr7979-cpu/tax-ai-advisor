// 백엔드 산출 fixture 를 빌드 타임에 로드(더미/빈 화면 금지 — 실제 데이터 렌더).
import fixtureJson from "../fixtures/draft_package.json";
import type { CitationView, Fixture } from "./types";

export const fixture = fixtureJson as unknown as Fixture;

// citation_id → CitationView 인덱스 (인용 링크 렌더용)
export const citationIndex: Record<string, CitationView> = Object.fromEntries(
  fixture.draft.citations.map((c) => [c.citation_id, c]),
);
