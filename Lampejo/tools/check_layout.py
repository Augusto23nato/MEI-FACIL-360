#!/usr/bin/env python3
"""Pre-flight layout checker for .drawio files.

Catches, BEFORE rendering, the defect classes that survive a visual audit
because they are invisible in a downscaled screenshot:

  1. TEXT OVERFLOW (height) — drawio does NOT grow a vertex to fit its label.
     If the text is taller than the box, it silently renders THROUGH and PAST
     the bottom border. Nothing errors.
  2. TEXT TOO WIDE (largura) — the mirror image. A `whiteSpace=wrap` box DOES
     word-wrap, so a long logical line that breaks into pieces that fit is NOT a
     defect. It IS a defect when (a) a single word is wider than the wrap width
     (it overflows the side), or (b) the box has so little horizontal padding
     that a wrapped SEGMENT ends up flush against — or crossing — a side border
     (the u_badge case: a 170px badge whose wrapped line "que jogar o livro
     inteiro" touches both edges). A box WITHOUT `whiteSpace=wrap` cannot wrap at
     all, so any line wider than the usable width is a defect there.
  3. ROUNDED-CORNER INTRUSION (canto) — `rounded=1` WITHOUT `absoluteArcSize=1`
     makes drawio use a PROPORTIONAL radius = 0.15 * min(w,h). On a big panel
     (e.g. 520x480 -> r≈72px) a `verticalAlign=top;align=left` label's first line
     starts INSIDE that arc and reads as text crossing the corner.
  4. VERTICAL SLACK (folgado) — a box far taller than its text leaves an ugly
     empty band at the bottom (advisory).
  5. PARTIAL OVERLAP / edge crossing a vertex / oversized edge label — geometry
     bugs that always read as broken.

A clean run is NECESSARY, NOT SUFFICIENT — it does not see color, contrast, or
corner aesthetics. Still audit the render at 100% (SKILL.md step 6), inspecting
the BORDERS of every card (left, right, rounded corners), not just the middle.

Width model — this is the part that must match what drawio ACTUALLY draws, so it
uses the real Adobe Helvetica / Helvetica-Bold advance-width tables (per-glyph,
in 1/1000 em), not a single average factor. Verified 2026-08-18: the bold string
"que jogar o livro inteiro" measures 166 px rendered and the table predicts
166.7 px. Wrapping is simulated at drawio's real threshold (box width minus a
small inset); a wrapped SEGMENT is only a defect if it ends up within MIN_GAP px
of a border. Pre-breaking long lines with <br> is a good authoring habit, but a
whiteSpace=wrap box whose wrapped segments fit is NOT flagged — that would make
the checker demand bloated, low-density diagrams.

Usage:
    check_layout.py <file.drawio> [more.drawio ...]

Exit 0 = clean (no blocking findings), 1 = blocking violations. Advisory
findings ([APERTADO], [FOLGADO]) are printed but do not fail the run.
"""
import sys, re, math, html, unicodedata
import xml.etree.ElementTree as ET

# ── Adobe Helvetica advance widths (1/1000 em) ──────────────────────────────
_HELV = {
    ' ':278,'!':278,'"':355,'#':556,'$':556,'%':889,'&':667,"'":191,'(':333,')':333,
    '*':389,'+':584,',':278,'-':333,'.':278,'/':278,
    '0':556,'1':556,'2':556,'3':556,'4':556,'5':556,'6':556,'7':556,'8':556,'9':556,
    ':':278,';':278,'<':584,'=':584,'>':584,'?':556,'@':1015,
    'A':667,'B':667,'C':722,'D':722,'E':667,'F':611,'G':778,'H':722,'I':278,'J':500,
    'K':667,'L':556,'M':833,'N':722,'O':778,'P':667,'Q':778,'R':722,'S':667,'T':611,
    'U':722,'V':667,'W':944,'X':667,'Y':667,'Z':611,
    '[':278,'\\':278,']':278,'^':469,'_':556,'`':333,
    'a':556,'b':556,'c':500,'d':556,'e':556,'f':278,'g':556,'h':556,'i':222,'j':222,
    'k':500,'l':222,'m':833,'n':556,'o':556,'p':556,'q':556,'r':333,'s':500,'t':278,
    'u':556,'v':500,'w':722,'x':500,'y':500,'z':500,'{':334,'|':260,'}':334,'~':584,
}
_HELVB = {
    ' ':278,'!':333,'"':474,'#':556,'$':556,'%':889,'&':722,"'":238,'(':333,')':333,
    '*':389,'+':584,',':278,'-':333,'.':278,'/':278,
    '0':556,'1':556,'2':556,'3':556,'4':556,'5':556,'6':556,'7':556,'8':556,'9':556,
    ':':333,';':333,'<':584,'=':584,'>':584,'?':611,'@':975,
    'A':722,'B':722,'C':722,'D':722,'E':667,'F':611,'G':778,'H':722,'I':278,'J':556,
    'K':722,'L':611,'M':833,'N':722,'O':778,'P':667,'Q':778,'R':722,'S':667,'T':611,
    'U':722,'V':667,'W':944,'X':667,'Y':667,'Z':611,
    '[':333,'\\':278,']':333,'^':584,'_':556,'`':333,
    'a':556,'b':611,'c':556,'d':611,'e':556,'f':333,'g':611,'h':611,'i':278,'j':278,
    'k':556,'l':278,'m':889,'n':611,'o':611,'p':611,'q':611,'r':389,'s':556,'t':333,
    'u':611,'v':556,'w':778,'x':556,'y':556,'z':500,'{':389,'|':280,'}':389,'~':584,
}
# glyphs outside Latin-1 that appear in diagrams (width approx, both weights)
_EXTRA = {
    '×':584,'·':278,'–':556,'—':1000,'…':1000,'→':838,'←':838,'↔':1000,
    '“':333,'”':333,'‘':222,'’':222,'•':350,'®':737,'©':737,'™':1000,'°':400,
    '①':1000,'②':1000,'③':1000,'④':1000,'⑤':1000,'⑥':1000,'⑦':1000,'⑧':1000,'⑨':1000,'⑩':1000,
}

def _base(ch):
    """Map an accented Latin letter to its base (advance width is the same in
    Helvetica for composed accents)."""
    d = unicodedata.normalize('NFD', ch)
    b = d[0]
    return b if b else ch

def char_w(ch, bold):
    table = _HELVB if bold else _HELV
    if ch in table:
        return table[ch]
    if ch in _EXTRA:
        return _EXTRA[ch]
    b = _base(ch)
    if b in table:
        return table[b]
    return 600  # unknown glyph fallback

def text_width(text, bold, fs):
    return sum(char_w(c, bold) for c in text) * fs / 1000.0

# ── tunables (calibrated 2026-08-18 against drawio v30 renders) ──────────────
LINE_H = 1.38
DEFAULT_FONT = 12
ARC_FACTOR = 0.15      # drawio mxConstants.RECTANGLE_ROUNDING_FACTOR
INSET = 1.5            # drawio internal horizontal label inset, per side (calibrated:
                       # reproduces "que jogar o livro inteiro" fitting a 170px badge)
PAD_Y = 8              # vertical breathing
MIN_GAP = 1.5          # visible breathing room (to the inner stroke edge) below which a
                       # wrapped segment reads as flush against the border. Calibrated so
                       # the u_badge badge (0px, thick stroke) flags but the g-boxes (>=2px)
                       # do not — a whiteSpace=wrap box that wraps with any real margin is fine.
CANTO_MARGIN = 6       # only flag a corner arc that intrudes clearly past spacingLeft
TOLERANCE = 6          # height slack absorbed by verticalAlign=middle
FOLGA_ABS = 125        # [FOLGADO] absolute empty px (pB=129 fires, pA=99 stays quiet)
FOLGA_RATIO = 1.7


def parse_style(style):
    d = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
        else:
            d[part.strip()] = True
    return d


def _all_bold(style):
    try:
        fs = int(float(style.get("fontStyle", 0)))
    except (TypeError, ValueError):
        fs = 0
    return bool(fs & 1)


def label_segments(value):
    """Explicit lines (as drawio sees <br>/<p>/<div>); each line is a list of
    (text, is_bold) runs so widths respect inline <b>…</b>."""
    if not value:
        return []
    v = html.unescape(value)
    v = re.sub(r"<\s*br\s*/?\s*>", "\n", v, flags=re.I)
    v = re.sub(r"</\s*(p|div|li)\s*>", "\n", v, flags=re.I)
    v = re.sub(r"<\s*(p|div|li)[^>]*>", "", v, flags=re.I)
    out = []
    for line in v.split("\n"):
        runs = []
        bold_depth = 0
        buf = ""
        for tok in re.split(r"(<[^>]+>)", line):
            if tok.startswith("<") and tok.endswith(">"):
                tl = tok.lower()
                if re.match(r"<\s*(b|strong)\s*>", tl):
                    if buf:
                        runs.append((buf, bold_depth > 0)); buf = ""
                    bold_depth += 1
                elif re.match(r"<\s*/\s*(b|strong)\s*>", tl):
                    if buf:
                        runs.append((buf, bold_depth > 0)); buf = ""
                    bold_depth = max(0, bold_depth - 1)
                else:
                    if buf:
                        runs.append((buf, bold_depth > 0)); buf = ""
            else:
                buf += html.unescape(tok)
        if buf:
            runs.append((buf, bold_depth > 0))
        out.append(runs)
    return out


def runs_width(runs, fs, force_bold):
    return sum(text_width(t, b or force_bold, fs) for t, b in runs)


def runs_words(runs):
    """Flatten runs to words carrying bold, plus the space width between them."""
    words = []
    for text, b in runs:
        for w in text.split(" "):
            if w != "":
                words.append((w, b))
    return words


def wrap_segments(runs, wrap_w, fs, force_bold):
    """Simulate drawio word-wrap. Returns (segments, widest_word_w) where each
    segment is its rendered width in px."""
    words = runs_words(runs)
    if not words:
        return [0.0], 0.0
    space = text_width(" ", force_bold, fs)
    segs = []
    cur = 0.0
    widest_word = 0.0
    for w, b in words:
        ww = text_width(w, b or force_bold, fs)
        widest_word = max(widest_word, ww)
        add = ww if cur == 0 else space + ww
        if cur > 0 and cur + add > wrap_w:
            segs.append(cur)
            cur = ww
        else:
            cur += add
    segs.append(cur)
    return segs, widest_word


def analyze(value, w, h, style):
    """Return dict: need_h, vlines, width_findings (list of (kind, detail))."""
    segs_in = label_segments(value)
    if not segs_in:
        return {"need_h": 0, "vlines": 0, "width_findings": []}
    fs = float(style.get("fontSize", DEFAULT_FONT))
    force_bold = _all_bold(style)
    sl = float(style.get("spacingLeft", 0))
    sr = float(style.get("spacingRight", 0))
    st = float(style.get("spacingTop", 0))
    sp = float(style.get("spacing", 0))
    try:
        stroke = float(style.get("strokeWidth", 1))
    except (TypeError, ValueError):
        stroke = 1.0
    align = str(style.get("align", "center"))
    wrap = ("whiteSpace" in style and str(style.get("whiteSpace")) == "wrap")

    wrap_w = max(12.0, w - sl - sr - sp * 2 - 2 * INSET)
    x_text = sl + sp + INSET               # left origin of text
    total_lines = 0
    findings = []
    for runs in segs_in:
        text = "".join(t for t, _ in runs).strip()
        if not text:
            total_lines += 1
            continue
        nat_w = runs_width(runs, fs, force_bold)
        short = (text[:44] + "…") if len(text) > 45 else text
        if not wrap:
            # no auto-wrap: the whole logical line must fit the usable width
            total_lines += 1
            if nat_w > wrap_w + 1:
                need = int(math.ceil((nat_w + sl + sr + 2 * INSET + 4) / 2) * 2)
                findings.append(("SEMWRAP", f"linha {short!r} ~{int(nat_w)}px não cabe em "
                                            f"{int(wrap_w)}px (sem whiteSpace=wrap) -> width >= {need}"))
            continue
        segs, widest_word = wrap_segments(runs, wrap_w, fs, force_bold)
        total_lines += len(segs)
        # (a) a single word wider than the wrap width -> overflows the side
        if widest_word > wrap_w + 1:
            need = int(math.ceil((widest_word + sl + sr + 2 * INSET + 6) / 2) * 2)
            findings.append(("PALAVRA", f"palavra em {short!r} ~{int(widest_word)}px > útil "
                                        f"{int(wrap_w)}px -> alargue: width >= {need}"))
            continue
        # (b) a wrapped segment ends up flush against a side border
        widest_seg = max(segs)
        if align == "center":
            gap = (w - widest_seg) / 2.0 - stroke / 2.0
            gl = gr = gap
        elif align == "right":
            gr = (w - sr - sp - INSET) - (w - stroke / 2)  # ~ -(sr+INSET)+stroke/2
            gr = sr + sp + INSET - stroke / 2
            gl = (w - stroke / 2) - (w - sr - sp - INSET - widest_seg)
            gl = w - stroke / 2 - (w - sr - sp - INSET - widest_seg)
        else:  # left (default for align=left)
            gl = x_text - stroke / 2
            gr = (w - stroke / 2) - (x_text + widest_seg)
        mn = min(gl, gr)
        if mn < MIN_GAP:
            grow = int(math.ceil((widest_seg + max(sl, MIN_GAP + 2) + max(sr, MIN_GAP + 2)
                                  + 2 * INSET) / 2) * 2)
            findings.append(("SEGMENTO", f"segmento {short!r} ~{int(widest_seg)}px cola na borda "
                                         f"(folga lateral ~{mn:.0f}px < {int(MIN_GAP)}px) -> "
                                         f"rebreak com &lt;br&gt; ou width >= {grow}"))
    need_h = total_lines * fs * LINE_H + PAD_Y + st
    return {"need_h": need_h, "vlines": total_lines, "width_findings": findings}


def arc_inset(radius, spacing_top):
    y = spacing_top
    if y >= radius:
        return 0.0
    return radius - math.sqrt(max(0.0, radius * radius - (radius - y) * (radius - y)))


def rect(cell):
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        return (float(g.get("x", 0)), float(g.get("y", 0)),
                float(g.get("width", 0)), float(g.get("height", 0)))
    except (TypeError, ValueError):
        return None


def contains(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax <= bx and ay <= by and ax + aw >= bx + bw and ay + ah >= by + bh


def intersects(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def check(path):
    tree = ET.parse(path)
    pages = tree.findall(".//diagram") or [tree.getroot()]
    out = []
    for i, page in enumerate(pages):
        name = page.get("name") or f"pagina {i+1}"
        for p in _check_page(page):
            out.append(f"  [{name}]" + p[2:] if len(pages) > 1 else p)
    return out


def _check_page(page):
    problems, advisories = [], []
    verts = []
    for cell in page.iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        r = rect(cell)
        if not r or r[2] <= 0 or r[3] <= 0:
            continue
        verts.append((cell.get("id"), cell.get("value") or "", r, parse_style(cell.get("style"))))

    def is_container(idx):
        r = verts[idx][2]
        for j in range(len(verts)):
            if j == idx:
                continue
            if contains(r, verts[j][2]) and r != verts[j][2]:
                return True
        return False

    for _i, (cid, value, (x, y, w, h), style) in enumerate(verts):
        if not value.strip():
            continue
        fill = str(style.get("fillColor", "none")).lower()
        stroke = str(style.get("strokeColor", "none")).lower()
        bordered = fill not in ("none", "") or stroke not in ("none", "")
        info = analyze(value, w, h, style)

        if bordered:
            for kind, detail in info["width_findings"]:
                problems.append(f"  [LARGURA ] id={cid!r:>16}  box={int(w)}x{int(h)}  {detail}")

            need = info["need_h"]; over = need - h
            if over > TOLERANCE:
                problems.append(
                    f"  [OVERFLOW] id={cid!r:>16}  box={int(w)}x{int(h)}  "
                    f"precisa ~{int(need)}px para {info['vlines']} linhas ({int(over)}px a mais)  "
                    f"-> height >= {int(math.ceil(need/2)*2)}")
            elif over > 0:
                advisories.append(
                    f"  [APERTADO] id={cid!r:>16}  box={int(w)}x{int(h)}  folga de {int(over)}px "
                    f"negativa — aceitável se verticalAlign=middle, confirme no recorte em 100%")
            elif info["vlines"] > 0 and str(style.get("verticalAlign", "middle")) == "top" \
                    and not is_container(_i):
                excess = h - need
                if excess > FOLGA_ABS or h > FOLGA_RATIO * need:
                    advisories.append(
                        f"  [FOLGADO ] id={cid!r:>16}  box={int(w)}x{int(h)}  texto usa ~{int(need)}px, "
                        f"sobram ~{int(excess)}px vazios embaixo -> height ~= {int(math.ceil((need+PAD_Y)/2)*2)}")

        # rounded-corner intrusion
        rounded = str(style.get("rounded", "0")) in ("1", "true", "True")
        abs_arc = str(style.get("absoluteArcSize", "0")) in ("1", "true", "True")
        va = str(style.get("verticalAlign", "middle"))
        al = str(style.get("align", "center"))
        if rounded and not abs_arc and va == "top" and al == "left" and value.strip():
            radius = ARC_FACTOR * min(w, h)
            st = float(style.get("spacingTop", 0))
            sl = float(style.get("spacingLeft", 0))
            inset = arc_inset(radius, st)
            if inset > sl + CANTO_MARGIN:
                problems.append(
                    f"  [CANTO   ] id={cid!r:>16}  box={int(w)}x{int(h)}  raio proporcional ~{int(radius)}px "
                    f"invade a 1ª linha (borda a ~{int(inset)}px, spacingLeft={int(sl)}px)  "
                    f"-> use absoluteArcSize=1;arcSize=14 (e spacingLeft/Top >= 16)")

    # edges
    byid = {cid: (r, st) for cid, _v, r, st in verts}
    for cell in page.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        src, tgt = cell.get("source"), cell.get("target")
        if src not in byid or tgt not in byid:
            continue
        (sx, sy, sw, sh), sst = byid[src]
        (tx, ty, tw, th), tst = byid[tgt]
        st = parse_style(cell.get("style"))
        ex = sx + float(st.get("exitX", 0.5)) * sw
        ey = sy + float(st.get("exitY", 1.0)) * sh
        nx = tx + float(st.get("entryX", 0.5)) * tw
        ny = ty + float(st.get("entryY", 0.0)) * th
        pts = [(ex, ey)]
        g = cell.find("mxGeometry")
        arr = g.find("Array") if g is not None else None
        if arr is not None:
            for p in arr.findall("mxPoint"):
                pts.append((float(p.get("x", 0)), float(p.get("y", 0))))
        pts.append((nx, ny))
        segs = []
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            segs.append((ax, ay, ax, by))
            segs.append((ax, by, bx, by))
        lbl = (cell.get("value") or "").strip()
        if lbl:
            fs = float(st.get("fontSize", 11))
            longest = max((runs_width(rl, fs, False) for rl in label_segments(lbl)), default=0)
            need_w = longest + 8
            gap = max(0.0, min(abs(tx - (sx + sw)), abs(sx - (tx + tw))))
            if abs(ey - ny) < 30 and gap < need_w:
                problems.append(
                    f"  [ROTULO  ] aresta {cell.get('id')!r} tem rótulo {lbl!r} (~{int(need_w)}px) "
                    f"num vão de {int(gap)}px — ele vai invadir as duas caixas. Remova ou abra o vão.")
        for cid2, (r2, st2) in byid.items():
            if cid2 in (src, tgt):
                continue
            x2, y2, w2, h2 = r2
            if contains(r2, (sx, sy, sw, sh)) or contains(r2, (tx, ty, tw, th)):
                continue
            for ax, ay, bx, by in segs:
                lo_x, hi_x = min(ax, bx), max(ax, bx)
                lo_y, hi_y = min(ay, by), max(ay, by)
                if hi_x < x2 + 2 or lo_x > x2 + w2 - 2:
                    continue
                if hi_y < y2 + 2 or lo_y > y2 + h2 - 2:
                    continue
                problems.append(
                    f"  [CRUZA   ] aresta {cell.get('id')!r} ({src}→{tgt}) passa por dentro de "
                    f"{cid2!r} — roteie pela margem ou encurte o rótulo")
                break

    # partial overlap
    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            id1, _, r1, s1 = verts[i]
            id2, _, r2, s2 = verts[j]
            if not intersects(r1, r2):
                continue
            if contains(r1, r2) or contains(r2, r1):
                continue
            problems.append(
                f"  [OVERLAP ] {id1!r} {tuple(int(v) for v in r1)} "
                f"intersecta {id2!r} {tuple(int(v) for v in r2)} sem conter")

    return problems + advisories


ADVISORY_TAGS = ("[APERTADO]", "[FOLGADO ]")


def _is_blocking(line):
    return not any(tag in line for tag in ADVISORY_TAGS)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bad = 0
    for path in sys.argv[1:]:
        probs = check(path)
        blocking = [p for p in probs if _is_blocking(p)]
        if probs:
            print(f"\n{path}: {len(probs)} achado(s) ({len(blocking)} bloqueante(s))")
            for p in probs:
                print(p)
            if blocking:
                bad += 1
        else:
            print(f"{path}: OK")
    if bad:
        print(f"\n{bad} arquivo(s) com defeito BLOQUEANTE. CORRIJA ANTES DE RENDERIZAR.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
