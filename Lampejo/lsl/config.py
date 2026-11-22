"""Configuração do protótipo: caminhos, portas e leitura de chaves EM TEMPO DE EXECUÇÃO.

Nenhuma chave vive no código. Elas ficam em .lampejo/config.env (criado pelo setup, fora do git)
ou em variáveis de ambiente, que têm prioridade. Nada disso é servido ao navegador.
"""
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNS = ROOT / "runs"
CONFIG_FILE = ROOT / ".lampejo" / "config.env"


def _load_env_file():
    """lê .lampejo/config.env (KEY=valor por linha) sem sobrescrever o que já veio do ambiente."""
    if not CONFIG_FILE.is_file():
        return
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env_file()

PORT = int(os.environ.get("LSL_PORT", "4242"))
HOST = os.environ.get("LSL_HOST", "127.0.0.1")
# HTTPS na rede: o navegador só libera microfone em https ou localhost (celular pelo IP precisa disto)
HTTPS_PORT = int(os.environ.get("LSL_HTTPS_PORT", "4243"))
CERT_FILE = ROOT / ".certs" / "lsl.pem"
KEY_FILE = ROOT / ".certs" / "lsl-key.pem"

# --- LLM (OpenRouter: opcional, só usado sem login no Claude Code) ---
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_MAIN = os.environ.get("LSL_MODEL_MAIN", "anthropic/claude-sonnet-5")
MODEL_FAST = os.environ.get("LSL_MODEL_FAST", "anthropic/claude-haiku-4.5")

# --- Claude pela ASSINATURA (Claude Code logado neste computador; sem chave de API) ---
# LSL_PROVIDER: auto (padrão: assinatura se houver login claude.ai; senão OpenRouter) | assinatura | openrouter
PROVIDER = os.environ.get("LSL_PROVIDER", "auto")
SUB_MODEL_MAIN = os.environ.get("LSL_SUB_MODEL_MAIN", "sonnet")        # alias do Claude Code → Claude Sonnet 5
SUB_MODEL_FAST = os.environ.get("LSL_SUB_MODEL_FAST", "haiku")         # → Claude Haiku 4.5
# esforço do Claude Code: "high" (com "low" a correção da prova oral piorou nos testes).
SUB_EFFORT = os.environ.get("LSL_SUB_EFFORT", "high")
SUB_FALLBACK_OPENROUTER = os.environ.get("LSL_FALLBACK_OPENROUTER", "0") == "1"   # logado: nunca cai para API paga, salvo pedido
CLAUDE_HOME = RUNS / "_claude_home"                                     # cwd neutro: nenhum CLAUDE.md de projeto entra

# preço por milhão de tokens (entrada, saída) — usado só se o OpenRouter não devolver usage.cost
PRICES = {MODEL_MAIN: (2.0, 10.0), MODEL_FAST: (1.0, 5.0)}

# --- ElevenLabs (sua conta e a voz que você escolheu no setup) ---
EL_VOICE = os.environ.get("LSL_ELEVEN_VOICE", "")
EL_MODEL = "eleven_flash_v2_5"
EL_SETTINGS = {"stability": 0.40, "similarity_boost": 0.65, "style": 0, "use_speaker_boost": True, "speed": 1.0}
EL_USD_PER_CREDIT = 99 / 600_000                                          # referência: plano Pro
EL_CREDITS_PER_CHAR = 0.5                                                 # flash v2.5

# --- ferramentas locais (instaladas pelo setup) ---
TOOLS = ROOT / "tools"
RENDER_DIAGRAM = TOOLS / "render_diagram.sh"
CHECK_LAYOUT = TOOLS / "check_layout.py"
FFMPEG = os.environ.get("LSL_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("LSL_FFPROBE") or shutil.which("ffprobe") or "ffprobe"
_DRAWIO_CANDIDATES = ["/Applications/draw.io.app/Contents/MacOS/draw.io", "/usr/bin/drawio", "/snap/bin/drawio"]
DRAWIO = os.environ.get("LSL_DRAWIO") or shutil.which("drawio") or next((c for c in _DRAWIO_CANDIDATES if Path(c).exists()), "drawio")


def openrouter_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    return ""


def eleven_key() -> str:
    return os.environ.get("LSL_ELEVEN_KEY", "").strip() or os.environ.get("ELEVENLABS_API_KEY", "").strip()


_AUTH = {"t": 0.0, "v": None}


def claude_cli():
    return os.environ.get("LSL_CLAUDE_CLI") or shutil.which("claude") or "claude"


def child_env() -> dict:
    """ambiente do processo `claude`: sem ANTHROPIC_API_KEY (senão cobra na API em vez da assinatura) e sem variáveis
    de sessão do Claude Code herdadas."""
    drop = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_EFFORT", "CLAUDE_PID", "CLAUDE_AGENT_SDK_VERSION", "ANTHROPIC_API_KEY")
    return {k: v for k, v in os.environ.items() if not any(k == d or k.startswith(d) for d in drop)}


def auth_status(max_age=60):
    """`claude auth status` (cache de 60 s): logou numa conta claude.ai → o projeto passa a usar a assinatura sozinho."""
    import subprocess, time
    if _AUTH["v"] is not None and time.time() - _AUTH["t"] < max_age:
        return _AUTH["v"]
    try:
        r = subprocess.run([claude_cli(), "auth", "status", "--json"], capture_output=True, text=True, timeout=15, env=child_env())
        d = json.loads(r.stdout)
        v = {"logado": bool(d.get("loggedIn")), "metodo": d.get("authMethod"), "plano": d.get("subscriptionType")}
    except Exception as e:  # noqa: BLE001
        # a checagem falhou (não é "deslogou"): vale o último estado conhecido; sem nenhum, tenta de novo em 5 s
        if _AUTH["v"] is not None and "erro" not in _AUTH["v"]:
            _AUTH["t"] = time.time()
            return _AUTH["v"]
        _AUTH.update(t=time.time() - max_age + 5, v={"logado": False, "erro": str(e)[:120]})
        return _AUTH["v"]
    _AUTH.update(t=time.time(), v=v)
    return v


def provider():
    if PROVIDER in ("assinatura", "openrouter"):
        return PROVIDER
    a = auth_status()
    if a.get("logado") and a.get("metodo") in ("claude.ai", "oauth", "claudeai"):
        return "assinatura"
    return "openrouter" if openrouter_key() else "assinatura"


def check() -> dict:
    """Diagnóstico sem expor segredo: só diz se cada recurso foi encontrado."""
    a = auth_status()
    return {
        "llm": provider(),
        "assinatura": {"logado": a.get("logado"), "plano": a.get("plano"), "metodo": a.get("metodo")},
        "openrouter_key": bool(openrouter_key()),
        "eleven_key": bool(eleven_key()),
        "render_diagram": RENDER_DIAGRAM.exists(),
        "check_layout": CHECK_LAYOUT.exists(),
        "eleven_voice": bool(EL_VOICE),
        "drawio": bool(shutil.which(DRAWIO) or Path(DRAWIO).exists()),
        "ffmpeg": bool(shutil.which(FFMPEG) or Path(FFMPEG).exists()),
    }
