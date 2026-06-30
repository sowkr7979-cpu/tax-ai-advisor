# 내부 RAG DB (공개 세무 실무 가이드 코퍼스)

이 폴더는 **온프렘 RAG 검색**을 위한 공개 세무 실무 가이드 PDF 코퍼스입니다. 원본 PDF와
임베딩 인덱스(`_index/`)는 **용량이 크고(약 317MB) 제3자 발행물**이라 형상관리(git)에서
제외합니다(`.gitignore`). 코드·빌드 스크립트·이 README 만 추적합니다.

## 구성

- `*.pdf` — 국세청·국세상담센터·공공기관 등의 공개 세무 가이드/안내서(31종). 스캔본(텍스트
  레이어 0)은 빌드 시 **온프렘 OCR**(Ghostscript 렌더 → Tesseract `kor`)로 본문을 확보합니다.
- `_index/` — 빌드 산출물(런타임 데이터, gitignore):
  - `vectors.npy` — (N, 256) float32 L2정규화 임베딩 행렬(model2vec, on-prem).
  - `chunks.jsonl` — 청크 본문·출처(`<파일명> p.<페이지>`)·세목(벡터와 동일 순서).
  - `manifest.json` — 완료 표식(모델·차원·파일목록·OCR 적용·content hash). **마지막에 기록**.

## 인덱스 빌드

```bash
# 온프렘 임베딩(model2vec) + 스캔본 OCR(Ghostscript + Tesseract kor) → numpy 코사인 인덱스
PYTHONUTF8=1 python scripts/build_rag_db_index.py            # OCR 포함(기본)
PYTHONUTF8=1 python scripts/build_rag_db_index.py --no-ocr   # 텍스트 PDF만
```

스캔본 OCR을 쓰려면(선택): Ghostscript + Tesseract(+ 한국어 데이터 `kor.traineddata`)가
설치돼 있어야 합니다(미설치 시 해당 PDF 는 정직하게 skip). 외부 전송 0(전부 로컬 프로세스).

빌드 후 회수는 `src.rag_db_index.load_index()` / `query_rag_db(...)` 로 사용하며, 매니페스트·
content hash·차원·행 수를 전수 대조해 **fail-closed** 합니다(부분/손상 인덱스 차단).

## 출처·라이선스

수록 PDF 는 각 발행기관의 공개 자료입니다. 재배포 조건은 발행처 정책을 따르며, 본 저장소는
**원본을 포함하지 않습니다**(각자 내려받아 이 폴더에 위치).
