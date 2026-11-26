"""Orquestração da importação → modelo canônico no banco."""
from __future__ import annotations

from ..db import agora, js
from ..seguranca import registrar
from . import base, sped, tabular, xml_fiscal
from .base import ArquivoInvalido, Lote

DOC_COLS = ("fonte", "chave", "modelo", "operacao", "numero", "serie", "data_emissao", "periodo", "situacao", "cnpj_emit",
            "cnpj_dest", "uf_emit", "uf_dest", "nome_part", "crt_emit", "valor_total", "vbc_icms", "v_icms", "v_st", "v_ipi",
            "v_pis", "v_cofins", "v_iss", "v_ibs", "v_cbs")
ITEM_COLS = ("n_item", "codigo", "descricao", "ncm", "cfop", "cst_icms", "orig", "vprod", "vdesc", "vfrete", "vseg", "voutro",
             "vbc_icms", "p_icms", "v_icms", "vbc_st", "v_st", "cst_ipi", "p_ipi", "v_ipi", "cst_pis", "vbc_pis", "p_pis",
             "v_pis", "cst_cofins", "vbc_cofins", "p_cofins", "v_cofins", "p_iss", "v_iss", "p_cred_sn", "v_cred_sn",
             "cst_ibscbs", "v_ibs", "v_cbs")


def _parse(nome: str, dados: bytes, tipo: str, empresa: dict, opcoes: dict) -> list[Lote]:
    cnpj = empresa["cnpj"]
    if tipo == "auto":
        tipo = base.detectar(nome, dados)
    if tipo == "zip":
        lotes = []
        for n, b in base.abrir_zip(dados):
            try:
                base.validar_basico(n, b)
                lotes += _parse(n, b, "auto", empresa, opcoes)
            except ArquivoInvalido as e:
                lt = Lote(tipo="zip", fonte="xml")
                lt.aviso(f"{n}: {e}")
                lotes.append(lt)
        return lotes
    if tipo == "nfe":
        return [xml_fiscal.ler_nfe(dados, cnpj)]
    if tipo == "evento_nfe":
        ev = xml_fiscal.ler_evento_nfe(dados)
        lt = Lote(tipo="evento_nfe", fonte="xml")
        if ev:
            lt.documentos = []
            lt.mensagens.append({"nivel": "info", "texto": f"evento de cancelamento da NF-e {ev['chave']}"})
            lt.cancelamentos = [ev["chave"]]  # type: ignore[attr-defined]
        else:
            lt.aviso("evento NF-e não tratado (apenas cancelamento 110111 altera a situação)")
        return [lt]
    if tipo == "cte":
        return [xml_fiscal.ler_cte(dados, cnpj)]
    if tipo == "nfse":
        return [xml_fiscal.ler_nfse(dados, cnpj)]
    if tipo == "efd_icms_ipi":
        return [sped.ler_efd(dados, contribuicoes=False)]
    if tipo == "efd_contribuicoes":
        return [sped.ler_efd(dados, contribuicoes=True)]
    if tipo == "ecd":
        return [sped.ler_ecd(dados)]
    if tipo == "ecf":
        return [sped.ler_ecf(dados)]
    if tipo in ("tabular", "json") or tipo.startswith("planilha"):
        return [tabular.ler(nome, dados, opcoes.get("tipo_planilha") or "documentos", opcoes.get("perfil") or "generico", cnpj)]
    raise ArquivoInvalido(f"tipo não suportado: {tipo}")


def importar(con, empresa_id: int, nome: str, dados: bytes, usuario: dict, tipo: str = "auto", opcoes: dict | None = None) -> dict:
    opcoes = opcoes or {}
    emp = con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone()
    if not emp:
        raise ArquivoInvalido("empresa inexistente")
    base.validar_basico(nome, dados)
    h = base.sha256(dados)
    dup = con.execute("SELECT id, criado_em FROM importacoes WHERE empresa_id=? AND sha256=? AND status='concluida'",
                      (empresa_id, h)).fetchone()
    if dup and not opcoes.get("forcar"):
        return {"status": "duplicado", "importacao_id": dup["id"],
                "mensagens": [{"nivel": "aviso", "texto": f"arquivo idêntico já importado em {dup['criado_em']} (id {dup['id']})"}]}
    lotes = _parse(nome, dados, tipo, dict(emp), opcoes)
    msgs = [m for lt in lotes for m in lt.mensagens]
    for lt in lotes:
        if lt.cnpj and lt.cnpj[:8] != emp["cnpj"][:8] and lt.tipo not in ("nfe", "cte", "nfse"):
            raise ArquivoInvalido(f"arquivo pertence ao CNPJ {lt.cnpj}, não à empresa {emp['cnpj']}")
    erros = [m for m in msgs if m["nivel"] == "erro"]
    status = "rejeitada" if erros and not any(lt.documentos or lt.apuracoes or lt.saldos for lt in lotes) else "concluida"
    pers = [p for lt in lotes for p in (lt.periodo_ini, lt.periodo_fim) if p]
    tipo_real = lotes[0].tipo if len({lt.tipo for lt in lotes}) == 1 else "lote"
    fonte = lotes[0].fonte if lotes else "?"
    cur = con.execute("INSERT INTO importacoes (empresa_id, tipo, fonte, nome_arquivo, sha256, tamanho, status, mensagens,"
                      " periodo_ini, periodo_fim, usuario_id, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (empresa_id, tipo_real, fonte, nome, h, len(dados), status, js(msgs[:500]),
                       min(pers) if pers else None, max(pers) if pers else None, usuario.get("id"), agora()))
    imp_id = cur.lastrowid
    n = 0
    if status == "concluida":
        for lt in lotes:
            for d in lt.documentos:
                vals = [d.get(c) for c in DOC_COLS]
                c2 = con.execute(f"INSERT INTO documentos (importacao_id, empresa_id, {', '.join(DOC_COLS)}, extra) "
                                 f"VALUES (?,?,{','.join('?' * len(DOC_COLS))},?)",
                                 (imp_id, empresa_id, *vals, js({**d.get("extra", {}), **({"c190": d["c190"]} if d.get("c190") else {})})))
                for it in d.get("itens", []):
                    con.execute(f"INSERT INTO itens (documento_id, {', '.join(ITEM_COLS)}, extra) VALUES (?,{','.join('?' * len(ITEM_COLS))},?)",
                                (c2.lastrowid, *[it.get(c) for c in ITEM_COLS], js(it.get("extra", {}))))
                n += 1
            for a in lt.apuracoes:
                campo = a["campo"] + (f"#{a['codigo_receita']}" if a.get("codigo_receita") else "")
                con.execute("INSERT INTO apuracoes (importacao_id, empresa_id, fonte, tributo, periodo, campo, valor) VALUES (?,?,?,?,?,?,?)",
                            (imp_id, empresa_id, lt.fonte, a["tributo"], a["periodo"] or "", campo, a["valor"]))
                n += 1
            for sd in lt.saldos:
                con.execute("INSERT INTO saldos_contabeis (importacao_id, empresa_id, fonte, periodo, conta, descricao, saldo_ini,"
                            " debitos, creditos, saldo_fim) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (imp_id, empresa_id, lt.fonte, sd["periodo"] or "", sd["conta"], sd.get("descricao"),
                             sd["saldo_ini"], sd["debitos"], sd["creditos"], sd["saldo_fim"]))
                n += 1
            for chave in getattr(lt, "cancelamentos", []):
                con.execute("UPDATE documentos SET situacao='cancelada' WHERE empresa_id=? AND chave=? AND fonte='xml'",
                            (empresa_id, chave))
                con.execute("INSERT INTO apuracoes (importacao_id, empresa_id, fonte, tributo, periodo, campo, valor) "
                            "VALUES (?,?,?,?,?,?,?)", (imp_id, empresa_id, "xml", "EVENTO", "", "cancelamento", chave))
        con.execute("UPDATE importacoes SET registros=? WHERE id=?", (n, imp_id))
    con.commit()
    registrar(con, usuario.get("login"), "importar", f"importacao:{imp_id}",
              {"arquivo": nome, "tipo": tipo_real, "sha256": h, "registros": n, "status": status})
    return {"status": status, "importacao_id": imp_id, "tipo": tipo_real, "registros": n, "sha256": h,
            "periodo": [min(pers) if pers else None, max(pers) if pers else None], "mensagens": msgs[:200]}
