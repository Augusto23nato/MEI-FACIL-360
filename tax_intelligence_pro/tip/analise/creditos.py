"""Motor de avaliação de créditos por item de entrada.

Princípio: NENHUMA aquisição gera crédito automaticamente. Cada item é avaliado
pelos critérios legais — regime do adquirente, finalidade (CFOP de entrada),
natureza da operação, situação tributária do fornecedor (CST), tipo de
fornecedor (PJ/PF), produto (monofásico/ST) e data (vigência da regra).

Classificações:
* DIREITO      — atende aos critérios objetivos da regra.
* POTENCIAL    — depende de análise (essencialidade do insumo, imobilizado, CFOP não classificado...).
* SEM_DIREITO  — vedação legal identificada (com o motivo).
"""
from __future__ import annotations

from ..num import D, ZERO, pct, brl

DIREITO, POTENCIAL, SEM = "DIREITO", "POTENCIAL", "SEM_DIREITO"


def finalidade(cfop: str, grupos: dict) -> str | None:
    suf = (cfop or "")[1:]
    for nome, lst in grupos.items():
        if suf in lst:
            return nome
    return None


def cfop_entrada(cfop_emitente: str) -> str:
    """CFOP de saída do emitente → CFOP de entrada equivalente (5xxx→1xxx, 6xxx→2xxx, 7xxx→3xxx)."""
    if not cfop_emitente:
        return ""
    return {"5": "1", "6": "2", "7": "3"}.get(cfop_emitente[0], cfop_emitente[0]) + cfop_emitente[1:]


def eh_monofasico(ncm: str, regra) -> dict | None:
    if not ncm or regra is None:
        return None
    for pref, info in sorted(regra.p["prefixos"].items(), key=lambda kv: -len(kv[0])):
        if ncm.startswith(pref):
            return {"prefixo": pref, **info}
    return None


def avaliar(item: dict, doc: dict, emp: dict, motor, cfop_escriturado: str | None = None) -> list[dict]:
    data = doc.get("data_emissao") or (doc.get("periodo") or "2000-01") + "-01"
    regime = emp["regime"]
    cfop = cfop_escriturado or cfop_entrada(item.get("cfop") or "")
    presumida = not cfop_escriturado and doc.get("fonte") == "xml"
    nota_fin = " (finalidade presumida pelo CFOP do emitente — confirmar na escrituração)" if presumida else ""
    out = []
    vprod, vdesc = D(item.get("vprod")), D(item.get("vdesc"))
    v_icms, v_ipi = D(item.get("v_icms")), D(item.get("v_ipi"))
    cst = (item.get("cst_icms") or "")[-3:] if len(item.get("cst_icms") or "") == 3 else (item.get("cst_icms") or "")[-2:]

    # ---------------- ICMS
    if regime in ("LUCRO_PRESUMIDO", "LUCRO_REAL"):
        r = motor.obter("CRED.ICMS", data)
        fin = finalidade(cfop, r.p["cfop"])
        v_cred = v_icms
        if doc.get("crt_emit") == "1":   # fornecedor do Simples: só o crédito informado (LC 123, art. 23)
            v_cred = D(item.get("v_cred_sn"))
        av = {"tributo": "ICMS", "finalidade": fin, "cfop": cfop, "fundamento": r.fundamento, "regra": r.ref(),
              "valor": ZERO, "base": D(item.get("vbc_icms"))}
        if v_cred <= 0:
            av.update(classe=SEM, motivo="sem ICMS destacado/creditável no documento", confianca="alta")
        elif fin == "st" or cst in r.p["cst_sem_credito"]:
            av.update(classe=SEM, motivo="mercadoria sujeita a ST: ICMS próprio do fornecedor não gera crédito ao substituído", confianca="alta")
        elif fin == "uso_consumo":
            av.update(classe=SEM, motivo="material de uso e consumo: crédito só a partir de 01/01/2033 (LC 87/96, art. 33, I)", confianca="alta")
        elif fin == "sem_credito":
            av.update(classe=SEM, motivo=f"CFOP {cfop}: operação sem natureza de aquisição creditável (remessa/bonificação/outras)", confianca="media")
        elif fin == "ativo":
            av.update(classe=DIREITO, valor=v_cred, motivo=f"ativo imobilizado: crédito em 48 parcelas mensais de {brl(v_cred / 48)} (CIAP)",
                      confianca="media")
        elif fin in ("revenda", "industrializacao", "energia", "frete_aquisicao", "devolucao_venda"):
            sn = " — fornecedor do Simples: valor de pCredSN/vCredICMSSN" if doc.get("crt_emit") == "1" else ""
            av.update(classe=DIREITO, valor=v_cred, motivo=f"aquisição para {fin.replace('_', ' ')}{sn}{nota_fin}",
                      confianca="media" if presumida else "alta")
        else:
            av.update(classe=POTENCIAL, valor=v_cred, motivo=f"CFOP {cfop} não classificado nas regras de crédito{nota_fin}", confianca="baixa")
        av["observacao"] = "Saídas isentas/não tributadas posteriores exigem estorno proporcional (LC 87/96, art. 21)."
        out.append(av)

    # ---------------- PIS/COFINS não cumulativos
    if regime == "LUCRO_REAL":
        r = motor.obter("CRED.PISCOFINS.NC", data)
        rp, rc = motor.obter("PIS.NAO_CUMULATIVO", data), motor.obter("COFINS.NAO_CUMULATIVO", data)
        excl = motor.tentar("PISCOFINS.EXCLUSAO_ICMS", data)
        mono = eh_monofasico(item.get("ncm"), motor.tentar("MONOFASICO.NCM", data))
        fin = finalidade(cfop, r.p["cfop"])
        base = vprod - vdesc + D(item.get("vfrete")) + D(item.get("vseg")) + D(item.get("voutro"))
        memo = [f"valor do item {brl(vprod)} − desconto {brl(vdesc)} + frete/seguro/outras"]
        if not emp.get("contribuinte_ipi") and v_ipi:
            base += v_ipi
            memo.append(f"+ IPI não recuperável {brl(v_ipi)}")
        if excl and data >= str(excl.p.get("icms_fora_base_credito_desde")) and v_icms:
            base -= v_icms
            memo.append(f"− ICMS destacado {brl(v_icms)} (Lei 14.592/2023)")
        cst_f = (item.get("cst_pis") or "").zfill(2) if item.get("cst_pis") else ""
        fornecedor_pj = len(doc.get("cnpj_emit") or "") == 14
        classe, motivo, conf = None, None, "alta"
        if not fornecedor_pj:
            classe, motivo = SEM, "aquisição de pessoa física: vedado (Lei 10.637/10.833, art. 3º, §3º, I)"
        elif fin is None:
            classe, motivo, conf = POTENCIAL, f"CFOP {cfop} não classificado nas regras de crédito{nota_fin}", "baixa"
        elif fin == "sem_credito":
            classe, motivo, conf = SEM, f"CFOP {cfop}: remessa/bonificação/outras — sem aquisição onerosa", "media"
        elif fin in ("revenda", "st_revenda") and cst_f in r.p["cst_fornecedor_sem_credito"]:
            classe, motivo = SEM, f"fornecedor com CST {cst_f} ({r.p['cst_fornecedor_sem_credito'][cst_f]}): bem não sujeito ao pagamento (art. 3º, §2º, II)"
        elif fin in ("revenda", "st_revenda") and (cst_f in r.p["cst_fornecedor_monofasico_fabricante"] or mono):
            classe, conf = SEM, "media" if mono and cst_f not in r.p["cst_fornecedor_monofasico_fabricante"] else "alta"
            motivo = ("revenda de produto monofásico: vedado (art. 3º, I, 'b')"
                      + (f" — NCM {item.get('ncm')} na lista {mono['lei']}; confirmar exceções" if mono else ""))
        elif fin in ("revenda", "st_revenda", "industrializacao", "st_industrializacao", "energia", "frete_aquisicao", "devolucao_venda"):
            classe, motivo = DIREITO, f"art. 3º — {fin.replace('_', ' ')}{nota_fin}"
            if fin in ("industrializacao", "st_industrializacao"):
                motivo += " (insumo: conferir essencialidade/relevância — Tema 779/STJ)"
            if presumida:
                conf = "media"
            if cst_f in r.p["cst_fornecedor_sem_credito"] and fin != "devolucao_venda":
                classe, motivo, conf = POTENCIAL, (f"insumo adquirido com CST {cst_f} do fornecedor "
                                                   f"({r.p['cst_fornecedor_sem_credito'][cst_f]}): avaliar art. 3º, §2º, II"), "baixa"
        elif fin == "uso_consumo":
            classe, motivo, conf = POTENCIAL, "uso e consumo: só gera crédito se essencial/relevante ao processo produtivo ou à prestação (Tema 779/STJ)", "baixa"
        elif fin == "ativo":
            classe, motivo, conf = POTENCIAL, ("imobilizado: crédito sobre depreciação ou imediato para máquinas/equipamentos "
                                               "(art. 3º, VI e §14; Lei 11.774/2008) — valor indica o total"), "media"
        else:
            classe, motivo, conf = POTENCIAL, f"finalidade '{fin}' requer análise", "baixa"
        base = max(base, ZERO)
        for trib, rr in (("PIS", rp), ("COFINS", rc)):
            valor = base * D(rr.p["aliquota"]) if classe != SEM else ZERO
            out.append({"tributo": trib, "classe": classe, "motivo": motivo, "confianca": conf, "finalidade": fin, "cfop": cfop,
                        "base": base, "valor": valor, "fundamento": r.fundamento, "regra": r.ref(),
                        "memoria": memo + [f"= base {brl(base)} × {pct(rr.p['aliquota'], 2)} = {brl(valor)}"]})

    # ---------------- IPI
    if emp.get("contribuinte_ipi") and v_ipi > 0:
        r = motor.obter("CRED.IPI", data)
        ok = cfop[1:] in r.p["cfop_credito"]
        out.append({"tributo": "IPI", "classe": DIREITO if ok else SEM, "valor": v_ipi if ok else ZERO, "base": D(item.get("vprod")),
                    "motivo": "insumo para industrialização" if ok else f"CFOP {cfop} não é de aquisição para industrialização",
                    "confianca": "media" if presumida else "alta", "fundamento": r.fundamento, "regra": r.ref(), "cfop": cfop})
    return out
