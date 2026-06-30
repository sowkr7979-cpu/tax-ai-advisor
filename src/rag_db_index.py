"""src/rag_db_index.py — 내부 RAG DB(세무 실무 가이드 PDF) → 임베딩 → 영속 벡터 DB.

``RAG DB/`` 폴더의 공개 세무 실무 가이드 PDF를 **페이지 단위**로 추출·청크하고, 로컬
on-prem 임베더(model2vec, ``minishlab/potion-multilingual-128M``)로 임베딩하여 **영속
numpy 코사인 인덱스**(벡터행렬 ``.npy`` + 사이드카 ``.jsonl``)로 저장한다.

설계 원칙
---------
* 온프렘 임베딩 — 벡터는 전부 로컬 model2vec 로 계산한다(외부 임베딩 전송 0).
* 공유 참고지식 — 가이드 PDF 는 공개자료이므로 테넌트 격리가 불필요하다. 모든 청크가
  ``L0_PUBLIC`` 동급의 공유 참고지식이다.
* 출처 보존 — 각 청크의 ``source_locator`` 에 ``"<파일명> p.<페이지>"`` 를 박아
  RAG 답변이 어느 가이드 몇 페이지에서 왔는지 추적 가능하게 한다(날조 차단).
* 영속/재개 — 벡터(L2정규화 행렬)는 ``vectors.npy`` 에, 청크 본문/출처/세목은 사이드카
  ``chunks.jsonl`` 에 **동일 순서**로 저장한다. ``load_index`` 는 둘을 함께 복원하고
  매니페스트(완료 표식)의 모델·차원과 행 수를 대조해 fail-closed 한다.

회수는 질의를 model2vec 로 1회 임베딩한 뒤 벡터행렬과 코사인(내적; 벡터가 L2정규화되어
dot=cosine) 으로 top-k 를 뽑는다. 가이드 passage 는 법령 조문이 아니므로 단정 답변을
합성하지 않고 **회수된 passage 와 출처**만 제공한다(웹/RAG 단독 단정 금지 원칙과 일관).

설계 메모: 초기에 chromadb PersistentClient 로 영속하려 했으나, 1.5.9 의 비동기 compactor
가 대용량 HNSW 세그먼트를 close 시 디스크에 flush 하지 않아(.bin 미생성) 다른 프로세스
재오픈에서 'Error loading hnsw index' 로 깨졌다. 공개 코퍼스라 격리가 불필요하므로 단순·
견고한 numpy 코사인으로 전환했다(로딩/질의 빠름·결정적).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from contract.base import ConfidentialityLevel
from src.ai.base import Embedder
from src.chunking import RagChunk

# repo root = .../src/rag_db_index.py → parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[1]
RAG_DB_DIR = _REPO_ROOT / "RAG DB"
RAG_INDEX_DIR = RAG_DB_DIR / "_index"            # 영속 산출물(런타임 데이터, gitignore)
RAG_SIDECAR = RAG_INDEX_DIR / "chunks.jsonl"     # 청크 본문/메타(라인=청크, 벡터와 동일 순서)
RAG_VECTORS = RAG_INDEX_DIR / "vectors.npy"      # (N, D) float32 L2정규화 임베딩 행렬
RAG_MANIFEST = RAG_INDEX_DIR / "manifest.json"
RAG_DOC_TYPE = "실무가이드"

# 파일명 키워드 → 세목(메타필터/표시용). 매칭 안 되면 '법인세'.
_TAX_TYPE_HINTS: list[tuple[str, str]] = [
    ("양도소득", "양도소득세"), ("증여", "증여세"), ("상속", "상속세"),
    ("가업승계", "상속세"), ("비상장주식", "상속세"), ("자본거래", "법인세"),
    ("최저한세", "법인세"), ("구조조정", "법인세"), ("비영리", "법인세"),
    ("공익법인", "상속세"), ("지방세", "지방세"), ("해외", "국제조세"),
    ("국제", "국제조세"), ("부가가치", "부가가치세"), ("종합소득", "소득세"),
    ("소득세", "소득세"), ("개정세법", "법인세"), ("중소기업", "법인세"),
    ("건물 기준시가", "양도소득세"),
]


def _guess_tax_type(stem: str) -> str:
    for kw, tt in _TAX_TYPE_HINTS:
        if kw in stem:
            return tt
    return "법인세"


_WS_RE = re.compile(r"[ \t ]+")
_BLANK_RE = re.compile(r"\n{2,}")


def _clean(text: str) -> str:
    # 손상 PDF 글리프가 만든 surrogate/비인코딩 문자 제거(UnicodeEncodeError 방지)
    text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    text = text.replace("\r", "\n").replace("\x00", "")
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n", text)
    return text.strip()


def _window(text: str, *, size: int, overlap: int) -> list[str]:
    """페이지 본문을 ~size 자 창(겹침 overlap)으로 분할. 문단 경계를 우선 존중한다."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 가까운 문단/문장 경계에서 끊기(가독성·인용 정확성)
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("다. "))
            if cut > size * 0.5:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


# --------------------------------------------------------------------------- #
# OCR (스캔본/이미지전용 PDF) — 온프렘 Ghostscript 렌더 + Tesseract(한국어)
# --------------------------------------------------------------------------- #
# 일부 RAG DB PDF(예: 세법해석 사례집)는 텍스트 레이어가 0인 **스캔 이미지**라 pypdf 로는
# 본문이 안 나온다. 외부 전송 없이(온프렘) 본문을 확보하기 위해 Ghostscript 로 페이지를
# 그레이스케일 PNG 로 렌더한 뒤 Tesseract(kor)로 OCR 한다. 엔진·버전·DPI 고정 시 결정적.
def _find_executable(names: list[str], globs: list[str]) -> Optional[str]:
    import glob as _glob
    from shutil import which

    for n in names:
        p = which(n)
        if p:
            return p
    for g in globs:
        hits = sorted(_glob.glob(g))
        if hits:
            return hits[-1]            # 여러 버전이면 최신(정렬 마지막)
    return None


def _find_ghostscript() -> Optional[str]:
    return _find_executable(
        ["gswin64c", "gswin64c.exe", "gs"],
        [r"C:\Program Files\gs\*\bin\gswin64c.exe",
         r"C:\Program Files (x86)\gs\*\bin\gswin64c.exe"],
    )


def _find_tesseract() -> Optional[str]:
    return _find_executable(
        ["tesseract", "tesseract.exe"],
        [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
         r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"],
    )


def _find_tessdata() -> Optional[str]:
    import os

    cands = [os.environ.get("TESSDATA_PREFIX"),
             str(Path.home() / "tessdata"),
             r"C:\Program Files\Tesseract-OCR\tessdata"]
    for d in cands:
        if d and (Path(d) / "kor.traineddata").exists():
            return d
    return None


def ocr_available() -> bool:
    """온프렘 OCR(Ghostscript + Tesseract + 한국어 데이터)이 모두 준비됐는지."""
    return bool(_find_ghostscript() and _find_tesseract() and _find_tessdata())


class OcrError(RuntimeError):
    """OCR 도구 실패(Ghostscript/Tesseract 비정상 종료) — 호출측이 해당 PDF 를 fail-closed skip."""


def _ocr_pdf(pdf_path: Path, *, dpi: int = 300, lang: str = "kor") -> list[tuple[int, str]]:
    """스캔 PDF → (페이지번호, OCR본문) 목록. 도구 부재 시 빈 목록(호출측이 skip 처리).

    Ghostscript 로 전 페이지를 한 번에 그레이스케일 PNG 로 렌더(프로세스 1회 — 빠름)한 뒤
    페이지별 Tesseract OCR. 외부 전송 0(전부 로컬 프로세스).

    **fail-closed(codex 적발)**: Ghostscript 또는 어느 한 페이지라도 Tesseract 가 **비정상
    종료(returncode≠0)** 하면 ``OcrError`` 를 던진다 — 부분 stdout 을 ‘성공한 OCR’ 로 조용히
    집계하지 않는다(불완전 인식을 정상으로 위장 금지). 호출측은 이 PDF 를 skip 처리한다."""
    import shutil
    import subprocess
    import tempfile

    gs = _find_ghostscript()
    tess = _find_tesseract()
    tdir = _find_tessdata()
    if not (gs and tess and tdir):
        return []
    out: list[tuple[int, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="ragocr_"))
    try:
        gres = subprocess.run(
            [gs, "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dSAFER",
             "-sDEVICE=pnggray", f"-r{dpi}",
             "-sOutputFile=" + str(tmp / "p-%05d.png"), str(pdf_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if gres.returncode != 0:
            raise OcrError(f"Ghostscript 렌더 실패(rc={gres.returncode}): {pdf_path.name}")
        for png in sorted(tmp.glob("p-*.png")):
            try:
                pageno = int(png.stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            res = subprocess.run(
                [tess, str(png), "stdout", "-l", lang, "--tessdata-dir", tdir, "--psm", "3"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore",
            )
            if res.returncode != 0:
                # 한 페이지라도 비정상 종료 → PDF 전체 fail-closed(부분 성공 위장 금지)
                raise OcrError(
                    f"Tesseract 실패(rc={res.returncode}, p.{pageno}): {pdf_path.name}")
            txt = res.stdout or ""
            if txt.strip():
                out.append((pageno, txt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _emit_windows(
    chunks: list, stem: str, tax_type: str, pageno: int, body: str,
    *, size: int, overlap: int, min_chars: int, src_suffix: str = "",
) -> None:
    """페이지 본문을 창분할해 RagChunk 들을 ``chunks`` 에 적재(추출/OCR 공통)."""
    for wi, win in enumerate(_window(body, size=size, overlap=overlap)):
        if len(win) < min_chars:
            continue
        chunks.append(
            RagChunk(
                chunk_id=f"ragdb::{stem}::p{pageno:04d}::w{wi}",
                text=win,
                doc_type=RAG_DOC_TYPE,
                confidentiality_level=ConfidentialityLevel.L0_PUBLIC,
                client_id=None,
                source_locator=f"{stem} p.{pageno}{src_suffix}",
                tax_type=tax_type,
            )
        )


def extract_chunks(
    pdf_dir: Path = RAG_DB_DIR,
    *,
    size: int = 1100,
    overlap: int = 160,
    min_chars: int = 40,
    return_skipped: bool = False,
    enable_ocr: bool = True,
    ocr_dpi: int = 300,
    progress: bool = False,
):
    """``RAG DB/`` PDF 들을 페이지 단위로 추출→정제→창분할한 SHARED 참고 청크 목록.

    각 청크는 ``L0_PUBLIC`` · ``client_id=None`` (공유 참고지식)이며 출처(파일명·페이지)를
    ``source_locator`` 에 보존한다. 텍스트 레이어가 0인 스캔 PDF 는 ``enable_ocr`` 시 온프렘
    OCR(Ghostscript+Tesseract)로 본문을 확보하고 출처에 ``(OCR)`` 를 표시한다. PDF 리더는
    지연 임포트한다. ``return_skipped`` 면 (청크, 추출실패목록, OCR적용목록) 3튜플을 반환한다
    (코퍼스 품질 가시화 — silent 누락 방지)."""
    from pypdf import PdfReader

    pdfs = sorted(p for p in Path(pdf_dir).glob("*.pdf"))
    chunks: list[RagChunk] = []
    skipped: list[str] = []
    ocr_files: list[str] = []
    for pdf in pdfs:
        stem = pdf.stem
        tax_type = _guess_tax_type(stem)
        try:
            reader = PdfReader(str(pdf))
        except Exception:  # noqa: BLE001 - 손상 PDF 는 건너뛰되 나머지는 색인
            skipped.append(stem)
            continue
        before = len(chunks)
        for pageno, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                raw = ""
            body = _clean(raw)
            if len(body) < min_chars:
                continue
            _emit_windows(chunks, stem, tax_type, pageno, body,
                          size=size, overlap=overlap, min_chars=min_chars)
        if len(chunks) == before:           # 텍스트가 전혀 안 나온 PDF(이미지 전용/스캔본)
            if enable_ocr and ocr_available():
                if progress:
                    print(f"  🔍 OCR(스캔본): {stem} … (페이지 렌더+인식)", flush=True)
                try:
                    ocr_pages = _ocr_pdf(pdf, dpi=ocr_dpi)
                except OcrError as exc:
                    # OCR 도구 실패 → 부분 결과를 성공으로 위장하지 않고 PDF 전체 skip(fail-closed)
                    ocr_pages = None
                    if progress:
                        print(f"     ↳ OCR 실패(skip): {exc}", flush=True)
                if ocr_pages:
                    for pageno, raw in ocr_pages:
                        body = _clean(raw)
                        if len(body) < min_chars:
                            continue
                        _emit_windows(chunks, stem, tax_type, pageno, body,
                                      size=size, overlap=overlap, min_chars=min_chars,
                                      src_suffix=" (OCR)")
                if len(chunks) > before:
                    ocr_files.append(stem)
                    if progress:
                        print(f"     ↳ OCR 완료: {stem} (+{len(chunks) - before} 청크)", flush=True)
                else:
                    skipped.append(stem)        # OCR 실패/본문 0 → 정직하게 skip
            else:
                skipped.append(stem)
    if return_skipped:
        return chunks, skipped, ocr_files
    return chunks


# --------------------------------------------------------------------------- #
# Build (embed → numpy 벡터행렬 + 사이드카 + manifest)
# --------------------------------------------------------------------------- #
# 영속은 **온프렘 numpy 코사인 인덱스**로 한다(외부 벡터DB 미사용). 이유: chromadb 1.5.9
# 의 PersistentClient 는 HNSW 세그먼트를 비동기 compactor 가 빌드하는데, 빌드 프로세스가
# close 할 때 대용량(수천~만 벡터) 세그먼트가 디스크에 flush 되지 않아(.bin 미생성) 다른
# 프로세스에서 재오픈 시 'Error loading hnsw index' 로 깨진다. 가이드 코퍼스는 전부 공개
# (SHARED·L0) 라 테넌트 격리가 불필요하므로, 벡터를 .npy 로 저장하고 질의 시 model2vec
# 임베딩 1회 + 코사인 내적(벡터는 L2정규화되어 dot=cosine)으로 top-k 를 뽑는다. 결정적·
# 견고하며 로딩/질의가 빠르다(외부 임베딩 전송 0 — 온프렘).
def _default_embedder() -> Embedder:
    """온프렘 실임베더(model2vec). 무거운 임포트는 사용 시점에만."""
    from src.ai.embedding_client import Model2VecEmbedder

    return Model2VecEmbedder()


def build_index(
    *,
    pdf_dir: Path = RAG_DB_DIR,
    sidecar: Path = RAG_SIDECAR,
    vectors_path: Path = RAG_VECTORS,
    manifest: Path = RAG_MANIFEST,
    embedder: Optional[Embedder] = None,
    built_at: Optional[date] = None,
    batch: int = 1000,
    progress: bool = True,
    ocr_dpi: int = 300,
) -> dict:
    """RAG DB PDF → 청크 → 임베딩(model2vec) → 벡터행렬(.npy) + 사이드카 + 매니페스트.

    벡터는 전부 로컬에서 계산한다(외부 임베딩 전송 0). 매니페스트는 **마지막에** 기록하는
    완료 표식이다. 결정적이므로 같은 입력이면 같은 인덱스."""
    import numpy as np

    embedder = embedder if embedder is not None else _default_embedder()
    chunks, skipped, ocr_files = extract_chunks(
        pdf_dir, return_skipped=True, progress=progress, ocr_dpi=ocr_dpi)
    if not chunks:
        raise RuntimeError(f"RAG DB PDF에서 추출된 청크가 0건입니다: {pdf_dir}")
    if ocr_files and progress:
        print(f"  🔍 OCR 적용 PDF {len(ocr_files)}건: {', '.join(ocr_files)}", flush=True)
    if skipped and progress:
        print(f"  ⚠ 추출 실패/스킵 PDF {len(skipped)}건: {', '.join(skipped)}", flush=True)

    import hashlib
    import os

    RAG_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    dim = int(getattr(embedder, "dimension", 0) or len(embedder.embed("차원")))
    mat = np.zeros((len(chunks), dim), dtype="float32")

    # 원자적 쓰기: 임시파일에 먼저 쓰고, 사이드카·벡터를 교체한 뒤 **매니페스트를 마지막에**
    # 교체한다. 매니페스트에 사이드카·벡터의 content hash 를 박아, 부분-덮어쓰기(크래시)로
    # 인한 사이드카↔벡터 불일치(행 수는 같지만 내용이 어긋남)를 load 시 fail-closed 한다.
    sidecar_tmp = sidecar.with_name(sidecar.name + ".tmp")
    vectors_tmp = RAG_INDEX_DIR / "vectors.tmp.npy"
    manifest_tmp = manifest.with_name(manifest.name + ".tmp")

    with sidecar_tmp.open("w", encoding="utf-8") as fh:
        for i, ch in enumerate(chunks):
            mat[i] = np.asarray(embedder.embed(ch.text), dtype="float32")
            fh.write(json.dumps({
                "chunk_id": ch.chunk_id, "text": ch.text, "doc_type": ch.doc_type,
                "source_locator": ch.source_locator, "tax_type": ch.tax_type,
            }, ensure_ascii=False) + "\n")
            if progress and (i + 1) % batch == 0:
                print(f"  …임베딩 {i + 1}/{len(chunks)} 청크", flush=True)
    # L2 정규화(혹시 미정규화 임베더 대비) → 질의 dot = cosine
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat = (mat / norms).astype("float32")
    np.save(vectors_tmp, mat)

    sidecar_sha = hashlib.sha256(sidecar_tmp.read_bytes()).hexdigest()
    vectors_sha = hashlib.sha256(vectors_tmp.read_bytes()).hexdigest()

    files = sorted({c.source_locator.rsplit(" p.", 1)[0] for c in chunks})
    pages = len({c.source_locator for c in chunks})
    stats = {
        "built_at": (built_at or date.today()).isoformat() if built_at else None,
        "model": getattr(embedder, "model_name", "unknown"),
        "dimension": dim,
        "files": len(files),
        "file_names": files,
        "pages_with_text": pages,
        "chunks": len(chunks),
        "ocr_files": ocr_files,
        "skipped_files": skipped,
        "backend": "numpy-cosine",
        "vectors": str(vectors_path),
        "sidecar_sha256": sidecar_sha,
        "vectors_sha256": vectors_sha,
    }
    # 사이드카·벡터를 먼저 교체하고(원자적), 완료 표식인 매니페스트를 **마지막에** 교체.
    os.replace(sidecar_tmp, sidecar)
    os.replace(vectors_tmp, vectors_path)
    manifest_tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(manifest_tmp, manifest)
    return stats


# --------------------------------------------------------------------------- #
# Load (사이드카 + 벡터행렬 복원 → 온프렘 코사인 retriever)
# --------------------------------------------------------------------------- #
def _reload_sidecar(sidecar: Path) -> tuple[list[str], list[str], list[str]]:
    """(texts, sources, tax_types) — 벡터행렬과 **동일 순서**."""
    texts: list[str] = []
    sources: list[str] = []
    tax_types: list[str] = []
    if not sidecar.exists():
        return texts, sources, tax_types
    with sidecar.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            texts.append(d["text"])
            sources.append(d.get("source_locator") or d.get("chunk_id", ""))
            tax_types.append(d.get("tax_type") or "")
    return texts, sources, tax_types


@dataclass
class RagDbStore:
    """온프렘 코사인 retriever — 사이드카 텍스트/출처 + L2정규화 벡터행렬."""

    texts: list
    sources: list
    tax_types: list
    vectors: "object"            # numpy.ndarray (N, D) float32, L2정규화
    embedder: Embedder

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        import numpy as np

        if top_k <= 0:
            return []
        qv = np.asarray(self.embedder.embed(query), dtype="float32")
        n = float(np.linalg.norm(qv))
        if n:
            qv = qv / n
        sims = self.vectors @ qv                       # (N,) cosine
        k = min(top_k, sims.shape[0])
        if k <= 0:
            return []
        # argpartition 으로 상위 k 후보를 뽑은 뒤 그 안에서만 내림차순 정렬(전체정렬 회피).
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [(int(i), float(sims[i])) for i in idx]


def load_index(
    *,
    sidecar: Path = RAG_SIDECAR,
    vectors_path: Path = RAG_VECTORS,
    manifest: Path = RAG_MANIFEST,
    embedder: Optional[Embedder] = None,
) -> RagDbStore:
    """사이드카 + 벡터행렬을 복원해 회수 가능한 ``RagDbStore`` 를 연다.

    매니페스트(완료 표식)·벡터파일·사이드카가 모두 있어야 하며, 빌드 임베더와 **모델·차원이
    다르면** 질의/문서 벡터 정렬이 깨지므로 fail-closed 한다. 행/사이드카 라인 수 불일치도
    fail-closed(부분 빌드 차단)."""
    import numpy as np

    if not manifest.exists():
        raise FileNotFoundError(
            f"RAG DB 매니페스트가 없습니다: {manifest} — 빌드 미완료/중단. build_index() 재빌드 필요.")
    if not vectors_path.exists():
        raise FileNotFoundError(f"RAG DB 벡터파일이 없습니다: {vectors_path} — 재빌드 필요.")
    embedder = embedder if embedder is not None else _default_embedder()
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if m.get("dimension") != getattr(embedder, "dimension", None):
        raise RuntimeError(
            f"RAG DB 임베딩 차원 불일치(index={m.get('dimension')} vs "
            f"loader={getattr(embedder, 'dimension', None)}) — 인덱스를 재빌드하세요.")
    if m.get("model") != getattr(embedder, "model_name", "unknown"):
        raise RuntimeError(
            f"RAG DB 임베딩 모델 불일치(index={m.get('model')} vs "
            f"loader={getattr(embedder, 'model_name', None)}) — 인덱스를 재빌드하세요.")
    # content hash 대조(부분-덮어쓰기로 인한 사이드카↔벡터 불일치 차단). 매니페스트에
    # 해시가 있으면(신규 빌드) 반드시 일치해야 한다(없으면 구버전 인덱스 — 행수 검증으로 폴백).
    import hashlib

    if not sidecar.exists():
        raise FileNotFoundError(
            f"RAG DB 사이드카가 없습니다: {sidecar} — 재빌드 필요(fail-closed).")
    exp_sc = m.get("sidecar_sha256")
    exp_vec = m.get("vectors_sha256")
    if exp_sc is not None:
        got_sc = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        if got_sc != exp_sc:
            raise RuntimeError(
                f"RAG DB 사이드카 해시 불일치 — 부분 덮어쓰기/손상 의심. 재빌드 필요(fail-closed).")
    if exp_vec is not None:
        got_vec = hashlib.sha256(vectors_path.read_bytes()).hexdigest()
        if got_vec != exp_vec:
            raise RuntimeError(
                f"RAG DB 벡터 해시 불일치 — 부분 덮어쓰기/손상 의심. 재빌드 필요(fail-closed).")

    texts, sources, tax_types = _reload_sidecar(sidecar)
    if not texts:
        raise FileNotFoundError(
            f"RAG DB 사이드카가 없거나 비었습니다: {sidecar} — 회수 0건 fail-closed. 재빌드 필요.")
    vectors = np.load(vectors_path)
    if vectors.ndim != 2:
        raise RuntimeError(f"RAG DB vectors.npy 가 2차원 행렬이 아닙니다(ndim={vectors.ndim}) — 재빌드 필요.")
    if vectors.shape[0] != len(texts):
        raise RuntimeError(
            f"RAG DB 벡터({vectors.shape[0]})와 사이드카({len(texts)}) 행 수 불일치 — 재빌드 필요.")
    if vectors.shape[1] != m.get("dimension"):
        raise RuntimeError(
            f"RAG DB 벡터 차원 불일치(vectors={vectors.shape[1]} vs manifest={m.get('dimension')}) — 재빌드 필요.")
    if vectors.dtype != np.float32:
        raise RuntimeError(f"RAG DB 벡터 dtype 불일치({vectors.dtype} != float32) — 재빌드 필요.")
    return RagDbStore(texts=texts, sources=sources, tax_types=tax_types,
                      vectors=vectors, embedder=embedder)


def close_index(index: Optional[object]) -> None:
    """API 호환용 — numpy 백엔드는 닫을 OS 핸들이 없다(no-op)."""
    return None


# --------------------------------------------------------------------------- #
# Retrieval-only RAG answer over the guide corpus (출처 페이지 인용)
# --------------------------------------------------------------------------- #
@dataclass
class RagDbPassage:
    rank: int
    text: str
    source: str           # "<파일명> p.<페이지>"
    score: float
    tax_type: Optional[str]


@dataclass
class RagDbResult:
    question: str
    passages: list[RagDbPassage]

    @property
    def grounded(self) -> bool:
        return bool(self.passages)

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for p in self.passages:
            if p.source not in seen:
                seen.append(p.source)
        return seen


def query_rag_db(
    index: RagDbStore,
    question: str,
    *,
    as_of: Optional[date] = None,
    top_k: int = 5,
) -> RagDbResult:
    """가이드 코퍼스에서 질의 관련 passage 를 회수해 출처(파일·페이지)와 함께 반환한다.

    법령 조문이 아니므로 단정 답변을 합성하지 않고 **회수된 근거 passage 와 출처**만
    제공한다(웹/RAG 단독 단정 금지 원칙과 일관). 상위 종합엔진/렌더러가 이를 RAG 채널
    근거로 사용한다. as_of 는 API 호환용(공개 가이드는 비시점)."""
    hits = index.search(question, top_k=top_k)
    passages = [
        RagDbPassage(
            rank=rank + 1,
            text=index.texts[i],
            source=index.sources[i] or f"chunk#{i}",
            score=round(float(score), 4),
            tax_type=index.tax_types[i] or None,
        )
        for rank, (i, score) in enumerate(hits)
    ]
    return RagDbResult(question=question, passages=passages)
