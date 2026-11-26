/* Gráficos em SVG puro (sem dependências externas). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const cor = (nome) => getComputedStyle(document.documentElement).getPropertyValue("--" + nome).trim() || "#888";
  function el(tag, attrs, pai) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (pai) pai.appendChild(e);
    return e;
  }
  const curto = (v) => {
    const a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mi";
    if (a >= 1e3) return (v / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil";
    return v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  };

  /* Barras horizontais: [{rotulo, valor, cor, extra}] */
  function barrasH(alvo, dados, opts = {}) {
    if (!alvo) return;   // a tela pode ter mudado enquanto os dados carregavam
    alvo.innerHTML = "";
    if (!dados.length) { alvo.innerHTML = '<div class="vazio">Sem dados</div>'; return; }
    const larg = Math.max(320, alvo.clientWidth || 640), alt = 30 * dados.length + 10, esq = Math.min(opts.esq || 170, larg * 0.32), max = Math.max(...dados.map((d) => d.valor), 1);
    const svg = el("svg", { viewBox: `0 0 ${larg} ${alt}`, role: "img", "aria-label": opts.titulo || "gráfico de barras" }, alvo);
    dados.forEach((d, i) => {
      const y = 6 + i * 30, w = Math.max(2, (larg - esq - Math.min(230, larg * 0.38)) * d.valor / max);
      el("text", { x: esq - 8, y: y + 15, "text-anchor": "end" }, svg).textContent = d.rotulo;
      const r = el("rect", { x: esq, y, width: w, height: 20, rx: 4, fill: cor(d.cor || "azul") }, svg);
      el("title", {}, r).textContent = `${d.rotulo}: ${opts.fmt ? opts.fmt(d.valor) : curto(d.valor)}`;
      el("text", { x: esq + w + 6, y: y + 15 }, svg).textContent = (opts.fmt ? opts.fmt(d.valor) : curto(d.valor)) + (d.extra ? "  " + d.extra : "");
    });
  }

  /* Linhas: series [{nome, cor, pontos:[{x,y}]}] */
  function linhas(alvo, series, opts = {}) {
    if (!alvo) return;
    alvo.innerHTML = "";
    const pts = series.flatMap((s) => s.pontos);
    if (!pts.length) { alvo.innerHTML = '<div class="vazio">Sem dados</div>'; return; }
    const larg = Math.max(320, alvo.clientWidth || 640), alt = 260, m = { e: 54, d: 14, t: 12, b: 30 };
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = 0, y1 = Math.max(...ys) * 1.08 || 1;
    const X = (v) => m.e + (larg - m.e - m.d) * (v - x0) / ((x1 - x0) || 1);
    const Y = (v) => alt - m.b - (alt - m.t - m.b) * (v - y0) / ((y1 - y0) || 1);
    const svg = el("svg", { viewBox: `0 0 ${larg} ${alt}`, role: "img", "aria-label": opts.titulo || "gráfico de linhas" }, alvo);
    for (let i = 0; i <= 4; i++) {
      const v = y0 + (y1 - y0) * i / 4;
      el("line", { x1: m.e, x2: larg - m.d, y1: Y(v), y2: Y(v), stroke: cor("borda") }, svg);
      el("text", { x: m.e - 6, y: Y(v) + 4, "text-anchor": "end" }, svg).textContent = opts.fmtY ? opts.fmtY(v) : curto(v);
    }
    for (let i = 0; i <= 4; i++) {
      const v = x0 + (x1 - x0) * i / 4;
      el("text", { x: X(v), y: alt - 10, "text-anchor": "middle" }, svg).textContent = opts.fmtX ? opts.fmtX(v) : curto(v);
    }
    series.forEach((s) => {
      const d = s.pontos.map((p, i) => (i ? "L" : "M") + X(p.x).toFixed(1) + " " + Y(p.y).toFixed(1)).join(" ");
      el("path", { d, fill: "none", stroke: s.cor || cor("azul"), "stroke-width": 2.2, "stroke-linejoin": "round" }, svg);
      s.pontos.forEach((p) => {
        if (!s.marcar) return;
        const c = el("circle", { cx: X(p.x), cy: Y(p.y), r: 3, fill: s.cor }, svg);
        el("title", {}, c).textContent = `${s.nome}: ${opts.fmtX ? opts.fmtX(p.x) : p.x} → ${opts.fmtY ? opts.fmtY(p.y) : p.y}`;
      });
    });
    if (opts.legenda !== false) {
      const leg = document.createElement("div");
      leg.className = "legenda";
      leg.innerHTML = series.map((s) => `<span><i style="background:${s.cor}"></i>${s.nome}</span>`).join("");
      alvo.appendChild(leg);
    }
  }

  /* Rosca de proporções: [{rotulo, valor, cor}] */
  function rosca(alvo, dados, centro) {
    if (!alvo) return;
    alvo.innerHTML = "";
    const tot = dados.reduce((a, d) => a + d.valor, 0);
    const svg = el("svg", { viewBox: "0 0 220 220", role: "img", "aria-label": "distribuição" }, alvo);
    let ang = -Math.PI / 2;
    if (!tot) el("circle", { cx: 110, cy: 110, r: 80, fill: "none", stroke: cor("borda"), "stroke-width": 26 }, svg);
    dados.forEach((d) => {
      if (!d.valor) return;
      const a2 = ang + 2 * Math.PI * d.valor / tot, grande = a2 - ang > Math.PI ? 1 : 0;
      const p = (a, r) => [110 + r * Math.cos(a), 110 + r * Math.sin(a)];
      const [x1, y1] = p(ang, 80), [x2, y2] = p(a2 - 0.0001, 80);
      const path = el("path", { d: `M${x1} ${y1} A80 80 0 ${grande} 1 ${x2} ${y2}`, fill: "none", stroke: cor(d.cor), "stroke-width": 26 }, svg);
      el("title", {}, path).textContent = `${d.rotulo}: ${d.valor}`;
      ang = a2;
    });
    el("text", { x: 110, y: 108, "text-anchor": "middle", style: "font-size:26px;font-weight:700;fill:var(--texto)" }, svg).textContent = centro ?? tot;
    el("text", { x: 110, y: 130, "text-anchor": "middle" }, svg).textContent = "achados";
    const leg = document.createElement("div");
    leg.className = "legenda";
    leg.innerHTML = dados.map((d) => `<span><i style="background:var(--${d.cor})"></i>${d.rotulo} (${d.valor})</span>`).join("");
    alvo.appendChild(leg);
  }

  window.Graficos = { barrasH, linhas, rosca, cor, curto };
})();
