"""Exporta um .drawio (mxGraph XML não comprimido) para PNG usando mxGraph + Playwright.

Implementa só o subconjunto da CLI do draw.io que o Lampejo usa:
    --export --format png --scale N --border N [--transparent] --output OUT IN
"""
import argparse
import base64
import json
import os
import sys
import urllib.parse
import zlib
from pathlib import Path

MX = Path(__file__).resolve().parent / "mxgraph"


def diagram_xml(src: str) -> str:
    """devolve o <mxGraphModel> (descomprime se o diagrama vier no formato compactado do draw.io)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(src)
    if root.tag == "mxGraphModel":
        return src
    d = root.find("diagram")
    if d is None:
        return src
    m = d.find("mxGraphModel")
    if m is not None:
        return ET.tostring(m, encoding="unicode")
    raw = zlib.decompress(base64.b64decode((d.text or "").strip()), -15).decode()
    return urllib.parse.unquote(raw)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:%(bg)s}#g{position:absolute;left:0;top:0;overflow:visible}</style>
<script>var mxBasePath=%(base)s;var mxLoadResources=false;var mxLoadStylesheet=false;</script>
<script src=%(client)s></script></head><body><div id="g"></div><script>
var c=document.getElementById('g');var g=new mxGraph(c);g.setHtmlLabels(true);g.setEnabled(false);
var vs=g.getStylesheet().getDefaultVertexStyle();vs[mxConstants.STYLE_FONTCOLOR]='#000000';vs[mxConstants.STYLE_FONTFAMILY]='Helvetica';vs[mxConstants.STYLE_FONTSIZE]=12;
var ss=g.getStylesheet().getDefaultEdgeStyle();ss[mxConstants.STYLE_EDGE]=mxEdgeStyle.OrthConnector;ss[mxConstants.STYLE_FONTCOLOR]='#000000';ss[mxConstants.STYLE_STROKECOLOR]='#000000';ss[mxConstants.STYLE_LABEL_BACKGROUNDCOLOR]='#ffffff';ss[mxConstants.STYLE_FONTSIZE]=11;ss[mxConstants.STYLE_ROUNDED]=0;
var doc=mxUtils.parseXml(%(xml)s);new mxCodec(doc).decode(doc.documentElement,g.getModel());
var b=g.getGraphBounds();var bd=%(border)d;g.view.setTranslate(-b.x+bd,-b.y+bd);
var b2=g.getGraphBounds();c.style.width=(b2.x+b2.width+bd)+'px';c.style.height=(b2.y+b2.height+bd)+'px';
window.__size=[Math.ceil(b2.x+b2.width+bd),Math.ceil(b2.y+b2.height+bd)];
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--format", default="png")
    ap.add_argument("--scale", type=float, default=1)
    ap.add_argument("--border", type=int, default=0)
    ap.add_argument("--transparent", action="store_true")
    ap.add_argument("--output", required=True)
    ap.add_argument("--no-sandbox", action="store_true")
    ap.add_argument("--disable-gpu", action="store_true")
    ap.add_argument("input")
    a = ap.parse_args()
    if a.format != "png":
        sys.exit("só png é suportado")
    model = diagram_xml(Path(a.input).read_text(encoding="utf-8"))
    html = PAGE % {"bg": "transparent" if a.transparent else "#ffffff",
                   "base": json.dumps(MX.as_uri()), "client": json.dumps((MX / "mxClient.min.js").as_uri()),
                   "xml": json.dumps(model), "border": a.border}
    page_file = Path(a.output).with_suffix(".render.html")
    page_file.write_text(html, encoding="utf-8")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-dev-shm-usage"])
            pg = b.new_page(device_scale_factor=a.scale, viewport={"width": 4000, "height": 3000})
            pg.goto(page_file.as_uri())
            pg.wait_for_function("window.__size")
            w, h = pg.evaluate("window.__size")
            pg.screenshot(path=a.output, clip={"x": 0, "y": 0, "width": w, "height": h}, omit_background=a.transparent)
            b.close()
    finally:
        page_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
