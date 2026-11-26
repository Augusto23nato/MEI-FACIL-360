"""Execução da análise (créditos + cruzamentos + oportunidades) e validação dos achados."""
from __future__ import annotations

import hashlib
import json
import traceback

from ..db import agora, js, row
from ..seguranca import registrar
from . import cruzamentos as cz
from .achados import STATUS, Achados

VERIFICACOES = [
    ("Integridade e duplicidades", lambda dd, A, m: cz.integridade(dd, A)),
    ("XML × EFD ICMS/IPI", lambda dd, A, m: cz.xml_x_escrituracao(dd, A, "efd_icms_ipi", ("valor_total", "vbc_icms", "v_icms", "v_st", "v_ipi"), "ICMS")),
    ("XML × EFD-Contribuições", lambda dd, A, m: cz.xml_x_escrituracao(dd, A, "efd_contribuicoes", ("valor_total", "v_pis", "v_cofins"), "PIS/COFINS")
     if dd.emp["regime"] != "SIMPLES_NACIONAL" else None),
    ("Créditos (PIS/COFINS, ICMS, IPI)", lambda dd, A, m: cz.creditos(dd, A, m)),
    ("Apuração do ICMS (E110)", lambda dd, A, m: cz.apuracao_icms(dd, A)),
    ("Apuração de PIS/COFINS (M200/M600)", lambda dd, A, m: cz.apuracao_contribuicoes(dd, A)),
    ("Apuração × declarações e pagamentos", lambda dd, A, m: cz.apuracao_x_declaracoes(dd, A)),
    ("Simples Nacional (PGDAS-D)", lambda dd, A, m: cz.simples(dd, A, m) if dd.emp["regime"] == "SIMPLES_NACIONAL" else None),
    ("Alíquotas, bases e tributação", lambda dd, A, m: cz.aliquotas(dd, A, m)),
    ("Contabilidade × fiscal", lambda dd, A, m: cz.contabil_x_fiscal(dd, A)),
    ("Comparação entre sistemas", lambda dd, A, m: cz.sistemas(dd, A)),
    ("Retenções", lambda dd, A, m: cz.retencoes(dd, A)),
    ("Reforma Tributária (IBS/CBS)", lambda dd, A, m: cz.reforma(dd, A)),
]

COLS = ("categoria", "tipo", "cor", "tributo", "periodo", "titulo", "descricao", "valor", "confianca", "origem", "fundamento",
        "memoria", "documentacao", "procedimento", "referencia", "status")


def executar(con, motor, empresa_id: int, ini: str, fim: str, usuario: dict) -> dict:
    emp = row(con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone())
    if not emp:
        raise ValueError("empresa inexistente")
    if ini > fim:
        raise ValueError("período inicial maior que o final")
    dd = cz.Dados(con, emp, ini, fim)
    A = Achados()
    log = []
    for nome, fn in VERIFICACOES:
        n0 = len(A.lista)
        try:
            fn(dd, A, motor)
            log.append({"verificacao": nome, "achados": len(A.lista) - n0, "status": "ok"})
        except Exception as e:  # noqa: BLE001 — uma verificação com problema não derruba as demais
            log.append({"verificacao": nome, "status": "erro", "erro": str(e)})
            A.add(categoria="sistema", tipo="VERIFICACAO_FALHOU", cor="AMARELO", titulo=f"Verificação não concluída: {nome}",
                  descricao=f"{type(e).__name__}: {e}", confianca="alta",
                  memoria=traceback.format_exc().splitlines()[-6:])
    regras = sorted({f"{r['codigo']}@{r['versao']}" for r in motor.listar() if r["ativo"]})
    resumo = {**A.resumo(), "verificacoes": log,
              "fontes": {f: len(v) for f, v in dd.fontes.items()},
              "apuracoes": len(dd.apur), "saldos": len(dd.saldos), "empresa": {"cnpj": emp["cnpj"], "razao_social": emp["razao_social"],
                                                                                "regime": emp["regime"]}}
    h = hashlib.sha256(js({"resumo": resumo, "achados": A.lista}).encode()).hexdigest()
    cur = con.execute("INSERT INTO analises (empresa_id, periodo_ini, periodo_fim, regime, resumo, regras_usadas, usuario_id, criado_em, hash)"
                      " VALUES (?,?,?,?,?,?,?,?,?)", (empresa_id, ini, fim, emp["regime"], js(resumo), js(regras), usuario.get("id"), agora(), h))
    aid = cur.lastrowid
    for a in A.lista:
        con.execute(f"INSERT INTO achados (analise_id, {', '.join(COLS)}) VALUES (?,{','.join('?' * len(COLS))})",
                    (aid, *[js(a[c]) if isinstance(a[c], (dict, list)) else a[c] for c in COLS]))
    con.commit()
    registrar(con, usuario.get("login"), "analisar", f"analise:{aid}",
              {"empresa_id": empresa_id, "periodo": [ini, fim], "hash": h, "achados": len(A.lista)})
    return obter(con, aid)


def obter(con, analise_id: int, cor: str | None = None) -> dict:
    a = row(con.execute("SELECT * FROM analises WHERE id=?", (analise_id,)).fetchone())
    if not a:
        raise LookupError("análise inexistente")
    sql, args = "SELECT * FROM achados WHERE analise_id=?", [analise_id]
    if cor:
        sql += " AND cor=?"
        args.append(cor)
    ordem = "CASE cor WHEN 'VERMELHO' THEN 0 WHEN 'AZUL' THEN 1 WHEN 'AMARELO' THEN 2 ELSE 3 END, CAST(valor AS REAL) DESC"
    a["achados"] = [row(r) for r in con.execute(sql + " ORDER BY " + ordem, args)]
    return a


def validar(con, achado_id: int, novo_status: str, justificativa: str, documentos: str, usuario: dict) -> dict:
    """Workflow de validação: pendente → validado_documental → validado_juridico (ou descartado).
    Exige justificativa e, para validações, referência aos documentos examinados."""
    if novo_status not in STATUS or novo_status == "pendente_validacao":
        raise ValueError(f"status inválido; use {', '.join(STATUS[1:])}")
    a = row(con.execute("SELECT * FROM achados WHERE id=?", (achado_id,)).fetchone())
    if not a:
        raise LookupError("achado inexistente")
    if not justificativa or len(justificativa.strip()) < 10:
        raise ValueError("justificativa obrigatória (mínimo 10 caracteres)")
    if novo_status.startswith("validado") and not (documentos or "").strip():
        raise ValueError("informe os documentos examinados para validar")
    if novo_status == "validado_juridico" and a["status"] != "validado_documental":
        raise ValueError("a validação jurídica exige validação documental prévia")
    hist = a["validacao"] or []
    hist.append({"de": a["status"], "para": novo_status, "por": usuario["login"], "em": agora(),
                 "justificativa": justificativa, "documentos": documentos})
    con.execute("UPDATE achados SET status=?, validacao=? WHERE id=?", (novo_status, json.dumps(hist, ensure_ascii=False), achado_id))
    con.commit()
    registrar(con, usuario["login"], "achado.validar", f"achado:{achado_id}", {"de": a["status"], "para": novo_status})
    return row(con.execute("SELECT * FROM achados WHERE id=?", (achado_id,)).fetchone())
