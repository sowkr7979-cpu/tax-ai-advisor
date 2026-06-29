#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TIW 쉬운설명 PDF 빌더 (비개발자 KICPA용 도식 PDF).
- 표준 CSS는 rfp_explainer.html(검증된 RFP 설명본)에서 추출해 재사용 -> 모든 PDF 스타일 동일.
- body fragment(.page div들)만 받아서 전체 HTML 조립 -> Edge headless print-to-pdf -> PyMuPDF 정규화(Adobe 호환) -> 검증 -> verify PNG.
사용:
  python build_pdf.py --body BODY.html --out OUT.pdf --title "..."
출력: 마지막 줄에 JSON 상태(pages, repaired, bytes, verify_pngs).
"""
import argparse, os, re, sys, subprocess, json, io

SCRATCH = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(SCRATCH, "rfp_explainer.html")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

def find_browser():
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("No Edge/Chrome found")

def extract_css(template_path):
    html = io.open(template_path, encoding="utf-8").read()
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    if not m:
        raise SystemExit("CSS block not found in template")
    return m.group(1)

def file_url(win_path):
    # Windows path -> proper file:/// URL (forward slashes, drive letter)
    p = os.path.abspath(win_path).replace("\\", "/")
    return "file:///" + p

def main():
    import shutil
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True, help="body fragment html (the .page divs)")
    ap.add_argument("--out", required=True, help="final pdf path (may be Korean/unicode)")
    ap.add_argument("--stem", required=True, help="ASCII work-name for intermediates, e.g. doc05")
    ap.add_argument("--title", default="법인세 세무 AI (TIW) 쉬운 설명")
    ap.add_argument("--css", default=TEMPLATE)
    args = ap.parse_args()

    css = extract_css(args.css)
    body = io.open(args.body, encoding="utf-8").read()

    full = (
        "<!DOCTYPE html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<title>" + args.title + "</title>\n<style>" + css + "</style></head>\n"
        "<body>\n" + body + "\n</body></html>\n"
    )

    # IMPORTANT: all intermediates live in ASCII scratchpad (Edge fails on non-ASCII
    # output paths). Only the final normalized PDF is copied to --out (may be Korean).
    out = os.path.abspath(args.out)
    wk = os.path.join(SCRATCH, args.stem)
    full_html = wk + ".full.html"
    raw_pdf = wk + ".raw.pdf"
    norm_pdf = wk + ".pdf"
    profile = wk + ".edgeprofile"
    io.open(full_html, "w", encoding="utf-8").write(full)

    for f in (raw_pdf, norm_pdf):
        if os.path.exists(f):
            try: os.remove(f)
            except OSError: pass

    browser = find_browser()
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--user-data-dir=" + profile,
        "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
        "--print-to-pdf=" + raw_pdf, file_url(full_html),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not os.path.exists(raw_pdf):
        print(json.dumps({"ok": False, "stage": "edge",
                          "stderr": (proc.stderr or "")[-800:]}, ensure_ascii=False))
        sys.exit(1)

    # normalize for Adobe compatibility (rewrite xref/objects cleanly)
    import fitz
    d = fitz.open(raw_pdf)
    d.save(norm_pdf, garbage=4, clean=True, deflate=True)
    d.close()

    v = fitz.open(norm_pdf)
    pages = v.page_count
    repaired = v.is_repaired
    idxs = sorted(set([0, pages // 2, pages - 1]))
    pngs = []
    for i in idxs:
        png = wk + (".verify_%d.png" % (i + 1))
        v[i].get_pixmap(dpi=100).save(png)
        pngs.append(png)
    bad = 0
    for i in range(pages):
        try: v[i].get_text("text")
        except Exception: bad += 1
    v.close()

    # copy final to destination (shutil handles unicode paths; Edge would not)
    shutil.copy(norm_pdf, out)

    for f in (raw_pdf,):
        try: os.remove(f)
        except OSError: pass
    shutil.rmtree(profile, ignore_errors=True)

    print(json.dumps({
        "ok": True, "out": out, "pages": pages, "repaired": repaired,
        "parse_ok": pages - bad, "bytes": os.path.getsize(out),
        "verify_pngs": pngs,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
