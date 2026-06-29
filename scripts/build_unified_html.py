#!/usr/bin/env python3
"""통합 설계서 md -> html 동기화 빌더.

`md 파일/법인세_세무AI_설계서_통합.md`(정본)를 읽어 동일 템플릿의 HTML을 생성하고,
`md 파일/`과 `Claude/` 두 사본에 동일하게 기록한다.

- 스타일/head/wrapper 템플릿은 기존 HTML의 head 부분을 그대로 재사용한다(슬라이스).
- 본문/TOC만 현재 md에서 재생성한다.
- 슬러그 규칙: 한글/영숫자 외 문자(공백··,.()"*→— 등)는 모두 '-'로 치환 후 trim.

사용: 레포 루트에서  python scripts/build_unified_html.py
"""
import re, html, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "md 파일", "법인세_세무AI_설계서_통합.md")
TEMPLATE_HTML = os.path.join(ROOT, "md 파일", "법인세_세무AI_설계서_통합.html")
OUT_PATHS = [
    os.path.join(ROOT, "md 파일", "법인세_세무AI_설계서_통합.html"),
    os.path.join(ROOT, "Claude", "법인세_세무AI_설계서_통합.html"),
]
SRC_LABEL = "md 파일/법인세_세무AI_설계서_통합.md"


def slug(t):
    return re.sub(r'[^0-9A-Za-z가-힣]+', '-', t).strip('-')


def inline(t):
    t = t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    t = re.sub(r'`([^`]+)`', lambda m: '<code>' + m.group(1) + '</code>', t)
    t = re.sub(r'\*\*(.+?)\*\*', lambda m: '<strong>' + m.group(1) + '</strong>', t)
    t = re.sub(r'\*([^*]+)\*', lambda m: '<em>' + m.group(1) + '</em>', t)
    return t


def esc_pre(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def is_sep(l):
    s = l.strip()
    return bool(s) and set(s) <= set('|:- ') and '-' in s


def is_block_start(l, nxt):
    return (re.match(r'^#{1,6}\s', l) or l.strip() == '---' or l.startswith('```')
            or (l.startswith('|') and nxt is not None and is_sep(nxt)) or l.startswith('>')
            or re.match(r'^- ', l) or re.match(r'^\d+\.\s', l))


def render(src):
    lines = src.split('\n')
    blocks, toc = [], []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == '':
            i += 1; continue
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            level = len(m.group(1)); raw = m.group(2).rstrip()
            if level == 1:
                blocks.append('<h1>' + inline(raw) + '</h1>')
            else:
                sid = slug(raw)
                blocks.append('<h%d id="%s">%s</h%d>' % (level, sid, inline(raw), level))
                if level in (2, 3):
                    cls = 'toc-h2' if level == 2 else 'toc-h3'
                    toc.append('<a class="%s" href="#%s">%s</a>' % (cls, sid, html.escape(raw)))
            i += 1; continue
        if line.strip() == '---':
            blocks.append('<hr>'); i += 1; continue
        if line.startswith('```'):
            i += 1; buf = []
            while i < n and not lines[i].startswith('```'):
                buf.append(lines[i]); i += 1
            i += 1
            blocks.append('<pre><code>' + '\n'.join(esc_pre(x) for x in buf) + '</code></pre>')
            continue
        nxt = lines[i+1] if i+1 < n else None
        if line.startswith('|') and nxt is not None and is_sep(nxt):
            header = line; i += 2; body = []
            while i < n and lines[i].startswith('|'):
                body.append(lines[i]); i += 1
            def cells(row):
                return [inline(p.strip()) for p in row.split('|')[1:-1]]
            th = ''.join('<th>%s</th>' % c for c in cells(header))
            trs = '\n'.join('<tr>' + ''.join('<td>%s</td>' % c for c in cells(r)) + '</tr>' for r in body)
            blocks.append('<div class="table-wrap"><table>\n<thead><tr>%s</tr></thead>\n<tbody>\n%s\n</tbody></table></div>' % (th, trs))
            continue
        if line.startswith('>'):
            buf = []
            while i < n and lines[i].startswith('>'):
                c = lines[i][1:]
                if c.startswith(' '): c = c[1:]
                buf.append(inline(c)); i += 1
            blocks.append('<blockquote>' + '<br>'.join(buf) + '</blockquote>')
            continue
        if re.match(r'^- ', line):
            buf = []
            while i < n and re.match(r'^- ', lines[i]):
                buf.append('<li>' + inline(lines[i][2:]) + '</li>'); i += 1
            blocks.append('<ul>\n' + '\n'.join(buf) + '\n</ul>')
            continue
        if re.match(r'^\d+\.\s', line):
            buf = []
            while i < n and re.match(r'^\d+\.\s', lines[i]):
                buf.append('<li>' + inline(re.sub(r'^\d+\.\s+', '', lines[i])) + '</li>'); i += 1
            blocks.append('<ol>\n' + '\n'.join(buf) + '\n</ol>')
            continue
        buf = []
        while i < n and lines[i].strip() != '' and not is_block_start(lines[i], lines[i+1] if i+1 < n else None):
            buf.append(lines[i]); i += 1
        blocks.append('<p>' + inline(' '.join(buf)) + '</p>')
    return '\n'.join(blocks), toc


def main():
    src = open(MD, encoding='utf-8').read()
    body_html, toc = render(src)
    existing = open(TEMPLATE_HTML, encoding='utf-8').read()
    marker = '      <h2>목차</h2>\n'
    head = existing[:existing.index(marker) + len(marker)]
    head = head.replace('Claude/법인세_세무AI_설계서_통합.md', SRC_LABEL)
    mid = '    </nav>\n    <main class="content">\n'
    tail = '    </main>\n  </div>\n  <footer>Generated from %s</footer>\n</div>\n</body>\n</html>\n' % SRC_LABEL
    out = head + '      ' + '\n'.join(toc) + '\n' + mid + body_html + '\n' + tail
    for p in OUT_PATHS:
        open(p, 'w', encoding='utf-8', newline='').write(out)
        print('wrote', os.path.relpath(p, ROOT))
    print('%d TOC entries, %d chars' % (len(toc), len(out)))


if __name__ == '__main__':
    main()
