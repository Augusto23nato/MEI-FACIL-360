/* Lampejo — 3 slides: explicação + chat (+ mais exemplos) · vídeo do fluxograma · prova oral de 3 perguntas. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtS = (x) => (x == null ? "—" : (x < 10 ? x.toFixed(1) : Math.round(x)) + " s").replace(".", ",");
const fmtUSD = (x) => "US$ " + (x || 0).toFixed(x < 0.1 ? 4 : 3).replace(".", ",");
const mmss = (t) => { t = Math.max(0, t | 0); return `${(t / 60) | 0}:${String(t % 60).padStart(2, "0")}`; };
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const ARCH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="8.5" y="14" width="7" height="7" rx="1.5"/><path d="M6.5 10v2h11v-2M12 12v2"/></svg>';

const App = { sid: null, S: null, s1: "", s1First: null, loadT: 0, loadedAt: 0, slides: [], cur: 0, news: new Set(), chat: [], lastEvent: -1,
  ex: { phase: "idle", err: "" } };

/* ================= microfone pela rede: versão https ================= */
const secureURL = () => `https://${location.hostname}:${App.httpsPort || 4243}${location.pathname}${location.search}`;
async function secureBanner() {
  if (window.isSecureContext) return;
  try { App.httpsPort = (await fetch("/api/health").then((r) => r.json())).https_port || 4243; } catch (e) {}
  const b = document.createElement("div"); b.className = "securebar";
  b.innerHTML = `🎙 Para falar pelo microfone aqui, abra a versão segura <a id="secureLink" href="${secureURL()}">${esc(secureURL().replace(/\?.*$/, ""))}</a> <span>— na 1ª vez, aceite o aviso de certificado (“Mostrar detalhes → visitar este site”)</span>`;
  document.body.appendChild(b); document.body.classList.add("insecure");
  const fit = () => document.documentElement.style.setProperty("--secure-h", b.offsetHeight + "px");
  fit(); window.addEventListener("resize", fit); if (window.ResizeObserver) new ResizeObserver(fit).observe(b);
  window.addEventListener("popstate", () => { $("#secureLink").href = secureURL(); });
}
const insecureMsg = () => `Pelo endereço http da rede o navegador bloqueia o microfone. Abra ${secureURL()} (mesma sessão) ou escreva.`;

/* ================= home ================= */
function boot() {
  secureBanner();
  const m = location.pathname.match(/^\/s\/([0-9a-f]{8})/);
  if (m) return openSession(m[1]);
  $("#home").hidden = false;
  const q = new URLSearchParams(location.search);
  const inp = $("#concept");
  if (q.get("c")) inp.value = q.get("c");
  // pré-geração do slide 1: começa quando o conceito está digitado (pausa de 600 ms) — o clique só "anexa"
  let tmr = null, last = "";
  const pre = () => { const c = inp.value.trim(); if (c.length >= 3 && c !== last && q.get("noprefetch") !== "1") { last = c;
    fetch("/api/prefetch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ concept: c }) }).catch(() => {}); } };
  inp.addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(pre, 600); });
  const again = () => { last = ""; pre(); };                 // página aberta há muito tempo: refaz ao voltar / ao mirar o botão
  window.addEventListener("focus", again); document.addEventListener("visibilitychange", () => { if (!document.hidden) again(); });
  $(".cta").addEventListener("mouseenter", again);
  if (q.get("auto") !== "1") pre();
  $("#startForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $(".cta"); btn.disabled = true; btn.textContent = "Abrindo…";
    const r = await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ concept: inp.value.trim() }) }).then((r) => r.json());
    if (!r.id) { btn.disabled = false; btn.textContent = "Tentar de novo"; alert(r.erro || "falhou"); return; }
    history.pushState({}, "", r.url); $("#home").hidden = true; openSession(r.id); const sl = $("#secureLink"); if (sl) sl.href = secureURL();
  });
  if (q.get("auto") === "1") $("#startForm").requestSubmit();
}

async function openSession(id) {
  App.sid = id;
  const S = await fetch(`/api/s/${id}/state`).then((r) => r.json());
  if (S.erro) { document.body.innerHTML = `<div class="home"><div class="home-inner"><h1 style="font-size:32px">Sessão não encontrada</h1><p class="hint">${esc(S.erro)}</p><a class="cta" href="/">Novo conceito →</a></div></div>`; return; }
  App.S = S; App.loadT = S.t; App.loadedAt = performance.now();
  S.jobs = S.jobs || {}; S.metrics = S.metrics || [];
  document.title = `${S.concept} · Lampejo`;
  $("#deck").hidden = false; $("#tbConcept").textContent = S.concept; document.body.classList.add("in-deck");
  buildSlides(); go(0); renderJobs();
  tickClock(); updateCost(); updateLLM(); setInterval(tickClock, 1000);
  wireNav(); connectSSE();
}

/* ================= SSE ================= */
function connectSSE() {
  const es = new EventSource(`/api/s/${App.sid}/events?since=0`);
  es.onmessage = (m) => { const ev = JSON.parse(m.data); if (ev.i <= App.lastEvent) return; App.lastEvent = ev.i; onEvent(ev, ev.t > App.loadT); };
}
function onEvent(ev, live) {
  const S = App.S;
  if (ev.kind === "s1_first") { App.s1First = ev.secs; renderMapInfo(); }
  else if (ev.kind === "s1") { App.s1 += ev.delta; renderS1Text(); }
  else if (ev.kind === "metric") { if (!S.metrics.find((m) => m.label === ev.metric.label && m.at === ev.metric.at)) S.metrics.push(ev.metric); S.usd = S.metrics.reduce((a, m) => a + (m.usd || 0), 0); updateCost(); llmFromMetric(ev.metric); }
  else if (ev.kind === "job") onJob(ev.job, live);
}

const JOB_NAMES = { slide1: "1º slide", mapa: "Perguntas da prova", video: "Vídeo", imagens: "Imagens" };
function onJob(j, live) {
  const S = App.S; const prev = S.jobs[j.name]; S.jobs[j.name] = j;
  if (j.name === "video" && j.status === "pronto") S.video = j.video;
  if (j.name === "imagens") {
    if (j.imagens) S.imagens = j.imagens;
    refresh("imagens");
    if (live && j.status === "pronto" && prev?.status !== "pronto") { toast(`<b>Imagens prontas</b> <span class="hint">${fmtS(j.secs)}</span>`, "imagens"); markNews("imagens"); }
    if (live && j.status === "erro" && prev?.status !== "erro") toast(`<b>Imagens: falharam</b>`, "imagens", true);
  }
  if (j.name === "mapa" && j.status === "pronto") S.mapa_publico = { n: j.n };
  if (j.name === "slide1" && j.fonte) S.slide1_source = j.fonte;
  renderJobs();
  if (j.name === "video") refresh("video");
  if (j.name === "slide1" || j.name === "mapa") { renderS1Text(); renderMapInfo(); }
  if (j.name === "mapa") refresh("explain");
  if (live && j.name === "video" && (!prev || prev.status !== j.status)) {
    if (j.status === "pronto") { toast(`<b>Vídeo pronto</b> <span class="hint">${fmtS(j.secs)}</span>`, "video"); markNews("video"); }
    if (j.status === "erro") toast(`<b>Vídeo: falhou</b>`, "video", true);
  }
}

/* ================= slides ================= */
const DEFS = [{ key: "s1", label: "Explicação" }, { key: "video", label: "Vídeo" }, { key: "imagens", label: "Imagens" }, { key: "explain", label: "Prova oral" }];
function addSlide(d) { const el = document.createElement("section"); el.className = "slide"; el.dataset.key = d.key; $("#stage").appendChild(el); const s = Object.assign({ el }, d); App.slides.push(s); renderSlide(s); return s; }
function buildSlides() { App.slides = []; DEFS.forEach(addSlide); }
function refresh(key) { const s = App.slides.find((x) => x.key === key); if (s) renderSlide(s); }
function slideByKey(k) { return App.slides.findIndex((s) => s.key === k); }
function head(kicker, title, arch) {
  return `<div class="slide-head"><div><div class="kicker">${kicker}</div><h2>${title}</h2></div>
  <button class="archbtn" data-arch="${arch}">${ARCH_ICON}<span>Como isto é arquitetado</span></button></div>`;
}
function renderSlide(s) { if (s.key === "s1") renderS1(s); else if (s.key === "video") renderVideo(s); else if (s.key === "imagens") renderImagens(s); else renderExam(s); }

/* ---------- 1. explicação + chat ---------- */
function renderS1(s) {
  if (s.el.querySelector(".s1")) return;
  s.el.innerHTML = head("1 · em um minuto", esc(cap(App.S.concept)), "s1") + `<div class="slide-body"><div class="s1">
    <div class="s1-main"><p class="lead" id="s1lead"></p><div class="duo"><div class="blk analogia"><div class="kicker">Analogia</div><p id="s1ana"></p></div>
    <div class="blk exemplo"><div class="kicker">Exemplo</div><p id="s1ex"></p></div></div>
    <div class="duo moreex" id="moreex"></div>
    <div class="moreex-bar"><button class="moreexbtn" id="moreexbtn" type="button" disabled>＋ Mais exemplos</button></div>
    <div class="mapinfo" id="mapinfo"></div></div>
    <div class="chat"><div class="chat-head"><div><div class="kicker">Dúvidas</div><div class="hint" id="convsub">escreva ou converse por voz</div></div>
      <button class="convbtn" id="convbtn" type="button" aria-pressed="false">🎙 Modo conversa</button></div>
    <div class="chat-log" id="chatlog"></div>
    <div class="conv" id="convbar" hidden><div class="orb" id="convorb"></div><div class="conv-info"><b id="convstate">Ouvindo…</b>
      <div class="meter on" id="convmeter">${"<i></i>".repeat(24)}</div><span class="hint" id="convhint">fale naturalmente — quando você parar, eu respondo</span></div>
      <button class="btn ghost small" id="convint" type="button" hidden>Interromper</button><button class="btn ghost small listenbtn" id="convpause" type="button">⏸ Parar de ouvir</button><button class="btn ghost small" id="convoff" type="button">Desligar</button></div>
    <form class="chat-in" id="chatform"><input class="field" id="chatq" placeholder="Pergunte qualquer coisa…" autocomplete="off"><button class="btn" type="submit">Enviar</button></form></div></div></div>`;
  $("#chatform", s.el).addEventListener("submit", (e) => { e.preventDefault(); const q = $("#chatq").value.trim(); if (q) { $("#chatq").value = ""; askChat(q); } });
  $("#convbtn", s.el).onclick = () => (Conv.on ? convStop() : convStart());
  $("#convoff", s.el).onclick = () => convStop();
  $("#convint", s.el).onclick = () => convInterrupt();
  $("#convpause", s.el).onclick = () => (Conv.paused ? convResume() : convPause());
  $("#moreexbtn", s.el).onclick = maisExemplos;
  renderChat(); renderS1Text(); renderMapInfo(); renderMoreEx();
}
function parseS1(t) {
  const out = { simples: "", analogia: "", exemplo: "", at: "simples" };
  const re = /\[(SIMPLES|ANALOGIA|EXEMPLO)\]/g; let m, last = null, idx = 0; const parts = [];
  while ((m = re.exec(t))) { if (last) parts.push([last, t.slice(idx, m.index)]); last = m[1].toLowerCase(); idx = re.lastIndex; }
  if (last) parts.push([last, t.slice(idx)]); else if (t.trim()) parts.push(["simples", t]);
  for (const [k, v] of parts) { out[k] = v.replace(/\[[A-Z]*$/, "").trim(); out.at = k; }
  return out;
}
function renderS1Text() {
  const p = parseS1(App.s1); const done = App.S.jobs.slide1?.status === "pronto";
  const put = (id, key, lines) => { const el = document.getElementById(id); if (!el) return;
    if (p[key]) { el.textContent = p[key]; el.classList.toggle("caret", !done && p.at === key); }
    else el.innerHTML = Array.from({ length: lines }, (_, i) => `<span class="skel" style="width:${[96, 88, 70, 92][i % 4]}%"></span>`).join(""); };
  put("s1lead", "simples", 4); put("s1ana", "analogia", 3); put("s1ex", "exemplo", 3);
  const b = $("#moreexbtn"); if (b && App.exStream == null) b.disabled = !done;
}

/* "MAIS EXEMPLOS": 2 exemplos novos por clique, de outras áreas da vida, gerados na hora (streaming) */
const splitEx = (t) => t.split("[EXEMPLO]").map((x) => x.replace(/\[[A-Z]*$/, "").trim()).filter(Boolean);
function renderMoreEx() {
  const box = $("#moreex"); if (!box) return;
  const fixos = (App.S.exemplos || []).map((t) => [t, false]);
  const vivos = App.exStream != null ? splitEx(App.exStream) : [];
  const itens = [...fixos, ...vivos.map((t, i) => [t, i === vivos.length - 1])];
  const skel = `<span class="skel" style="width:94%"></span><span class="skel" style="width:86%"></span><span class="skel" style="width:60%"></span>`;
  box.innerHTML = itens.map(([t, live], k) => `<div class="blk exemplo extra"><div class="kicker">Exemplo ${k + 2}</div><p class="${live ? "caret" : ""}">${esc(t)}</p></div>`).join("")
    + (App.exStream != null && vivos.length < 2 ? Array.from({ length: 2 - vivos.length }, (_, k) => `<div class="blk exemplo extra"><div class="kicker">Exemplo ${itens.length + k + 2}</div><p>${skel}</p></div>`).join("") : "");
  box.hidden = !box.innerHTML;
  const b = $("#moreexbtn"); if (b) { b.disabled = App.exStream != null || App.S.jobs.slide1?.status !== "pronto"; b.textContent = App.exStream != null ? "Gerando exemplos…" : "＋ Mais exemplos"; }
}
async function maisExemplos() {
  if (App.exStream != null) return;
  App.exStream = ""; renderMoreEx(); $("#moreex")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  try {
    const r = await fetch(`/api/s/${App.sid}/exemplos`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const rd = r.body.getReader(); const dec = new TextDecoder();
    for (;;) { const { value, done } = await rd.read(); if (done) break; App.exStream += dec.decode(value, { stream: true }); renderMoreEx(); }
    App.S.exemplos = [...(App.S.exemplos || []), ...splitEx(App.exStream)];
  } catch (e) { toast("<b>Mais exemplos:</b> não saiu desta vez — toque de novo.", "ex", true); }
  App.exStream = null; renderMoreEx();
  $("#moreexbtn")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function renderMapInfo() {
  const el = $("#mapinfo"); if (!el) return; const S = App.S; const mp = S.mapa_publico; let h = "";
  const pre = (S.slide1_source || "").startsWith("pré");
  if (App.s1First != null) h += `<span class="chip ${pre ? "green" : ""}">${pre ? "⚡ pré-gerado enquanto você digitava" : "1º texto em " + fmtS(App.s1First)}</span>`;
  if (mp) h += `<span class="chip amber">Prova oral do slide 4: ${mp.n} perguntas, só do que esta aula mostrou</span>`;
  el.innerHTML = h;
}
function renderChat() {
  const log = $("#chatlog"); if (!log) return;
  if (!App.chat.length) { log.innerHTML = `<div class="chat-empty">Travou em alguma parte? Pergunte aqui — ou ligue o 🎙 modo conversa e só fale.<div class="sugs">${["Qual o erro mais comum?", "Onde isso aparece no dia a dia?", "Por que isso importa?"].map((q) => `<button class="sug" type="button">${q}</button>`).join("")}</div></div>`;
    log.querySelectorAll(".sug").forEach((b) => b.addEventListener("click", () => askChat(b.textContent))); return; }
  log.innerHTML = App.chat.map((m) => `<div class="msg ${m.role}">${m.voz ? `<span class="vtag">${m.role === "me" ? "🎙 falado" : "🔊 respondido em voz"}</span>` : ""}${esc(m.text)}${m.role === "bot" && !m.done ? '<span class="caret"></span>' : ""}</div>`).join("");
  log.scrollTop = log.scrollHeight;
}
async function askChat(q, opts = {}) {
  App.chat.push({ role: "me", text: q, voz: !!opts.voz }); const m = { role: "bot", text: "", done: false, voz: !!opts.voz }; App.chat.push(m); renderChat();
  try {
    const r = await fetch(`/api/s/${App.sid}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q, modo: opts.voz ? "voz" : "texto" }) });
    const rd = r.body.getReader(); const dec = new TextDecoder();
    for (;;) { const { value, done } = await rd.read(); if (done) break; m.text += dec.decode(value, { stream: true }); renderChat(); opts.onDelta?.(m.text); }
  } catch (e) { m.text += " (falhou: " + e.message + ")"; }
  if (opts.voz) { const fixed = fixQuestions(m.text); if (fixed !== m.text) m.text = fixed; }
  m.done = true; renderChat(); opts.onDone?.(m.text);
  return m.text;
}

/* frase que É pergunta mas veio sem '?' → devolve o '?' (mesma regra do servidor em voice.fix_questions) */
const INTERROG = /^(?:e\s+|mas\s+|então,?\s+|agora,?\s+)?(?:qual|quais|por\s*que|pra\s+que|para\s+que|será\s+que|o\s+que\s+você|você\s+(?:acha|consegue|sabe|lembra|percebe|imagina|entendeu|concorda)|consegue|dá\s+pra|faz\s+sentido|me\s+di[zg]a?|me\s+fala|me\s+conta\s+(?:se|qual|como|o\s+que|por\s*que)|é\s+isso|tá\s+claro|ficou\s+claro|tem\s+como)(?![\p{L}-])/iu;
const fixQuestions = (t) => t.trim().split(/(?<=[.!?])\s+/).map((s) => (s.endsWith(".") && INTERROG.test(s) ? s.slice(0, -1) + "?" : s)).join(" ");

/* ---------- modo conversa (voz ↔ voz, mãos livres) ---------- */
const Conv = { on: false, paused: false, stream: null, ctx: null, an: null, buf: null, mr: null, raf: 0, audio: null, q: [], streamDone: true,
  cancel: false, gen: 0, state: "off", tEnd: 0, lastLatency: null };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function convUI(state, hint) {
  Conv.state = state; const bar = $("#convbar"); if (!bar) return;
  bar.hidden = state === "off"; bar.dataset.state = state;
  const label = { ouvindo: "Ouvindo…", falando_usuario: "Estou ouvindo você…", transcrevendo: "Entendendo o que você disse…", pensando: "Pensando…", falando: "Respondendo…", pausado: "Microfone pausado", off: "" }[state] || state;
  $("#convstate").textContent = label; if (hint != null) $("#convhint").textContent = hint;
  $("#convint").hidden = state !== "falando" && state !== "pensando";
  const pb = $("#convpause"); if (pb) { pb.textContent = Conv.paused ? "▶ Voltar a ouvir" : "⏸ Parar de ouvir"; pb.classList.toggle("resume", Conv.paused); }
  const b = $("#convbtn"); if (b) { b.classList.toggle("on", Conv.on); b.setAttribute("aria-pressed", Conv.on); b.textContent = Conv.on ? "● Conversa ligada" : "🎙 Modo conversa"; }
}
async function convStart() {
  if (!window.isSecureContext) { toast(`<b>Microfone bloqueado no http.</b> <a href="${secureURL()}">Abrir versão segura →</a> (mesma sessão)`); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast("<b>Modo conversa:</b> este navegador não grava áudio."); return; }
  post("aquecer", { alvo: "voz" });   // enquanto você fala, o Claude da resposta falada já abre
  Conv.audio = Conv.audio || new Audio();
  try { Conv.audio.src = "data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQxAADB8AhSmxhIIEVCSiJrDCQBTcu3UrAIwUdkRgQbFAZC1CQEwTJ9mjRvBA4UOLD8nKVOWfh+UlK3z/177OXrfOdKl7pyn3Xf//WreyTRUoAWgBgkOAGbZHBgG1OF6zM82DWbZaUmMBptgQhGjsyYqc9ae9XFz280948NMBWInljyzsNRFLPWdnZGWrddDsjK1unuSrVN9jJsK8KuQtQCtMBjCEtImISdNKJOopIpBFpNSMbIHCSRpRR5iakjTiyzLhchUUBwCgyKiweBv/7UsQbg8isVNoMPMjAAAA0gAAABEVFGmgqK////9bP/6XCykxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqg=="; await Conv.audio.play(); } catch (e) {}   // destrava o áudio no gesto do clique
  if (!(await convMic())) return;
  Conv.on = true; Conv.paused = false; convListen();
  if (window.innerWidth < 980) $("#convbar")?.scrollIntoView({ block: "nearest", behavior: "smooth" });   // celular: barra à vista
}
async function convMic() {
  if (Conv.stream) return true;
  try { Conv.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
  catch (e) { toast("<b>Microfone indisponível</b> (" + esc(e.name) + "). Escreva as dúvidas."); return false; }
  Conv.ctx = new (window.AudioContext || window.webkitAudioContext)(); Conv.an = Conv.ctx.createAnalyser(); Conv.an.fftSize = 1024;
  Conv.ctx.createMediaStreamSource(Conv.stream).connect(Conv.an); Conv.buf = new Float32Array(Conv.an.fftSize);
  return true;
}
function convMicOff() { Conv.stream?.getTracks().forEach((t) => t.stop()); Conv.stream = null; try { Conv.ctx?.close(); } catch (e) {} Conv.ctx = null; }
function convStopRec() { cancelAnimationFrame(Conv.raf); try { if (Conv.mr && Conv.mr.state !== "inactive") { Conv.mr.onstop = null; Conv.mr.stop(); } } catch (e) {} }
function convStop() {
  Conv.on = false; Conv.paused = false; Conv.cancel = true; Conv.gen++; convStopRec(); convMicOff();
  try { Conv.audio?.pause(); } catch (e) {} Conv.q = []; convUI("off");
}
/* parar de ouvir: o microfone fecha (nada é gravado) mas o modo conversa continua ligado; se ele estiver respondendo, termina a resposta e não volta a ouvir */
function convPause() {
  Conv.paused = true;
  if (["ouvindo", "falando_usuario"].includes(Conv.state)) { Conv.gen++; convStopRec(); convMicOff(); convUI("pausado", "nada do que você falar é gravado — toque em “Voltar a ouvir” quando quiser"); }
  else convUI(Conv.state, "termino esta resposta e paro de ouvir");
}
function convResume() {
  Conv.paused = false; if (!Conv.on) return;
  if (["pausado", "ouvindo", "falando_usuario"].includes(Conv.state)) convListen(); else convUI(Conv.state, "volto a ouvir quando terminar de responder");
}
function convInterrupt() { Conv.cancel = true; Conv.gen++; try { Conv.audio.pause(); } catch (e) {} Conv.q = []; if (Conv.on) convListen(); }
function rms() { Conv.an.getFloatTimeDomainData(Conv.buf); let s = 0; for (const v of Conv.buf) s += v * v; return Math.sqrt(s / Conv.buf.length); }
function convListen() {
  if (!Conv.on) return;
  if (Conv.paused) { convMicOff(); return convUI("pausado", "nada do que você falar é gravado — toque em “Voltar a ouvir” quando quiser"); }
  if (!Conv.stream) { convMic().then((ok) => ok && Conv.on && !Conv.paused && convListen()); return; }
  Conv.cancel = false; const gen = ++Conv.gen;
  const chunks = []; const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  const mr = Conv.mr = new MediaRecorder(Conv.stream, mime ? { mimeType: mime } : undefined);
  mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  mr.start(200);
  convUI("ouvindo", Conv.lastLatency ? `última resposta começou a tocar ${fmtS(Conv.lastLatency)} depois que você parou de falar` : "fale naturalmente — quando você parar, eu respondo");
  const t0 = performance.now(); const calib = []; let thr = 0.02, speaking = false, sStart = 0, lastVoice = 0, above = 0;
  const tick = () => {
    if (gen !== Conv.gen || !Conv.on) return;
    const now = performance.now(), v = rms();
    const meter = $("#convmeter"); if (meter) { const bars = meter.children; for (let i = bars.length - 1; i > 0; i--) bars[i].style.height = bars[i - 1].style.height; bars[0].style.height = Math.max(4, Math.min(26, v * 260)) + "px"; }
    if (now - t0 < 350) { calib.push(v); Conv.raf = requestAnimationFrame(tick); return; }
    if (calib.length) { calib.sort((a, b) => a - b); thr = Math.min(0.045, Math.max(0.012, calib[calib.length >> 1] * 3.2)); calib.length = 0; }
    if (!speaking) {
      above = v > thr ? above + 1 : 0;
      if (above >= 3) { speaking = true; sStart = now; lastVoice = now; convUI("falando_usuario"); }
      else if (now - t0 > 25000) { mr.onstop = null; mr.stop(); return convListen(); }   // silêncio longo: recomeça (arquivo não cresce)
    } else {
      if (v > thr * 0.7) lastVoice = now;
      if ((now - lastVoice > 1000 && now - sStart > 450) || now - sStart > 30000) {
        Conv.tEnd = performance.now() - Math.min(1000, now - lastVoice);
        mr.onstop = () => convHandle(new Blob(chunks, { type: (mr.mimeType || "audio/webm").split(";")[0] }), gen);
        mr.stop(); return;
      }
    }
    Conv.raf = requestAnimationFrame(tick);
  };
  Conv.raf = requestAnimationFrame(tick);
}
async function convHandle(blob, gen) {
  if (gen !== Conv.gen || !Conv.on) return;
  convUI("transcrevendo");
  const r = await fetch(`/api/s/${App.sid}/stt`, { method: "POST", headers: { "Content-Type": blob.type }, body: blob }).then((x) => x.json()).catch(() => ({}));
  if (gen !== Conv.gen || !Conv.on) return;
  const q = (r.text || "").trim();
  if (q.length < 2) return convListen();
  convUI("pensando"); Conv.q = []; Conv.streamDone = false; let cut = 0; let first = true;
  const enqueue = (t) => { t = t.trim(); if (t.length < 2) return;
    Conv.q.push(fetch(`/api/s/${App.sid}/say`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) })
      .then((x) => (x.ok ? x.blob() : null)).then((b) => (b ? URL.createObjectURL(b) : null)).catch(() => null)); };
  const player = (async () => {
    while (!Conv.cancel && gen === Conv.gen && (Conv.q.length || !Conv.streamDone)) {
      if (!Conv.q.length) { await sleep(60); continue; }
      const url = await Conv.q.shift(); if (!url || Conv.cancel || gen !== Conv.gen) continue;
      convUI("falando");
      if (first) { first = false; Conv.lastLatency = (performance.now() - Conv.tEnd) / 1000; }
      await new Promise((res) => { Conv.audio.onended = res; Conv.audio.onerror = res; Conv.audio.src = url; Conv.audio.play().catch(res); });
      URL.revokeObjectURL(url);
    }
  })();
  await askChat(q, { voz: true,
    onDelta: (txt) => { if (gen !== Conv.gen) return; const rest = txt.slice(cut); const mm = rest.match(/^[\s\S]*?[.!?…](?=\s|$)|^[\s\S]*?\n/);
      if (mm && mm[0].trim().length >= 12) { enqueue(mm[0]); cut += mm[0].length; } },
    onDone: (txt) => { if (gen !== Conv.gen) return; enqueue(txt.slice(cut)); Conv.streamDone = true; } });
  await player;
  if (Conv.on && gen === Conv.gen) convListen();
}

/* ---------- 2. fluxograma em vídeo ---------- */
const ETAPAS = [["fluxograma", "Fluxograma + roteiro"], ["drawio", "Desenho no draw.io"], ["narracao", "Narração em voz"], ["motion", "Animação"]];
function renderVideo(s) {
  const S = App.S; const j = S.jobs.video || {};
  if (j.status === "pronto" && S.video) {
    if (s.el.querySelector("video")) return;
    s.el.innerHTML = head("2 · o fluxograma em movimento", esc(S.video.titulo || cap(S.concept)), "video") + `<div class="slide-body"><div class="video-wrap">
      <video src="${S.video.url}" poster="${S.video.poster}" controls preload="auto" playsinline></video>
      <div class="caption">${fmtS(S.video.seconds)} · ${S.video.caixas} caixas acendendo no tempo da fala · pronto ${fmtS(j.at)} depois do clique</div></div></div>`;
    return;
  }
  const i = Math.max(0, ETAPAS.findIndex(([k]) => k === j.etapa)); const err = j.status === "erro";
  const steps = ETAPAS.map(([k, t], n) => `<li class="${err ? "" : n < i ? "ok" : n === i && j.status === "gerando" ? "now" : ""}"><i></i>${t}</li>`).join("");
  s.el.innerHTML = head("2 · o fluxograma em movimento", "Preparando o vídeo", "video") + `<div class="slide-body"><div class="wait ${err ? "err" : ""}"><div>
    <h3>${err ? "O vídeo não saiu desta vez" : "Desenhando e animando o fluxograma"}</h3>
    <p>${err ? esc(j.detail || "") : "Cada caixa vai acender no momento em que a narração fala dela. Leva cerca de 1 minuto — você pode ler o slide 1 ou tirar dúvidas enquanto isso; aviso quando ficar pronto."}</p>
    <ol class="stepper">${steps}</ol>${err ? "" : `<div class="elapsed" id="vidElapsed"></div>`}</div></div></div>`;
}

/* ---------- 3. o conceito em imagens (geradas enquanto o vídeo é assistido) ---------- */
function renderImagens(s) {
  const S = App.S; const j = S.jobs.imagens || {}; const ims = S.imagens || [];
  const sig = JSON.stringify([j.status, ims.map((x) => x.url || (x.erro ? "e" : ""))]);
  if (s.sig === sig) return; s.sig = sig;
  if (!ims.length) {
    const off = j.status === "desligado";
    if (off) {
      s.el.innerHTML = head("3 · o conceito em imagens", "Imagens desligadas", "imagens") + `<div class="slide-body"><div class="wait"><div>
        <h3>As ilustrações estão desligadas</h3><p>${esc(j.detail || "")}</p></div></div></div>`;
      return;
    }
    const err = j.status === "erro";
    s.el.innerHTML = head("3 · o conceito em imagens", "Preparando as imagens", "imagens") + `<div class="slide-body"><div class="wait ${err ? "err" : ""}"><div>
      <h3>${err ? "As imagens não saíram desta vez" : "Desenhando o conceito"}</h3>
      <p>${err ? esc(j.detail || "") : "Quatro ilustrações, uma para cada ideia da aula. Ficam prontas enquanto você assiste ao vídeo."}</p>
      ${err ? "" : `<p class="hint" style="margin-top:10px">${esc(j.detail || "na fila")}</p>`}</div></div></div>`;
    return;
  }
  const cards = ims.map((x, k) => `<figure class="imcard">
      <div class="imframe">${x.url ? `<img src="${x.url}" alt="${esc(x.titulo)}" data-k="${k}" loading="eager">` : x.erro ? `<div class="imerr">esta imagem não saiu</div>` : `<div class="imskel"></div>`}</div>
      <figcaption><b><span class="imnum">${k + 1}</span>${esc(x.titulo)}</b><p>${esc(x.legenda)}</p></figcaption></figure>`).join("");
  s.el.innerHTML = head("3 · o conceito em imagens", esc(cap(S.concept)), "imagens") + `<div class="slide-body"><div class="imgrid">${cards}</div></div>`;
  s.el.querySelectorAll(".imframe img").forEach((im) => (im.onclick = () => lightbox(+im.dataset.k)));
}
function lightbox(k) {
  const ims = (App.S.imagens || []).filter((x) => x.url); if (!ims.length) return;
  let box = $("#lightbox");
  if (!box) { box = document.createElement("div"); box.id = "lightbox"; box.className = "lightbox"; document.body.appendChild(box);
    box.onclick = (e) => { if (e.target === box || e.target.closest(".lbx")) box.hidden = true; };
    document.addEventListener("keydown", (e) => { if (box.hidden) return; if (e.key === "Escape") box.hidden = true;
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.stopImmediatePropagation(); showLb(box.k + (e.key === "ArrowRight" ? 1 : -1)); } }, true); }
  showLb(k); box.hidden = false;
}
function showLb(i) {
  const box = $("#lightbox"); const all = App.S.imagens || []; const n = all.length;
  i = ((i % n) + n) % n; let t = 0; while (!all[i].url && t++ < n) i = (i + 1) % n;
  box.k = i; const x = all[i];
  box.innerHTML = `<figure><img src="${x.url}" alt=""><figcaption><b>${i + 1} · ${esc(x.titulo)}</b> ${esc(x.legenda)}</figcaption></figure><button class="lbx iconbtn" aria-label="Fechar">✕</button>`;
}

/* ---------- 4. prova oral rápida: o que é · exemplo · cenário → resultado ---------- */
const PASSOS = [["O que é", "com as suas palavras"], ["Exemplo", "um caso concreto, seu"], ["Cenário", "aplique o conceito"]];
const Exam = { stream: null, ctx: null, an: null, buf: null, mr: null, raf: 0, gen: 0, audio: null, state: "idle", micOk: false, micMsg: "", forceEnd: false, hold: false };
const exState = () => App.S.exam;

const FINAL_UI = { primeira: ["✓", "ok", "de primeira"], reforco: ["✓", "ok", "com reforço"], explicado: ["✓", "ok", "depois da explicação"],
  so_vista: ["✗", "bad", "resposta na tela"], pulado: ["–", "skip", "pulada"] };
function studentPanel(e, st, reapr) {
  const ouvindo = ["ouvindo", "falando"].includes(st); const ocupado = ["pensando", "transcrevendo"].includes(st);
  const label = { professor: reapr ? "Professor explicando…" : "Professor perguntando…", pensando: reapr ? "Corrigindo…" : "Anotando…",
    ouvindo: "Sua vez — pode falar", falando: "Ouvindo você…", transcrevendo: "Anotando o que você disse…", escreva: "Sua vez — escreva a resposta", pausada: "Microfone pausado", idle: "Sua vez" }[st] || "Sua vez";
  const pausado = st === "pausada" || (Exam.hold && st === "professor");
  const toggle = Exam.micOk ? (pausado ? `<button class="btn listenbtn resume" id="exlisten">▶ Voltar a ouvir</button>`
    : `<button class="btn ghost small listenbtn" id="exhold" ${ocupado ? "disabled" : ""}>⏸ Parar de ouvir</button>`) : "";
  const hint = Exam.micMsg || (st === "pausada" ? "Pausado: nada do que você falar é gravado. Toque em “Voltar a ouvir” — ou escreva."
    : pausado ? "Depois da fala do professor, o microfone fica pausado." : reapr ? "Responda com as suas palavras — curto já vale." : e.atual === 1 ? "Um caso concreto — de preferência seu, do dia a dia." : "Responda falando — quando você parar, eu entendo que terminou.");
  return { label, html: `<div class="student">
      <div class="stu-row"><div class="stu-mic ${st === "falando" ? "live" : ""} ${ouvindo ? "on" : ""}">🎙</div>
        <div class="stu-info"><b>${esc(label)}</b><div class="meter ${ouvindo ? "on" : ""}" id="exmeter">${"<i></i>".repeat(30)}</div><span class="hint">${esc(hint)}</span></div>
        <div class="stu-btns">${ouvindo ? `<button class="btn ghost small" id="exdone">Terminei de falar</button>` : ""}${toggle}</div></div>
      <div class="stu-row"><input class="field" id="exin" placeholder="…ou escreva a resposta" autocomplete="off" ${ocupado ? "disabled" : ""}>
        <button class="btn" id="exsend" ${ocupado ? "disabled" : ""}>Enviar</button><button class="btn ghost small" id="exidk" ${ocupado || st === "professor" ? "disabled" : ""}>Não sei</button></div>
    </div>` };
}
function clipBox(tr) {
  if (!tr || !App.S.video) return "";
  return `<div class="clipbox"><button class="btn ghost small cliplay" type="button" data-ini="${tr.inicio}" data-fim="${tr.fim}">▶ Rever este trecho do vídeo (${mmss(tr.inicio)}–${mmss(tr.fim)})</button><div class="hint">“${esc(tr.texto)}”</div></div>`;
}
/* o trecho toca num player FIXO fora do slide: a tela da prova se redesenha a cada mudança e mataria um <video> lá dentro */
function playClip(ini, fim) {
  let box = $("#clipPlayer");
  if (!box) {
    box = document.createElement("div"); box.id = "clipPlayer"; box.className = "clipplayer";
    box.innerHTML = `<video playsinline preload="auto"></video><div class="cp-bar"><span></span><button class="btn ghost small" type="button">Fechar</button></div>`;
    document.body.appendChild(box);
    box.querySelector("button").onclick = () => { box.querySelector("video").pause(); box.hidden = true; fimClip(); };
  }
  const v = box.querySelector("video"); box.hidden = false;
  box.querySelector("span").textContent = `Trecho do vídeo · ${mmss(ini)}–${mmss(fim)}`;
  const vai = () => { v.currentTime = ini; v.play().catch(() => {}); };
  if (!v.src.endsWith(App.S.video.url)) { v.src = App.S.video.url; v.onloadedmetadata = vai; } else vai();
  const acabou = () => { v.pause(); fimClip(); setTimeout(() => { if (v.paused) box.hidden = true; }, 700); };   // fecha sozinho
  v.ontimeupdate = () => { if (v.currentTime >= fim + 0.3) acabou(); };
  v.onended = acabou;
}
function fimClip() { if (Exam.clipHold) { Exam.clipHold = false; if (Exam.state === "pausada") examResume(); else Exam.hold = false; } }
function wireClips(root) {
  // tocar o trecho: encerra a fala do professor (sem travar o fluxo) e segura o microfone enquanto o vídeo toca
  root.querySelectorAll(".cliplay").forEach((b) => { b.onclick = () => {
    if (Exam.state === "professor") { Exam.skip = true; try { Exam.audio.pause(); Exam.audio.onended?.(); } catch (e) {} }
    if (!Exam.hold) { Exam.clipHold = true; examHold(); }
    playClip(+b.dataset.ini, +b.dataset.fim); }; });
}
function cartaoHtml(ra) {
  const c = ra.cartao || {};
  let h = "";
  if (ra.tipo === "definicao") h = `<div class="rgrid"><div class="sim"><b>É</b><p>${esc(c.e)}</p></div><div class="nao"><b>Não é</b><p>${esc(c.nao_e)}</p></div></div>`;
  else if (ra.tipo === "exemplo") h = `<div class="rgrid"><div class="sim"><b>✓ É exemplo</b><p>${esc(c.caso_sim)}</p></div><div class="nao"><b>✗ Parece, mas não é</b><p>${esc(c.caso_nao)}</p></div></div><p class="rwhy">${esc(c.por_que)}</p>`;
  else if (ra.tipo === "cenario") h = `<div class="rcen"><b>Um parecido, resolvido</b><p>${esc(c.situacao)}</p><ol>${(c.passos || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ol></div>`;
  return `<div class="rcard"><div class="kicker">Mini-aula · ${esc(ra.rotulo)}</div>${h}${clipBox(ra.trecho)}
    ${ra.explicacao ? `<div class="rexp"><b>A resposta, com as palavras da aula</b><p>${esc(ra.explicacao)}</p></div>` : ""}</div>`;
}
function qresHtml(e, final) {
  const falas = e.turnos.filter((t) => t.papel === "aluno" && !t.r);
  return `<div class="qres">${e.perguntas.map((q, i) => {
    const r = falas.find((t) => t.q === i);
    const [ic, cls, txt] = final && q.final ? FINAL_UI[q.final] : q.status === "certa" ? ["✓", "ok", ""] : ["✗", "bad", ""];
    return `<div class="${cls}"><div class="qres-h"><b>${ic} ${q.n} · ${esc(q.rotulo)}${txt ? ` <em>· ${txt}</em>` : ""}</b><span>${esc(q.pergunta || "")}</span></div>
      <p><em>Você:</em> ${esc((final && q.ultima) || r?.texto || "—")}</p>${(final && q.motivo_final) || q.motivo ? `<p class="qres-why">${esc((final && q.motivo_final) || q.motivo)}</p>` : ""}
      ${final && ["so_vista", "pulado"].includes(q.final) && q.resposta ? `<p class="qres-exp"><em>Resposta:</em> ${esc(q.resposta)}</p>` : ""}</div>`; }).join("")}</div>`;
}

function renderExam(s) {
  const S = App.S; const e = exState(); const pronto = !!S.mapa_publico?.n;
  const fase = e?.fase; const fim = fase === "veredito"; const res = fase === "resultado"; const reapr = fase === "reaprender";
  const ra = e?.reaprender || {};
  const keepInput = $("#exin", s.el)?.value || "";
  const logScroll = $("#exlog", s.el);
  const atBottom = !logScroll || logScroll.scrollHeight - logScroll.scrollTop - logScroll.clientHeight < 40;
  const depois = fim || res || reapr;
  const rail = PASSOS.map(([nome, sub], i) => {
    const q = e?.perguntas?.[i]; let cls = "", b = i + 1;
    if (reapr && ra.q === i) { cls = "on"; b = "↻"; }
    else if (fim && q?.final) { [b, cls] = FINAL_UI[q.final]; }
    else if (depois) { cls = q?.status === "certa" ? "ok" : "bad"; b = q?.status === "certa" ? "✓" : "✗"; }
    else if (e && e.atual === i) cls = "on";
    else if (e && i < e.atual) { cls = "done"; b = "✓"; }
    return `<div class="strat ${cls}"><b>${b}</b><div><strong>${nome}</strong><span>${sub}</span></div></div>`; }).join('<i class="strat-arrow">→</i>')
    + `<i class="strat-arrow">→</i><div class="strat ${res || reapr || fim ? "on" : ""}"><b>${reapr || res ? "↻" : "★"}</b><div><strong>${reapr || res ? "Reaprender" : "Resultado"}</strong><span>${
      reapr ? `${ra.i + 1} de ${ra.fila.length}` : res ? `${ra.fila.length} para fechar` : fim ? esc(e.veredito.rotulo) : "no fim, de uma vez"}</span></div></div>`;
  const certas = e ? e.perguntas.filter((q) => q.status === "certa").length : 0;
  const why = !e ? "Três perguntas rápidas, só sobre o que o slide e o vídeo mostraram. A próxima vem logo depois da sua resposta; a correção sai no fim."
    : fim ? "Resultado final: o que saiu de primeira, com reforço, depois da explicação — e, se sobrou algo, a resposta na tela."
    : res ? `Você acertou ${certas} de 3. Em seguida, só o que faltou: uma mini-aula e uma pergunta nova para fechar.`
    : reapr ? `Reaprendendo ${ra.i + 1} de ${ra.fila.length} · ${ra.rotulo} — ${ra.passo === 2 ? "o professor explicou; agora diga com as suas palavras." : "veja o cartão e responda a pergunta nova."}`
    : `Pergunta ${e.atual + 1} de 3 · ${PASSOS[e.atual][0]} — ${PASSOS[e.atual][1]}.`;
  let stage;
  if (!e) stage = `<div class="prof-card intro"><div class="prof-orb idle"></div><div class="prof-name">Professor</div>
      <p class="prof-line">Três perguntas rápidas sobre <b>${esc(S.concept)}</b></p>
      <ol class="rules"><li><b>O que é?</b> — com as suas palavras.</li><li><b>Um exemplo</b> — específico, de preferência seu.</li><li><b>Um cenário</b> — uma situação concreta em que você aplica o conceito.</li></ol>
      <p class="hint" style="margin:-6px 0 14px">Errou alguma? No fim, uma mini-aula só do que faltou e uma pergunta nova para fechar.</p>
      <button class="cta" id="exstart" ${pronto ? "" : "disabled"}>${pronto ? "Começar" : "Montando as perguntas a partir da aula…"}</button>
      <p class="hint" style="margin-top:12px">${window.isSecureContext ? "Você responde falando (mãos livres). Dá para escrever também." : `Aqui o microfone está bloqueado (http). <a href="${secureURL()}">Abrir versão segura</a> para falar — ou responda escrevendo.`}</p></div>`;
  else if (fim) {
    const v = e.veredito;
    stage = `<div class="verdict ${v.so_vista || v.pulado ? "incompleta" : v.primeira === 3 ? "louvor" : "ajuda"}"><div class="kicker">Resultado</div><h3>${esc(v.rotulo)}</h3>${qresHtml(e, true)}
      <div class="vfoot"><span class="hint">${v.primeira} de 3 de primeira${v.reforco ? ` · ${v.reforco} com reforço` : ""}${v.explicado ? ` · ${v.explicado} depois da explicação` : ""} · ${mmss(v.duracao_s)}</span><button class="btn ghost" id="exredo">Refazer a prova</button></div></div>`;
  } else if (res) {
    stage = `<div class="verdict incompleta"><div class="kicker">Primeira passada</div><h3>${certas} de 3</h3>${qresHtml(e, false)}
      <div class="countdown ${Exam.state === "pensando" ? "wait" : ""}"><div><b>${Exam.state === "pensando" ? "Preparando a mini-aula…" : "Fechando o que faltou em 2 s"}</b><div class="cbar"><i style="animation-delay:-${Math.min(2, (performance.now() - (Exam.countStart || performance.now())) / 1000).toFixed(2)}s"></i></div></div>
        <button class="btn ghost small" id="exskipall" ${Exam.state === "pensando" ? "disabled" : ""}>Pular</button></div></div>`;
  } else {
    const st = Exam.state;
    const last = [...e.turnos].reverse().findIndex((t) => t.papel === "aluno");
    const profNow = (last < 0 ? e.turnos : e.turnos.slice(e.turnos.length - last)).filter((t) => t.papel === "professor");
    const q = reapr ? ra.pergunta : e.perguntas[e.atual]?.pergunta || "…";
    const falas = reapr ? profNow.filter((t) => t.tipo === "fala").map((t) => `<p>${esc(t.texto)}</p>`).join("") : "";
    const sp = studentPanel(e, st, reapr);
    // página recarregada no meio da prova: nada está ouvindo; retoma na mesma pergunta
    const parada = st === "idle";
    stage = `<div class="prof-card"><div class="prof-top"><div class="prof-orb ${st}"></div><div><div class="prof-name">${reapr ? `Reaprendendo · ${esc(ra.rotulo)} · ${ra.i + 1} de ${ra.fila.length}` : `Pergunta ${e.atual + 1} de 3 · ${esc(PASSOS[e.atual][0])}`}</div><div class="hint">${esc(parada ? "Prova parada" : sp.label)}</div></div>
        <div class="prof-acts">${st === "professor" ? `<button class="btn ghost small" id="exskip">Pular fala ⏭</button>` : ""}${reapr ? `<button class="btn ghost small" id="exskipall">Encerrar</button>` : ""}<button class="btn ghost small" id="exrestart" ${st === "pensando" ? "disabled" : ""}>↺ Recomeçar a prova</button></div></div>
      <div class="prof-say">${falas}<p class="q">${esc(q)}</p></div></div>
      ${reapr ? cartaoHtml(ra) : ""}${parada ? `<div class="student"><div class="stu-row"><div class="stu-info"><b>A prova parou aqui</b><span class="hint">A página foi recarregada e o microfone fechou. Continue desta pergunta — ou recomece do zero.</span></div>
        <div class="stu-btns"><button class="btn" id="excontinue">▶ Continuar a prova</button></div></div></div>` : sp.html}`;
  }
  const ata = e ? e.turnos.map((t) => `<div class="ata ${t.papel}"><div class="who">${t.papel === "aluno" ? "Você" : "Professor"}${t.q != null ? ` · <span class="st-q">${PASSOS[t.q][0]}${t.r ? " · reaprender" : ""}</span>` : ""}</div>${esc(t.texto)}</div>`).join("")
    + (Exam.state === "pensando" ? `<div class="ata professor"><div class="who">Professor</div><span class="skel" style="width:70%"></span></div>` : "")
    : `<div class="hint" style="padding:10px">A ata aparece aqui: cada pergunta e cada resposta.</div>`;
  s.el.innerHTML = head("4 · prova oral", "Prova oral", "explain") + `<div class="slide-body"><div class="exam">
    <div class="rail">${rail}<div class="exclock mono" id="examClock"></div></div>
    <div class="why">${esc(why)}</div>
    <div class="exgrid"><div class="exstage">${stage}</div><div class="atabox"><div class="kicker" style="margin-bottom:8px">Ata da prova</div><div class="exlog" id="exlog">${ata}</div></div></div></div></div>`;
  const log = $("#exlog", s.el); if (log && atBottom) log.scrollTop = log.scrollHeight;
  const inp = $("#exin", s.el); if (inp) { inp.value = keepInput; inp.onkeydown = (ev) => { if (ev.key === "Enter" && inp.value.trim()) examSend(inp.value.trim()); }; }
  $("#exstart", s.el)?.addEventListener("click", examBegin);
  $("#exredo", s.el)?.addEventListener("click", examBegin);
  $("#exrestart", s.el)?.addEventListener("click", examRestart);
  $("#excontinue", s.el)?.addEventListener("click", examContinue);
  $("#exsend", s.el)?.addEventListener("click", () => { const t = $("#exin").value.trim(); if (t) examSend(t); });
  $("#exidk", s.el)?.addEventListener("click", () => examSend("Não sei."));
  $("#exdone", s.el)?.addEventListener("click", () => { Exam.forceEnd = true; });
  $("#exhold", s.el)?.addEventListener("click", examHold);
  $("#exlisten", s.el)?.addEventListener("click", examResume);
  $("#exskipall", s.el)?.addEventListener("click", examPular);
  $("#exskip", s.el)?.addEventListener("click", () => { Exam.skip = true; try { Exam.audio.pause(); Exam.audio.onended?.(); } catch (err) {} });
  wireClips(s.el);
  tickClock();
}

window.addEventListener("beforeunload", (ev) => { if (Exam.recording && Exam.state === "falando") { ev.preventDefault(); ev.returnValue = ""; } });
function exSet(state) { Exam.state = state; refresh("explain"); }

async function examMic() {
  if (Exam.stream) return true;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { Exam.micMsg = window.isSecureContext ? "Este navegador não grava áudio — responda escrevendo." : insecureMsg(); return false; }
  try { Exam.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
  catch (e) { Exam.micMsg = "Microfone indisponível (" + e.name + ") — responda escrevendo."; return false; }
  Exam.ctx = new (window.AudioContext || window.webkitAudioContext)(); Exam.an = Exam.ctx.createAnalyser(); Exam.an.fftSize = 1024;
  Exam.ctx.createMediaStreamSource(Exam.stream).connect(Exam.an); Exam.buf = new Float32Array(Exam.an.fftSize);
  return true;
}
function examMicOff() { Exam.stream?.getTracks().forEach((t) => t.stop()); Exam.stream = null; try { Exam.ctx?.close(); } catch (e) {} Exam.ctx = null; }
function examRelease() { Exam.gen++; Exam.recording = false; cancelAnimationFrame(Exam.raf); try { if (Exam.mr?.state !== "inactive") { Exam.mr.onstop = null; Exam.mr.stop(); } } catch (e) {}
  examMicOff(); try { Exam.audio?.pause(); } catch (e) {} }

async function examBegin() {
  clearTimeout(Exam.countdown);
  Exam.audio = Exam.audio || new Audio(); try { Exam.audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="; await Exam.audio.play(); } catch (e) {}  // destrava o áudio no clique
  Exam.micOk = await examMic(); examMicOff(); Exam.hold = false; Exam.micMsg = "";   // permissão pedida no clique; o microfone só abre na sua vez
  exSet("pensando");
  const r = await post("exam", { acao: "start" });
  if (r.erro) { Exam.micMsg = r.erro; return exSet("idle"); }
  App.S.exam = r; await examTurn(++Exam.gen);
}
function examRestart() { clearTimeout(Exam.countdown); examRelease(); closeClip(); examBegin(); }
async function examContinue() {
  Exam.audio = Exam.audio || new Audio(); try { Exam.audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="; await Exam.audio.play(); } catch (e) {}
  Exam.micOk = await examMic(); examMicOff(); Exam.hold = false; Exam.micMsg = "";
  await examTurn(++Exam.gen);
}
async function examTurn(gen) {                        // professor faz a próxima pergunta (sem reação antes) → sua vez
  const e = exState(); const last = [...e.turnos].reverse().findIndex((t) => t.papel === "aluno");
  const falas = (last < 0 ? e.turnos : e.turnos.slice(e.turnos.length - last)).filter((t) => t.papel === "professor").map((t) => t.texto);
  exSet("professor");
  await examSpeak(falas.join(" "), gen);
  if (gen !== Exam.gen) return;
  if (e.fase === "veredito") { closeClip(); examRelease(); return exSet("idle"); }
  if (e.fase === "resultado") {                        // mostra o resultado e, em 2 s, começa a reaprender o que faltou
    examRelease(); exSet("idle"); clearTimeout(Exam.countdown);
    Exam.countStart = performance.now(); refresh("explain");
    Exam.countdown = setTimeout(() => { if (exState()?.fase === "resultado") examReaprender(); }, 2000); return;
  }
  if (Exam.hold) return exSet("pausada");
  if (Exam.micOk) examListen(gen); else { exSet("escreva"); $("#exin")?.focus(); }
}
async function examSpeak(text, gen) {
  const frases = (text.match(/[^.!?…]+[.!?…]+["”]?|[^.!?…]+$/g) || []).map((f) => f.trim()).filter(Boolean);
  const urls = frases.map((f) => fetch(`/api/s/${App.sid}/say`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: f }) })
    .then((x) => (x.ok ? x.blob() : null)).then((b) => (b ? URL.createObjectURL(b) : null)).catch(() => null));
  Exam.skip = false;
  for (const u of urls) { const url = await u; if (gen !== Exam.gen || Exam.skip) return; if (!url) continue;
    await new Promise((res) => { Exam.audio.onended = res; Exam.audio.onerror = res; Exam.audio.src = url; Exam.audio.play().catch(res); }); URL.revokeObjectURL(url); }
}
function examRms() { Exam.an.getFloatTimeDomainData(Exam.buf); let v = 0; for (const x of Exam.buf) v += x * x; return Math.sqrt(v / Exam.buf.length); }
async function examListen(gen) {
  if (gen !== Exam.gen) return;
  if (Exam.hold) return exSet("pausada");
  if (!(await examMic())) { Exam.micOk = false; return exSet("escreva"); }
  if (gen !== Exam.gen) return examMicOff();
  const e = exState(); const silence = [2000, 1500, 1800][e.atual] || 1600; const maxMs = 60000;
  const chunks = []; const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  const mr = Exam.mr = new MediaRecorder(Exam.stream, mime ? { mimeType: mime } : undefined);
  mr.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data); mr.start(200);
  Exam.forceEnd = false; exSet("ouvindo");
  const t0 = performance.now(); const calib = []; let thr = 0.02, speaking = false, sStart = 0, lastVoice = 0, above = 0, peak = 0;
  Exam.recording = true;
  const finish = () => { cancelAnimationFrame(Exam.raf); Exam.recording = false; mr.onstop = async () => {
      examMicOff();
      if (gen !== Exam.gen) return;
      exSet("transcrevendo");
      const blob = new Blob(chunks, { type: (mr.mimeType || "audio/webm").split(";")[0] });
      const r = await fetch(`/api/s/${App.sid}/stt`, { method: "POST", headers: { "Content-Type": blob.type }, body: blob }).then((x) => x.json()).catch(() => ({}));
      if (gen !== Exam.gen) return;
      const t = (r.text || "").trim();
      if (t.length < 2) { Exam.micMsg = "Não entendi nada — fale de novo, mais perto do microfone."; return examListen(gen); }
      Exam.micMsg = ""; examSend(t);
    }; mr.stop(); };
  const tick = () => {
    if (gen !== Exam.gen) return;
    const now = performance.now(), v = examRms();
    const meter = $("#exmeter"); if (meter) { const bars = meter.children; for (let i = bars.length - 1; i > 0; i--) bars[i].style.height = bars[i - 1].style.height; bars[0].style.height = Math.max(4, Math.min(26, v * 260)) + "px"; }
    if (now - t0 < 350) { calib.push(v); Exam.raf = requestAnimationFrame(tick); return; }
    if (calib.length) { calib.sort((a, b) => a - b); thr = Math.min(0.045, Math.max(0.012, calib[calib.length >> 1] * 3.2)); calib.length = 0; }
    if (!speaking) { above = v > thr ? above + 1 : 0; if (above >= 3) { speaking = true; sStart = now; lastVoice = now; exSet("falando"); } }
    else { peak = Math.max(peak, v);
      // ruído de fundo constante acima do limiar calibrado prendia a gravação para sempre: a pausa é medida contra o pico da sua voz
      if (v > Math.max(thr * 0.7, peak * 0.2)) lastVoice = now;
      if ((now - lastVoice > silence && now - sStart > 500) || now - sStart > maxMs) return finish(); }
    if (Exam.forceEnd) { Exam.forceEnd = false; if (speaking || now - t0 > 1500) return finish(); }
    Exam.raf = requestAnimationFrame(tick);
  };
  Exam.raf = requestAnimationFrame(tick);
}
async function examSend(text) {
  const gen = ++Exam.gen; Exam.recording = false; cancelAnimationFrame(Exam.raf); try { if (Exam.mr?.state === "recording") { Exam.mr.onstop = null; Exam.mr.stop(); } } catch (e) {}
  examMicOff();
  try { Exam.audio?.pause(); } catch (e) {}
  const e = exState(); const ra = e.fase === "reaprender" ? e.reaprender : null;
  e.turnos.push({ papel: "aluno", texto: text, q: ra ? ra.q : e.atual, r: ra ? ra.passo : undefined }); const inp = $("#exin"); if (inp) inp.value = "";
  exSet("pensando");
  const r = await post("exam", { text });
  if (gen !== Exam.gen) return;
  if (r.erro) { e.turnos.pop(); Exam.micMsg = r.erro; return exSet(Exam.micOk ? "ouvindo" : "escreva"); }
  if (r.reaprender && (r.reaprender.i !== ra?.i || r.reaprender.passo !== ra?.passo)) closeClip();   // outro item/passo: fecha o trecho anterior
  App.S.exam = r; await examTurn(gen);
}
async function examReaprender() {
  const gen = ++Exam.gen; exSet("pensando");
  const r = await post("exam", { acao: "reaprender" });
  if (gen !== Exam.gen) return;
  if (r.erro) { Exam.micMsg = r.erro; return exSet("idle"); }
  App.S.exam = r; await examTurn(gen);
}
async function examPular() {                          // pula a reaprendizagem (antes de começar ou no meio): encerra com as respostas na tela
  clearTimeout(Exam.countdown); const gen = ++Exam.gen; examRelease(); exSet("pensando");
  const r = await post("exam", { acao: "pular" });
  if (r.erro) { Exam.micMsg = r.erro; return exSet("idle"); }
  App.S.exam = r; await examTurn(++Exam.gen);
}
/* parar de ouvir: fecha o microfone sem mandar nada; se o professor estiver perguntando, pausa depois da pergunta */
function examHold() {
  Exam.hold = true;
  if (["ouvindo", "falando"].includes(Exam.state)) { examRelease(); exSet("pausada"); } else refresh("explain");
}
async function examResume() {
  Exam.hold = false; Exam.micMsg = "";
  if (Exam.state === "professor") return refresh("explain");       // termina a pergunta e já ouve
  const gen = ++Exam.gen; if (Exam.micOk) examListen(gen); else exSet("escreva");
}
function closeClip() { const box = $("#clipPlayer"); if (box && !box.hidden) { box.querySelector("video").pause(); box.hidden = true; } Exam.clipHold = false; }
function examPause() { if (!exState() || ["veredito", "resultado"].includes(exState().fase) || Exam.state === "idle") return; examRelease(); Exam.hold = true; Exam.state = "pausada"; refresh("explain"); }

/* ================= navegação ================= */
function go(i) {
  if (i < 0 || i >= App.slides.length) return;
  if (Conv.on && App.slides[i].key !== "s1") { convStop(); toast("<b>Modo conversa desligado</b> ao sair do slide 1"); }
  if (App.slides[App.cur]?.key === "explain" && App.slides[i].key !== "explain") { examPause(); closeClip(); }
  App.slides.forEach((s, k) => { s.el.classList.toggle("active", k === i); s.el.classList.toggle("left", k < i); });
  App.cur = i; App.news.delete(App.slides[i].key); renderTabs();
  $("#prev").disabled = i === 0; $("#next").disabled = i === App.slides.length - 1;
}
function renderTabs() {
  $("#tabs").innerHTML = App.slides.map((s, k) => `<button class="tab ${k === App.cur ? "active" : ""} ${App.news.has(s.key) ? "news" : ""}" data-k="${k}"><b>${k + 1}</b><span>${s.label}</span></button>`).join("");
  $("#tabs").querySelectorAll(".tab").forEach((b) => (b.onclick = () => go(+b.dataset.k)));
}
function markNews(key) { if (App.slides[App.cur]?.key !== key) App.news.add(key); renderTabs(); }
function wireNav() {
  $("#prev").onclick = () => go(App.cur - 1); $("#next").onclick = () => go(App.cur + 1);
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea")) return;
    if ($("#arch").classList.contains("on")) { if (e.key === "Escape") closeArch(); return; }
    if (e.key === "ArrowRight") go(App.cur + 1); else if (e.key === "ArrowLeft") go(App.cur - 1);
  });
  document.addEventListener("click", (e) => { const b = e.target.closest(".archbtn"); if (b) openArch(b.dataset.arch); });
  $("#archClose").onclick = closeArch; $("#scrim").onclick = closeArch;
}
function renderJobs() {
  const S = App.S;
  $("#jobs").innerHTML = ["slide1", "video", "imagens", "mapa"].map((n) => { const j = S.jobs[n] || { status: "fila" };
    const extra = j.status === "pronto" && j.at ? ` <span class="mono" style="color:var(--dim)">${fmtS(j.at)}</span>` : j.status === "gerando" && j.detail ? ` <span style="color:var(--dim)">· ${esc(j.detail)}</span>` : "";
    return `<span class="job ${j.status} ${n !== "mapa" ? "clickable" : ""}" data-job="${n}"><span class="dot"></span>${JOB_NAMES[n]}${extra}</span>`; }).join("");
  $("#jobs").querySelectorAll(".job.clickable").forEach((el) => (el.onclick = () => go(slideByKey(el.dataset.job === "slide1" ? "s1" : el.dataset.job))));
}
function toast(html, key, err) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : "");
  t.innerHTML = `<div>${html}</div>${key ? `<button class="go">ver →</button>` : ""}<button class="x" aria-label="fechar">✕</button>`;
  $("#toasts").appendChild(t);
  if (key) t.querySelector(".go").onclick = () => { go(slideByKey(key)); t.remove(); };
  t.querySelector(".x").onclick = () => t.remove(); setTimeout(() => t.remove(), 14000);
}
const sessionT = () => App.loadT + (performance.now() - App.loadedAt) / 1000;
function tickClock() { $("#tbClock").textContent = mmss(sessionT());
  const ec = $("#examClock"); const ex = App.S?.exam; if (ec) ec.textContent = ex ? "⏱ " + mmss((ex.t_fim ?? sessionT()) - ex.t_inicio) : ""; const e = $("#vidElapsed"); const j = App.S.jobs.video; if (e && j?.started != null) e.textContent = "gerando há " + mmss(sessionT() - j.started); }
function updateCost() {}   // custo fica só no painel "Como isto é arquitetado"
/* quem responde pelo Claude: assinatura (Claude Code logado, sem chave de API) ou OpenRouter (API paga, só sem login) */
const isSub = () => (App.S.llm?.provedor || "assinatura") === "assinatura";
function updateLLM() {
  const el = $("#tbLLM"); if (!App.S.llm) return;
  const plano = App.S.llm.plano ? " " + App.S.llm.plano.charAt(0).toUpperCase() + App.S.llm.plano.slice(1) : "";
  el.hidden = false; el.classList.toggle("api", !isSub());
  el.innerHTML = isSub() ? `Claude<span class="llm-long"> · assinatura${esc(plano)}</span>` : `Claude<span class="llm-long"> · API OpenRouter</span>`;
  el.title = isSub() ? "Claude pela sua assinatura: Claude Code logado neste computador, sem chave de API e sem custo por chamada" : "Sem login no Claude Code: usando a API paga do OpenRouter. Faça login (claude → /login) e o projeto volta sozinho para a assinatura.";
}
function llmFromMetric(m) {
  const pv = (m.provider || "").toLowerCase(); if (!/assinatura|openrouter/.test(pv) || !App.S.llm || m.label.startsWith("imagem_")) return;
  const nv = pv.includes("assinatura") ? "assinatura" : "openrouter";
  if (App.S.llm.provedor !== nv) { App.S.llm.provedor = nv; updateLLM(); }
}
const llmTag = () => isSub() ? "assinatura Claude (Claude Code)" : "OpenRouter (API)";
const llmVia = () => isSub()
  ? "pela sua assinatura do Claude: o Claude Code logado neste computador responde (sem chave de API, sessão enxuta sem ferramentas, pensamento estendido desligado)"
  : "pela API do OpenRouter (sem login no Claude Code), reasoning desligado";
async function post(act, body) { try { return await fetch(`/api/s/${App.sid}/${act}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()); } catch (e) { return { erro: e.message }; } }

/* ================= "Como isto é arquitetado" ================= */
function mrow(name, label) { const ms = App.S.metrics.filter((m) => m.label === label || m.label.startsWith(label)); if (!ms.length) return `<tr><td>${name}</td><td>ainda não rodou</td></tr>`;
  const m = ms[ms.length - 1]; const sub = /assinatura/i.test(m.provider || "");
  return `<tr><td>${name}</td><td>${fmtS(m.total)}${m.usd ? " · " + fmtUSD(m.usd) : sub ? " · assinatura" : ""}</td></tr>`; }
function jrow(name, job) { const j = App.S.jobs[job]; return `<tr><td>${name}</td><td>${j?.status === "pronto" ? "pronto em " + fmtS(j.at) : j?.status || "na fila"}</td></tr>`; }
const ARCH = {
  s1: () => ({ t: "Explicação quase instantânea + chat", steps: [
    ["Pré-geração", "enquanto você digita o conceito (pausa de 600 ms), o servidor já pede o texto ao Claude Sonnet 5. O clique em Começar só se conecta ao texto que já está vindo."],
    ["Streaming", `Claude Sonnet 5 ${llmVia()}; formato fixo [SIMPLES]/[ANALOGIA]/[EXEMPLO]; cada pedaço chega por SSE.`],
    ["Mais exemplos", "o botão sob o exemplo pede ao Sonnet 5 mais 2 exemplos na hora, de outras áreas da vida e diferentes dos que você já viu; chegam em streaming (1ª palavra em ~1 s, com o Claude já aberto) e ficam salvos na sessão."],
    ["Perguntas da prova", "quando o texto do slide e o roteiro do vídeo ficam prontos, o Sonnet 5 monta DELES as 3 perguntas do slide 3, com gabarito e o trecho literal da aula conferido no código. A prova só cobra o que a aula mostrou."],
    ["Chat com memória", "Sonnet 5 em streaming; vai o histórico da conversa (últimas 12 mensagens) + o texto do slide como contexto."],
    ["Modo conversa (voz)", "o navegador detecta quando você fala e quando para (1 s de silêncio) → Scribe transcreve → Sonnet 5 responde curto, para ser falado → cada frase que fica pronta já vira voz do narrador (ElevenLabs flash v2.5) e toca enquanto a próxima é gerada → volta a ouvir. Meia-duplex: não ouve enquanto fala (sem eco). Tudo isso roda enquanto o vídeo é gerado em 2º plano."]],
    tags: ["Claude Sonnet 5", llmTag(), "SSE", "pré-geração", "ElevenLabs Scribe", "ElevenLabs flash v2.5"],
    rows: `<tr><td>origem do texto</td><td>${esc(App.S.slide1_source || "—")}</td></tr><tr><td>1º texto na tela (após o clique)</td><td>${fmtS(App.s1First)}</td></tr>${jrow("slide completo", "slide1")}${mrow("mais exemplos (últimos 2)", "mais_exemplos")}${jrow("perguntas da prova", "mapa")}${mrow("última resposta do chat", "chat")}${mrow("conversa: transcrição", "transcricao")}${mrow("conversa: resposta (LLM)", "chat_voz")}${mrow("conversa: voz de 1 frase", "voz_conversa")}<tr><td>conversa: você parou de falar → voz começou</td><td>${fmtS(Conv.lastLatency)}</td></tr>`,
    fb: "Claude Code logado numa conta claude.ai → tudo pela assinatura. Sem login → OpenRouter (API paga); ao fazer login, o projeto volta sozinho para a assinatura em até 1 min, sem reiniciar. Se a pré-geração falhar, o texto é gerado no clique. Modo conversa precisa de microfone: https pela rede (porta 4243) ou localhost no Mac." }),
  video: () => ({ t: "Fluxograma draw.io em vídeo", steps: [
    ["1 chamada", "Sonnet 5 devolve o fluxograma (3–5 caixas em fluxo, até 3 laterais, 1 seta de volta) E a frase de narração de cada caixa."],
    ["draw.io", "layout calculado em Python → .drawio → check_layout.py (skill diagram-from-anything) → PNG pelo drawio CLI."],
    ["Voz", "ElevenLabs flash v2.5, voz escolhida no setup, 1 chamada /with-timestamps: o tempo de cada letra diz quando cada caixa deve acender."],
    ["Motion", "cena HTML com seek(t) (contrato do Motion Designer): 1 caixa acesa por vez, zoom logarítmico, legenda da fala. Playwright fotografa só as transições; ffmpeg monta 1280×720 com áudio −14 LUFS."]],
    tags: ["Claude Sonnet 5", llmTag(), "drawio CLI", "ElevenLabs flash v2.5", "Playwright", "ffmpeg"],
    rows: `${mrow("fluxograma + roteiro (LLM)", "fluxograma_e_roteiro")}${mrow("draw.io", "drawio")}${mrow("narração", "narracao")}${mrow("animação + montagem", "motion")}${jrow("vídeo", "video")}`,
    fb: "Se o vídeo falhar, o slide mostra o erro; o resto da aula segue." }),
  imagens: () => ({ t: "O conceito em imagens", steps: [
    ["Quando", "começa assim que o roteiro do vídeo existe (~10 s após o clique), em paralelo ao desenho, à voz e à animação do vídeo: quando você termina de assistir, as imagens já estão prontas."],
    ["O que desenhar", "Claude Sonnet 5 lê a aula (slide 1 + narração do vídeo) e escolhe 4 ideias na ordem da história: o panorama, os 2 mecanismos principais por dentro e a analogia/exemplo. Para cada uma escreve título, legenda e a cena em inglês."],
    ["Desenho", "Gemini 3.1 Flash Lite Image pelo OpenRouter, as 4 em paralelo (~4–10 s cada, ~US$ 0,03 por imagem). Estilo fixo no código: ilustração editorial de revista científica, adulta, sem texto na imagem."]],
    tags: ["Claude Sonnet 5", llmTag(), "Gemini 3.1 Flash Lite Image", "OpenRouter"],
    rows: `${mrow("plano das imagens (LLM)", "imagens_plano")}${[1, 2, 3, 4].map((k) => mrow(`imagem ${k}`, `imagem_${k}`)).join("")}${jrow("imagens", "imagens")}`,
    fb: "Uma imagem que falha não derruba as outras (cada uma tenta 2 vezes). Se nenhuma sair, o slide mostra o erro; o resto da aula segue." }),
  explain: () => ({ t: "Prova oral rápida: o que é · exemplo · cenário → reaprender o que faltou", steps: [
    ["Só o que foi ensinado", "as 3 perguntas saem do slide 1 e da narração do vídeo, montadas assim que a aula fica pronta (~17 s após o clique). O gabarito da 1ª e da 3ª traz o trecho literal da aula, conferido no código."],
    ["3 perguntas fixas", "1) O que é? — com as suas palavras. 2) Um exemplo específico — de preferência seu. 3) Um cenário concreto novo, com uma pergunta em que o conceito se aplica."],
    ["Sem espera entre perguntas", "você responde e a próxima pergunta já é feita (a voz das 3 fica pronta antes de você chegar aqui). A correção de cada resposta roda em 2º plano no Sonnet 5; nada de “entendi” no meio."],
    ["Correção", "generosa: o essencial certo com as suas palavras conta. Exemplo precisa ser um caso concreto e ser mesmo do conceito. Acerto só vale com o trecho literal da sua resposta que o mostra (conferido no código)."],
    ["Microfone", "abre sozinho na sua vez; o fim da resposta é o silêncio ou o botão “Terminei de falar”. “Parar de ouvir” fecha o microfone a qualquer momento (nada é gravado); “Voltar a ouvir” reabre. Barulho (“[ruído]”) não conta como resposta. A pausa é medida contra o pico da sua voz (ruído de fundo não prende a gravação), teto de 60 s; página recarregada no meio → “Continuar a prova” na mesma pergunta; “Recomeçar a prova” zera a qualquer momento."],
    ["Resultado", "no fim, de uma vez: ✓/✗ em cada pergunta e o motivo. Acertou as 3? Acabou."],
    ["Reaprender o que faltou", "começa sozinha 2 s depois do resultado (dá para pular), só nas perguntas erradas. Para cada uma: mini-aula no formato que conserta aquele erro (o que é: “é / não é” + o trecho do vídeo; exemplo: um caso que vale e um que parece mas não vale; cenário: um parecido resolvido em 3 passos) e uma pergunta NOVA. Errou de novo? O professor explica com as palavras da aula e você repete com as suas. Sem voltas extras e sem revisão depois: o conceito fecha aqui."],
    ["Sem espera", "a mini-aula de cada pergunta errada é preparada em 2º plano durante a própria prova (texto e voz em cache); quando o resultado aparece, ela já está pronta."]],
    tags: ["ElevenLabs Scribe v1", "Claude Sonnet 5", llmTag(), "ElevenLabs flash v2.5", "MediaRecorder + detecção de fala"],
    rows: `${mrow("transcrição da fala", "transcricao")}${mrow("correção · o que é", "prova_correcao_definicao")}${mrow("correção · exemplo", "prova_correcao_exemplo")}${mrow("correção · cenário", "prova_correcao_cenario")}${mrow("preparo da mini-aula (2º plano)", "reaprender_prepara")}${mrow("correção na reaprendizagem", "reaprender_correcao")}${mrow("voz do professor (1 frase)", "voz_conversa")}`,
    fb: "Sem microfone (http pela rede, navegador sem gravação): a prova segue por escrito. Microfone precisa de https ou localhost." }),
};
function openArch(key) {
  const a = ARCH[key]();
  $("#archTitle").textContent = a.t;
  $("#archBody").innerHTML = `<ol class="pipe">${a.steps.map(([b, t]) => `<li><b>${b}.</b> <span>${t}</span></li>`).join("")}</ol>
    <h4>Modelos e ferramentas</h4><div class="tags">${a.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    <h4>Medido nesta sessão</h4><table class="measure">${a.rows}<tr><td>custo total da sessão (US$)</td><td>${fmtUSD(App.S.usd)}${isSub() ? " · Claude pela assinatura" : ""}</td></tr></table>${a.fb ? `<h4>Fallback e limites</h4><div class="note">${a.fb}</div>` : ""}`;
  $("#arch").classList.add("on"); $("#scrim").classList.add("on"); $("#arch").setAttribute("aria-hidden", "false");
}
function closeArch() { $("#arch").classList.remove("on"); $("#scrim").classList.remove("on"); $("#arch").setAttribute("aria-hidden", "true"); }

boot();
