"""Spec do diagrama (LLM) → layout determinístico → .drawio → check_layout.py → PNG + SVG (drawio CLI).

Usa tools/render_diagram.sh + tools/check_layout.py.
Layout fixo: fluxo principal numa linha (esq→dir), laterais embaixo do seu principal, 1 seta de volta por cima.
"""
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from . import config

COR = {  # papel → (fill, stroke)
    "entrada": ("#d5e8d4", "#82b366"),
    "processo": ("#dae8fc", "#6c8ebf"),
    "saida": ("#e1d5e7", "#9673a6"),
    "risco": ("#f8cecc", "#b85450"),
    "apoio": ("#fff2cc", "#d6b656"),
}
BOX_W, GAP_X, X0 = 240, 120, 40
ROW_Y, SIDE_GAP = 70, 90


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(html):
    return escape(html, {'"': "&quot;"})


def _lines(text, px_per_char, width):
    per = max(1, int(width / px_per_char))
    n, cur = 1, 0
    for w in (text or "").split():
        add = len(w) + (1 if cur else 0)
        if cur + add > per:
            n, cur = n + 1, len(w)
        else:
            cur += add
    return n


def _edge_label(t):
    """rótulo de seta cabe no vão entre caixas: até ~15 caracteres por linha (camada no código, o LLM não conta)."""
    w = (t or "").split()
    if len(" ".join(w)) <= 15 or len(w) < 2:
        return _esc(" ".join(w))
    best = min(range(1, len(w)), key=lambda k: abs(len(" ".join(w[:k])) - len(" ".join(w[k:]))))
    return _esc(" ".join(w[:best])) + "<br>" + _esc(" ".join(w[best:]))


def _box_h(n):
    nl1, nl2 = _lines(n["rotulo"], 11.6, BOX_W - 36), _lines(n.get("detalhe", ""), 8.6, BOX_W - 36)
    return max(96, int(nl1 * 26 + nl2 * 21 + 30))


def build_xml(spec):
    fluxo = spec["fluxo"][:5]
    laterais = [l for l in spec.get("laterais", [])][:3]
    ids = {n["id"] for n in fluxo}
    used, lat_ok = set(), []
    for l in laterais:                                  # no máximo 1 lateral por principal
        if l.get("abaixo_de") in ids and l["abaixo_de"] not in used:
            used.add(l["abaixo_de"]); lat_ok.append(l)
    geo = {}
    main_h = max(_box_h(n) for n in fluxo)
    for k, n in enumerate(fluxo):
        geo[n["id"]] = (X0 + k * (BOX_W + GAP_X), ROW_Y, BOX_W, main_h)
    side_y = ROW_Y + main_h + SIDE_GAP
    side_h = max([_box_h(l) for l in lat_ok], default=0)
    col = {n["id"]: k for k, n in enumerate(fluxo)}
    for l in lat_ok:
        x = X0 + col[l["abaixo_de"]] * (BOX_W + GAP_X)
        geo[l["id"]] = (x, side_y, BOX_W, side_h)
    W = X0 * 2 + len(fluxo) * BOX_W + (len(fluxo) - 1) * GAP_X
    H = (side_y + side_h + 36) if lat_ok else (ROW_Y + main_h + 40)

    cells = [f'<mxCell id="bg" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="{W}" height="{H}" as="geometry"/></mxCell>']

    def vtx(n):
        x, y, w, h = geo[n["id"]]
        fill, stroke = COR.get(n.get("papel"), COR["processo"])
        label = f'<b>{_esc(n["rotulo"])}</b><br><font style="font-size:15px" color="#333333">{_esc(n.get("detalhe", ""))}</font>'
        cells.append(f'<mxCell id="{n["id"]}" value="{_attr(label)}" style="rounded=1;absoluteArcSize=1;arcSize=14;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=2;fontSize=19;align=center;verticalAlign=middle;spacing=8;spacingLeft=12;spacingRight=12;" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')

    for n in fluxo + lat_ok:
        vtx(n)
    es = "edgeStyle=orthogonalEdgeStyle;rounded=1;endArrow=block;endFill=1;strokeColor=#555555;strokeWidth=2;html=1;fontSize=14;labelBackgroundColor=#ffffff;fontColor=#444444;"
    for a, b in zip(fluxo, fluxo[1:]):
        cells.append(f'<mxCell id="e_{a["id"]}_{b["id"]}" value="{_attr(_edge_label(a.get("seta", "")))}" style="{es}exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="{a["id"]}" target="{b["id"]}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    for l in lat_ok:
        cells.append(f'<mxCell id="e_{l["abaixo_de"]}_{l["id"]}" value="{_attr(_edge_label(l.get("seta", "")))}" style="{es}dashed=1;exitX=0.5;exitY=1;entryX=0.5;entryY=0;" edge="1" parent="1" source="{l["abaixo_de"]}" target="{l["id"]}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    v = spec.get("volta")
    if v and v.get("de") in geo and v.get("para") in geo and col.get(v["de"], 0) > col.get(v["para"], 0) and v["de"] in ids:
        (x1, y1, w1, _), (x2, _, w2, _) = geo[v["de"]], geo[v["para"]]
        ytop = ROW_Y - 34
        cells.append(f'<mxCell id="e_volta" value="{_attr(_esc(v.get("rotulo", "")))}" style="{es}dashed=1;strokeColor=#b85450;fontColor=#b85450;exitX=0.5;exitY=0;entryX=0.5;entryY=0;" edge="1" parent="1" source="{v["de"]}" target="{v["para"]}"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="{x1 + w1 / 2}" y="{ytop}"/><mxPoint x="{x2 + w2 / 2}" y="{ytop}"/></Array></mxGeometry></mxCell>')
    xml = ('<mxfile host="app.diagrams.net"><diagram name="lsl" id="lsl"><mxGraphModel dx="1200" dy="800" grid="0" gridSize="10" guides="1" '
           f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}" math="0" shadow="0"><root>'
           '<mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")
    nodes = [{"id": n["id"], "rotulo": n["rotulo"], "detalhe": n.get("detalhe", ""), "ideia": n.get("ideia"),
              "papel": n.get("papel"), "x": geo[n["id"]][0], "y": geo[n["id"]][1], "w": geo[n["id"]][2], "h": geo[n["id"]][3]}
             for n in fluxo + lat_ok]
    return xml, nodes, (W, H)


def check(path):
    r = subprocess.run([sys.executable, str(config.CHECK_LAYOUT), str(path)], capture_output=True, text=True, timeout=60)
    blocking = [l.strip() for l in r.stdout.splitlines() if re.match(r"^\s+\[", l) and not re.search(r"\[(APERTADO|FOLGADO)", l)]
    return r.returncode, blocking, r.stdout[-1500:]


def export_fast(src: Path, out: Path, fmt="png", timeout=45):
    """drawio CLI com os mesmos parâmetros do render_diagram.sh (scale 2). O Electron às vezes grava o arquivo e
    não sai (sob carga, o script da skill espera o timeout de 90 s) → espera o arquivo estabilizar, valida e encerra."""
    import os, signal, time
    from PIL import Image
    out.unlink(missing_ok=True)
    p = subprocess.Popen([config.DRAWIO, "--export", "--format", fmt, "--scale", "2", "--border", "0",
                          "--output", str(out), str(src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    t0, last, ok = time.time(), -1, False
    while time.time() - t0 < timeout:
        done = p.poll() is not None
        if out.exists():
            sz = out.stat().st_size
            if sz > 0 and (sz == last or done):
                try:
                    with Image.open(out) as im:
                        im.verify()
                    ok = True
                    break
                except Exception:  # noqa: BLE001 — ainda escrevendo
                    pass
            last = sz
        if done and not out.exists():
            break
        time.sleep(0.4)
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return ok


def render(spec, out_dir: Path):
    """Devolve dict com png, nós (coordenadas no espaço do diagrama e em % da imagem) e o relatório do checker."""
    out_dir.mkdir(parents=True, exist_ok=True)
    xml, nodes, (W, H) = build_xml(spec)
    src = out_dir / "diagrama.drawio"
    src.write_text(xml, encoding="utf-8")
    rc, blocking, report = check(src)
    if blocking:                                       # 1 correção automática: caixas mais altas e mais largas
        global BOX_W
        old = BOX_W
        BOX_W = 240
        try:
            for n in spec["fluxo"] + spec.get("laterais", []):
                n["detalhe"] = " ".join((n.get("detalhe") or "").split()[:9])
            xml, nodes, (W, H) = build_xml(spec)
            src.write_text(xml, encoding="utf-8")
            rc, blocking, report = check(src)
        finally:
            BOX_W = old
    png = out_dir / "diagrama.png"
    via = "drawio CLI direto"
    if not export_fast(src, png):                  # fallback: o script canônico da skill
        via = "render_diagram.sh"
        r = subprocess.run(["bash", str(config.RENDER_DIAGRAM), str(src), str(png), "--scale", "2", "--border", "0"],
                           capture_output=True, text=True, timeout=150)
        if r.returncode != 0 or not png.exists():
            raise RuntimeError(f"render_diagram falhou: {r.stderr[-400:]}")
    for n in nodes:                                    # posição em % (a imagem começa no retângulo de fundo 0,0,W,H)
        n["px"], n["py"], n["pw"], n["ph"] = n["x"] / W * 100, n["y"] / H * 100, n["w"] / W * 100, n["h"] / H * 100
    return {"png": png, "nodes": nodes, "size": [W, H],
            "check_rc": rc, "check_blocking": blocking, "check_report": report, "via": via}
