"""Leitores SPED: EFD ICMS/IPI, EFD-Contribuições, ECD e ECF (leitura genérica).

Layouts conforme os Guias Práticos da EFD ICMS/IPI e da EFD-Contribuições e o
Manual de Orientação do Leiaute da ECD (apenas os registros usados nos cruzamentos).
"""
from __future__ import annotations

from ..num import D, s
from .base import Lote, texto

L = {
    "0000_ICMS": "REG COD_VER COD_FIN DT_INI DT_FIN NOME CNPJ CPF UF IE COD_MUN IM SUFRAMA IND_PERFIL IND_ATIV",
    "0000_CONTRIB": "REG COD_VER TIPO_ESCRIT IND_SIT_ESP NUM_REC_ANTERIOR DT_INI DT_FIN NOME CNPJ UF COD_MUN SUFRAMA IND_NAT_PJ IND_ATIV",
    "0000_ECD": "REG LECD DT_INI DT_FIN NOME CNPJ UF IE COD_MUN IM IND_SIT_ESP",
    "0150": "REG COD_PART NOME COD_PAIS CNPJ CPF IE COD_MUN SUFRAMA END NUM COMPL BAIRRO",
    "0200": "REG COD_ITEM DESCR_ITEM COD_BARRA COD_ANT_ITEM UNID_INV TIPO_ITEM COD_NCM EX_IPI COD_GEN COD_LST ALIQ_ICMS CEST",
    "C100": "REG IND_OPER IND_EMIT COD_PART COD_MOD COD_SIT SER NUM_DOC CHV_NFE DT_DOC DT_E_S VL_DOC IND_PGTO VL_DESC "
            "VL_ABAT_NT VL_MERC IND_FRT VL_FRT VL_SEG VL_OUT_DA VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_IPI VL_PIS "
            "VL_COFINS VL_PIS_ST VL_COFINS_ST",
    "C170": "REG NUM_ITEM COD_ITEM DESCR_COMPL QTD UNID VL_ITEM VL_DESC IND_MOV CST_ICMS CFOP COD_NAT VL_BC_ICMS ALIQ_ICMS "
            "VL_ICMS VL_BC_ICMS_ST ALIQ_ST VL_ICMS_ST IND_APUR CST_IPI COD_ENQ VL_BC_IPI ALIQ_IPI VL_IPI CST_PIS VL_BC_PIS "
            "ALIQ_PIS QUANT_BC_PIS ALIQ_PIS_QUANT VL_PIS CST_COFINS VL_BC_COFINS ALIQ_COFINS QUANT_BC_COFINS "
            "ALIQ_COFINS_QUANT VL_COFINS COD_CTA VL_ABAT_NT",
    "C190": "REG CST_ICMS CFOP ALIQ_ICMS VL_OPR VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_RED_BC VL_IPI COD_OBS",
    "D100": "REG IND_OPER IND_EMIT COD_PART COD_MOD COD_SIT SER SUB NUM_DOC CHV_CTE DT_DOC DT_A_P TP_CTE CHV_CTE_REF "
            "VL_DOC VL_DESC IND_FRT VL_SERV VL_BC_ICMS VL_ICMS VL_NT COD_INF COD_CTA",
    "E110": "REG VL_TOT_DEBITOS VL_AJ_DEBITOS VL_TOT_AJ_DEBITOS VL_ESTORNOS_CRED VL_TOT_CREDITOS VL_AJ_CREDITOS "
            "VL_TOT_AJ_CREDITOS VL_ESTORNOS_DEB VL_SLD_CREDOR_ANT VL_SLD_APURADO VL_TOT_DED VL_ICMS_RECOLHER "
            "VL_SLD_CREDOR_TRANSPORTAR DEB_ESP",
    "E116": "REG COD_OR VL_OR DT_VCTO COD_REC NUM_PROC IND_PROC PROC TXT_COMPL MES_REF",
    "E520": "REG VL_SD_ANT_IPI VL_DEB_IPI VL_CRED_IPI VL_OD_IPI VL_OC_IPI VL_SC_IPI VL_SD_IPI",
    "0110": "REG COD_INC_TRIB IND_APRO_CRED COD_TIPO_CONT IND_REG_CUM",
    "M100": "REG COD_CRED IND_CRED_ORI VL_BC_PIS ALIQ_PIS QUANT_BC_PIS ALIQ_PIS_QUANT VL_CRED VL_AJUS_ACRES VL_AJUS_REDUC "
            "VL_CRED_DIF VL_CRED_DISP IND_DESC_CRED VL_CRED_DESC SLD_CRED",
    "M200": "REG VL_TOT_CONT_NC_PER VL_TOT_CRED_DESC VL_TOT_CRED_DESC_ANT VL_TOT_CONT_NC_DEV VL_RET_NC VL_OUT_DED_NC "
            "VL_CONT_NC_REC VL_TOT_CONT_CUM_PER VL_RET_CUM VL_OUT_DED_CUM VL_CONT_CUM_REC VL_TOT_CONT_REC",
    "I150": "REG DT_INI DT_FIN",
    "I050": "REG DT_ALT COD_NAT IND_CTA NIVEL COD_CTA COD_CTA_SUP CTA",
    "I155": "REG COD_CTA COD_CCUS VL_SLD_INI IND_DC_INI VL_DEB VL_CRED VL_SLD_FIN IND_DC_FIN",
}
L["M500"] = L["M100"].replace("PIS", "COFINS")
L["M600"] = L["M200"]
LAY = {k: v.split() for k, v in L.items()}


def registros(conteudo: str):
    for n, linha in enumerate(conteudo.splitlines(), 1):
        linha = linha.strip()
        if not linha.startswith("|"):
            continue
        campos = linha.split("|")[1:-1]
        if campos:
            yield n, campos


def mapa(reg: str, campos: list[str]) -> dict:
    nomes = LAY.get(reg)
    if not nomes:
        return {"REG": reg, "_campos": campos}
    return {nome: (campos[i] if i < len(campos) else "") for i, nome in enumerate(nomes)}


def data_sped(v: str) -> str | None:
    """DDMMAAAA → AAAA-MM-DD."""
    return f"{v[4:8]}-{v[2:4]}-{v[0:2]}" if v and len(v) == 8 else None


def _contar_9900(lote: Lote, contagem: dict, declarados: dict):
    for reg, qtd in declarados.items():
        if contagem.get(reg, 0) != qtd:
            lote.aviso(f"Bloco 9: registro {reg} declarado {qtd} vez(es), encontrado {contagem.get(reg, 0)}")


def ler_efd(dados: bytes, contribuicoes: bool) -> Lote:
    conteudo = texto(dados)
    fonte = "efd_contribuicoes" if contribuicoes else "efd_icms_ipi"
    lote = Lote(tipo=fonte, fonte=fonte)
    part: dict = {}
    prod: dict = {}
    doc = None
    periodo = None
    contagem: dict = {}
    decl9900: dict = {}
    for n, campos in registros(conteudo):
        reg = campos[0]
        contagem[reg] = contagem.get(reg, 0) + 1
        if reg == "0000":
            r = mapa("0000_CONTRIB" if contribuicoes else "0000_ICMS", campos)
            lote.cnpj = r["CNPJ"]
            ini = data_sped(r["DT_INI"])
            if not ini:
                lote.erro(f"linha {n}: 0000 sem DT_INI válida")
                continue
            periodo = ini[:7]
            lote.periodo_ini = periodo
            lote.periodo_fim = (data_sped(r["DT_FIN"]) or ini)[:7]
        elif reg == "0150":
            r = mapa(reg, campos)
            part[r["COD_PART"]] = r
        elif reg == "0200":
            r = mapa(reg, campos)
            prod[r["COD_ITEM"]] = r
        elif reg in ("C100", "D100"):
            r = mapa(reg, campos)
            p = part.get(r["COD_PART"], {})
            if reg == "C100":
                chave = r["CHV_NFE"]
                ext = {"vl_merc": r["VL_MERC"], "vl_desc": r["VL_DESC"], "vl_frt": r["VL_FRT"], "linha": n,
                       "ind_emit": r["IND_EMIT"]}
            else:
                chave = r["CHV_CTE"]
                ext = {"linha": n, "ind_emit": r["IND_EMIT"], "ind_frt": r["IND_FRT"]}
            situacao = {"00": "normal", "01": "normal", "02": "cancelada", "03": "cancelada", "04": "denegada",
                        "05": "inutilizada", "06": "normal", "07": "normal", "08": "normal"}.get(r["COD_SIT"], "normal")
            dt = data_sped(r["DT_DOC"]) or (periodo + "-01" if periodo else None)
            doc = {"fonte": fonte, "chave": chave or None, "modelo": r["COD_MOD"],
                   "operacao": "E" if r["IND_OPER"] == "0" else "S", "numero": r["NUM_DOC"].lstrip("0"),
                   "serie": r["SER"], "data_emissao": dt, "periodo": periodo or (dt or "")[:7], "situacao": situacao,
                   "cnpj_emit": (p.get("CNPJ") or p.get("CPF") or "") if r["IND_OPER"] == "0" else lote.cnpj,
                   "cnpj_dest": lote.cnpj if r["IND_OPER"] == "0" else (p.get("CNPJ") or p.get("CPF") or ""),
                   "nome_part": p.get("NOME"), "valor_total": s(D(r["VL_DOC"])),
                   "vbc_icms": s(D(r["VL_BC_ICMS"])), "v_icms": s(D(r["VL_ICMS"])),
                   "v_st": s(D(r.get("VL_ICMS_ST"))), "v_ipi": s(D(r.get("VL_IPI"))),
                   "v_pis": s(D(r.get("VL_PIS"))), "v_cofins": s(D(r.get("VL_COFINS"))),
                   "extra": ext, "itens": [], "c190": []}
            lote.documentos.append(doc)
        elif reg == "C170" and doc is not None:
            r = mapa(reg, campos)
            pr = prod.get(r["COD_ITEM"], {})
            doc["itens"].append({
                "n_item": int(r["NUM_ITEM"] or 0), "codigo": r["COD_ITEM"], "descricao": pr.get("DESCR_ITEM") or r["DESCR_COMPL"],
                "ncm": pr.get("COD_NCM"), "cfop": r["CFOP"], "cst_icms": r["CST_ICMS"][-2:] if len(r["CST_ICMS"]) == 3 else r["CST_ICMS"],
                "orig": r["CST_ICMS"][:1] if len(r["CST_ICMS"]) == 3 else None,
                "vprod": s(D(r["VL_ITEM"])), "vdesc": s(D(r["VL_DESC"])), "vbc_icms": s(D(r["VL_BC_ICMS"])),
                "p_icms": s(D(r["ALIQ_ICMS"]) / 100), "v_icms": s(D(r["VL_ICMS"])), "vbc_st": s(D(r["VL_BC_ICMS_ST"])),
                "v_st": s(D(r["VL_ICMS_ST"])), "cst_ipi": r["CST_IPI"], "p_ipi": s(D(r["ALIQ_IPI"]) / 100), "v_ipi": s(D(r["VL_IPI"])),
                "cst_pis": r["CST_PIS"], "vbc_pis": s(D(r["VL_BC_PIS"])), "p_pis": s(D(r["ALIQ_PIS"]) / 100), "v_pis": s(D(r["VL_PIS"])),
                "cst_cofins": r["CST_COFINS"], "vbc_cofins": s(D(r["VL_BC_COFINS"])), "p_cofins": s(D(r["ALIQ_COFINS"]) / 100),
                "v_cofins": s(D(r["VL_COFINS"])), "extra": {"linha": n}})
        elif reg == "C190" and doc is not None:
            r = mapa(reg, campos)
            doc["c190"].append({k: r[k] for k in ("CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS", "VL_ICMS", "VL_ICMS_ST", "VL_IPI")})
        elif reg in ("E110", "E520", "M200", "M600"):
            r = mapa(reg, campos)
            trib = {"E110": "ICMS", "E520": "IPI", "M200": "PIS", "M600": "COFINS"}[reg]
            for k, v in r.items():
                if k != "REG" and v not in ("",):
                    lote.apuracoes.append({"tributo": trib, "periodo": periodo, "campo": f"{reg}.{k}", "valor": s(D(v))})
        elif reg == "E116":
            r = mapa(reg, campos)
            lote.apuracoes.append({"tributo": "ICMS", "periodo": periodo, "campo": "E116.VL_OR", "valor": s(D(r["VL_OR"]))})
        elif reg in ("M100", "M500"):
            r = mapa(reg, campos)
            trib = "PIS" if reg == "M100" else "COFINS"
            for k in ("VL_BC_PIS" if trib == "PIS" else "VL_BC_COFINS", "VL_CRED", "VL_CRED_DISP", "VL_CRED_DESC", "SLD_CRED"):
                lote.apuracoes.append({"tributo": trib, "periodo": periodo, "campo": f"{reg}.{r['COD_CRED']}.{k}",
                                       "valor": s(D(r.get(k)))})
        elif reg == "0110":
            r = mapa(reg, campos)
            lote.apuracoes.append({"tributo": "PIS/COFINS", "periodo": periodo, "campo": "0110.COD_INC_TRIB",
                                   "valor": r["COD_INC_TRIB"] or "0"})
        elif reg == "9900":
            if len(campos) >= 3 and campos[2].isdigit():
                decl9900[campos[1]] = int(campos[2])
    _contar_9900(lote, contagem, decl9900)
    if not lote.cnpj:
        lote.erro("registro 0000 ausente: arquivo não parece SPED válido")
    lote.info(f"{len(lote.documentos)} documentos, {sum(len(d['itens']) for d in lote.documentos)} itens, "
              f"{len(lote.apuracoes)} valores de apuração")
    return lote


def ler_ecd(dados: bytes) -> Lote:
    lote = Lote(tipo="ecd", fonte="ecd")
    contas: dict = {}
    periodo = None
    for n, campos in registros(texto(dados)):
        reg = campos[0]
        if reg == "0000":
            r = mapa("0000_ECD", campos)
            lote.cnpj = r["CNPJ"]
            lote.periodo_ini = (data_sped(r["DT_INI"]) or "")[:7]
            lote.periodo_fim = (data_sped(r["DT_FIN"]) or "")[:7]
        elif reg == "I050":
            r = mapa(reg, campos)
            contas[r["COD_CTA"]] = r["CTA"]
        elif reg == "I150":
            periodo = (data_sped(mapa(reg, campos)["DT_INI"]) or "")[:7]
        elif reg == "I155":
            r = mapa(reg, campos)
            sinal = lambda v, ind: D(v) * (-1 if ind == "C" else 1)  # noqa: E731 — saldo devedor positivo
            lote.saldos.append({"periodo": periodo, "conta": r["COD_CTA"], "descricao": contas.get(r["COD_CTA"]),
                                "saldo_ini": s(sinal(r["VL_SLD_INI"], r["IND_DC_INI"])), "debitos": s(D(r["VL_DEB"])),
                                "creditos": s(D(r["VL_CRED"])), "saldo_fim": s(sinal(r["VL_SLD_FIN"], r["IND_DC_FIN"]))})
    lote.info(f"{len(lote.saldos)} saldos contábeis (I155)")
    return lote


def ler_ecf(dados: bytes) -> Lote:
    """Leitura genérica da ECF: registros de cálculo no formato |REG|CODIGO|DESCRICAO|VALOR|
    (N500, N620, N630, N650, N660, N670, P200, P300, P400, P500...)."""
    lote = Lote(tipo="ecf", fonte="ecf")
    ano = None
    for n, campos in registros(texto(dados)):
        reg = campos[0]
        if reg == "0000" and len(campos) > 5:
            lote.cnpj = campos[3]
            # primeira data DDMMAAAA após o nome = início do período
            datas = [c for c in campos[5:] if len(c) == 8 and c.isdigit() and 1 <= int(c[2:4]) <= 12]
            ano = datas[0][4:] if datas else None
        elif reg[:1] in ("N", "P", "M") and len(campos) == 4 and campos[1]:
            try:
                valor = D(campos[3])
            except ValueError:
                continue
            lote.apuracoes.append({"tributo": "IRPJ/CSLL", "periodo": f"{ano}-12" if ano else "",
                                   "campo": f"{reg}.{campos[1]}", "valor": s(valor), "descricao": campos[2]})
    lote.periodo_ini = lote.periodo_fim = f"{ano}-12" if ano else None
    lote.info(f"{len(lote.apuracoes)} linhas de cálculo lidas (leitura genérica)")
    return lote
