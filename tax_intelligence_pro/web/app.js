/* TAX INTELLIGENCE PRO — dashboard (JS puro; toda regra de cálculo fica no servidor). */
(function () {
  "use strict";
  const G = window.Graficos;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => Number(v || 0);
  const brl = (v) => num(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const pct = (v, c = 2) => (num(v) * 100).toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c }) + "%";
  const ROT = { VERDE: "Conciliado", AMARELO: "Requer análise", VERMELHO: "Inconsistência", AZUL: "Oportunidade" };
  const REGIMES = { SIMPLES_NACIONAL: "Simples Nacional", LUCRO_PRESUMIDO: "Lucro Presumido", LUCRO_REAL: "Lucro Real" };
  const STATUS = { pendente_validacao: "Pendente de validação", validado_documental: "Validado (documental)",
    validado_juridico: "Validado (jurídico)", descartado: "Descartado" };
  const mesAtual = () => new Date().toISOString().slice(0, 7);

  const S = {
    token: sessionStorage.getItem("tip_token"), usuario: null, empresas: [], empresa: null, tela: "visao",
    lerEmpresa() { try { return Number(localStorage.getItem("tip_empresa")) || null; } catch (e) { return null; } },
    gravarEmpresa(id) { try { localStorage.setItem("tip_empresa", id); } catch (e) { /* armazenamento indisponível */ } },
  };
  const pode = (p) => S.usuario && S.usuario.permissoes.includes(p);

  async function api(metodo, caminho, corpo, extra = {}) {
    const h = { ...(extra.headers || {}) };
    if (S.token) h.Authorization = "Bearer " + S.token;
    let body;
    if (corpo instanceof Blob || corpo instanceof ArrayBuffer) body = corpo;
    else if (corpo !== undefined) { body = JSON.stringify(corpo); h["Content-Type"] = "application/json"; }
    const r = await fetch(caminho, { method: metodo, headers: h, body });
    if (extra.bruto) { if (!r.ok) throw new Error((await r.json()).erro); return r; }
    const j = await r.json().catch(() => ({ erro: "resposta inválida do servidor" }));
    if (r.status === 401 && caminho !== "/api/login") { sair(); throw new Error(j.erro || "sessão expirada"); }
    if (!r.ok) throw new Error(j.erro || "erro " + r.status);
    return j;
  }
  function aviso(msg, erro) {
    const t = document.createElement("div");
    t.className = "toast" + (erro ? " erro" : "");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), erro ? 6000 : 3200);
  }
  async function tentar(fn) { try { return await fn(); } catch (e) { aviso(e.message, true); } }
  async function baixar(caminho, nome) {
    const r = await api("GET", caminho, undefined, { bruto: true });
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: nome });
    if (!nome) { window.open(url, "_blank", "noopener"); } else { a.click(); }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  // ------------------------------------------------------------------ casca
  function telaLogin() {
    $("#raiz").innerHTML = `<div class="login cartao"><div class="logo">TAX INTELLIGENCE PRO<small>Auditoria e inteligência tributária</small></div>
      <form id="f-login" class="grade"><div><label for="l-login">Usuário</label><input id="l-login" autocomplete="username" required></div>
      <div><label for="l-senha">Senha</label><input id="l-senha" type="password" autocomplete="current-password" required></div>
      <button class="btn primario">Entrar</button>
      <p class="suave peq">Primeiro acesso: usuário <b>admin</b>, senha em <span class="mono">data/SENHA_INICIAL_ADMIN.txt</span>.</p></form></div>`;
    $("#f-login").addEventListener("submit", (e) => {
      e.preventDefault();
      tentar(async () => {
        const r = await api("POST", "/api/login", { login: $("#l-login").value, senha: $("#l-senha").value });
        S.token = r.token; sessionStorage.setItem("tip_token", r.token);
        iniciar();
      });
    });
  }
  function sair() {
    if (S.token) fetch("/api/logout", { method: "POST", headers: { Authorization: "Bearer " + S.token } }).catch(() => {});
    S.token = null; sessionStorage.removeItem("tip_token"); telaLogin();
  }

  const TELAS = [
    ["Análise", [["visao", "Visão geral"], ["simuladores", "Simuladores"], ["importacao", "Importação"], ["achados", "Cruzamentos e achados"], ["historico", "Histórico"]]],
    ["Cadastros", [["empresas", "Empresas"], ["regras", "Motor de regras"]]],
    ["Sistema", [["admin", "Administração"]]],
  ];
  function casca() {
    $("#raiz").innerHTML = `<div class="app"><aside class="lateral"><div class="logo">TAX INTELLIGENCE PRO<small>Auditoria tributária</small></div>
      <nav class="nav">${TELAS.map(([g, it]) => `<div class="grupo">${g}</div>` + it.map(([id, nome]) => `<button data-tela="${id}">${nome}</button>`).join("")).join("")}</nav></aside>
      <main class="principal"><div class="topo"><h1 id="titulo"></h1>
        <select id="sel-empresa" aria-label="Empresa" style="max-width:340px"></select>
        <span class="usuario">${esc(S.usuario.nome)} · ${esc(S.usuario.papel)}</span><button class="btn peq" id="b-sair">Sair</button></div>
      <div id="conteudo"></div></main></div>`;
    $$(".nav button").forEach((b) => b.addEventListener("click", () => ir(b.dataset.tela)));
    $("#b-sair").addEventListener("click", sair);
    $("#sel-empresa").addEventListener("change", (e) => { S.empresa = Number(e.target.value) || null; S.gravarEmpresa(S.empresa); ir(S.tela); });
    preencherEmpresas();
  }
  function preencherEmpresas() {
    const sel = $("#sel-empresa");
    sel.innerHTML = S.empresas.length ? S.empresas.map((e) => `<option value="${e.id}" ${e.id === S.empresa ? "selected" : ""}>${esc(e.razao_social)} — ${esc(REGIMES[e.regime])}</option>`).join("")
      : '<option value="">Cadastre uma empresa</option>';
  }
  const empresaAtual = () => S.empresas.find((e) => e.id === S.empresa);
  async function carregarEmpresas() {
    S.empresas = await api("GET", "/api/empresas");
    if (!S.empresas.find((e) => e.id === S.empresa)) S.empresa = S.empresas[0]?.id || null;
  }
  async function iniciar() {
    if (!S.token) return telaLogin();
    try { S.usuario = await api("GET", "/api/me"); } catch (e) { return telaLogin(); }
    S.empresa = S.lerEmpresa();
    await carregarEmpresas();
    casca();
    ir(S.empresas.length ? "visao" : "empresas");
  }
  function ir(tela) {
    S.tela = tela;
    $$(".nav button").forEach((b) => b.classList.toggle("ativo", b.dataset.tela === tela));
    const nome = TELAS.flatMap((g) => g[1]).find((t) => t[0] === tela)[1];
    $("#titulo").textContent = nome;
    $("#conteudo").innerHTML = '<div class="vazio">Carregando…</div>';
    tentar(() => RENDER[tela]($("#conteudo")));
  }
  const precisaEmpresa = (c) => { if (S.empresa) return false; c.innerHTML = '<div class="cartao vazio">Cadastre ou selecione uma empresa em <b>Empresas</b>.</div>'; return true; };

  // ------------------------------------------------------------------ componentes
  const selo = (cor, txt) => `<span class="selo ${cor}">${esc(txt || ROT[cor])}</span>`;
  function tabelaAchados(lista, opts = {}) {
    if (!lista.length) return '<div class="vazio">Nenhum achado.</div>';
    return `<div class="rolagem"><table class="tab"><thead><tr><th>Status</th><th>Achado</th><th>Tributo</th><th>Período</th><th class="num">Valor</th><th>Confiança</th>${opts.validacao ? "<th>Validação</th>" : ""}</tr></thead><tbody>
      ${lista.map((a) => `<tr class="clic" data-achado="${a.id}"><td>${selo(a.cor)}</td><td><b>${esc(a.titulo)}</b><div class="suave peq">${esc(a.descricao).slice(0, 220)}</div></td>
        <td>${esc(a.tributo || "—")}</td><td>${esc(a.periodo || "—")}</td><td class="num">${brl(a.valor)}</td><td>${esc(a.confianca || "")}</td>
        ${opts.validacao ? `<td><span class="selo neutro">${esc(STATUS[a.status])}</span></td>` : ""}</tr>`).join("")}</tbody></table></div>`;
  }
  function ligarAchados(raiz, lista, aoMudar) {
    $$("[data-achado]", raiz).forEach((tr) => tr.addEventListener("click", () => abrirAchado(lista.find((a) => a.id === Number(tr.dataset.achado)), aoMudar)));
  }
  function gaveta(html) {
    fecharGaveta();
    const v = document.createElement("div"); v.className = "veu"; v.id = "veu";
    const g = document.createElement("aside"); g.className = "gaveta"; g.id = "gaveta"; g.setAttribute("role", "dialog");
    g.innerHTML = `<div class="linha" style="justify-content:flex-end"><button class="btn peq" id="b-fechar">Fechar</button></div>` + html;
    document.body.append(v, g);
    v.addEventListener("click", fecharGaveta); $("#b-fechar").addEventListener("click", fecharGaveta);
    document.addEventListener("keydown", escFecha);
    return g;
  }
  function escFecha(e) { if (e.key === "Escape") fecharGaveta(); }
  function fecharGaveta() { $("#veu")?.remove(); $("#gaveta")?.remove(); document.removeEventListener("keydown", escFecha); }

  function abrirAchado(a, aoMudar) {
    const docs = (a.origem && a.origem.documentos) || [];
    const outros = Object.entries(a.origem || {}).filter(([k]) => k !== "documentos");
    const g = gaveta(`<div class="linha">${selo(a.cor)}<span class="selo neutro">${esc(STATUS[a.status])}</span><span class="suave peq">#${a.id} · ${esc(a.categoria)} · ${esc(a.tipo)}</span></div>
      <h2 style="margin:10px 0 4px">${esc(a.titulo)}</h2><p>${esc(a.descricao)}</p>
      <div class="ficha">
        <div>Valor estimado (d)</div><div><b>${brl(a.valor)}</b></div>
        <div>Grau de confiabilidade (e)</div><div>${esc(a.confianca)}</div>
        <div>Origem da informação (a)</div><div>${outros.map(([k, v]) => `<div class="peq"><b>${esc(k)}:</b> ${esc(Array.isArray(v) ? v.slice(0, 12).join(" · ") : typeof v === "object" ? JSON.stringify(v) : v)}</div>`).join("")}
          ${docs.length ? `<table class="tab peq"><tr><th>Fonte</th><th>Nº</th><th>Data</th><th>Participante</th><th>Chave</th></tr>${docs.slice(0, 30).map((d) => `<tr><td>${esc(d.fonte)}</td><td>${esc(d.numero)}</td><td>${esc(d.data)}</td><td>${esc(d.participante || "")}</td><td class="mono">${esc(d.chave || "")}</td></tr>`).join("")}</table>` : ""}</div>
        <div>Fundamentação legal (b)</div><div>${esc(a.fundamento || "—")}</div>
        <div>Memória de cálculo (c)</div><div><ol class="memoria">${(a.memoria || []).map((m) => `<li>${esc(m)}</li>`).join("") || "<li>—</li>"}</ol></div>
        <div>Documentação necessária (f)</div><div>${esc(a.documentacao || "—")}</div>
        <div>Procedimento de validação (g)</div><div>${esc(a.procedimento)}</div>
      </div>
      <h3>Histórico de validação</h3>${(a.validacao || []).map((v) => `<div class="alerta VERDE"><b>${esc(STATUS[v.para])}</b> por ${esc(v.por)} em ${esc(v.em)}<br>${esc(v.justificativa)}<br><span class="suave">Documentos: ${esc(v.documentos)}</span></div>`).join("") || '<p class="suave">Ainda não validado. Nenhum crédito ou recuperação é definitivo sem validação documental e jurídica.</p>'}
      ${pode("validar") && a.cor !== "VERDE" ? `<form id="f-val" class="form" style="margin-top:12px"><div><label>Novo status</label><select id="v-status">
          <option value="validado_documental">Validado (documental)</option><option value="validado_juridico">Validado (jurídico)</option><option value="descartado">Descartado</option></select></div>
        <div class="larga"><label>Justificativa</label><textarea id="v-just" required></textarea></div>
        <div class="larga"><label>Documentos examinados</label><input id="v-docs" placeholder="XML, C170, parecer nº…"></div>
        <div><button class="btn primario">Registrar validação</button></div></form>` : ""}`);
    $("#f-val", g)?.addEventListener("submit", (e) => {
      e.preventDefault();
      tentar(async () => {
        const r = await api("POST", `/api/achados/${a.id}/validar`, { status: $("#v-status").value, justificativa: $("#v-just").value, documentos: $("#v-docs").value });
        Object.assign(a, r); aviso("Validação registrada na trilha de auditoria"); abrirAchado(a, aoMudar); aoMudar && aoMudar();
      });
    });
  }

  // ------------------------------------------------------------------ telas
  const RENDER = {};

  RENDER.visao = async (c) => {
    if (precisaEmpresa(c)) return;
    const d = await api("GET", "/api/dashboard?empresa=" + S.empresa);
    const e = empresaAtual();
    if (!d.ultima_analise) {
      c.innerHTML = `<div class="cartao vazio"><p>Nenhuma análise para <b>${esc(e.razao_social)}</b> ainda.</p>
        <p>1) Importe XMLs, SPED e planilhas · 2) rode a análise em <b>Cruzamentos e achados</b>.</p>
        <button class="btn primario" data-ir="importacao">Importar arquivos</button></div>` + cartaoCarga(d);
      ligarIr(c); desenharCarga(c, d); return;
    }
    const cores = d.cores, cr = d.creditos;
    c.innerHTML = `
      <div class="suave peq" style="margin-bottom:10px">Última análise #${d.ultima_analise.id} · ${esc(d.ultima_analise.periodo_ini)} a ${esc(d.ultima_analise.periodo_fim)} · ${esc(REGIMES[d.ultima_analise.regime])} · ${new Date(d.ultima_analise.criado_em).toLocaleString("pt-BR")}</div>
      <div class="grade g4">
        <div class="kpi AZUL"><div class="rot">Economia potencial estimada</div><div class="num">${brl(d.economia_potencial)}</div><div class="det">${cores.AZUL.quantidade} oportunidade(s) — pendentes de validação</div></div>
        <div class="kpi VERMELHO"><div class="rot">Exposição a risco</div><div class="num">${brl(d.exposicao_risco)}</div><div class="det">${cores.VERMELHO.quantidade} inconsistência(s) relevante(s)</div></div>
        <div class="kpi AMARELO"><div class="rot">Divergências para análise</div><div class="num">${cores.AMARELO.quantidade}</div><div class="det">${brl(cores.AMARELO.valor)} envolvidos</div></div>
        <div class="kpi VERDE"><div class="rot">Verificações conciliadas</div><div class="num">${cores.VERDE.quantidade}</div><div class="det">fontes que batem entre si</div></div>
      </div>
      <div class="grade g4" style="margin-top:16px">
        <div class="kpi"><div class="rot">Créditos identificados</div><div class="num">${brl(cr.identificados)}</div></div>
        <div class="kpi"><div class="rot">Créditos utilizados (escrituração)</div><div class="num">${brl(cr.utilizados_escrituracao)}</div></div>
        <div class="kpi"><div class="rot">Pendentes de validação</div><div class="num">${brl(cr.pendentes_validacao)}</div><div class="det">validados: ${brl(cr.validados)}</div></div>
        <div class="kpi VERMELHO"><div class="rot">Créditos indevidos/duplicados</div><div class="num">${brl(cr.indevidos)}</div></div>
      </div>
      <div class="grade g3" style="margin-top:16px">
        <div class="cartao"><h2>Distribuição dos achados</h2><div class="grafico" id="g-rosca" style="max-width:260px;margin:auto"></div></div>
        <div class="cartao" style="grid-column:span 2"><h2>Achados por categoria</h2><div class="grafico" id="g-cat"></div></div>
      </div>
      <div class="grade g2">
        <div class="cartao"><h2>Principais oportunidades ${selo("AZUL")}</h2>${tabelaAchados(d.top_oportunidades)}</div>
        <div class="cartao"><h2>Principais inconsistências ${selo("VERMELHO")}</h2>${tabelaAchados(d.top_riscos)}</div>
      </div>
      ${cartaoCarga(d)}
      <div class="grade g2">
        <div class="cartao"><h2>Evolução das análises</h2><div class="grafico" id="g-hist"></div></div>
        <div class="cartao"><h2>Importações recentes</h2>${tabelaImportacoes(d.importacoes.slice(0, 8))}</div>
      </div>`;
    G.rosca($("#g-rosca"), ["AZUL", "VERMELHO", "AMARELO", "VERDE"].map((k) => ({ rotulo: ROT[k], valor: cores[k].quantidade, cor: { AZUL: "azul", VERMELHO: "vermelho", AMARELO: "amarelo", VERDE: "verde" }[k] })));
    G.barrasH($("#g-cat"), d.categorias.filter((x) => x.cor !== "VERDE").sort((a, b) => b.quantidade - a.quantidade).slice(0, 12)
      .map((x) => ({ rotulo: x.categoria, valor: x.quantidade, cor: x.cor.toLowerCase(), extra: ROT[x.cor] })), { esq: 130 });
    const h = d.historico_analises.slice().reverse();
    G.linhas($("#g-hist"), [
      { nome: "Economia potencial", cor: G.cor("azul"), marcar: true, pontos: h.map((x, i) => ({ x: i + 1, y: num(x.economia) })) },
      { nome: "Exposição a risco", cor: G.cor("vermelho"), marcar: true, pontos: h.map((x, i) => ({ x: i + 1, y: num(x.risco) })) }],
      { fmtX: (v) => "#" + (h[Math.round(v) - 1]?.id ?? ""), fmtY: G.curto });
    ligarAchados(c, [...d.top_oportunidades, ...d.top_riscos]);
    desenharCarga(c, d); ligarIr(c);
  };
  function cartaoCarga(d) {
    return `<div class="cartao"><h2>Carga tributária — comparativo de regimes <span class="acoes"><button class="btn peq" data-ir="simuladores">Nova simulação</button></span></h2>
      ${d.carga ? `<div class="grafico" id="g-carga"></div><p class="suave peq">${(d.carga.premissas || []).map(esc).join(" ")}</p>` : '<div class="vazio">Rode o comparativo de regimes em <b>Simuladores</b> para ver a carga projetada.</div>'}</div>`;
  }
  function desenharCarga(c, d) {
    if (!d.carga || !$("#g-carga", c)) return;
    G.barrasH($("#g-carga", c), d.carga.cenarios.filter((x) => x.total).map((x) => ({ rotulo: REGIMES[x.regime], valor: num(x.total),
      cor: x.regime === d.carga.melhor ? "verde" : "azul", extra: "carga " + pct(x.carga_efetiva) })), { fmt: brl, esq: 140 });
  }
  function ligarIr(c) { $$("[data-ir]", c).forEach((b) => b.addEventListener("click", () => ir(b.dataset.ir))); }
  function tabelaImportacoes(l) {
    if (!l.length) return '<div class="vazio">Nada importado ainda.</div>';
    return `<div class="rolagem"><table class="tab"><tr><th>Arquivo</th><th>Tipo</th><th>Período</th><th class="num">Registros</th><th>Status</th></tr>
      ${l.map((i) => `<tr><td>${esc(i.nome_arquivo)}</td><td>${esc(i.tipo)}</td><td>${esc(i.periodo_ini || "")}${i.periodo_fim && i.periodo_fim !== i.periodo_ini ? " a " + esc(i.periodo_fim) : ""}</td><td class="num">${i.registros}</td>
      <td>${selo(i.status === "concluida" ? "VERDE" : "VERMELHO", i.status)}</td></tr>`).join("")}</table></div>`;
  }

  // ---------------- simuladores
  const SIMS = {
    simples: {
      nome: "Simples Nacional",
      form: () => `<div><label>Período (AAAA-MM)</label><input name="periodo" value="${mesAtual()}"></div>
        <div><label>RBT12 (receita 12 meses)</label><input name="rbt12" value="720000"></div>
        <div><label>Folha 12 meses (Fator R)</label><input name="folha12" value="0"></div>
        <div><label>Meses de atividade</label><input name="meses_atividade" value="13"></div>
        <div><label>DAS pago (opcional)</label><input name="das_pago"></div>
        <div class="larga"><label>Parcelas de receita do mês</label><div id="parcelas"></div><button type="button" class="btn peq" id="b-parcela">+ parcela</button></div>`,
      montar: (f) => ({ periodo: f.periodo, rbt12: f.rbt12, folha12: f.folha12, meses_atividade: f.meses_atividade, das_pago: f.das_pago || null,
        parcelas: $$("#parcelas .parc").map((p) => ({ descricao: $("[name=p_desc]", p).value, anexo: $("[name=p_anexo]", p).value, valor: $("[name=p_valor]", p).value,
          tipos: $$("[name=p_tipo]:checked", p).map((x) => x.value) })) }),
      numeros: (r) => [["DAS do mês", brl(r.das)], ["Alíquota efetiva total", pct(r.aliquota_efetiva_total, 4)], ["RBT12 utilizada", brl(r.rbt12_utilizada)],
        ["Fator R", r.fator_r ? pct(r.fator_r) : "—"], ["Economia pela segregação", brl(r.economia_segregacao)]],
      extra: (r) => `<h3>Parcelas</h3><div class="rolagem"><table class="tab"><tr><th>Parcela</th><th>Anexo/faixa</th><th class="num">Nominal</th><th class="num">Dedução</th><th class="num">Efetiva</th><th class="num">Após segregação</th><th class="num">DAS</th></tr>
        ${r.parcelas.map((p) => `<tr><td>${esc(p.descricao || "")}</td><td>${p.anexo} · ${p.faixa}ª</td><td class="num">${pct(p.aliquota_nominal)}</td><td class="num">${brl(p.parcela_deduzir)}</td><td class="num">${pct(p.aliquota_efetiva, 4)}</td><td class="num">${pct(p.aliquota_efetiva_apos_segregacao, 4)}</td><td class="num">${brl(p.das)}</td></tr>`).join("")}</table></div>
        <h3>Por tributo</h3><div class="resultado-num">${Object.entries(r.por_tributo).map(([k, v]) => `<div><span>${k}</span><b>${brl(v)}</b></div>`).join("")}</div>
        <h3>Gráfico de alíquotas — Anexo ${r.parcelas[0].anexo}</h3><div class="grafico" id="g-curva"></div>`,
      depois: async (r) => {
        const anexo = r.parcelas[0].anexo, curva = await api("GET", `/api/simples/curva?anexo=${anexo}&data=${r.data_referencia}`);
        G.linhas($("#g-curva"), [
          { nome: "Alíquota efetiva", cor: G.cor("azul"), pontos: curva.map((p) => ({ x: num(p.rbt12), y: num(p.efetiva) })) },
          { nome: "Alíquota nominal", cor: G.cor("amarelo"), pontos: curva.map((p) => ({ x: num(p.rbt12), y: num(p.nominal) })) },
          { nome: "Sua posição", cor: G.cor("vermelho"), marcar: true, pontos: [{ x: num(r.rbt12_utilizada), y: num(r.parcelas[0].aliquota_efetiva) }] }],
          { fmtY: (v) => pct(v, 1), fmtX: G.curto });
      },
    },
    presumido: {
      nome: "Lucro Presumido",
      form: () => `<div><label>Ano</label><input name="ano" value="${new Date().getFullYear()}"></div><div><label>Trimestre</label><select name="trimestre"><option>1</option><option>2</option><option>3</option><option>4</option></select></div>
        <div><label>Atividade</label><select name="atividade">${["comercio", "industria", "servicos", "servicos_ate_120mil", "transporte_cargas", "transporte_passageiros", "servicos_hospitalares", "revenda_combustiveis", "intermediacao_negocios"].map((a) => `<option>${a}</option>`).join("")}</select></div>
        <div><label>Receita do trimestre</label><input name="receita" value="300000"></div><div><label>Outras receitas</label><input name="outras" value="0"></div>
        <div><label>ICMS destacado (exclusão PIS/COFINS)</label><input name="icms" value="0"></div><div><label>Receita monofásica (alíq. zero)</label><input name="mono" value="0"></div>
        <div><label>IRRF retido</label><input name="ret_ir" value="0"></div><div><label>CSLL retida</label><input name="ret_cs" value="0"></div>`,
      montar: (f) => ({ ano: f.ano, trimestre: f.trimestre, receitas: [{ atividade: f.atividade, valor: f.receita }], outras_receitas: f.outras,
        pis_cofins: { receita_bruta: f.receita, icms_destacado: f.icms, receita_monofasica_aliquota_zero: f.mono }, retencoes: { IRPJ: f.ret_ir, CSLL: f.ret_cs } }),
      numeros: (r) => [["Total a recolher", brl(r.total)], ["Carga sobre a receita", pct(r.carga_sobre_receita)], ["IRPJ + adicional", brl(num(r.irpj) + num(r.irpj_adicional))],
        ["CSLL", brl(r.csll)], ["PIS", brl(r.pis)], ["COFINS", brl(r.cofins)], ["Base IRPJ", brl(r.base_irpj)], ["Base CSLL", brl(r.base_csll)]],
    },
    real: {
      nome: "Lucro Real",
      form: () => `<div><label>Início do período</label><input name="data_inicio" value="${new Date().getFullYear()}-01-01"></div><div><label>Meses (3 = trimestral, 12 = anual)</label><input name="meses" value="12"></div>
        <div><label>Lucro contábil</label><input name="lucro" value="500000"></div><div><label>Adições</label><input name="adicoes" value="0"></div><div><label>Exclusões</label><input name="exclusoes" value="0"></div>
        <div><label>Prejuízo fiscal disponível</label><input name="prej" value="0"></div><div><label>Base negativa CSLL</label><input name="bneg" value="0"></div>
        <div><label>Receita tributável PIS/COFINS</label><input name="receita" value="4000000"></div><div><label>ICMS destacado nas vendas</label><input name="icms" value="0"></div>
        <div><label>Base de créditos — revenda/insumos</label><input name="cr1" value="2000000"></div><div><label>Base de créditos — energia/aluguéis/outros</label><input name="cr2" value="0"></div>`,
      montar: (f) => ({ data_inicio: f.data_inicio, meses: f.meses, lucro_contabil: f.lucro, adicoes: f.adicoes, exclusoes: f.exclusoes, prejuizo_fiscal_disponivel: f.prej,
        base_negativa_disponivel: f.bneg, receita_tributavel: f.receita, icms_destacado: f.icms, creditos: { revenda_insumos: f.cr1, outros: f.cr2 } }),
      numeros: (r) => [["Total a recolher", brl(r.total)], ["Carga sobre a receita", pct(r.carga_sobre_receita)], ["IRPJ + adicional", brl(num(r.irpj) + num(r.irpj_adicional))],
        ["CSLL", brl(r.csll)], ["PIS (débito − crédito)", brl(num(r.pis_debito) - num(r.pis_credito))], ["COFINS (débito − crédito)", brl(num(r.cofins_debito) - num(r.cofins_credito))]],
    },
    comparativo: {
      nome: "Comparativo de regimes",
      form: () => `<div><label>Ano</label><input name="ano" value="${new Date().getFullYear()}"></div><div><label>Receita anual</label><input name="receita_anual" value="1800000"></div>
        <div><label>Anexo do Simples</label><select name="anexo">${["I", "II", "III", "IV", "V", "FATOR_R"].map((a) => `<option>${a}</option>`).join("")}</select></div>
        <div><label>Folha anual (Fator R)</label><input name="folha_anual" value="0"></div>
        <div><label>Atividade (Presumido)</label><select name="atividade_presumido">${["comercio", "industria", "servicos"].map((a) => `<option>${a}</option>`).join("")}</select></div>
        <div><label>Lucro contábil anual (Real)</label><input name="lucro_contabil_anual" value="180000"></div><div><label>Base de créditos PIS/COFINS (Real)</label><input name="creditos_pis_cofins_base" value="900000"></div>
        <div><label>ICMS/ISS fora do Simples (anual, informado)</label><input name="icms_iss_fora_simples" value="0"></div><div><label>CPP fora do Simples (anual, informado)</label><input name="cpp_fora_simples" value="0"></div>
        <div><label>ICMS destacado anual</label><input name="icms_destacado_anual" value="0"></div>
        <div><label>Regime atual</label><select name="regime_atual">${Object.entries(REGIMES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>`,
      montar: (f) => ({ ...f }),
      numeros: (r) => [["Melhor cenário", REGIMES[r.melhor] || "—"], ["Economia vs regime atual", brl(r.economia_potencial)], ...r.cenarios.map((c) => [REGIMES[c.regime], c.total ? brl(c.total) + " (" + pct(c.carga_efetiva) + ")" : "inviável"])],
      extra: (r) => `<div class="grafico" id="g-comp"></div>${r.cenarios.filter((c) => c.erro).map((c) => `<div class="alerta AMARELO">${REGIMES[c.regime]}: ${esc(c.erro)}</div>`).join("")}
        <h3>Premissas</h3><ul>${r.premissas.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`,
      depois: (r) => G.barrasH($("#g-comp"), r.cenarios.filter((x) => x.total).map((x) => ({ rotulo: REGIMES[x.regime], valor: num(x.total), cor: x.regime === r.melhor ? "verde" : "azul", extra: pct(x.carga_efetiva) })), { fmt: brl, esq: 140 }),
    },
    reforma: {
      nome: "Reforma Tributária (IBS/CBS)",
      form: () => `<div><label>Ano</label><select name="ano">${[2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033].map((a) => `<option>${a}</option>`).join("")}</select></div>
        <div><label>Base das operações</label><input name="base" value="100000"></div><div><label>Base das aquisições com crédito</label><input name="creditos_base" value="40000"></div>
        <div><label>Alíquota CBS de referência (≥ 2027)</label><input name="aliquota_cbs_referencia" placeholder="fração, ex.: 0.088"></div>
        <div><label>Alíquota IBS de referência (≥ 2029)</label><input name="aliquota_ibs_referencia" placeholder="fração"></div>`,
      montar: (f) => ({ ...f }),
      numeros: (r) => [["CBS líquida", brl(r.cbs_liquida)], ["IBS líquido", brl(r.ibs_liquido)], ["Alíquota CBS", pct(r.aliquota_cbs, 3)], ["Alíquota IBS", pct(r.aliquota_ibs, 3)],
        ["PIS/COFINS", r.cronograma.pis_cofins], ["ICMS/ISS", r.cronograma.icms_iss]],
    },
  };
  RENDER.simuladores = async (c, tipo = "simples") => {
    c.innerHTML = `<div class="abas">${Object.entries(SIMS).map(([k, v]) => `<button data-sim="${k}" class="${k === tipo ? "ativo" : ""}">${v.nome}</button>`).join("")}</div>
      <div class="grade g2" style="grid-template-columns:minmax(0,5fr) minmax(0,7fr)"><div class="cartao"><h2>Parâmetros</h2><form id="f-sim" class="form">${SIMS[tipo].form()}
      <div class="larga"><label>Título (histórico)</label><input name="_titulo" placeholder="opcional"></div><div class="larga linha"><button class="btn primario">Simular e salvar</button></div></form></div>
      <div class="cartao" id="res-sim"><h2>Resultado</h2><div class="vazio">Preencha os parâmetros e simule. Cada cálculo fica salvo no histórico com a memória e as regras usadas.</div></div></div>`;
    $$("[data-sim]", c).forEach((b) => b.addEventListener("click", () => RENDER.simuladores(c, b.dataset.sim)));
    if (tipo === "simples") {
      const add = (d = "Revenda de mercadorias", anexo = "I", valor = "60000") => {
        const div = document.createElement("div"); div.className = "parc form"; div.style.marginBottom = "8px";
        div.innerHTML = `<div><input name="p_desc" value="${esc(d)}" aria-label="descrição"></div><div><select name="p_anexo" aria-label="anexo">${["I", "II", "III", "IV", "V", "FATOR_R"].map((a) => `<option ${a === anexo ? "selected" : ""}>${a}</option>`).join("")}</select></div>
          <div><input name="p_valor" value="${valor}" aria-label="valor"></div><div class="larga peq linha">${["monofasico", "icms_st", "iss_retido", "exportacao"].map((t) => `<label style="display:inline-flex;gap:4px;align-items:center;margin:0"><input type="checkbox" name="p_tipo" value="${t}" style="width:auto">${t}</label>`).join("")}</div>`;
        $("#parcelas").appendChild(div);
      };
      add(); $("#b-parcela").addEventListener("click", () => add("Outra receita", "I", "0"));
    }
    $("#f-sim").addEventListener("submit", (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target).entries());
      for (const k of Object.keys(f)) if (f[k] === "" ) delete f[k];
      tentar(async () => {
        const dados = SIMS[tipo].montar(f);
        const r = await api("POST", "/api/simular/" + tipo, { dados, empresa_id: S.empresa, titulo: f._titulo });
        mostrarSim($("#res-sim"), tipo, r);
      });
    });
  };
  function mostrarSim(alvo, tipo, r) {
    const s = SIMS[tipo];
    alvo.innerHTML = `<h2>Resultado <span class="acoes"><button class="btn peq" id="b-mem">Memória de cálculo (HTML)</button></span></h2>
      ${(r.alertas || []).map((a) => `<div class="alerta ${a.cor}">${esc(a.texto)}</div>`).join("")}
      <div class="resultado-num">${s.numeros(r).map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("")}</div>
      ${s.extra ? s.extra(r) : ""}
      ${r.memoria ? `<h3>Memória de cálculo</h3><ol class="memoria">${r.memoria.map((p) => `<li><b>${esc(p.titulo)}:</b> ${esc(p.detalhe)} ${p.regra ? `<small>[${esc(p.regra)}]</small>` : ""}</li>`).join("")}</ol>` : ""}
      <h3>Regras aplicadas</h3><ul class="peq">${(r.regras_usadas || []).filter((x, i, a) => a.findIndex((y) => y.codigo === x.codigo) === i).map((x) => `<li><b>${esc(x.codigo)}</b> v${x.versao} — ${esc(x.fundamento)} ${x.situacao === "validar" ? selo("AMARELO", "validar") : ""}</li>`).join("")}</ul>
      <p class="suave peq">Simulação #${r.simulacao_id} · hash ${esc((r.hash || "").slice(0, 16))}…</p>`;
    $("#b-mem").addEventListener("click", () => tentar(() => baixar(`/api/simulacoes/${r.simulacao_id}/memoria.html`)));
    if (s.depois) tentar(() => s.depois(r));
  }

  // ---------------- importação
  RENDER.importacao = async (c) => {
    if (precisaEmpresa(c)) return;
    const [imps, perfis] = await Promise.all([api("GET", "/api/importacoes?empresa=" + S.empresa), api("GET", "/api/perfis")]);
    c.innerHTML = `<div class="cartao"><h2>Enviar arquivos — ${esc(empresaAtual().razao_social)}</h2>
      <div class="form"><div><label>Tipo</label><select id="i-tipo"><option value="auto">Detectar automaticamente (XML, SPED, ZIP)</option><option value="tabular">Planilha / CSV / XLSX</option></select></div>
      <div id="i-plan" class="escondido"><label>Conteúdo da planilha</label><select id="i-tipo-plan">${perfis.tipos.map((t) => `<option>${t}</option>`).join("")}</select></div>
      <div id="i-perfil-d" class="escondido"><label>Perfil do sistema</label><select id="i-perfil">${perfis.perfis.map((p) => `<option>${p}</option>`).join("")}</select></div></div>
      <p class="suave peq">Aceitos: XML de NF-e/NFC-e/CT-e/NFS-e e eventos, ZIP com XMLs, EFD ICMS/IPI, EFD-Contribuições, ECD, ECF, CSV/XLSX (documentos, apuração, balancete, PGDAS-D, DCTFWeb, pagamentos). ${esc(perfis.nota)}</p>
      <div class="soltar" id="soltar" tabindex="0" role="button">Arraste os arquivos aqui ou clique para escolher<input type="file" id="arquivos" multiple class="escondido"></div>
      <div id="i-log" style="margin-top:10px"></div></div>
      <div class="cartao"><h2>Importações</h2><div id="i-lista"></div></div>`;
    const tipo = $("#i-tipo");
    tipo.addEventListener("change", () => { $("#i-plan").classList.toggle("escondido", tipo.value !== "tabular"); $("#i-perfil-d").classList.toggle("escondido", tipo.value !== "tabular"); });
    const zona = $("#soltar"), inp = $("#arquivos");
    zona.addEventListener("click", () => inp.click());
    zona.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") inp.click(); });
    zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("sobre"); });
    zona.addEventListener("dragleave", () => zona.classList.remove("sobre"));
    zona.addEventListener("drop", (e) => { e.preventDefault(); zona.classList.remove("sobre"); enviar([...e.dataTransfer.files]); });
    inp.addEventListener("change", () => enviar([...inp.files]));
    async function enviar(arqs) {
      const log = $("#i-log");
      // eventos de cancelamento por último, para encontrarem as NF-e
      arqs.sort((a, b) => /cancel|evento/i.test(a.name) - /cancel|evento/i.test(b.name));
      for (const f of arqs) {
        const q = new URLSearchParams({ empresa: S.empresa, tipo: tipo.value });
        if (tipo.value === "tabular") { q.set("tipo_planilha", $("#i-tipo-plan").value); q.set("perfil", $("#i-perfil").value); }
        const linha = document.createElement("div"); linha.className = "alerta AMARELO"; linha.textContent = "Enviando " + f.name + "…"; log.prepend(linha);
        try {
          const r = await api("POST", "/api/importar?" + q, f, { headers: { "X-Filename": encodeURIComponent(f.name) } });
          linha.className = "alerta " + (r.status === "concluida" ? "VERDE" : r.status === "duplicado" ? "AMARELO" : "VERMELHO");
          linha.innerHTML = `<b>${esc(f.name)}</b>: ${esc(r.status)} · ${esc(r.tipo || "")} · ${r.registros ?? 0} registro(s)` + (r.mensagens || []).slice(0, 5).map((m) => `<div class="peq">${esc(m.nivel)}: ${esc(m.texto)}</div>`).join("");
        } catch (e) { linha.className = "alerta VERMELHO"; linha.textContent = f.name + ": " + e.message; }
      }
      lista();
    }
    async function lista() {
      const l = await api("GET", "/api/importacoes?empresa=" + S.empresa);
      $("#i-lista").innerHTML = l.length ? `<div class="rolagem"><table class="tab"><tr><th>#</th><th>Arquivo</th><th>Tipo / fonte</th><th>Período</th><th class="num">Registros</th><th>Status</th><th>SHA-256</th><th></th></tr>
        ${l.map((i) => `<tr><td>${i.id}</td><td>${esc(i.nome_arquivo)}<div class="suave peq">${(i.mensagens || []).filter((m) => m.nivel !== "info").slice(0, 2).map((m) => esc(m.texto)).join("<br>")}</div></td><td>${esc(i.tipo)}<div class="suave peq">${esc(i.fonte)}</div></td>
          <td>${esc(i.periodo_ini || "")}</td><td class="num">${i.registros}</td><td>${selo(i.status === "concluida" ? "VERDE" : "VERMELHO", i.status)}</td><td class="mono">${esc(i.sha256.slice(0, 12))}</td>
          <td>${pode("importar") ? `<button class="btn peq perigo" data-del="${i.id}">Excluir</button>` : ""}</td></tr>`).join("")}</table></div>` : '<div class="vazio">Nenhum arquivo importado.</div>';
      $$("[data-del]", c).forEach((b) => b.addEventListener("click", () => { if (confirm("Excluir esta importação e todos os registros dela?")) tentar(async () => { await api("DELETE", "/api/importacoes/" + b.dataset.del); lista(); }); }));
    }
    void imps; lista();
  };

  // ---------------- achados
  RENDER.achados = async (c, analiseId) => {
    if (precisaEmpresa(c)) return;
    const analises = await api("GET", "/api/analises?empresa=" + S.empresa);
    const ult = analiseId || analises[0]?.id;
    c.innerHTML = `<div class="cartao"><h2>Executar análise</h2><form id="f-an" class="form">
        <div><label>Período inicial</label><input name="ini" type="month" value="${analises[0]?.periodo_ini || mesAtual()}"></div>
        <div><label>Período final</label><input name="fim" type="month" value="${analises[0]?.periodo_fim || mesAtual()}"></div>
        <div><button class="btn primario" ${pode("analisar") ? "" : "disabled"}>Cruzar informações</button></div>
        <div><label>Análise exibida</label><select id="sel-an">${analises.map((a) => `<option value="${a.id}" ${a.id === ult ? "selected" : ""}>#${a.id} · ${a.periodo_ini}–${a.periodo_fim} · ${new Date(a.criado_em).toLocaleString("pt-BR")}</option>`).join("")}</select></div></form>
        <p class="suave peq">Créditos (PIS/COFINS, ICMS, IPI), XML × EFD, apurações (E110, M200/M600), declarações e pagamentos, PGDAS-D, alíquotas e bases, contabilidade × fiscal, sistemas, retenções e IBS/CBS.</p></div>
      <div id="an-corpo"></div>`;
    $("#f-an").addEventListener("submit", (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target).entries());
      tentar(async () => { const r = await api("POST", "/api/analisar", { empresa_id: S.empresa, periodo_ini: f.ini, periodo_fim: f.fim }); aviso(`Análise #${r.id}: ${r.achados.length} achado(s)`); RENDER.achados(c, r.id); });
    });
    $("#sel-an")?.addEventListener("change", (e) => RENDER.achados(c, Number(e.target.value)));
    if (!ult) { $("#an-corpo").innerHTML = '<div class="cartao vazio">Nenhuma análise executada.</div>'; return; }
    const a = await api("GET", "/api/analises/" + ult);
    let filtro = { cor: "", cat: "", busca: "" };
    const corpo = $("#an-corpo");
    const cats = [...new Set(a.achados.map((x) => x.categoria))].sort();
    corpo.innerHTML = `<div class="grade g4">${["AZUL", "VERMELHO", "AMARELO", "VERDE"].map((k) => `<button class="kpi ${k}" data-cor="${k}" style="text-align:left;cursor:pointer"><div class="rot">${ROT[k]}</div><div class="num">${a.resumo.por_cor[k].quantidade}</div><div class="det">${brl(a.resumo.por_cor[k].valor)}</div></button>`).join("")}</div>
      <div class="cartao" style="margin-top:16px"><h2>Achados da análise #${a.id} <span class="acoes"><button class="btn peq" id="b-rel">Relatório técnico (HTML)</button><button class="btn peq" id="b-csv">Exportar CSV</button></span></h2>
      <div class="form" style="margin-bottom:10px"><div><label>Cor</label><select id="fl-cor"><option value="">Todas</option>${Object.entries(ROT).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
      <div><label>Categoria</label><select id="fl-cat"><option value="">Todas</option>${cats.map((x) => `<option>${esc(x)}</option>`).join("")}</select></div>
      <div class="larga" style="grid-column:span 2"><label>Buscar</label><input id="fl-busca" placeholder="título, tributo, documento…"></div></div><div id="an-tab"></div></div>
      <div class="cartao"><h2>Verificações executadas</h2><table class="tab">${a.resumo.verificacoes.map((v) => `<tr><td>${esc(v.verificacao)}</td><td>${v.status === "ok" ? selo("VERDE", "ok") : selo("VERMELHO", "erro")}</td><td class="num">${v.achados ?? ""}</td><td class="suave peq">${esc(v.erro || "")}</td></tr>`).join("")}</table>
      <p class="suave peq">Fontes: ${Object.entries(a.resumo.fontes).map(([k, v]) => `${esc(k)} (${v})`).join(" · ")} · hash ${esc(a.hash.slice(0, 20))}…</p></div>`;
    const desenhar = () => {
      const l = a.achados.filter((x) => (!filtro.cor || x.cor === filtro.cor) && (!filtro.cat || x.categoria === filtro.cat) &&
        (!filtro.busca || JSON.stringify([x.titulo, x.descricao, x.tributo, x.origem]).toLowerCase().includes(filtro.busca.toLowerCase())));
      $("#an-tab").innerHTML = tabelaAchados(l, { validacao: true });
      ligarAchados($("#an-tab"), l, desenhar);
    };
    $("#fl-cor").addEventListener("change", (e) => { filtro.cor = e.target.value; desenhar(); });
    $("#fl-cat").addEventListener("change", (e) => { filtro.cat = e.target.value; desenhar(); });
    $("#fl-busca").addEventListener("input", (e) => { filtro.busca = e.target.value; desenhar(); });
    $$("[data-cor]", corpo).forEach((b) => b.addEventListener("click", () => { filtro.cor = b.dataset.cor; $("#fl-cor").value = b.dataset.cor; desenhar(); }));
    $("#b-rel").addEventListener("click", () => tentar(() => baixar(`/api/analises/${a.id}/relatorio.html`)));
    $("#b-csv").addEventListener("click", () => tentar(() => baixar(`/api/analises/${a.id}/achados.csv`, `achados-${a.id}.csv`)));
    desenhar();
  };

  // ---------------- histórico
  RENDER.historico = async (c) => {
    const q = S.empresa ? "?empresa=" + S.empresa : "";
    const [sims, ans] = await Promise.all([api("GET", "/api/simulacoes" + q), S.empresa ? api("GET", "/api/analises?empresa=" + S.empresa) : []]);
    c.innerHTML = `<div class="grade g2"><div class="cartao"><h2>Simulações</h2>${sims.length ? `<table class="tab"><tr><th>#</th><th>Tipo</th><th>Título</th><th>Data</th><th></th></tr>
      ${sims.map((s) => `<tr><td>${s.id}</td><td>${esc(s.tipo)}</td><td>${esc(s.titulo || "")}</td><td>${new Date(s.criado_em).toLocaleString("pt-BR")}</td><td><button class="btn peq" data-sim-id="${s.id}">Abrir</button></td></tr>`).join("")}</table>` : '<div class="vazio">Sem simulações.</div>'}</div>
      <div class="cartao"><h2>Análises</h2>${ans.length ? `<table class="tab"><tr><th>#</th><th>Períodos</th><th class="num">Oportunidades</th><th class="num">Risco</th><th></th></tr>
      ${ans.map((a) => `<tr><td>${a.id}</td><td>${a.periodo_ini}–${a.periodo_fim}</td><td class="num">${brl(a.resumo.economia_potencial)}</td><td class="num">${brl(a.resumo.exposicao_risco)}</td><td><button class="btn peq" data-an-id="${a.id}">Abrir</button></td></tr>`).join("")}</table>` : '<div class="vazio">Sem análises.</div>'}</div></div>`;
    $$("[data-sim-id]", c).forEach((b) => b.addEventListener("click", () => tentar(async () => {
      const s = await api("GET", "/api/simulacoes/" + b.dataset.simId);
      const g = gaveta(`<h2>Simulação #${s.id} — ${esc(s.tipo)}</h2><p class="suave">${new Date(s.criado_em).toLocaleString("pt-BR")} · hash ${esc(s.hash.slice(0, 20))}…</p><div id="sim-res"></div><h3>Entrada</h3><pre class="json">${esc(JSON.stringify(s.entrada, null, 2))}</pre>`);
      mostrarSim($("#sim-res", g), s.tipo, { ...s.resultado, simulacao_id: s.id, hash: s.hash });
    })));
    $$("[data-an-id]", c).forEach((b) => b.addEventListener("click", () => { ir("achados"); setTimeout(() => RENDER.achados($("#conteudo"), Number(b.dataset.anId)), 50); }));
  };

  // ---------------- empresas
  RENDER.empresas = async (c) => {
    await carregarEmpresas(); preencherEmpresas();
    const e = empresaAtual();
    c.innerHTML = `<div class="grade g2"><div class="cartao"><h2>Empresas</h2>${S.empresas.length ? `<table class="tab"><tr><th>Razão social</th><th>CNPJ</th><th>Regime</th><th>UF</th></tr>
      ${S.empresas.map((x) => `<tr class="clic" data-emp="${x.id}"><td>${esc(x.razao_social)}</td><td class="mono">${esc(x.cnpj)}</td><td>${esc(REGIMES[x.regime])}</td><td>${esc(x.uf || "")}</td></tr>`).join("")}</table>` : '<div class="vazio">Nenhuma empresa.</div>'}</div>
      <div class="cartao"><h2>${e ? "Editar " + esc(e.razao_social) : "Nova empresa"} <span class="acoes">${e ? '<button class="btn peq" id="b-nova">+ Nova</button>' : ""}</span></h2>${formEmpresa(e)}</div></div>
      ${e ? '<div class="cartao"><h2>Mapeamento de contas (contabilidade × fiscal)</h2><div id="mapa"></div></div>' : ""}`;
    $$("[data-emp]", c).forEach((tr) => tr.addEventListener("click", () => { S.empresa = Number(tr.dataset.emp); S.gravarEmpresa(S.empresa); preencherEmpresas(); RENDER.empresas(c); }));
    $("#b-nova")?.addEventListener("click", () => { $(".cartao:nth-child(2)", c).innerHTML = "<h2>Nova empresa</h2>" + formEmpresa(null); ligarForm(null); });
    ligarForm(e);
    if (e) mapaContas(e);
    function ligarForm(emp) {
      $("#f-emp", c)?.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const f = Object.fromEntries(new FormData(ev.target).entries());
        f.contribuinte_ipi = f.contribuinte_ipi ? 1 : 0;
        tentar(async () => {
          const r = emp ? await api("PUT", "/api/empresas/" + emp.id, f) : await api("POST", "/api/empresas", f);
          S.empresa = r.id; S.gravarEmpresa(r.id); aviso("Empresa salva"); RENDER.empresas(c);
        });
      });
    }
  };
  function formEmpresa(e) {
    const v = (k) => esc(e?.[k] ?? "");
    return `<form id="f-emp" class="form"><div><label>CNPJ</label><input name="cnpj" value="${v("cnpj")}" ${e ? "disabled" : "required"}></div>
      <div class="larga"><label>Razão social</label><input name="razao_social" value="${v("razao_social")}" required></div>
      <div><label>Regime</label><select name="regime">${Object.entries(REGIMES).map(([k, n]) => `<option value="${k}" ${e?.regime === k ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <div><label>UF</label><input name="uf" maxlength="2" value="${v("uf")}"></div><div><label>Município (cód. IBGE)</label><input name="municipio" value="${v("municipio")}"></div>
      <div><label>CNAE</label><input name="cnae" value="${v("cnae")}"></div>
      <div><label>Anexo padrão (Simples)</label><select name="anexo_padrao"><option value="">—</option>${["I", "II", "III", "IV", "V"].map((a) => `<option ${e?.anexo_padrao === a ? "selected" : ""}>${a}</option>`).join("")}</select></div>
      <div><label>Atividade (Presumido)</label><input name="atividade_presumido" value="${v("atividade_presumido")}" placeholder="comercio, servicos…"></div>
      <div><label style="display:flex;gap:6px;align-items:center"><input type="checkbox" name="contribuinte_ipi" style="width:auto" ${e?.contribuinte_ipi ? "checked" : ""}> Contribuinte do IPI</label></div>
      <div class="larga"><button class="btn primario" ${pode("empresas_editar") ? "" : "disabled"}>Salvar</button></div></form>`;
  }
  async function mapaContas(e) {
    const contas = await api("GET", `/api/empresas/${e.id}/contas`);
    const grupos = ["", "RECEITA_BRUTA", "ICMS_A_RECOLHER", "PIS_A_RECOLHER", "COFINS_A_RECOLHER", "ICMS_A_RECUPERAR"];
    $("#mapa").innerHTML = contas.length ? `<table class="tab"><tr><th>Conta</th><th>Descrição</th><th>Grupo fiscal</th></tr>${contas.map((x) => `<tr><td class="mono">${esc(x.conta)}</td><td>${esc(x.descricao || "")}</td>
      <td><select data-conta="${esc(x.conta)}">${grupos.map((g) => `<option value="${g}" ${x.grupo === g ? "selected" : ""}>${g || "—"}</option>`).join("")}</select></td></tr>`).join("")}</table>
      <button class="btn primario" id="b-mapa" style="margin-top:10px">Salvar mapeamento</button>` : '<div class="vazio">Importe a ECD ou um balancete para mapear as contas.</div>';
    $("#b-mapa")?.addEventListener("click", () => tentar(async () => {
      const m = {}; $$("[data-conta]").forEach((s) => { m[s.dataset.conta] = s.value; });
      await api("PUT", `/api/empresas/${e.id}/contas`, m); aviso("Mapeamento salvo");
    }));
  }

  // ---------------- regras
  RENDER.regras = async (c) => {
    const regras = await api("GET", "/api/regras");
    const tributos = [...new Set(regras.map((r) => r.tributo))].sort();
    c.innerHTML = `<div class="cartao"><h2>Regras vigentes e históricas <span class="acoes">${pode("regras_editar") ? '<button class="btn peq primario" id="b-nova-regra">+ Nova regra / vigência</button>' : ""}</span></h2>
      <p class="suave peq">Cada regra tem tributo, ente, regime, vigência, fundamentação legal, critério e fórmula. Alterar gera nova versão com motivo obrigatório; o cálculo usa a regra vigente na data da operação. O sistema não pré-carrega alíquotas internas de ICMS nem alíquotas de referência de IBS/CBS: elas devem ser cadastradas a partir da legislação.</p>
      <div class="form" style="margin-bottom:10px"><div><label>Tributo</label><select id="r-trib"><option value="">Todos</option>${tributos.map((t) => `<option>${esc(t)}</option>`).join("")}</select></div><div class="larga" style="grid-column:span 2"><label>Buscar</label><input id="r-busca"></div></div>
      <div id="r-tab"></div></div>`;
    const desenhar = () => {
      const t = $("#r-trib").value, b = $("#r-busca").value.toLowerCase();
      const l = regras.filter((r) => (!t || r.tributo === t) && (!b || JSON.stringify(r).toLowerCase().includes(b)));
      $("#r-tab").innerHTML = `<div class="rolagem"><table class="tab"><tr><th>Código</th><th>Tributo</th><th>Ente</th><th>Regime</th><th>Vigência</th><th>v.</th><th>Fundamentação</th></tr>
        ${l.map((r) => `<tr class="clic" data-regra="${r.id}"><td class="mono">${esc(r.codigo)} ${r.situacao === "validar" ? selo("AMARELO", "validar") : ""}</td><td>${esc(r.tributo)}</td><td>${esc(r.ente)}${r.uf ? "/" + esc(r.uf) : ""}</td><td>${esc(r.regime)}</td>
          <td>${esc(r.vigencia_inicio)} → ${esc(r.vigencia_fim || "…")}</td><td>${r.versao}</td><td class="peq">${esc(r.fundamento).slice(0, 160)}</td></tr>`).join("")}</table></div>`;
      $$("[data-regra]", c).forEach((tr) => tr.addEventListener("click", () => abrirRegra(regras.find((r) => r.id === Number(tr.dataset.regra)), () => RENDER.regras(c))));
    };
    $("#r-trib").addEventListener("change", desenhar); $("#r-busca").addEventListener("input", desenhar); desenhar();
    $("#b-nova-regra")?.addEventListener("click", () => editarRegra(null, () => RENDER.regras(c)));
  };
  async function abrirRegra(r, aoMudar) {
    const hist = await api("GET", "/api/regras/historico/" + encodeURIComponent(r.codigo));
    const g = gaveta(`<h2 class="mono">${esc(r.codigo)} <span class="selo neutro">v${r.versao}</span></h2><p>${esc(r.descricao || "")}</p>
      <div class="ficha"><div>Tributo / ente</div><div>${esc(r.tributo)} · ${esc(r.ente)} ${esc(r.uf || "")} ${esc(r.municipio || "")}</div><div>Regime</div><div>${esc(r.regime)}</div>
      <div>Vigência</div><div>${esc(r.vigencia_inicio)} → ${esc(r.vigencia_fim || "indeterminada")}</div><div>Fundamentação legal</div><div>${esc(r.fundamento)}</div>
      <div>Critério de aplicação</div><div class="mono">${esc(r.criterio || "—")}</div><div>Fórmula de cálculo</div><div class="mono">${esc(r.formula || "—")}</div>
      <div>Situação</div><div>${esc(r.situacao)}</div><div>Hash</div><div class="mono">${esc(r.hash.slice(0, 24))}…</div></div>
      <h3>Parâmetros</h3><pre class="json">${esc(JSON.stringify(r.parametros, null, 2))}</pre>
      <h3>Histórico de alterações</h3><table class="tab"><tr><th>v.</th><th>Vigência</th><th>Ativa</th><th>Por</th><th>Em</th><th>Motivo</th></tr>${hist.map((h) => `<tr><td>${h.versao}</td><td>${esc(h.vigencia_inicio)}</td><td>${h.ativo ? "sim" : "não"}</td><td>${esc(h.criado_por)}</td><td>${esc(h.criado_em)}</td><td>${esc(h.motivo || "")}</td></tr>`).join("")}</table>
      ${pode("regras_editar") ? '<div class="linha" style="margin-top:12px"><button class="btn primario" id="b-edit-regra">Alterar (nova versão)</button></div>' : ""}`);
    $("#b-edit-regra", g)?.addEventListener("click", () => editarRegra(r, aoMudar));
  }
  function editarRegra(r, aoMudar) {
    const base = r || { codigo: "", tributo: "", ente: "ESTADUAL", uf: "", municipio: "", regime: "TODOS", vigencia_inicio: new Date().toISOString().slice(0, 10), vigencia_fim: "", fundamento: "", descricao: "", criterio: "", formula: "", parametros: {}, situacao: "vigente" };
    const v = (k) => esc(base[k] ?? "");
    const g = gaveta(`<h2>${r ? "Alterar " + esc(r.codigo) : "Nova regra ou nova vigência"}</h2><form id="f-regra" class="form">
      <div><label>Código</label><input name="codigo" value="${v("codigo")}" ${r ? "disabled" : "required"}></div><div><label>Tributo</label><input name="tributo" value="${v("tributo")}" required></div>
      <div><label>Ente</label><select name="ente">${["FEDERAL", "ESTADUAL", "MUNICIPAL", "NACIONAL"].map((x) => `<option ${base.ente === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
      <div><label>UF</label><input name="uf" value="${v("uf")}"></div><div><label>Município</label><input name="municipio" value="${v("municipio")}"></div><div><label>Regime</label><input name="regime" value="${v("regime")}"></div>
      <div><label>Vigência inicial</label><input type="date" name="vigencia_inicio" value="${v("vigencia_inicio")}" required></div><div><label>Vigência final</label><input type="date" name="vigencia_fim" value="${v("vigencia_fim")}"></div>
      <div><label>Situação</label><select name="situacao">${["vigente", "validar"].map((x) => `<option ${base.situacao === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
      <div class="larga"><label>Fundamentação legal (obrigatória)</label><input name="fundamento" value="${v("fundamento")}" required></div>
      <div class="larga"><label>Descrição</label><input name="descricao" value="${v("descricao")}"></div>
      <div class="larga"><label>Critério de aplicação (expressão)</label><input name="criterio" class="mono" value="${v("criterio")}"></div>
      <div class="larga"><label>Fórmula de cálculo (expressão)</label><input name="formula" class="mono" value="${v("formula")}"></div>
      <div class="larga"><label>Parâmetros (JSON)</label><textarea name="parametros" style="min-height:200px">${esc(JSON.stringify(base.parametros, null, 2))}</textarea></div>
      <div class="larga"><label>Motivo da alteração (histórico)</label><input name="motivo" required></div>
      <div class="larga"><button class="btn primario">Salvar</button></div></form>`);
    $("#f-regra", g).addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = Object.fromEntries(new FormData(ev.target).entries());
      tentar(async () => {
        f.parametros = JSON.parse(f.parametros || "{}");
        for (const k of ["vigencia_fim", "uf", "municipio", "criterio", "formula"]) if (!f[k]) f[k] = null;
        const motivo = f.motivo; delete f.motivo;
        if (r) { delete f.codigo; await api("PUT", "/api/regras/" + r.id, { mudancas: f, motivo }); }
        else await api("POST", "/api/regras", { regra: f, motivo });
        fecharGaveta(); aviso("Regra salva com nova versão"); aoMudar();
      });
    });
  }

  // ---------------- administração
  RENDER.admin = async (c) => {
    c.innerHTML = `<div class="grade g2"><div class="cartao"><h2>Minha senha</h2><form id="f-senha" class="form"><div><label>Senha atual</label><input type="password" name="atual" required></div>
      <div><label>Nova senha (mín. 10)</label><input type="password" name="nova" minlength="10" required></div><div><button class="btn">Trocar</button></div></form></div>
      <div class="cartao"><h2>Proteção de dados (LGPD)</h2><p class="suave peq">CPFs são mascarados em relatórios e trilha. Arquivos e banco ficam em pasta com acesso restrito ao processo; backups podem ser cifrados (variável TIP_BACKUP_KEY).</p>
      ${pode("lgpd") && S.empresa ? `<div class="linha"><button class="btn" id="b-anon">Anonimizar participantes PF da empresa</button><button class="btn perigo" id="b-elim">Eliminar dados importados da empresa</button></div>` : '<p class="suave">Sem permissão.</p>'}</div></div>
      ${pode("usuarios") ? '<div class="cartao"><h2>Usuários e permissões</h2><div id="ad-users"></div></div>' : ""}
      ${pode("backup") ? '<div class="cartao"><h2>Backup e recuperação <span class="acoes"><button class="btn peq primario" id="b-bk">Gerar backup agora</button></span></h2><div id="ad-bk"></div></div>' : ""}
      ${pode("auditoria_ver") ? '<div class="cartao"><h2>Trilha de auditoria</h2><div id="ad-aud"></div></div>' : ""}`;
    $("#f-senha").addEventListener("submit", (e) => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); tentar(async () => { await api("POST", "/api/me/senha", f); aviso("Senha alterada; entre novamente"); sair(); }); });
    $("#b-anon")?.addEventListener("click", () => { if (confirm("Anonimizar nomes e CPFs de participantes desta empresa?")) tentar(async () => { const r = await api("POST", `/api/empresas/${S.empresa}/anonimizar`); aviso(`${r.documentos_anonimizados} documento(s) anonimizado(s)`); }); });
    $("#b-elim")?.addEventListener("click", () => { if (confirm("Eliminar TODAS as importações e análises desta empresa? Observe o prazo legal de guarda dos documentos fiscais.")) tentar(async () => { await api("DELETE", `/api/empresas/${S.empresa}/dados`); aviso("Dados eliminados"); }); });
    if (pode("usuarios")) {
      const us = await api("GET", "/api/usuarios");
      if (!$("#ad-users")) return;
      $("#ad-users").innerHTML = `<table class="tab"><tr><th>Login</th><th>Nome</th><th>Papel</th><th>Ativo</th><th>Último acesso</th></tr>${us.map((u) => `<tr><td>${esc(u.login)}</td><td>${esc(u.nome)}</td>
        <td><select data-papel="${u.id}">${["admin", "auditor", "analista", "leitura"].map((p) => `<option ${u.papel === p ? "selected" : ""}>${p}</option>`).join("")}</select></td>
        <td><input type="checkbox" data-ativo="${u.id}" style="width:auto" ${u.ativo ? "checked" : ""}></td><td>${esc(u.ultimo_login || "")}</td></tr>`).join("")}</table>
        <form id="f-user" class="form" style="margin-top:12px"><div><label>Login</label><input name="login" required></div><div><label>Nome</label><input name="nome" required></div>
        <div><label>Senha inicial</label><input name="senha" type="password" minlength="10" required></div><div><label>Papel</label><select name="papel"><option>analista</option><option>auditor</option><option>leitura</option><option>admin</option></select></div>
        <div><button class="btn primario">Criar usuário</button></div></form>
        <p class="suave peq">admin: tudo · auditor: importar, analisar, validar achados, cadastros · analista: importar, simular, analisar · leitura: consulta.</p>`;
      $$("[data-papel]").forEach((s) => s.addEventListener("change", () => tentar(() => api("PUT", "/api/usuarios/" + s.dataset.papel, { papel: s.value }).then(() => aviso("Papel alterado")))));
      $$("[data-ativo]").forEach((s) => s.addEventListener("change", () => tentar(() => api("PUT", "/api/usuarios/" + s.dataset.ativo, { ativo: s.checked ? 1 : 0 }).then(() => aviso("Usuário atualizado")))));
      $("#f-user").addEventListener("submit", (e) => { e.preventDefault(); tentar(async () => { await api("POST", "/api/usuarios", Object.fromEntries(new FormData(e.target))); aviso("Usuário criado"); RENDER.admin(c); }); });
    }
    if (pode("backup")) {
      const lbk = async () => {
        const bks = await api("GET", "/api/backups");
        if (!$("#ad-bk")) return;   // usuário já saiu da tela
        $("#ad-bk").innerHTML = bks.length ? `<table class="tab"><tr><th>Arquivo</th><th class="num">Tamanho</th><th></th></tr>${bks.map((b) => `<tr><td class="mono">${esc(b.arquivo)}</td><td class="num">${(b.tamanho / 1024).toFixed(0)} KB</td><td><button class="btn peq perigo" data-rest="${esc(b.arquivo)}">Restaurar</button></td></tr>`).join("")}</table>` : '<div class="vazio">Nenhum backup.</div>';
        $$("[data-rest]").forEach((b) => b.addEventListener("click", () => { if (confirm("Restaurar este backup? O banco atual será guardado como .antes-restauracao.")) tentar(async () => { await api("POST", "/api/restaurar", { arquivo: b.dataset.rest }); aviso("Backup restaurado"); }); }));
      };
      $("#b-bk").addEventListener("click", () => tentar(async () => { const r = await api("POST", "/api/backup"); aviso("Backup " + r.arquivo + " (SHA-256 " + r.sha256.slice(0, 12) + "…)"); lbk(); }));
      lbk();
    }
    if (pode("auditoria_ver")) {
      const a = await api("GET", "/api/auditoria");
      if (!$("#ad-aud")) return;
      $("#ad-aud").innerHTML = `<div class="alerta ${a.verificacao.integra ? "VERDE" : "VERMELHO"}">${a.verificacao.integra ? `Cadeia íntegra: ${a.verificacao.registros} registro(s) encadeados por hash.` : `Cadeia QUEBRADA no registro #${a.verificacao.quebra_no_id}: possível adulteração.`}</div>
        <div class="rolagem" style="max-height:420px"><table class="tab"><tr><th>#</th><th>Quando</th><th>Usuário</th><th>Ação</th><th>Objeto</th><th>Detalhe</th></tr>${a.trilha.map((t) => `<tr><td>${t.id}</td><td class="peq">${esc(t.criado_em)}</td><td>${esc(t.usuario)}</td><td>${esc(t.acao)}</td><td class="mono">${esc(t.objeto || "")}</td><td class="mono">${esc(JSON.stringify(t.detalhe)).slice(0, 140)}</td></tr>`).join("")}</table></div>`;
    }
  };

  iniciar();
})();
