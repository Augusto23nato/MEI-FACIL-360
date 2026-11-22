"""Cliente LLM do projeto.

Provedor padrão = ASSINATURA do Claude: logado numa conta claude.ai neste computador (`claude auth status`),
toda chamada vai pelo Claude Code (`claude -p`, sessão enxuta, sem chave de API, US$ 0). Sem login, cai no
OpenRouter (Claude Sonnet 5 / Haiku 4.5, chave paga). LSL_PROVIDER=assinatura|openrouter força um dos dois.

Lições da casa aplicadas:
- Sonnet 5 pelo OpenRouter SEM `reasoning` pensa sozinho e volta vazio com max_tokens curto → sempre
  `reasoning: {enabled: false}` no Sonnet. No Haiku o parâmetro é omitido.
- Processo `claude` filho herda ANTHROPIC_API_KEY/CLAUDECODE da sessão mãe → env limpo (config.child_env).
- Todo JSON que não vier é registrado com finish_reason (nada de None silencioso).
"""
import atexit
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import config


class LLMError(RuntimeError):
    pass


def _body(model, system, messages, max_tokens, temperature, stream):
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    b = {"model": model, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature,
         "stream": stream, "usage": {"include": True}}
    if "sonnet" in model or "opus" in model:
        b["reasoning"] = {"enabled": False}
    return b


def _cost(model, usage):
    if not usage:
        return 0.0
    if usage.get("cost") is not None:
        return float(usage["cost"])
    pin, pout = config.PRICES.get(model, (2.0, 10.0))
    return usage.get("prompt_tokens", 0) / 1e6 * pin + usage.get("completion_tokens", 0) / 1e6 * pout


def _request(body):
    key = config.openrouter_key()
    if not key:
        raise LLMError("sem chave OpenRouter")
    return urllib.request.Request(
        config.OPENROUTER_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "HTTP-Referer": "http://localhost", "X-Title": "lampejo"})


def _flatten(messages):
    """o `claude -p` recebe um prompt só: histórico (chat, correção de JSON) vira transcrição rotulada."""
    if len(messages) == 1:
        return messages[0]["content"]
    partes = []
    for m in messages[:-1]:
        partes.append(("[VOCÊ RESPONDEU ANTES]\n" if m["role"] == "assistant" else "[MENSAGEM ANTERIOR DO USUÁRIO]\n") + m["content"])
    return "\n\n".join(partes) + "\n\n[MENSAGEM ATUAL — responda a esta]\n" + messages[-1]["content"]


# ---------- reserva de processos `claude` pré-abertos (assinatura) ----------
# Abrir um `claude` custa ~1–1,5 s (às vezes 5–12 s). Um processo aberto ANTES, já esperando a mensagem em stream-json,
# dá a 1ª palavra em ~0,6 s (Haiku) / ~1,1 s (Sonnet), contra ~1,6 s num processo novo.
# Cada processo atende UMA mensagem e sai (nada de contexto misturado entre chamadas).
SPARE_TTL, MAX_SPARES = 600, 4
_POOL, _POOL_LOCK = [], threading.Lock()          # [(chave, criado_em, Popen, arquivo_stderr)]
_REAPER = []


def _alias(model):
    return config.SUB_MODEL_FAST if model == config.MODEL_FAST else config.SUB_MODEL_MAIN


def _key(alias, system):
    return alias, hashlib.sha1(system.encode()).hexdigest()


def _spawn(alias, system):
    config.CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
    cmd = [config.claude_cli(), "-p", "--model", alias, "--input-format", "stream-json", "--output-format", "stream-json",
           "--include-partial-messages", "--verbose", "--system-prompt", system, "--tools", "", "--strict-mcp-config",
           "--safe-mode", "--no-session-persistence", "--effort", config.SUB_EFFORT, "--settings", json.dumps({"alwaysThinkingEnabled": False})]
    err = tempfile.TemporaryFile(mode="w+")          # stderr em arquivo: PIPE sem leitor pode travar o processo
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
                         cwd=str(config.CLAUDE_HOME), env=config.child_env())
    return p, err


def _kill(entry):
    p, err = entry[2], entry[3]
    if p.poll() is None:
        p.kill()
        p.wait()
    err.close()


def _reap_locked():
    now, keep = time.time(), []
    for e in _POOL:
        (keep.append(e) if e[2].poll() is None and now - e[1] < SPARE_TTL else _kill(e))
    _POOL[:] = keep


def _reaper():
    while True:
        time.sleep(60)
        with _POOL_LOCK:
            _reap_locked()


def close_spares():
    with _POOL_LOCK:
        for e in _POOL:
            _kill(e)
        _POOL.clear()


atexit.register(close_spares)


def prewarm(system, model=None):
    """Deixa 1 processo `claude` aberto com este prompt de sistema, esperando a próxima mensagem. Só na assinatura."""
    if not system or config.provider() != "assinatura":
        return
    alias = _alias(model or config.MODEL_MAIN)
    k = _key(alias, system)
    with _POOL_LOCK:
        if not _REAPER:
            _REAPER.append(threading.Thread(target=_reaper, daemon=True))
            _REAPER[0].start()
        _reap_locked()
        if any(e[0] == k for e in _POOL):
            return
        try:
            p, err = _spawn(alias, system)
        except OSError:
            return
        _POOL.append((k, time.time(), p, err))
        while len(_POOL) > MAX_SPARES:
            _kill(_POOL.pop(0))


def discard(system, model=None):
    """fecha o reserva deste prompt (ex.: o prompt do chat mudou quando o gabarito ficou pronto)."""
    k = _key(_alias(model or config.MODEL_MAIN), system)
    with _POOL_LOCK:
        for e in [e for e in _POOL if e[0] == k]:
            _POOL.remove(e)
            _kill(e)


def prewarm_async(system, model=None):
    threading.Thread(target=prewarm, args=(system, model), daemon=True).start()


def _take(k):
    with _POOL_LOCK:
        _reap_locked()
        for i, e in enumerate(_POOL):
            if e[0] == k:
                return _POOL.pop(i)[2:]
    return None


def _stream_assinatura(system, messages, model, on_delta, meter, label, warm=False):
    """Claude pela ASSINATURA: `claude -p` do Claude Code logado, sessão enxuta (sem ferramentas, MCP, CLAUDE.md, hooks),
    stream-json com deltas de texto. Custo em US$ = 0 (sai da cota da assinatura); guardamos o equivalente de API.
    warm=True: usa/repõe um processo pré-aberto para este prompt de sistema (caminhos interativos)."""
    alias = _alias(model)
    system = system or "Responda em português do Brasil."
    t0 = time.time()
    got = _take(_key(alias, system))
    p, err = got or _spawn(alias, system)
    ttft, out, res = None, [], None
    try:
        try:
            p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": _flatten(messages)},
                                      "parent_tool_use_id": None, "session_id": "default"}) + "\n")
            p.stdin.close()
        except BrokenPipeError:          # o claude morreu antes de ler: o stderr diz por quê
            pass
        for line in p.stdout:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("type") == "stream_event":
                ev = j.get("event") or {}
                d = ev.get("delta") or {}
                if ev.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                    if ttft is None:
                        ttft = time.time() - t0
                    out.append(d["text"])
                    if on_delta:
                        on_delta(d["text"])
            elif j.get("type") == "result":
                res = j
                break
        p.wait(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
        if warm:
            prewarm_async(system, model)                    # repõe o reserva para a próxima vez
    res = res or {}
    text = "".join(out) or ("" if res.get("is_error") else res.get("result") or "")
    if not text.strip() or res.get("is_error"):
        err.seek(0)
        motivo = res.get("result") or err.read().strip()[:300] or f"resposta vazia (saída {p.returncode})"
        err.close()
        raise LLMError(f"assinatura Claude: {motivo}")
    err.close()
    if meter:
        u = res.get("usage") or {}
        meter(label, {"provider": "assinatura Claude (Claude Code)", "model": ",".join(res.get("modelUsage", {}).keys()) or alias,
                      "ttft": ttft, "total": time.time() - t0, "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens"),
                      "usd": 0.0, "usd_equiv_api": res.get("total_cost_usd"), "pre_aberto": bool(got)})
    return text


def stream(system, messages, *, model=None, max_tokens=900, temperature=0.4, on_delta=None, meter=None, label="llm", warm=False):
    """Gera texto em streaming. on_delta(str) a cada pedaço. Devolve o texto completo.
    meter(label, dict) recebe tempos (ttft, total), tokens e custo.
    Provedor: assinatura do Claude (Claude Code logado) sempre que houver login; OpenRouter só sem login."""
    model = model or config.MODEL_MAIN
    if config.provider() == "assinatura":
        try:
            return _stream_assinatura(system, messages, model, on_delta, meter, label, warm)
        except (LLMError, OSError, subprocess.SubprocessError) as e:
            if not (config.SUB_FALLBACK_OPENROUTER and config.openrouter_key()):
                raise
            if meter:
                meter(label + "_fallback", {"provider": "openrouter (fallback pedido)", "total": 0.0, "usd": 0.0, "motivo": str(e)[:200]})
    t0 = time.time()
    ttft, out, usage, finish = None, [], None, None
    try:
        req = _request(_body(model, system, messages, max_tokens, temperature, True))
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    j = json.loads(data)
                except ValueError:
                    continue
                if j.get("usage"):
                    usage = j["usage"]
                ch = (j.get("choices") or [{}])[0]
                finish = ch.get("finish_reason") or finish
                c = (ch.get("delta") or {}).get("content")
                if c:
                    if ttft is None:
                        ttft = time.time() - t0
                    out.append(c)
                    if on_delta:
                        on_delta(c)
        text = "".join(out)
        if not text.strip():
            raise LLMError(f"resposta vazia (finish_reason={finish})")
        if meter:
            meter(label, {"provider": "openrouter", "model": model, "ttft": ttft, "total": time.time() - t0,
                          "tokens_in": (usage or {}).get("prompt_tokens"), "tokens_out": (usage or {}).get("completion_tokens"),
                          "usd": _cost(model, usage), "finish": finish})
        return text
    except (urllib.error.URLError, LLMError, TimeoutError, OSError) as e:
        if out:          # já mostramos parte ao aluno: não duplica, devolve o que veio
            return "".join(out)
        try:             # OpenRouter caiu: tenta a assinatura (o login pode ter acontecido depois do último teste)
            return _stream_assinatura(system, messages, model, on_delta, meter, label)
        except (LLMError, OSError, subprocess.SubprocessError) as e2:
            raise LLMError(f"OpenRouter falhou ({e}) e a assinatura Claude também ({e2})") from e2


def complete(system, messages, *, model=None, max_tokens=1500, temperature=0.3, meter=None, label="llm", warm=False):
    return stream(system, messages, model=model, max_tokens=max_tokens, temperature=temperature, meter=meter, label=label, warm=warm)


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        return json.loads(text[a:b + 1])
    raise ValueError("sem JSON")


def _guarda_invalido(label, attempt, err, text):
    """toda resposta JSON recusada fica em runs/_json_invalidos/ (para entender o formato que o modelo devolveu)."""
    try:
        d = config.RUNS / "_json_invalidos"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-t{attempt}.txt").write_text(f"{err}\n\n{text}")
    except OSError:
        pass


def json_call(system, user, *, model=None, max_tokens=2500, temperature=0.2, meter=None, label="json", validate=None, warm=False):
    """Chamada que precisa devolver JSON. 2 tentativas; a 2ª recebe o erro da 1ª."""
    messages = [{"role": "user", "content": user}]
    last_err = None
    for attempt in range(2):
        text = complete(system, messages, model=model, max_tokens=max_tokens, temperature=temperature,
                        meter=meter, label=label if attempt == 0 else label + "_retry", warm=warm)
        try:
            data = _extract_json(text)
            if validate:
                validate(data)
            return data
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            last_err = f"{type(e).__name__}: {e}"
            _guarda_invalido(label, attempt, last_err, text)
            messages = messages + [{"role": "assistant", "content": text[:6000]},
                                   {"role": "user", "content": f"Seu JSON veio inválido ({last_err}). Devolva SÓ o JSON corrigido, completo, sem comentários."}]
    raise LLMError(f"{label}: JSON inválido após 2 tentativas ({last_err})")
