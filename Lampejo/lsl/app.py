"""Sessão de estudo (v2) — 3 peças:
1. slide 1 em streaming + chat/conversa por voz + "mais exemplos" na hora (pré-gerado enquanto você digita o conceito);
2. fluxograma draw.io animado em vídeo com narração;
3. prova oral rápida de 3 perguntas tiradas SÓ da aula: o que é · um exemplo · um cenário. A correção de cada
   resposta roda em 2º plano enquanto a próxima pergunta já é feita (sem "entendi" no meio). Errou alguma? No fim,
   reaprendizagem só no que faltou (mini-aula + pergunta nova; se errar de novo, explicação + repetir), preparada em
   2º plano durante a própria prova. Sessão única: o conceito fecha aqui, sem revisão depois.
Estado público (vai ao navegador) × gabarito oculto (fica aqui)."""
import json
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, llm, prompts, voice

POOL = ThreadPoolExecutor(max_workers=16)
SESSIONS = {}
PREFETCH = {}                     # conceito normalizado → slide 1 sendo gerado antes do clique
PREFETCH_TTL = 1800


def slugify(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip())
    return s.strip("-")[:40] or "conceito"


def norm(c):
    return " ".join(c.lower().split())


def llm_info():
    """quem responde pelo Claude agora: a assinatura (Claude Code logado) ou a API paga do OpenRouter."""
    a = config.auth_status()
    return {"provedor": config.provider(), "plano": a.get("plano") if a.get("logado") else None}


class Session:
    def __init__(self, concept):
        self.id = uuid.uuid4().hex[:8]
        self.concept = concept.strip()
        self.t0 = time.time()
        self.dir = config.RUNS / f"{slugify(concept)}-{self.id}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events, self.cv = [], threading.Condition()
        self.metrics, self.lock = [], threading.Lock()
        self.jobs = {}
        self.mapa = None                 # OCULTO — só o que a aula ensinou (slide 1 + narração do vídeo)
        self.map_ready = threading.Event()
        self.roteiro = None              # fluxograma + narração do vídeo (o que o vídeo ENSINA), base do gabarito
        self.slide1_done, self.roteiro_ready = threading.Event(), threading.Event()
        self.slide1 = ""
        self.slide1_source = "gerado ao clicar"
        self.video = None
        self.imagens = []                # slide 3: [{titulo, legenda, url}] na ordem da aula
        self.exam = None                 # prova oral: fase, estratégia, turnos, estado de cada ideia, veredito
        self.chat = []                   # histórico da conversa de dúvidas [{"role", "content"}]
        self.exemplos = []               # exemplos extras pedidos no slide 1 ("MAIS EXEMPLOS")
        self.dirty = True

    # ---------- eventos / métricas ----------
    def emit(self, kind, **data):
        with self.cv:
            ev = {"i": len(self.events), "t": round(time.time() - self.t0, 2), "kind": kind, **data}
            self.events.append(ev)
            self.dirty = True
            self.cv.notify_all()
        return ev

    # ---------- persistência: a sessão sobrevive a reinícios do servidor ----------
    SAVE = ("id", "concept", "t0", "slide1", "slide1_source", "mapa", "roteiro", "video", "imagens", "exam", "chat", "exemplos", "jobs",
            "metrics", "events")

    def save(self):
        with self.cv:                            # só o cv (meter() pega lock → cv; pegar os dois aqui travaria)
            data = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                    for k, v in ((k, getattr(self, k)) for k in self.SAVE)}
            self.dirty = False
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(self.dir / "session.json")

    @classmethod
    def restore(cls, path: Path):
        d = json.loads(path.read_text())
        s = cls.__new__(cls)
        s.dir = path.parent
        s.events, s.cv, s.lock = [], threading.Condition(), threading.Lock()
        s.map_ready, s.dirty = threading.Event(), False
        for k in cls.SAVE:
            setattr(s, k, d.get(k))
        s.events, s.jobs, s.metrics = s.events or [], s.jobs or {}, s.metrics or []
        s.chat, s.exemplos, s.imagens = s.chat or [], s.exemplos or [], s.imagens or []
        if s.exam and not isinstance(s.exam.get("respostas"), list):   # prova do formato antigo (socrático): recomeça
            s.exam = None
        s.slide1_done, s.roteiro_ready = threading.Event(), threading.Event()
        if s.mapa and s.mapa.get("perguntas"):          # gabarito do formato antigo (pontos) é refeito no boot
            s.map_ready.set()
        if s.slide1:
            s.slide1_done.set()
        if s.roteiro or (s.jobs.get("video") or {}).get("status") == "pronto":
            s.roteiro_ready.set()
        return s

    def meter(self, label, d):
        d = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}
        d["label"], d["at"] = label, round(time.time() - self.t0, 2)
        with self.lock:
            self.metrics.append(d)
        self.emit("metric", metric=d)

    def job(self, name, status, **extra):
        j = self.jobs.setdefault(name, {"name": name})
        j.update(status=status, at=round(time.time() - self.t0, 2), **extra)
        if status == "gerando" and "started" not in j:
            j["started"] = j["at"]
        if status in ("pronto", "erro") and "started" in j:
            j["secs"] = round(j["at"] - j["started"], 1)
        self.emit("job", job=dict(j))

    def usd(self):
        return round(sum(m.get("usd") or 0 for m in self.metrics), 4)

    def public(self):
        m = self.mapa
        return {"id": self.id, "concept": self.concept, "t": round(time.time() - self.t0, 1), "jobs": self.jobs,
                "usd": self.usd(), "metrics": self.metrics, "slide1_source": self.slide1_source, "llm": llm_info(),
                "mapa_publico": {"n": len(m["perguntas"])} if m and m.get("perguntas") else None,
                "video": self.video, "imagens": self.imagens, "exam": exam_public(self), "exemplos": self.exemplos}

    def url(self, p):
        return "/runs/" + str(Path(p).relative_to(config.RUNS)) if p else None

    def keyterms(self):
        return [w for w in re.findall(r"\w{3,}", self.concept)] + list((self.mapa or {}).get("palavras_chave") or [])


def _safe(s, name, fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 — erro vira estado visível no slide, nunca some
        traceback.print_exc()
        s.job(name, "erro", detail=f"{type(e).__name__}: {str(e)[:300]}")


def _saver():
    while True:
        time.sleep(1.0)
        for s in list(SESSIONS.values()):
            if getattr(s, "dirty", False):
                try:
                    s.save()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()


def restore_sessions(max_age_h=48):
    """No boot: recarrega as sessões salvas em runs/*/session.json e retoma o que o reinício interrompeu."""
    n = 0
    for f in sorted(config.RUNS.glob("*/session.json")):
        if time.time() - f.stat().st_mtime > max_age_h * 3600:
            continue
        try:
            s = Session.restore(f)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        SESSIONS[s.id] = s
        n += 1
        if s.jobs.get("mapa", {}).get("status") != "pronto" or not (s.mapa or {}).get("perguntas"):
            POOL.submit(_safe, s, "mapa", run_map, s)
        if s.jobs.get("video", {}).get("status") not in ("pronto",):
            s.jobs.pop("video", None)
            POOL.submit(_safe, s, "video", run_video, s)
        if "imagens" in s.jobs and s.jobs["imagens"].get("status") != "pronto":   # sessão de antes do slide 3 não ganha imagens (custo)
            s.jobs.pop("imagens", None)
            POOL.submit(_safe, s, "imagens", run_imagens, s)
        if s.jobs.get("slide1", {}).get("status") != "pronto":
            s.job("slide1", "erro", detail="interrompido por um reinício do servidor — abra um conceito novo")
    threading.Thread(target=_saver, daemon=True).start()
    return n


# ---------- pré-geração do slide 1 (enquanto o conceito é digitado) ----------
def prefetch(concept):
    key = norm(concept)
    if not key or len(key) < 3:
        return {"ok": False}
    for k in [k for k, v in PREFETCH.items() if time.time() - v["t0"] > PREFETCH_TTL]:
        PREFETCH.pop(k, None)
    if key in PREFETCH:
        return {"ok": True, "status": "já estava gerando"}
    e = PREFETCH[key] = {"t0": time.time(), "text": "", "done": False, "first": None, "metric": None, "cv": threading.Condition()}

    def run():
        def on_delta(c):
            with e["cv"]:
                if e["first"] is None:
                    e["first"] = time.time() - e["t0"]
                e["text"] += c
                e["cv"].notify_all()

        def meter(label, d):
            e["metric"] = d
        try:
            llm.stream(prompts.SLIDE1_SYS, [{"role": "user", "content": prompts.slide1_user(concept)}],
                       max_tokens=450, temperature=0.5, on_delta=on_delta, meter=meter, label="slide1", warm=True)
        except Exception:  # noqa: BLE001 — sessão gera de novo se a pré-geração falhar
            traceback.print_exc()
            e["failed"] = True
        with e["cv"]:
            e["done"] = True
            e["cv"].notify_all()
    POOL.submit(run)
    return {"ok": True, "status": "gerando"}


def create(concept):
    s = Session(concept)
    SESSIONS[s.id] = s
    s.emit("start", concept=s.concept)
    POOL.submit(_safe, s, "slide1", run_slide1, s)
    POOL.submit(_safe, s, "mapa", run_map, s)
    POOL.submit(_safe, s, "video", run_video, s)
    POOL.submit(_safe, s, "imagens", run_imagens, s)
    return s


# ---------- 1. slide 1 ----------
def run_slide1(s):
    s.job("slide1", "gerando")
    e = PREFETCH.get(norm(s.concept))
    if e and not e.get("failed") and time.time() - e["t0"] < PREFETCH_TTL:
        s.slide1_source = f"pré-gerado enquanto você digitava (começou {round(s.t0 - e['t0'], 1)} s antes do clique)"
        pos = 0
        while True:
            with e["cv"]:
                while pos == len(e["text"]) and not e["done"]:
                    e["cv"].wait(0.5)
                chunk, done = e["text"][pos:], e["done"]
            if chunk:
                if pos == 0:
                    s.emit("s1_first", secs=round(time.time() - s.t0, 2))
                pos += len(chunk)
                s.slide1 += chunk
                s.emit("s1", delta=chunk)
            if done and pos == len(e["text"]):
                break
        if not e.get("failed") and s.slide1.strip():
            if e["metric"]:
                s.meter("slide1", dict(e["metric"], prefetch=True))
            s.job("slide1", "pronto", secs_total=round(time.time() - s.t0, 2), fonte=s.slide1_source)
            s.slide1_done.set()
            _aquece_chat_cedo(s)
            return
        s.slide1 = ""                             # pré-geração falhou: gera agora
        s.slide1_source = "gerado ao clicar"
    first = [None]

    def on_delta(c):
        if first[0] is None:
            first[0] = True
            s.emit("s1_first", secs=round(time.time() - s.t0, 2))
        s.slide1 += c
        s.emit("s1", delta=c)
    llm.stream(prompts.SLIDE1_SYS, [{"role": "user", "content": prompts.slide1_user(s.concept)}],
               max_tokens=450, temperature=0.5, on_delta=on_delta, meter=s.meter, label="slide1", warm=True)
    s.job("slide1", "pronto", secs_total=round(time.time() - s.t0, 2), fonte=s.slide1_source)
    s.slide1_done.set()
    _aquece_chat_cedo(s)


# ---------- mapa oculto (gabarito da explicação de volta) ----------
def aula_texto(s):
    """o que a aula ENSINOU: o texto do slide 1 + a narração do vídeo, na ordem em que o aluno ouviu."""
    partes = []
    if s.slide1:
        partes.append("SLIDE 1 (texto na tela):\n" + re.sub(r"\[(SIMPLES|ANALOGIA|EXEMPLO)\]", lambda m: m.group(1).capitalize() + ":", s.slide1).strip())
    r = s.roteiro
    if r:
        fluxo = r.get("fluxo", [])[:5]
        ids = {n["id"] for n in fluxo}
        laterais = {l.get("abaixo_de"): l for l in r.get("laterais", []) if l.get("abaixo_de") in ids}
        def ouvida(n):          # a frase narrada; a legenda só entra se for a mesma frase na grafia normal ("F1" em vez de "efe um")
            f, lg = n.get("fala", ""), n.get("legenda") or ""
            return lg if lg and len(lg.split()) >= 0.6 * len(f.split()) else f
        falas = [r.get("abertura", "")]
        for n in fluxo:
            falas.append(ouvida(n))
            if n["id"] in laterais:
                falas.append(ouvida(laterais[n["id"]]))
        falas.append(r.get("fechamento", ""))
        caixas = " → ".join(f"{n.get('rotulo', '')} ({n.get('detalhe', '')})" for n in fluxo)
        partes.append(f"VÍDEO — fluxograma: {caixas}\nNarração do vídeo:\n" + "\n".join(f for f in falas if f))
    if s.exemplos:
        partes.append("MAIS EXEMPLOS que o aluno pediu:\n" + "\n".join(f"- {x}" for x in s.exemplos))
    return "\n\n".join(partes)


def run_map(s):
    """plano da prova: 3 perguntas (o que é · exemplo · cenário) com gabarito, tiradas do slide 1 + narração do vídeo."""
    s.job("mapa", "gerando", detail="esperando a aula (slide 1 + roteiro do vídeo)")
    s.slide1_done.wait(60)
    s.roteiro_ready.wait(90)
    aula = aula_texto(s)
    if not aula:
        raise RuntimeError("a aula não ficou pronta: sem ela não há o que perguntar na prova")
    s.job("mapa", "gerando", detail="montando as 3 perguntas a partir da aula")
    s.mapa = llm.json_call(prompts.PROVA_SYS, prompts.prova_user(s.concept, aula), max_tokens=1400, meter=s.meter,
                           label="prova_perguntas", validate=prompts.validate_prova(aula))
    for q in s.mapa["perguntas"]:
        q["pergunta"] = voice.fix_questions(q["pergunta"])
    s.map_ready.set()
    s.job("mapa", "pronto", n=len(s.mapa["perguntas"]))
    aquecer(s, "prova")
    POOL.submit(_pre_voz, [_fala_pergunta(s, k) for k in range(3)])   # a voz das 3 perguntas já fica pronta


# ---------- 2. fluxograma + vídeo ----------
def run_video(s):
    from . import diagram, video
    s.job("video", "gerando", etapa="fluxograma", detail="escrevendo o fluxograma e a narração")
    try:
        spec = llm.json_call(prompts.VIDEO_SYS, prompts.video_user(s.concept), max_tokens=2200, meter=s.meter,
                             label="fluxograma_e_roteiro", validate=prompts.validate_video)
        s.roteiro = spec
    finally:
        s.roteiro_ready.set()                    # o gabarito da prova nunca fica esperando para sempre
    s.job("video", "gerando", etapa="drawio", detail="desenhando no draw.io")
    t = time.time()
    dg = diagram.render(spec, s.dir / "fluxograma")
    s.meter("drawio", {"provider": f"draw.io CLI ({dg['via']})", "total": time.time() - t, "usd": 0.0,
                       "check_blocking": len(dg["check_blocking"])})
    drawn = {n["id"] for n in dg["nodes"]}
    segs = [{"no": "todos", "fala": spec["abertura"]}]
    laterais = {l.get("abaixo_de"): l for l in spec.get("laterais", []) if l["id"] in drawn}
    for n in spec["fluxo"]:
        if n["id"] in drawn:
            segs.append({"no": n["id"], "fala": n["fala"], "legenda": n.get("legenda")})
            if n["id"] in laterais:
                l = laterais[n["id"]]
                segs.append({"no": l["id"], "fala": l["fala"], "legenda": l.get("legenda")})
    segs.append({"no": "todos", "fala": spec["fechamento"]})
    for g in segs:
        f = voice.sanitize(g["fala"]).rstrip(".! ")
        g["fala"] = re.sub(r"[.!]\s+", ", ", f) + "."            # 1 frase por segmento (camada no código)
        if g.get("legenda"):
            g["legenda"] = g["legenda"].strip()
    s.job("video", "gerando", etapa="narracao", detail="narração em voz")
    tts = voice.narrate(" ".join(g["fala"] for g in segs), s.dir / "video" / "narracao.mp3")
    s.meter("narracao", {"provider": "ElevenLabs flash v2.5 (with-timestamps)", "total": tts["ms"] / 1000,
                         "usd": tts["usd"], "chars": tts["chars"]})
    s.job("video", "gerando", etapa="motion", detail="animando o fluxograma no ritmo da voz")
    t = time.time()
    mp4, eventos = video.render_tour(dg, spec.get("titulo") or s.concept, segs, tts, s.dir / "video" / "fluxograma.mp4")
    s.meter("motion", {"provider": "HTML seek(t) + Playwright + ffmpeg", "total": time.time() - t, "usd": 0.0})
    s.video = {"url": s.url(mp4), "poster": s.url(dg["png"]), "seconds": round(tts["seconds"], 1),
               "titulo": spec.get("titulo"), "caixas": len(dg["nodes"]),
               "trechos": [{"i": k, "inicio": round(ev["t"], 2), "fim": round(eventos[k + 1]["t"] if k + 1 < len(eventos) else tts["seconds"], 2),
                            "texto": ev["text"]} for k, ev in enumerate(eventos)]}
    s.job("video", "pronto", etapa="pronto", detail="", video=s.video)


# ---------- 3. o conceito em imagens ----------
def run_imagens(s):
    """começa assim que o roteiro do vídeo existe: as 4 imagens ficam prontas enquanto o vídeo é desenhado e assistido."""
    from . import imagens
    if not config.openrouter_key():                    # opcional: sem chave, o slide só explica como ligar
        s.job("imagens", "desligado", detail="Imagens desligadas. Para ativar, peça ao Claude: ativar as imagens do Lampejo.")
        return
    s.job("imagens", "gerando", detail="esperando a aula")
    s.slide1_done.wait(60)
    s.roteiro_ready.wait(120)
    s.job("imagens", "gerando", detail="escolhendo o que desenhar")
    plano = llm.json_call(prompts.IMAGENS_SYS, prompts.imagens_user(s.concept, aula_texto(s)), max_tokens=1400,
                          meter=s.meter, label="imagens_plano", validate=prompts.validate_imagens)["imagens"]
    s.imagens = [{"titulo": p["titulo"], "legenda": p["legenda"], "url": None} for p in plano]
    s.job("imagens", "gerando", detail=f"desenhando 0 de {len(plano)}", imagens=[dict(x) for x in s.imagens])
    feitas = [0]

    def uma(k):
        try:
            r = imagens.gerar(plano[k]["cena"], s.dir / "imagens" / f"{k + 1}.png")
        except Exception as e:  # noqa: BLE001 — uma imagem que falha não derruba as outras
            traceback.print_exc()
            s.imagens[k]["erro"] = str(e)[:200]
            return
        s.imagens[k]["url"] = s.url(s.dir / "imagens" / f"{k + 1}.png")
        s.meter(f"imagem_{k + 1}", {"provider": f"{imagens.MODEL} (OpenRouter)", "total": r["secs"], "usd": r["usd"]})
        with s.lock:
            feitas[0] += 1
        s.job("imagens", "gerando", detail=f"desenhando {feitas[0]} de {len(plano)}", imagens=[dict(x) for x in s.imagens])
    with ThreadPoolExecutor(max_workers=len(plano)) as ex:
        list(ex.map(uma, range(len(plano))))
    if not feitas[0]:
        raise RuntimeError(next((x.get("erro") for x in s.imagens if x.get("erro")), "nenhuma imagem saiu"))
    s.job("imagens", "pronto", detail="", imagens=[dict(x) for x in s.imagens])


# ---------- chat ----------
def _chat_sys(s, modo="texto"):
    ctx = f"\n\nConceito: {s.concept}\nExplicação já mostrada ao aluno no slide:\n{s.slide1[:1500]}"
    return (prompts.CHAT_VOICE_SYS if modo == "voz" else prompts.CHAT_SYS) + ctx


def aquecer(s=None, alvo=None):
    """Pré-abre o processo `claude` (assinatura) do próximo passo provável: a 1ª palavra chega ~0,5–1 s antes."""
    if s is None:
        llm.prewarm_async(prompts.SLIDE1_SYS)
    elif alvo in ("voz", "texto"):
        warm = s.__dict__.setdefault("_warm", {})       # prompt do chat já pré-aberto, por modo
        if not s.slide1:                                 # texto do slide ainda vindo: fica anotado, abre quando o slide terminar
            warm.setdefault(alvo, None)
            return {"ok": True}
        sp = _chat_sys(s, alvo)
        if warm.get(alvo) not in (None, sp):
            llm.discard(warm[alvo])                      # prompt mudou: o reserva velho não serve mais
        warm[alvo] = sp
        llm.prewarm_async(sp)
    elif alvo == "prova":
        llm.prewarm_async(prompts.AVALIA_SYS)
        llm.prewarm_async(prompts.REAPRENDER_SYS)
    elif alvo == "exemplos":
        llm.prewarm_async(prompts.EXEMPLOS_SYS)
    return {"ok": True}


def _aquece_chat_cedo(s):
    """slide 1 pronto: a próxima dúvida (texto ou voz) e o "mais exemplos" já encontram o Claude aberto."""
    for modo in {"texto", *s.__dict__.get("_warm", {})}:
        aquecer(s, modo)
    aquecer(s, "exemplos")


def chat_stream(s, q, write, modo="texto"):
    """Conversa com memória: o histórico inteiro da sessão vai junto (últimas 12 mensagens)."""
    with s.lock:
        msgs = s.chat[-12:] + [{"role": "user", "content": q}]
    out = llm.stream(_chat_sys(s, modo), msgs, max_tokens=400 if modo == "texto" else 260, on_delta=write, meter=s.meter,
                     label="chat_voz" if modo == "voz" else "chat", warm=True)
    with s.lock:
        s.chat += [{"role": "user", "content": q}, {"role": "assistant", "content": out}]
    s.dirty = True
    return out


def exemplos_stream(s, write):
    """ "MAIS EXEMPLOS" no slide 1: 2 exemplos novos, de outras áreas da vida, gerados na hora em streaming."""
    ex0 = re.search(r"\[EXEMPLO\](.*)", s.slide1 or "", re.S)
    vistos = ([ex0.group(1).strip()] if ex0 else []) + s.exemplos
    out = llm.stream(prompts.EXEMPLOS_SYS, [{"role": "user", "content": prompts.exemplos_user(s.concept, s.slide1, vistos)}],
                     max_tokens=400, on_delta=write, meter=s.meter, label="mais_exemplos", warm=True)
    novos = [x.strip() for x in re.split(r"\[EXEMPLO\]", out) if x.strip()]
    with s.lock:
        s.exemplos += novos
    s.dirty = True
    return out


CACHE_VOZ = config.RUNS / "_cache_voz"


def _voz_cache(t):
    """cache em disco por texto: frase repetida (reações, aberturas) não paga nem espera a ElevenLabs de novo."""
    import hashlib
    CACHE_VOZ.mkdir(parents=True, exist_ok=True)
    f = CACHE_VOZ / (hashlib.sha1(t.encode()).hexdigest()[:16] + ".mp3")
    if f.exists():
        return f.read_bytes(), 0.0, 0
    r = voice.speak(t)
    f.write_bytes(r["audio"])
    return r["audio"], r["usd"], r["ms"]


def say(s, text):
    """Uma frase da resposta falada (modo conversa e prova oral) → MP3 (voz do narrador)."""
    t = voice.sanitize(text, keep_questions=True)[:700]
    audio, usd, ms = _voz_cache(t)
    s.meter("voz_conversa", {"provider": "ElevenLabs flash v2.5" + (" (cache)" if not ms else ""), "total": ms / 1000, "usd": usd, "chars": len(t)})
    return audio


def _pre_voz(textos):
    """grava no cache as frases que o navegador vai pedir ao /say (mesmo corte por frase do app.js)."""
    for t in textos:
        for f in re.findall(r'[^.!?…]+[.!?…]+["”]?|[^.!?…]+$', t or ""):
            if f.strip():
                try:
                    _voz_cache(voice.sanitize(f.strip(), keep_questions=True)[:700])
                except Exception:  # noqa: BLE001 — sem cache a frase só demora um pouco mais
                    traceback.print_exc()


# ---------- 3. prova oral rápida ----------
def transcribe(s, audio, mime):
    r = voice.transcribe(audio, mime, s.keyterms())
    s.meter("transcricao", {"provider": r["engine"], "total": r["ms"] / 1000, "usd": r["usd"], **({"fallback": r["fallback"]} if r.get("fallback") else {})})
    return {"text": r["text"], "engine": r["engine"], "ms": r["ms"]}


TIPOS = ("definicao", "exemplo", "cenario")
ROTULO_Q = {"definicao": "O que é", "exemplo": "Exemplo", "cenario": "Cenário"}
NAO_SEI = re.compile(r"^\W*(n[ãa]o\s+(sei|lembro|fa[çc]o\s+ideia)|sei\s+l[áa]|pass(o|ar)|pula)\W*$", re.I)


def _fala_pergunta(s, k):
    q = s.mapa["perguntas"][k]["pergunta"]
    return f"Três perguntas rápidas. {q}" if k == 0 else f"Última. {q}" if k == 2 else q


FINAL = {"certa": "primeira", "reforco": "reforco", "explicado": "explicado", "so_vista": "so_vista", "pulado": "pulado"}


def exam_public(s):
    e = s.exam
    if not e:
        return None
    fim = e["fase"] == "veredito"
    ra = e.get("reaprender") or {}
    itens = ra.get("itens") or {}
    qs = []
    for k, r in enumerate(e["respostas"]):
        g = s.mapa["perguntas"][k]
        st = (r or {}).get("status", "aguardando")
        item = itens.get(str(k)) or {}
        final = "primeira" if st == "certa" else item.get("status") if item.get("status") != "pendente" else None
        qs.append({"n": k + 1, "tipo": g["tipo"], "rotulo": ROTULO_Q[g["tipo"]], "feita": k <= e["atual"],
                   "pergunta": g["pergunta"] if k <= e["atual"] else None, "status": st, "motivo": (r or {}).get("motivo"),
                   "final": final if e["fase"] in ("reaprender", "veredito") else None,
                   "ultima": item.get("ultima") if fim else None, "motivo_final": item.get("motivo") if fim else None,
                   "resposta": (item.get("explicacao") or g.get("esperado") or g.get("criterio") or g.get("resposta_esperada")) if fim else None})
    pub = {k: e.get(k) for k in ("fase", "atual", "turnos", "t_inicio", "t_fim", "veredito")} | {"perguntas": qs}
    if ra:
        pub["reaprender"] = {"fila": ra["fila"], "i": ra["i"], "passo": ra["passo"]}
        if e["fase"] == "reaprender" and ra["passo"]:
            k = ra["fila"][ra["i"]]
            mini = ra["mini"][str(k)]
            seg = mini["passo1"].get("segmento")
            trecho = next((t for t in ((s.video or {}).get("trechos") or []) if t["i"] == seg), None) if isinstance(seg, int) else None
            pub["reaprender"] |= {"q": k, "tipo": s.mapa["perguntas"][k]["tipo"], "rotulo": ROTULO_Q[s.mapa["perguntas"][k]["tipo"]],
                                  "cartao": mini["passo1"]["cartao"], "trecho": trecho,
                                  "explicacao": mini["passo2"]["fala"] if ra["passo"] == 2 else None,
                                  "pergunta": mini[f"passo{ra['passo']}"]["pergunta"]}
    return pub


def _prof(s, texto, tipo="pergunta", **meta):
    s.exam["turnos"].append({"papel": "professor", "texto": texto, "tipo": tipo, "t": round(time.time() - s.t0, 1),
                             **{k: v for k, v in meta.items() if v is not None}})


def _garante_plano(s):
    """sessão antiga (gabarito por pontos) ou plano que ainda não saiu: faz agora."""
    s.map_ready.wait(90)
    if not (s.mapa or {}).get("perguntas"):
        run_map(s)


def exam_start(s):
    _garante_plano(s)
    aquecer(s, "prova")
    s.exam = {"fase": "perguntas", "atual": 0, "turnos": [], "t_inicio": round(time.time() - s.t0, 1), "t_fim": None,
              "veredito": None, "respostas": [None, None, None]}
    s.__dict__["_correcoes"] = {}
    _prof(s, _fala_pergunta(s, 0), q=0)
    s.dirty = True
    return exam_public(s)


def exam_answer(s, text):
    """Registra a resposta, dispara a correção em 2º plano e já devolve a PRÓXIMA pergunta (sem reação no meio).
    Na 3ª resposta, espera as correções e fecha o resultado."""
    e = s.exam
    if not e or e["fase"] in ("veredito", "resultado"):
        raise RuntimeError("a prova não está em andamento")
    if e["fase"] == "reaprender":
        return _reaprender_resposta(s, text)
    k = e["atual"]
    e["turnos"].append({"papel": "aluno", "texto": text, "q": k, "t": round(time.time() - s.t0, 1)})
    e["respostas"][k] = {"texto": text, "status": "corrigindo"}
    cor = s.__dict__.setdefault("_correcoes", {})
    cor[k] = POOL.submit(_corrige, s, k, text)
    if k < 2:
        e["atual"] = k + 1
        _prof(s, _fala_pergunta(s, k + 1), q=k + 1)
        s.dirty = True
        return exam_public(s)
    for j in range(3):
        f = cor.get(j)
        if f is None and (e["respostas"][j] or {}).get("status") == "corrigindo":   # reinício no meio: corrige de novo
            f = POOL.submit(_corrige, s, j, e["respostas"][j]["texto"])
        if f is not None:
            f.result(timeout=90)
    erradas = [j for j in range(3) if (e["respostas"][j] or {}).get("status") != "certa"]
    if not erradas:
        _fecha(s)
    else:                                   # mostra o resultado; em 2 s a tela chama "reaprender" (ou o aluno pula)
        e["fase"] = "resultado"
        e["reaprender"] = {"fila": erradas, "i": 0, "passo": 0, "mini": {}, "itens": {str(j): {"status": "pendente"} for j in erradas}}
    s.dirty = True
    return exam_public(s)


def _avalia(s, pergunta, text, label):
    """corrige uma resposta (generoso, só a aula) + trava no código: acerto sem trecho literal da resposta não conta."""
    if NAO_SEI.match(text.strip()) or len(re.findall(r"\w+", text)) < 2:
        return {"correta": False, "evidencia": None, "motivo": "Sem resposta."}
    try:
        r = llm.json_call(prompts.AVALIA_SYS, prompts.avalia_user(aula_texto(s), pergunta, text), max_tokens=300, meter=s.meter,
                          label=label, warm=True, validate=_valida_correcao)
    except llm.LLMError as ex:
        return {"correta": False, "evidencia": None, "motivo": "Não consegui corrigir esta resposta agora.", "erro": str(ex)[:200]}
    if r.get("correta") and not _evidencia_ok(r.get("evidencia") or "", text):
        s.meter("trava_evidencia", {"provider": "código", "total": 0.0, "usd": 0.0, "pergunta": pergunta.get("tipo")})
        r["correta"] = False
    return r


def _corrige(s, k, text):
    g = s.mapa["perguntas"][k]
    t = time.time()
    r = _avalia(s, g, text, f"prova_correcao_{g['tipo']}")
    with s.lock:
        s.exam["respostas"][k].update(status="certa" if r.get("correta") else "errada", motivo=r.get("motivo"),
                                      evidencia=r.get("evidencia"), secs=round(time.time() - t, 2))
    s.emit("exam_correcao", q=k, status=s.exam["respostas"][k]["status"], motivo=r.get("motivo"))
    if not r.get("correta"):                # já prepara a reaprendizagem desta pergunta, durante a prova
        s.__dict__.setdefault("_preps", {})[k] = POOL.submit(_prepara_reaprender, s, k, text, r.get("motivo") or "")
    s.dirty = True


def _prepara_reaprender(s, k, resposta, motivo):
    g = s.mapa["perguntas"][k]
    mini = llm.json_call(prompts.REAPRENDER_SYS,
                         prompts.reaprender_user(aula_texto(s), g, resposta, motivo, (s.video or {}).get("trechos") or []),
                         max_tokens=1400, meter=s.meter, label=f"reaprender_prepara_{g['tipo']}", warm=True,
                         validate=prompts.validate_reaprender(g["tipo"]))
    for p_ in ("passo1", "passo2"):
        mini[p_]["pergunta"] = voice.fix_questions(mini[p_]["pergunta"])
    with s.lock:
        s.exam.setdefault("_mini_pronto", {})[str(k)] = mini
    _pre_voz([ABRE_REAPRENDER, mini["passo1"]["fala"], mini["passo1"]["pergunta"], mini["passo2"]["fala"], mini["passo2"]["pergunta"]])
    return mini


ABRE_REAPRENDER = "Vamos fechar o que faltou."


def _mini(s, k):
    """a mini-aula da pergunta k: já pronta (preparada durante a prova) ou prepara agora."""
    e = s.exam
    pronta = (e.get("_mini_pronto") or {}).get(str(k))
    if pronta:
        return pronta
    f = (s.__dict__.get("_preps") or {}).get(k)
    if f is not None:
        return f.result(timeout=120)
    r = e["respostas"][k]
    return _prepara_reaprender(s, k, r.get("texto", ""), r.get("motivo") or "")


def exam_action(s, acao):
    """"reaprender": começa a reaprendizagem (a tela chama 2 s depois do resultado) · "pular": encerra sem ela."""
    e = s.exam
    if not e or e["fase"] not in ("resultado", "reaprender"):
        raise RuntimeError("não há reaprendizagem para fazer agora")
    ra = e["reaprender"]
    if acao == "pular":
        for it in ra["itens"].values():
            if it["status"] == "pendente":
                it["status"] = "pulado"
        _fecha(s)
    elif acao == "reaprender" and e["fase"] == "resultado":
        e["fase"] = "reaprender"
        _abre_item(s, primeira=True)
    s.dirty = True
    return exam_public(s)


def _abre_item(s, primeira=False):
    e = s.exam
    ra = e["reaprender"]
    k = ra["fila"][ra["i"]]
    mini = _mini(s, k)
    ra["mini"][str(k)] = mini
    ra["passo"] = 1
    fala = (ABRE_REAPRENDER + " " if primeira else "") + mini["passo1"]["fala"]
    _prof(s, fala, tipo="fala", q=k, r=1)
    _prof(s, mini["passo1"]["pergunta"], tipo="pergunta", q=k, r=1)


def _reaprender_resposta(s, text):
    e = s.exam
    ra = e["reaprender"]
    k = ra["fila"][ra["i"]]
    g = s.mapa["perguntas"][k]
    mini = ra["mini"][str(k)]
    item = ra["itens"][str(k)]
    e["turnos"].append({"papel": "aluno", "texto": text, "q": k, "r": ra["passo"], "t": round(time.time() - s.t0, 1)})
    if ra["passo"] == 1:
        p1 = mini["passo1"]
        chave = {"definicao": "esperado", "exemplo": "criterio", "cenario": "resposta_esperada"}[g["tipo"]]
        pergunta = {"tipo": g["tipo"], "pergunta": p1["pergunta"], chave: p1["gabarito"]}
        if g["tipo"] == "definicao":
            pergunta["essencial"] = g.get("essencial")
        if g["tipo"] == "exemplo":
            pergunta |= {"contraexemplo": p1["cartao"].get("caso_nao"), "nao_vale_repetir": p1["cartao"].get("caso_sim")}
        r = _avalia(s, pergunta, text, f"reaprender_correcao_{g['tipo']}")
        if r.get("correta"):
            item.update(status="reforco", ultima=text, motivo=r.get("motivo"))
            return _proximo_item(s)
        ra["passo"] = 2
        _prof(s, mini["passo2"]["fala"], tipo="fala", q=k, r=2)
        _prof(s, mini["passo2"]["pergunta"], tipo="pergunta", q=k, r=2)
        s.dirty = True
        return exam_public(s)
    p2 = mini["passo2"]
    r = _avalia(s, {"tipo": "repeticao", "pergunta": p2["pergunta"], "explicacao": p2["fala"], "esperado": p2["gabarito"]},
                text, "reaprender_correcao_repeticao")
    item.update(status="explicado" if r.get("correta") else "so_vista", ultima=text, motivo=r.get("motivo"), explicacao=p2["fala"])
    return _proximo_item(s)


def _proximo_item(s):
    e = s.exam
    ra = e["reaprender"]
    if ra["i"] + 1 < len(ra["fila"]):
        ra["i"] += 1
        _abre_item(s)
    else:
        _fecha(s)
    s.dirty = True
    return exam_public(s)


def _valida_correcao(d):
    assert isinstance(d.get("correta"), bool), "'correta' precisa ser true ou false"


def _evidencia_ok(evid, fala):
    """camada no código: a citação tem de existir na fala do aluno (>= 3 palavras, ou a resposta inteira se for curta)."""
    ev = re.findall(r"[a-z0-9]+", _norm(evid))
    fa = re.findall(r"[a-z0-9]+", _norm(fala))
    if not fa or len(ev) < min(3, len(fa)):
        return False
    if " ".join(ev) in " ".join(fa):
        return True
    return sum(1 for w in ev if w in set(fa)) / len(ev) >= 0.8


def _norm(t):
    t = (t or "").lower()
    for a, b in (("áàâã", "a"), ("éê", "e"), ("í", "i"), ("óôõ", "o"), ("ú", "u"), ("ç", "c")):
        for ch in a:
            t = t.replace(ch, b)
    return t


def _fecha(s):
    e = s.exam
    primeira = sum(1 for r in e["respostas"] if (r or {}).get("status") == "certa")
    itens = ((e.get("reaprender") or {}).get("itens") or {}).values()
    n = {st: sum(1 for it in itens if it["status"] == st) for st in ("reforco", "explicado", "so_vista", "pulado")}
    if primeira == 3:
        rotulo, frase = "Aprovado", "Acertou as três. Aprovado."
    elif n["so_vista"] == 0 and n["pulado"] == 0:
        rotulo = "Aprovado com reforço"
        frase = "Fechado. " + ("Tudo certo depois do reforço." if n["explicado"] == 0 else "Agora você explicou tudo com as suas palavras.")
    elif n["pulado"]:
        rotulo, frase = f"Encerrado · {primeira} de 3 de primeira", "Encerrado. As respostas estão na tela."
    else:
        rotulo, frase = "Encerrado com a resposta na tela", "Encerrado. O que ainda não saiu com as suas palavras está na tela."
    e["fase"], e["atual"] = "veredito", 2
    e["t_fim"] = round(time.time() - s.t0, 1)
    e["veredito"] = {"rotulo": rotulo, "primeira": primeira, "total": 3, **n, "duracao_s": round(e["t_fim"] - e["t_inicio"], 1)}
    _prof(s, frase, tipo="veredito")
