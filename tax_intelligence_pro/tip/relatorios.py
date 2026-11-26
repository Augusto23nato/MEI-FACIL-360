"""Relatórios técnicos de auditoria (HTML imprimível e CSV)."""
from __future__ import annotations

import csv
import html
import io

from .num import D, brl, pct
from .seguranca import mascarar

COR_HEX = {"VERDE": "#1a7f4b", "AMARELO": "#b7791f", "VERMELHO": "#c53030", "AZUL": "#2b6cb0"}
ROT = {"VERDE": "Conciliado", "AMARELO": "Requer análise", "VERMELHO": "Inconsistência relevante", "AZUL": "Oportunidade"}


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def html_analise(analise: dict, usuario: dict) -> str:
    a = mascarar(analise)
    r = a["resumo"]
    emp = r["empresa"]
    linhas = []
    for x in a["achados"]:
        mem = "".join(f"<li>{_e(m)}</li>" for m in (x["memoria"] or [])[:40])
        docs = (x["origem"] or {}).get("documentos") or []
        orig = "".join(f"<li>{_e(d.get('fonte'))} · nº {_e(d.get('numero'))} · {_e(d.get('data'))} · {_e(d.get('chave') or '')}</li>"
                       for d in docs[:15])
        extra = {k: v for k, v in (x["origem"] or {}).items() if k != "documentos"}
        linhas.append(f"""
<section class="achado" style="border-left-color:{COR_HEX[x['cor']]}">
  <div class="cab"><span class="tag" style="background:{COR_HEX[x['cor']]}">{ROT[x['cor']]}</span>
  <strong>#{x['id']} {_e(x['titulo'])}</strong><span class="valor">{brl(x['valor'])}</span></div>
  <p>{_e(x['descricao'])}</p>
  <table>
   <tr><th>Tributo / período</th><td>{_e(x['tributo'] or '—')} · {_e(x['periodo'] or '—')}</td></tr>
   <tr><th>a) Origem da informação</th><td>{_e(extra) if extra else ''}<ul>{orig}</ul>{'<em>+ ' + str(len(docs) - 15) + ' documento(s)</em>' if len(docs) > 15 else ''}</td></tr>
   <tr><th>b) Fundamentação legal</th><td>{_e(x['fundamento'] or '—')}</td></tr>
   <tr><th>c) Memória de cálculo</th><td><ul>{mem}</ul></td></tr>
   <tr><th>d) Valor estimado</th><td>{brl(x['valor'])}</td></tr>
   <tr><th>e) Grau de confiabilidade</th><td>{_e(x['confianca'])}</td></tr>
   <tr><th>f) Documentação necessária</th><td>{_e(x['documentacao'] or '—')}</td></tr>
   <tr><th>g) Procedimento de validação</th><td>{_e(x['procedimento'])}</td></tr>
   <tr><th>Status</th><td>{_e(x['status'])}</td></tr>
  </table>
</section>""")
    cores = "".join(f"<div class='kpi' style='border-top-color:{COR_HEX[c]}'><span>{ROT[c]}</span><b>{v['quantidade']}</b>"
                    f"<small>{brl(v['valor'])}</small></div>" for c, v in r["por_cor"].items())
    verif = "".join(f"<li>{_e(v['verificacao'])}: {v.get('achados', 0)} achado(s) — {v['status']}</li>" for v in r["verificacoes"])
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Relatório de auditoria tributária</title>
<style>
body{{font:13px/1.5 system-ui,sans-serif;color:#1a202c;max-width:1000px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0}} .sub{{color:#4a5568}} .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:16px 0}}
.kpi{{border:1px solid #e2e8f0;border-top:4px solid;padding:8px;border-radius:6px}} .kpi b{{display:block;font-size:22px}}
.achado{{border:1px solid #e2e8f0;border-left:5px solid;border-radius:6px;padding:10px 14px;margin:12px 0;page-break-inside:avoid}}
.cab{{display:flex;gap:8px;align-items:center}} .valor{{margin-left:auto;font-weight:600}}
.tag{{color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}} table{{width:100%;border-collapse:collapse}}
th{{text-align:left;width:220px;vertical-align:top;color:#4a5568;font-weight:500;padding:3px 8px 3px 0}} td{{padding:3px 0}}
ul{{margin:0;padding-left:18px}} .aviso{{background:#fffbea;border:1px solid #f6e05e;padding:10px;border-radius:6px}}
</style></head><body>
<h1>Relatório técnico de auditoria tributária</h1>
<div class="sub">{_e(emp['razao_social'])} · CNPJ {_e(emp['cnpj'])} · {_e(emp['regime'])} · períodos {_e(a['periodo_ini'])} a {_e(a['periodo_fim'])}<br>
Análise #{a['id']} gerada em {_e(a['criado_em'])} · emitido por {_e(usuario['nome'])} · hash {_e(a['hash'][:24])}…</div>
<div class="kpis">{cores}</div>
<p><b>Economia potencial estimada:</b> {brl(r['economia_potencial'])} &nbsp; · &nbsp; <b>Exposição a risco:</b> {brl(r['exposicao_risco'])}</p>
<div class="aviso"><b>Natureza do relatório.</b> Os valores são estimativas produzidas por regras parametrizadas e cruzamento de dados
importados. Nenhum crédito, restituição ou recuperação é definitivo sem validação documental e jurídica pelo profissional
responsável, à luz da legislação vigente na data de cada operação.</div>
<h2>Verificações executadas</h2><ul>{verif}</ul>
<h2>Achados ({len(a['achados'])})</h2>{''.join(linhas)}
<h2>Regras aplicadas</h2><p>{_e(', '.join(a.get('regras_usadas') or []))}</p>
</body></html>"""


def csv_analise(analise: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "cor", "categoria", "tipo", "tributo", "periodo", "titulo", "descricao", "valor", "confianca",
                "fundamento", "documentacao", "status"])
    for x in mascarar(analise["achados"]):
        w.writerow([x["id"], x["cor"], x["categoria"], x["tipo"], x["tributo"], x["periodo"], x["titulo"], x["descricao"],
                    str(D(x["valor"])).replace(".", ","), x["confianca"], x["fundamento"], x["documentacao"], x["status"]])
    return "﻿" + buf.getvalue()


def html_simulacao(sim: dict) -> str:
    r = sim["resultado"]
    mem = "".join(f"<li><b>{_e(p['titulo'])}</b>: {_e(p['detalhe'])}{' <small>[' + _e(p['regra']) + ']</small>' if p.get('regra') else ''}</li>"
                  for p in r.get("memoria", []))
    regras = "".join(f"<li>{_e(x['codigo'])} v{x['versao']} — {_e(x['fundamento'])}</li>" for x in r.get("regras_usadas", []))
    principais = {k: v for k, v in r.items() if isinstance(v, (str, int)) and k not in ("tipo",)}
    linhas = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in principais.items())
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Memória de cálculo</title>
<style>body{{font:13px/1.5 system-ui;max-width:900px;margin:24px auto;padding:0 16px}}th{{text-align:left;padding-right:12px;color:#4a5568}}</style>
</head><body><h1>Memória de cálculo — simulação #{sim['id']} ({_e(sim['tipo'])})</h1><p>{_e(sim['criado_em'])} · hash {_e(sim['hash'][:24])}…</p>
<table>{linhas}</table><h2>Passos</h2><ol>{mem}</ol><h2>Regras e fundamentação</h2><ul>{regras}</ul></body></html>"""


__all__ = ["html_analise", "csv_analise", "html_simulacao", "pct"]
