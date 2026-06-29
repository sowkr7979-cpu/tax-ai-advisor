import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(__dirname, "..", "screenshots");
mkdirSync(SHOTS, { recursive: true });

// PROMPT.md §2.4 '렌더' 인정 기준: 각 화면 = 스크린샷 + 핵심 텍스트/테이블/근거링크 assertion.
// (빈 페이지·더미 텍스트 ✕ — 실제 fixture 데이터가 표시되어야 통과)

test("화면① Intake 자료수집 챗 — 인터뷰 루프 + 상태칩 + 마감 한계", async ({ page }) => {
  await page.goto("/#/intake");
  const screen = page.getByTestId("screen-intake");
  await expect(screen).toBeVisible();

  // 인터뷰 루프: bot 질문 + user 답변이 실제로 렌더
  await expect(page.getByText("Intake Agent").first()).toBeVisible();
  await expect(page.getByText("전기(2025) 법인세 신고서가 있나요?")).toBeVisible();

  // 체크리스트 상태(수집/없음/모름/결손) 4종이 모두 표시
  const checklist = page.getByTestId("intake-checklist");
  for (const st of ["수집", "없음", "모름", "결손"]) {
    await expect(checklist.getByText(st, { exact: true }).first()).toBeVisible();
  }

  // 조기 종료 + 마감 정리(검토범위·결손·한계 고지)
  await expect(page.getByTestId("intake-early-stop")).toBeVisible();
  const closing = page.getByTestId("intake-closing");
  await expect(closing.getByText("검토 가능 범위:", { exact: false })).toBeVisible();
  await expect(closing.getByText("자료한계 꼬리표", { exact: false })).toBeVisible();

  await page.screenshot({ path: `${SHOTS}/screen1-intake.png`, fullPage: true });
});

test("화면② 선택지 비교표 — 보수/중립/적극 행 + 세부담 값 + 근거링크", async ({ page }) => {
  await page.goto("/#/strategy");
  const table = page.getByTestId("strategy-table");
  await expect(table).toBeVisible();

  // 보수/중립/적극 3행 존재 + 각 행에 세부담 값(텍스트 비어있지 않음)
  for (const key of ["보수", "중립", "적극"]) {
    await expect(page.getByTestId(`strategy-row-${key}`)).toBeVisible();
    const burden = page.getByTestId(`burden-${key}`);
    await expect(burden).not.toBeEmpty();
  }
  // 구체 세부담 값 표기 확인(증가/중간/감소 + 금액)
  await expect(page.getByTestId("burden-보수")).toContainText("증가");
  await expect(page.getByTestId("burden-적극")).toContainText("감소");

  // 과세논리/방어논리 헤더 + 근거 인용 링크(법령) href
  await expect(table.getByText("세무 리스크(과세논리)")).toBeVisible();
  await expect(table.getByText("방어 가능성(방어논리)")).toBeVisible();
  const cite = table.getByRole("link").first();
  await expect(cite).toHaveAttribute("href", /law\.go\.kr/);

  await page.screenshot({ path: `${SHOTS}/screen2-strategy.png`, fullPage: true });
});

test("화면③ DOCX 검토패키지 미리보기 — 11목차 섹션명 + 근거링크 href", async ({ page }) => {
  await page.goto("/#/draft");
  await expect(page.getByTestId("screen-draft")).toBeVisible();

  // 11목차 TOC 항목 수 = 11
  const tocItems = page.getByTestId("draft-toc").locator("li");
  await expect(tocItems).toHaveCount(11);

  // 핵심 섹션명이 본문 <h2>로 렌더
  const sections = [
    "1. Executive Summary",
    "6. 선택지별 세부담·리스크 비교표",
    "8. 관련 법령·근거 자료",
    "10. 회계사 검토 필요사항",
    "11. 결론 초안·추천 검토 순서",
  ];
  for (const s of sections) {
    await expect(page.getByRole("heading", { name: s })).toBeVisible();
  }

  // 8. 근거: 법령 인용 링크 href (law.go.kr) + 제25조 라벨
  const citeList = page.getByTestId("draft-citations");
  const firstCite = citeList.getByRole("link").first();
  await expect(firstCite).toHaveAttribute("href", /law\.go\.kr\/.+제25조/);
  await expect(citeList).toContainText("기업업무추진비");

  // 10. 검토항목: slice⑤ review_items + 고위험 검토경고(⚠)
  const items = page.getByTestId("draft-review-items");
  await expect(items.getByText("⚠검토경고").first()).toBeVisible();

  await page.screenshot({ path: `${SHOTS}/screen3-draft.png`, fullPage: true });
});
