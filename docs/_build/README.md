# 쉬운설명 PDF 빌드 키트 (`docs/_build/`)

`docs/*_쉬운설명.pdf`(비개발자 KICPA용 도식 해설본 9종)를 **재생성**하는 도구 모음.
세션 임시폴더가 아니라 여기(레포 내부)에 보관하므로, 언제든 본문만 고쳐 다시 빌드할 수 있다.

## 구성
| 파일 | 역할 |
|---|---|
| `build_pdf.py` | 빌더 — CSS 주입 → Edge headless 인쇄 → PyMuPDF 정규화(Adobe 호환) → 검증 |
| `rfp_explainer.html` | **CSS 템플릿**(모든 PDF 공용 스타일의 원천). 03의 원본 전체 HTML이기도 함 |
| `body_01.html` … `body_09.html` · `body_unified.html` | 각 문서의 **본문 fragment**(`.page` div들). 여기만 고치면 됨 |

> 문서↔파일: 01 보안 · 02 출처/시점 · 03 RFP · 04 ERD · 05 내부RAG · 06 웹 · 07 외부API · 08 환각방지 · 09 채점표 · **unified = 통합 서사 설계서**(출력은 `md 파일/법인세_세무AI_설계서_통합_쉬운설명.pdf`, --stem docunified) · **understand = 설계 동작·기술 해설(16쪽) + 면접 Q&A**(출력은 `md 파일/법인세_세무AI_설계서_통합_프로그램이해_면접질답.pdf`, --stem docunderstand; 동반 마크다운 `md 파일/면접_질답_TIW_프로그램설계.md`).
>
> *unified vs understand: unified=왜/어떻게 다르게(전략·포지셔닝 서사), understand=어떻게 동작하나(아키텍처·동작·개발용어 해부)+면접 질답.*
>
> **product = 검토자(면접관)용 제품·시스템 설계 개요(12쪽)** — 지원자 개인 서사(왜 나·면접 질답·자기홍보) 전부 제거한 중립 3인칭 제품 문서. 출력 `md 파일/법인세_세무AI_TIW_제품설계_개요_검토자용.pdf`, --stem docproduct. (understand에서 서사 제거+중립화한 파생본.)

## 재생성 (1건)
```bash
cd "docs/_build"
PYTHONUTF8=1 python build_pdf.py \
  --body body_03.html \
  --out "../03_RFP_기능요구사항_쉬운설명.pdf" \
  --stem doc03 \
  --title "법인세 세무 AI (TIW) — RFP·기능요구사항 쉬운 설명"
```
마지막 줄 JSON에서 `"ok": true, "repaired": false` 확인. (`repaired:false` = Adobe Acrobat 정상 오픈)

## 재생성 (9종 일괄)
`build_all` 한 줄이 없으므로 위 명령을 body/out/stem만 바꿔 9번 실행(또는 셸 루프).
- out 파일명 = `../NN_<원래이름>_쉬운설명.pdf`, stem = `docNN`.

## 작동 원리 / 주의
- **본문만 수정**: 스타일(CSS)은 `build_pdf.py`가 `rfp_explainer.html`의 `<style>`을 자동 주입. body_*.html에 **새 CSS 클래스를 만들지 말 것**(템플릿 클래스만 사용). 색이 더 필요하면 inline style.
- **함정**: Git Bash 경로(`/c/...`)를 file URL에 그대로 넣으면 Edge가 빈 페이지를 만든다 → `build_pdf.py`가 Windows `file:///C:/...`로 변환해 처리(직접 명령 짤 때 주의).
- **한글 출력경로** OK: Edge는 ASCII 임시파일로 만들고 최종본만 `shutil`로 한글 경로에 복사.
- **요구 환경**: Microsoft Edge(또는 Chrome) + Python + PyMuPDF(`pip install pymupdf`). 한글 폰트 Malgun Gothic.

## 페이지 번호
각 `.page` 끝 `<div class="pgnote">… — N / M</div>`. 페이지를 추가/삭제하면 분모 M과 이후 N을 손으로 맞춰야 한다.
