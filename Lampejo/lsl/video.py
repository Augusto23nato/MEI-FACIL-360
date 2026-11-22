"""Vídeo motion: fluxograma (PNG do draw.io) + narração → timeline → cena HTML seek(t) → Playwright → ffmpeg."""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from PIL import Image

from . import config

LEAD = 0.12          # o destaque chega um pouco antes da palavra (regra C08 do Motion Designer: 2–4 quadros de antecipação)


def _base_cfg(diagram, title):
    W, H = diagram["size"]
    pw = Image.open(diagram["png"]).size[0]
    return {"png": Path(diagram["png"]).resolve().as_uri(), "W": W, "H": H, "pngW": pw, "title": title, "idea": "",
            "nodes": {n["id"]: {"x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"]} for n in diagram["nodes"]}}


def _capture(cfg, audio, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    cfgp = out.with_suffix(".cfg.json")
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False))
    p = subprocess.Popen([sys.executable, "-m", "lsl.motion_capture", str(cfgp), str(audio), str(out)],
                         cwd=str(config.ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        so, se = p.communicate(timeout=300)
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)       # Chromium órfão não sobrevive (lição da casa)
        except ProcessLookupError:
            pass
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"captura falhou: {(se or so)[-400:]}")
    return out


def _starts(frases, al):
    """início (s) de cada frase, pelo alinhamento por caractere da ElevenLabs."""
    starts = al.get("character_start_times_seconds") or []
    chars = "".join(al.get("characters") or [])
    out, pos = [], 0
    for f in frases:
        i = chars.find(f[:14], pos)
        if i < 0:
            i = chars.find(f[:6], pos)
        out.append(starts[i] if 0 <= i < len(starts) else None)
        pos = max(pos, i + 1) if i >= 0 else pos
    for k, v in enumerate(out):                    # frase não achada: herda a anterior + 2 s
        if v is None:
            out[k] = (out[k - 1] + 2.0) if k else 0.0
    return out


def render_tour(diagram, title, segs, tts, out: Path):
    """segs: [{no, fala, legenda?}] na ordem da narração; tts: resultado de voice.narrate (mp3 + alinhamento)."""
    ts = _starts([g["fala"] for g in segs], tts["alignment"])
    events = [{"t": max(0.0, t - LEAD), "node": g["no"], "text": g.get("legenda") or g["fala"]} for g, t in zip(segs, ts)]
    events[0]["t"] = 0.0
    cfg = _base_cfg(diagram, title)
    cfg.update(events=events, duration=float(tts["seconds"]) + 0.5)
    return _capture(cfg, tts["path"], out), events
