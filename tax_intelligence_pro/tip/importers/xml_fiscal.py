"""Leitores de XML fiscais: NF-e/NFC-e (inclusive grupo IBS/CBS), eventos, CT-e e NFS-e.

A leitura usa o nome local das tags (ignora namespace) para tolerar variações de
versão e de padrão municipal (ABRASF, NFS-e Nacional).
"""
from __future__ import annotations

from ..num import D, s
from .base import ArquivoInvalido, Lote, xml_seguro


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def achar(el, *caminho):
    """Primeiro descendente que casa a sequência de nomes locais (busca em profundidade)."""
    if el is None:
        return None
    atual = el
    for nome in caminho:
        prox = None
        for e in atual.iter():
            if e is not atual and _ln(e.tag) == nome:
                prox = e
                break
        if prox is None:
            return None
        atual = prox
    return atual


def txt(el, *caminho, padrao=""):
    e = achar(el, *caminho) if caminho else el
    return (e.text or "").strip() if e is not None and e.text else padrao


def filho(el, nome):
    for e in list(el) if el is not None else []:
        if _ln(e.tag) == nome:
            return e
    return None


def _um(el, *nomes):
    """Primeiro elemento encontrado entre nomes alternativos (Element vazio é falsy: não usar `or`)."""
    for nome in nomes:
        e = achar(el, nome)
        if e is not None:
            return e
    return None


def _grupo_icms(imposto):
    icms = filho(imposto, "ICMS")
    if icms is None:
        return None
    return _primeiro_filho(icms)


def _primeiro_filho(el):
    return None if el is None else next(iter(list(el)), None)


def ler_nfe(dados: bytes, cnpj_empresa: str) -> Lote:
    raiz = xml_seguro(dados)
    inf = achar(raiz, "infNFe") if _ln(raiz.tag) != "infNFe" else raiz
    if inf is None:
        raise ArquivoInvalido("XML não contém infNFe")
    lote = Lote(tipo="nfe", fonte="xml")
    chave = (inf.get("Id") or "").replace("NFe", "")
    ide, emit, dest, tot = filho(inf, "ide"), filho(inf, "emit"), filho(inf, "dest"), achar(inf, "ICMSTot")
    cnpj_emit = txt(emit, "CNPJ") or txt(emit, "CPF")
    cnpj_dest = (txt(dest, "CNPJ") or txt(dest, "CPF")) if dest is not None else ""
    tp_nf = txt(ide, "tpNF")
    if cnpj_emit == cnpj_empresa:
        operacao = "S" if tp_nf == "1" else "E"   # entrada por emissão própria (tpNF=0)
    elif cnpj_dest == cnpj_empresa:
        operacao = "E"
    else:
        lote.aviso(f"NF-e {chave}: empresa não é emitente nem destinatária — documento ignorado")
        return lote
    dh = txt(ide, "dhEmi") or txt(ide, "dEmi")
    data = dh[:10]
    prot = achar(raiz, "protNFe")
    c_stat = txt(prot, "cStat") if prot is not None else ""
    if prot is None:
        lote.aviso(f"NF-e {chave}: XML sem protocolo de autorização (nfeProc)")
    elif c_stat not in ("100", "150"):
        lote.aviso(f"NF-e {chave}: protocolo com cStat {c_stat} (não autorizada)")
    ibscbs_tot = achar(inf, "IBSCBSTot")
    doc = {"fonte": "xml", "chave": chave, "modelo": txt(ide, "mod"), "operacao": operacao, "numero": txt(ide, "nNF"),
           "serie": txt(ide, "serie"), "data_emissao": data, "periodo": data[:7],
           "situacao": "normal" if c_stat in ("100", "150", "") else "denegada",
           "cnpj_emit": cnpj_emit, "cnpj_dest": cnpj_dest, "uf_emit": txt(emit, "enderEmit", "UF"),
           "uf_dest": txt(dest, "enderDest", "UF") if dest is not None else "",
           "nome_part": txt(dest, "xNome") if operacao == "S" else txt(emit, "xNome"), "crt_emit": txt(emit, "CRT"),
           "valor_total": s(D(txt(tot, "vNF"))), "vbc_icms": s(D(txt(tot, "vBC"))), "v_icms": s(D(txt(tot, "vICMS"))),
           "v_st": s(D(txt(tot, "vST"))), "v_ipi": s(D(txt(tot, "vIPI"))), "v_pis": s(D(txt(tot, "vPIS"))),
           "v_cofins": s(D(txt(tot, "vCOFINS"))),
           "v_ibs": s(D(txt(ibscbs_tot, "vIBS"))) if ibscbs_tot is not None else None,
           "v_cbs": s(D(txt(ibscbs_tot, "vCBS"))) if ibscbs_tot is not None else None,
           "extra": {"tpNF": tp_nf, "finNFe": txt(ide, "finNFe"), "idDest": txt(ide, "idDest"),
                     "indFinal": txt(ide, "indFinal"), "natOp": txt(ide, "natOp"),
                     "indIEDest": txt(dest, "indIEDest") if dest is not None else ""}, "itens": []}
    for det in inf:
        if _ln(det.tag) != "det":
            continue
        prod, imp = filho(det, "prod"), filho(det, "imposto")
        g = _grupo_icms(imp)
        ipi = filho(imp, "IPI")
        ipit = filho(ipi, "IPITrib") if ipi is not None else None
        pis = _primeiro_filho(filho(imp, "PIS"))
        cof = _primeiro_filho(filho(imp, "COFINS"))
        iss = filho(imp, "ISSQN")
        ibs = filho(imp, "IBSCBS")
        cst_ipi = txt(ipit, "CST") if ipit is not None else (txt(ipi, "CST") if ipi is not None else "")
        doc["itens"].append({
            "n_item": int(det.get("nItem") or 0), "codigo": txt(prod, "cProd"), "descricao": txt(prod, "xProd"),
            "ncm": txt(prod, "NCM"), "cfop": txt(prod, "CFOP"),
            "cst_icms": txt(g, "CST") or txt(g, "CSOSN") if g is not None else "", "orig": txt(g, "orig") if g is not None else "",
            "vprod": s(D(txt(prod, "vProd"))), "vdesc": s(D(txt(prod, "vDesc"))), "vfrete": s(D(txt(prod, "vFrete"))),
            "vseg": s(D(txt(prod, "vSeg"))), "voutro": s(D(txt(prod, "vOutro"))),
            "vbc_icms": s(D(txt(g, "vBC"))) if g is not None else "0", "p_icms": s(D(txt(g, "pICMS")) / 100) if g is not None else "0",
            "v_icms": s(D(txt(g, "vICMS"))) if g is not None else "0",
            "vbc_st": s(D(txt(g, "vBCST"))) if g is not None else "0", "v_st": s(D(txt(g, "vICMSST"))) if g is not None else "0",
            "cst_ipi": cst_ipi, "p_ipi": s(D(txt(ipit, "pIPI")) / 100) if ipit is not None else "0",
            "v_ipi": s(D(txt(ipit, "vIPI"))) if ipit is not None else "0",
            "cst_pis": txt(pis, "CST") if pis is not None else "", "vbc_pis": s(D(txt(pis, "vBC"))) if pis is not None else "0",
            "p_pis": s(D(txt(pis, "pPIS")) / 100) if pis is not None else "0", "v_pis": s(D(txt(pis, "vPIS"))) if pis is not None else "0",
            "cst_cofins": txt(cof, "CST") if cof is not None else "",
            "vbc_cofins": s(D(txt(cof, "vBC"))) if cof is not None else "0",
            "p_cofins": s(D(txt(cof, "pCOFINS")) / 100) if cof is not None else "0",
            "v_cofins": s(D(txt(cof, "vCOFINS"))) if cof is not None else "0",
            "p_iss": s(D(txt(iss, "vAliq")) / 100) if iss is not None else None, "v_iss": s(D(txt(iss, "vISSQN"))) if iss is not None else None,
            "p_cred_sn": s(D(txt(g, "pCredSN")) / 100) if g is not None and txt(g, "pCredSN") else None,
            "v_cred_sn": s(D(txt(g, "vCredICMSSN"))) if g is not None and txt(g, "vCredICMSSN") else None,
            "cst_ibscbs": txt(ibs, "CST") if ibs is not None else None,
            "v_ibs": s(D(txt(ibs, "vIBS"))) if ibs is not None else None,
            "v_cbs": s(D(txt(ibs, "vCBS"))) if ibs is not None else None,
            "extra": {"cest": txt(prod, "CEST"), "vICMSSTRet": txt(g, "vICMSSTRet") if g is not None else "",
                      "pRedBC": txt(g, "pRedBC") if g is not None else ""}})
    lote.documentos.append(doc)
    lote.periodo_ini = lote.periodo_fim = doc["periodo"]
    return lote


def ler_evento_nfe(dados: bytes) -> dict | None:
    """Evento de cancelamento (110111) → {'chave':..., 'tipo': 'cancelamento'}."""
    raiz = xml_seguro(dados)
    tp = txt(raiz, "tpEvento")
    if tp == "110111":
        return {"chave": txt(raiz, "chNFe"), "tipo": "cancelamento", "data": txt(raiz, "dhEvento")[:10]}
    return None


def ler_cte(dados: bytes, cnpj_empresa: str) -> Lote:
    raiz = xml_seguro(dados)
    inf = achar(raiz, "infCte")
    if inf is None:
        raise ArquivoInvalido("XML não contém infCte")
    lote = Lote(tipo="cte", fonte="xml")
    ide, emit = filho(inf, "ide"), filho(inf, "emit")
    toma = txt(ide, "toma3", "toma") or txt(ide, "toma4", "toma")
    papeis = {"0": "rem", "1": "exped", "2": "receb", "3": "dest"}
    cnpj_toma = txt(filho(inf, papeis.get(toma, "")) , "CNPJ") if toma in papeis else txt(ide, "toma4", "CNPJ")
    cnpj_emit = txt(emit, "CNPJ")
    cnpj_rem = txt(filho(inf, "rem"), "CNPJ")
    if cnpj_emit == cnpj_empresa:
        operacao = "S"
    elif cnpj_toma == cnpj_empresa:
        operacao = "E"
    else:
        lote.aviso("CT-e em que a empresa não é emitente nem tomadora — ignorado")
        return lote
    data = (txt(ide, "dhEmi") or "")[:10]
    icms = _primeiro_filho(achar(inf, "imp", "ICMS"))
    vprest = txt(inf, "vPrest", "vTPrest")
    lote.documentos.append({
        "fonte": "xml", "chave": (inf.get("Id") or "").replace("CTe", ""), "modelo": txt(ide, "mod") or "57",
        "operacao": operacao, "numero": txt(ide, "nCT"), "serie": txt(ide, "serie"), "data_emissao": data,
        "periodo": data[:7], "situacao": "normal", "cnpj_emit": cnpj_emit, "cnpj_dest": cnpj_toma,
        "uf_emit": txt(ide, "UFIni"), "uf_dest": txt(ide, "UFFim"), "nome_part": txt(emit, "xNome"),
        "valor_total": s(D(vprest)), "vbc_icms": s(D(txt(icms, "vBC"))) if icms is not None else "0",
        "v_icms": s(D(txt(icms, "vICMS"))) if icms is not None else "0",
        "extra": {"tomador": toma, "empresa_remetente": cnpj_rem == cnpj_empresa, "cfop": txt(ide, "CFOP")},
        "itens": [{"n_item": 1, "descricao": "Prestação de serviço de transporte", "cfop": txt(ide, "CFOP"),
                   "cst_icms": txt(icms, "CST") if icms is not None else "", "vprod": s(D(vprest)),
                   "vbc_icms": s(D(txt(icms, "vBC"))) if icms is not None else "0",
                   "p_icms": s(D(txt(icms, "pICMS")) / 100) if icms is not None else "0",
                   "v_icms": s(D(txt(icms, "vICMS"))) if icms is not None else "0", "extra": {}}]})
    lote.periodo_ini = lote.periodo_fim = data[:7]
    return lote


def ler_nfse(dados: bytes, cnpj_empresa: str) -> Lote:
    """NFS-e: padrão Nacional (infNFSe/DPS) e ABRASF (InfNfse). Campos lidos por nome local."""
    raiz = xml_seguro(dados)
    lote = Lote(tipo="nfse", fonte="xml")
    notas = [e for e in raiz.iter() if _ln(e.tag) in ("infNFSe", "InfNfse")] or [raiz]
    for n in notas:
        prest = _um(n, "prest", "PrestadorServico", "Prestador", "emit")
        toma = _um(n, "toma", "TomadorServico", "Tomador")
        cnpj_p = txt(prest, "CNPJ") or txt(prest, "Cnpj")
        cnpj_t = (txt(toma, "CNPJ") or txt(toma, "Cnpj") or txt(toma, "CPF") or txt(toma, "Cpf")) if toma is not None else ""
        if cnpj_p == cnpj_empresa:
            op = "S"
        elif cnpj_t == cnpj_empresa:
            op = "E"
        else:
            lote.aviso("NFS-e em que a empresa não é prestadora nem tomadora — ignorada")
            continue
        data = (txt(n, "dhEmi") or txt(n, "DataEmissao") or txt(n, "dCompet") or txt(n, "Competencia"))[:10]
        v_serv = D(txt(n, "vServ") or txt(n, "ValorServicos"))
        v_iss = D(txt(n, "vISSQN") or txt(n, "ValorIss"))
        aliq_txt = txt(n, "pAliqAplic") or txt(n, "pAliq") or txt(n, "Aliquota")
        aliq = D(aliq_txt)
        if aliq > 1:
            aliq = aliq / 100   # ABRASF usa fração (0.05) em alguns municípios e percentual (5.00) em outros
        retido = (txt(n, "tpRetISSQN") in ("2", "3")) or (txt(n, "IssRetido") == "1")
        ret = {k: s(D(txt(n, tag) or txt(n, alt))) for k, tag, alt in
               (("IR", "vRetIRRF", "ValorIr"), ("CSLL", "vRetCSLL", "ValorCsll"), ("PIS", "vPis", "ValorPis"),
                ("COFINS", "vCofins", "ValorCofins"), ("INSS", "vRetCP", "ValorInss"))}
        numero = txt(n, "nNFSe") or txt(n, "Numero")
        lote.documentos.append({
            "fonte": "xml", "chave": (n.get("Id") or f"NFSE-{cnpj_p}-{numero}"), "modelo": "NFSE", "operacao": op,
            "numero": numero, "serie": "", "data_emissao": data, "periodo": data[:7], "situacao": "normal",
            "cnpj_emit": cnpj_p, "cnpj_dest": cnpj_t, "nome_part": txt(toma, "xNome") if op == "S" else txt(prest, "xNome"),
            "valor_total": s(v_serv), "v_iss": s(v_iss),
            "extra": {"iss_retido": retido, "retencoes": ret, "cod_servico": txt(n, "cTribNac") or txt(n, "ItemListaServico"),
                      "municipio": txt(n, "cLocIncid") or txt(n, "CodigoMunicipio")},
            "itens": [{"n_item": 1, "descricao": txt(n, "xDescServ") or txt(n, "Discriminacao"), "vprod": s(v_serv),
                       "p_iss": s(aliq), "v_iss": s(v_iss), "extra": {}}]})
        lote.periodo_ini = lote.periodo_fim = data[:7]
    return lote
