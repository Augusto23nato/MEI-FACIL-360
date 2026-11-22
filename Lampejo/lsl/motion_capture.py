#!/usr/bin/env python3
"""Captura esparsa da cena web/motion.html (roda como subprocesso, para o Chromium morrer junto).

Só os quadros de transição são fotografados; nas pausas o quadro é repetido pelo concat do ffmpeg.
    python3 -m lsl.motion_capture cfg.json audio.mp3 out.mp4
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FPS, TR = 25, 0.55


def main(cfg_path, audio, out):
    cfg = json.loads(Path(cfg_path).read_text())
    dur = float(cfg["duration"])
    times = sorted(max(0.0, e["t"]) for e in cfg["events"])
    # instantes a fotografar: t=0, cada quadro das transições e o fim de cada uma
    shots = {0.0}
    for t in times:
        k = 0
        while k / FPS <= TR + 1e-6:
            shots.add(round(t + k / FPS, 3)); k += 1
    shots = sorted(s for s in shots if s < dur)
    tmp = Path(tempfile.mkdtemp(prefix="lsl-motion-"))
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--disable-dev-shm-usage", "--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        pg.add_init_script("window.CFG = " + json.dumps(cfg) + ";")
        pg.goto((ROOT / "web" / "motion.html").as_uri())
        pg.wait_for_function("window.READY === true", timeout=20000)
        files = []
        for i, t in enumerate(shots):
            pg.evaluate(f"window.seek({t})")
            f = tmp / f"f{i:05d}.jpg"
            pg.screenshot(path=str(f), type="jpeg", quality=92)
            files.append((f, t))
        b.close()
    lst = tmp / "list.txt"
    lines = []
    for i, (f, t) in enumerate(files):
        nxt = files[i + 1][1] if i + 1 < len(files) else dur
        lines += [f"file '{f}'", f"duration {max(1 / FPS, nxt - t):.4f}"]
    lines.append(f"file '{files[-1][0]}'")
    lst.write_text("\n".join(lines) + "\n")
    ff = os.environ.get("LSL_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-af", "loudnorm=I=-14:TP=-2:LRA=11", "-c:a", "aac", "-b:a", "160k", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(out)], check=True)
    print(json.dumps({"out": str(out), "frames_capturados": len(files), "duracao": dur}))


if __name__ == "__main__":
    main(*sys.argv[1:4])
