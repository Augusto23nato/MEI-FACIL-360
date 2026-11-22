"""Voz: narração do vídeo (ElevenLabs, a voz escolhida no setup) e transcrição da SUA explicação falada.

- narrate: 1 chamada /with-timestamps (flash v2.5); o alinhamento por
  caractere sincroniza cada caixa do fluxograma com a frase que fala dela.
- transcribe: ElevenLabs Scribe (1–2 s para ~1 min de fala, com keyterms do conceito); se falhar, Whisper local.
"""
import base64
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import config


def credits_usd(chars):
    return chars * config.EL_CREDITS_PER_CHAR * config.EL_USD_PER_CREDIT


def sanitize(text, keep_questions=False):
    """Última camada (no código) antes do TTS. Narração do vídeo: sem perguntas (narração afirmativa).
    Conversa: '?' fica — é ele que dá a entonação de pergunta."""
    t = text if keep_questions else text.replace("?", ".")
    t = t.replace("…", ".").replace("...", ".")
    t = re.sub(r"[#*_>`→]", " ", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    return fix_questions(t) if keep_questions else t


# frase que É pergunta mas veio sem '?' (ex.: "Me diz, esse modelo precisa funcionar bem ... que ele nunca viu.")
_INTERROG = re.compile(  # só inícios que SÃO pergunta; "quando/como/onde/quem/o que" também abrem afirmações → ficam de fora
    r"^(?:e\s+|mas\s+|então,?\s+|agora,?\s+)?(?:qual|quais|por\s*que|pra\s+que|para\s+que|será\s+que|o\s+que\s+você|"
    r"você\s+(?:acha|consegue|sabe|lembra|percebe|imagina|entendeu|concorda)|consegue|dá\s+pra|faz\s+sentido|"
    r"me\s+di[zg]a?|me\s+fala|me\s+conta\s+(?:se|qual|como|o\s+que|por\s*que)|é\s+isso|tá\s+claro|ficou\s+claro|tem\s+como)(?![\w-])", re.I)


def fix_questions(text):
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if sent.endswith(".") and _INTERROG.match(sent):
            sent = sent[:-1] + "?"
        out.append(sent)
    return " ".join(out)


def narrate(text, out_mp3: Path):
    t0 = time.time()
    body = {"text": text, "model_id": config.EL_MODEL, "language_code": "pt", "seed": 42,
            "voice_settings": config.EL_SETTINGS}
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{config.EL_VOICE}/with-timestamps?output_format=mp3_44100_128",
                      headers={"xi-api-key": config.eleven_key()}, json=body, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    out_mp3.write_bytes(base64.b64decode(j["audio_base64"]))
    al = j.get("alignment") or j.get("normalized_alignment") or {}
    ends = al.get("character_end_times_seconds") or [0]
    return {"path": out_mp3, "seconds": ends[-1], "alignment": al, "chars": len(text),
            "usd": credits_usd(len(text)), "ms": int((time.time() - t0) * 1000)}


def speak(text):
    """Frase curta → MP3 sem timestamps (mais rápido): usado no modo conversa, frase a frase."""
    t0 = time.time()
    body = {"text": text, "model_id": config.EL_MODEL, "language_code": "pt", "voice_settings": config.EL_SETTINGS}
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{config.EL_VOICE}?output_format=mp3_44100_128",
                      headers={"xi-api-key": config.eleven_key()}, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
    return {"audio": r.content, "ms": int((time.time() - t0) * 1000), "usd": credits_usd(len(text))}


def so_fala(txt):
    """só a fala: sons marcados pela transcrição ("[ruído]", "(pigarro)", "[música]") não são resposta do aluno —
    um "[ruído]" não pode virar resposta e gastar tentativa."""
    txt = re.sub(r"\[[^\]]{0,40}\]|\([^)]{0,40}\)", " ", txt or "")
    txt = re.sub(r"\s+", " ", txt).strip(" ,.;")
    return txt if re.search(r"\w{2,}", txt) else ""


def transcribe(audio: bytes, mime: str, keyterms=()):
    """Devolve {text, engine, ms, usd}. Scribe primeiro; Whisper local (mlx) se o Scribe falhar."""
    t0 = time.time()
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(
        (mime or "").split(";")[0], "webm")
    try:
        data = {"model_id": "scribe_v1", "language_code": "por", "tag_audio_events": "false"}
        kt = [k for k in dict.fromkeys(keyterms) if 1 < len(k) <= 20][:50]
        if kt:
            data["keyterms"] = kt
        r = requests.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": config.eleven_key()},
                          data=data, files={"file": (f"fala.{ext}", audio, mime or "audio/webm")}, timeout=60)
        if r.status_code == 200:
            txt = so_fala(r.json().get("text") or "")
            return {"text": txt, "engine": "ElevenLabs Scribe v1", "ms": int((time.time() - t0) * 1000),
                    "usd": _duration(audio, ext) / 3600 * 0.40}
        err = f"Scribe HTTP {r.status_code}: {r.text[:160]}"
    except requests.RequestException as e:
        err = f"Scribe: {e}"
    txt = so_fala(_whisper_local(audio, ext))
    return {"text": txt, "engine": "Whisper local (mlx)", "ms": int((time.time() - t0) * 1000), "usd": 0.0, "fallback": err}


def _duration(audio, ext):
    with tempfile.NamedTemporaryFile(suffix="." + ext) as f:
        f.write(audio)
        f.flush()
        r = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f.name],
                           capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _whisper_local(audio, ext):
    try:
        import mlx_whisper
    except ImportError as e:
        raise RuntimeError("a transcrição do ElevenLabs falhou e não há Whisper local instalado (opcional, só Mac Apple Silicon: pip install mlx-whisper)") from e
    with tempfile.TemporaryDirectory() as d:
        src, wav = Path(d) / f"in.{ext}", Path(d) / "in.wav"
        src.write_bytes(audio)
        subprocess.run([config.FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav)], check=True)
        r = mlx_whisper.transcribe(str(wav), language="pt", path_or_hf_repo=config.WHISPER_REPO)
    return (r.get("text") or "").strip()
