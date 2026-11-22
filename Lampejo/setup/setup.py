#!/usr/bin/env python3
"""Setup do Lampejo — conduzido pelo Claude Code na primeira conversa (ver setup/SETUP.md).

Só usa a biblioteca padrão do Python. Cada passo é um subcomando, para o Claude rodar e explicar um de cada vez:

    python3 setup/setup.py check                      # o que já está instalado (JSON)
    python3 setup/setup.py install                    # instala o que falta (Homebrew no Mac / apt no Linux)
    python3 setup/setup.py open-signup                # abre a página de cadastro do ElevenLabs
    python3 setup/setup.py open-keys                  # abre a página de chaves de API do ElevenLabs
    python3 setup/setup.py eleven-test --key K        # valida a chave e lista as vozes da conta
    python3 setup/setup.py openrouter-test --key K    # (opcional) valida a chave do OpenRouter
    python3 setup/setup.py save --eleven-key K --voice ID [--voice-name N] [--openrouter-key K]
    python3 setup/setup.py verify                     # sobe o servidor e confere /api/health
    python3 setup/setup.py finish                     # remove os arquivos de setup (autodestruição)
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CFG_DIR = ROOT / ".lampejo"
CFG = CFG_DIR / "config.env"
ELEVEN_SIGNUP = "https://try.elevenlabs.io/yjgjgf3prib4"
ELEVEN_KEYS = "https://elevenlabs.io/app/settings/api-keys"
OPENROUTER_KEYS = "https://openrouter.ai/settings/keys"
PIP_PKGS = ["requests", "Pillow", "playwright"]
DRAWIO_MAC = "/Applications/draw.io.app/Contents/MacOS/draw.io"
MAC = platform.system() == "Darwin"
LINUX = platform.system() == "Linux"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def run(cmd, **kw):
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kw)


def drawio_path():
    return shutil.which("drawio") or (DRAWIO_MAC if Path(DRAWIO_MAC).exists() else None)


def venv_ok():
    if not VPY.exists():
        return False
    r = subprocess.run([str(VPY), "-c", "import requests, PIL, playwright"], capture_output=True)
    return r.returncode == 0


def chromium_ok():
    if not venv_ok():
        return False
    code = ("from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n b=p.chromium.launch(); b.close()")
    r = subprocess.run([str(VPY), "-c", code], capture_output=True, timeout=120)
    return r.returncode == 0


def claude_login():
    exe = shutil.which("claude")
    if not exe:
        return {"instalado": False, "logado": False}
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY" and not k.startswith("CLAUDECODE")}
    try:
        r = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=20, env=env)
        d = json.loads(r.stdout)
        return {"instalado": True, "logado": bool(d.get("loggedIn")), "metodo": d.get("authMethod")}
    except Exception:  # noqa: BLE001
        return {"instalado": True, "logado": None}


def cmd_check(_):
    v = sys.version_info
    out({
        "sistema": platform.system(),
        "python_ok": v >= (3, 10),
        "python": f"{v.major}.{v.minor}",
        "homebrew": bool(shutil.which("brew")) if MAC else None,
        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "drawio": bool(drawio_path()),
        "ambiente_python": venv_ok(),
        "navegador_de_captura": chromium_ok(),
        "claude_code": claude_login(),
        "config_salva": CFG.exists(),
    })


def cmd_install(_):
    falhas = []
    if MAC:
        if not shutil.which("brew"):
            out({"precisa_homebrew": True,
                 "comando_para_o_usuario": '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
                 "explicacao": "O Homebrew instala programas no Mac e pede a senha do computador, então a própria pessoa precisa rodar."})
            sys.exit(2)
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            if run(["brew", "install", "ffmpeg"]).returncode:
                falhas.append("ffmpeg")
        if not drawio_path():
            if run(["brew", "install", "--cask", "drawio"]).returncode:
                falhas.append("drawio")
    elif LINUX:
        if not shutil.which("ffmpeg"):
            if run(["sudo", "apt-get", "install", "-y", "ffmpeg"]).returncode:
                falhas.append("ffmpeg")
        if not drawio_path():
            if not shutil.which("snap") or run(["sudo", "snap", "install", "drawio"]).returncode:
                falhas.append("drawio (baixe em https://github.com/jgraph/drawio-desktop/releases)")
    else:
        falhas.append("Windows: instale o ffmpeg (winget install ffmpeg) e o draw.io (winget install JGraph.Draw) e rode o check de novo")
    if not VPY.exists():
        if run([sys.executable, "-m", "venv", str(VENV)]).returncode:
            falhas.append("ambiente python (.venv)")
    if VPY.exists():
        run([str(VPY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        if run([str(VPY), "-m", "pip", "install", "-q", *PIP_PKGS]).returncode:
            falhas.append("pacotes python")
        elif run([str(VPY), "-m", "playwright", "install", "chromium"]).returncode:
            falhas.append("navegador de captura (playwright chromium)")
    out({"ok": not falhas, "falhas": falhas})
    sys.exit(1 if falhas else 0)


def cmd_open(url):
    def _f(_):
        ok = False if os.environ.get("LAMPEJO_NO_OPEN") else webbrowser.open(url)
        out({"abriu": bool(ok), "url": url})
    return _f


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def cmd_eleven_test(a):
    h = {"xi-api-key": a.key.strip()}
    try:
        vozes = _get("https://api.elevenlabs.io/v1/voices", h).get("voices", [])
    except urllib.error.HTTPError as e:
        out({"ok": False, "erro": f"HTTP {e.code}", "dica": "Confira se copiou a chave inteira e se ela tem permissão de Text to Speech, Speech to Text e Voices (leitura)."})
        sys.exit(1)
    def idiomas(v):
        langs = [str((v.get("labels") or {}).get("language") or "")]
        langs += [str(x.get("language") or "") for x in (v.get("verified_languages") or [])]
        return {l.lower()[:2] for l in langs if l}

    def ordem(v):  # 1º clones da própria pessoa, depois vozes em português, depois o resto
        return (v.get("category") != "cloned", "pt" not in idiomas(v), v.get("category") != "professional", v.get("name") or "")
    lista = [{"voice_id": v["voice_id"], "nome": v.get("name"), "tipo": v.get("category"),
              "portugues": "pt" in idiomas(v),
              "descricao": ", ".join(str(x) for x in (v.get("labels") or {}).values())} for v in sorted(vozes, key=ordem)]
    out({"ok": True, "total": len(lista), "vozes": lista,
         "dica": "A lista já vem ordenada: clones criados pela pessoa ('cloned') primeiro, depois vozes em português. "
                 "'professional' pode ser um clone da pessoa OU uma voz da biblioteca adicionada à conta — pergunte antes de dizer que é a voz dela."})


def cmd_openrouter_test(a):
    try:
        d = _get("https://openrouter.ai/api/v1/key", {"Authorization": "Bearer " + a.key.strip()})
        out({"ok": True, "limite": (d.get("data") or {}).get("limit")})
    except urllib.error.HTTPError as e:
        out({"ok": False, "erro": f"HTTP {e.code}"})
        sys.exit(1)


def cmd_save(a):
    CFG_DIR.mkdir(exist_ok=True)
    chave = (a.eleven_key or os.environ.get("LAMPEJO_ELEVEN_KEY", "")).strip()
    if not chave:
        out({"ok": False, "erro": "falta a chave do ElevenLabs (--eleven-key ou LAMPEJO_ELEVEN_KEY)"})
        sys.exit(1)
    linhas = ["# Lampejo — configuração local. NÃO compartilhe este arquivo.",
              f"LSL_ELEVEN_KEY={chave}",
              f"LSL_ELEVEN_VOICE={a.voice.strip()}"]
    if a.voice_name:
        linhas.append(f"LSL_ELEVEN_VOICE_NAME={a.voice_name.strip()}")
    if a.openrouter_key:
        linhas.append(f"OPENROUTER_API_KEY={a.openrouter_key.strip()}")
    dw = drawio_path()
    if dw:
        linhas.append(f"LSL_DRAWIO={dw}")
    CFG.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    try:
        os.chmod(CFG, 0o600)
    except OSError:
        pass
    out({"ok": True, "arquivo": str(CFG.relative_to(ROOT))})


def cmd_verify(_):
    if not CFG.exists():
        out({"ok": False, "erro": "rode o passo save antes"})
        sys.exit(1)
    r = subprocess.run(["bash", str(ROOT / "iniciar.sh")], capture_output=True, text=True, cwd=ROOT)
    print(r.stdout.strip())
    health = None
    for _ in range(20):
        try:
            health = _get("http://127.0.0.1:" + os.environ.get("LSL_PORT", "4242") + "/api/health", {})
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    if not health:
        out({"ok": False, "erro": "servidor não respondeu", "log": "runs/server.log"})
        sys.exit(1)
    rec = health.get("recursos") or health
    faltando = [k for k in ("eleven_key", "eleven_voice", "render_diagram", "check_layout", "drawio", "ffmpeg") if rec.get(k) is False]
    out({"ok": not faltando, "faltando": faltando, "claude": rec.get("llm"), "imagens": bool(rec.get("openrouter_key")), "health": rec})
    sys.exit(1 if faltando else 0)


def cmd_finish(_):
    claude_md = ROOT / "CLAUDE.md"
    s = claude_md.read_text(encoding="utf-8")
    ini, fim = "<!-- SETUP:INICIO -->", "<!-- SETUP:FIM -->"
    if ini in s and fim in s:
        s = s[:s.index(ini)] + s[s.index(fim) + len(fim):].lstrip("\n")
        claude_md.write_text(s, encoding="utf-8")
    shutil.rmtree(ROOT / "setup", ignore_errors=True)
    out({"ok": True, "removido": ["setup/", "bloco de setup do CLAUDE.md"]})


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check").set_defaults(f=cmd_check)
    sp.add_parser("install").set_defaults(f=cmd_install)
    sp.add_parser("open-signup").set_defaults(f=cmd_open(ELEVEN_SIGNUP))
    sp.add_parser("open-keys").set_defaults(f=cmd_open(ELEVEN_KEYS))
    sp.add_parser("open-openrouter").set_defaults(f=cmd_open(OPENROUTER_KEYS))
    p = sp.add_parser("eleven-test"); p.add_argument("--key", required=True); p.set_defaults(f=cmd_eleven_test)
    p = sp.add_parser("openrouter-test"); p.add_argument("--key", required=True); p.set_defaults(f=cmd_openrouter_test)
    p = sp.add_parser("save")
    p.add_argument("--eleven-key"); p.add_argument("--voice", required=True)
    p.add_argument("--voice-name"); p.add_argument("--openrouter-key")
    p.set_defaults(f=cmd_save)
    sp.add_parser("verify").set_defaults(f=cmd_verify)
    sp.add_parser("finish").set_defaults(f=cmd_finish)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
