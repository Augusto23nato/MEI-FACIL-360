"""Simuladores de Lucro Presumido, Lucro Real e transição IBS/CBS."""
from __future__ import annotations

from ..num import D, ZERO, money, pct, brl, s
from .memoria import Memoria


def _irpj(mem, base, meses, rotulo="IRPJ"):
    r = mem.regra("IRPJ.ALIQUOTAS")
    normal = base * D(r.p["aliquota"])
    limite = D(r.p["limite_mensal_adicional"]) * meses
    adicional = max(base - limite, ZERO) * D(r.p["adicional"])
    mem.passo(rotulo, f"{brl(base)} × {pct(r.p['aliquota'], 2)} = {brl(normal)}; adicional: "
              f"max({brl(base)} − {brl(limite)}, 0) × {pct(r.p['adicional'], 2)} = {brl(adicional)}", regra=r.codigo)
    assert money(r.calcular({"base": base, "meses": D(meses)})) == money(normal + adicional)
    return normal, adicional


def presumido(motor, dados: dict) -> dict:
    """``dados``: ano, trimestre (1–4); receitas: [{atividade, valor}] do trimestre;
    outras_receitas (ganhos de capital, receitas financeiras etc., somadas integralmente);
    receita_anual_acumulada_anterior (para LC 224/2025, opcional);
    pis_cofins: {receita_bruta, exclusoes, icms_destacado, receita_monofasica_aliquota_zero};
    retencoes: {IRPJ, CSLL, PIS, COFINS}; pagos: {IRPJ, ...} (opcional)."""
    ano, tri = int(dados["ano"]), int(dados["trimestre"])
    if tri not in (1, 2, 3, 4):
        raise ValueError("trimestre deve ser 1, 2, 3 ou 4")
    data = f"{ano}-{(tri - 1) * 3 + 1:02d}-01"
    mem = Memoria(motor, data)
    pres = mem.regra("LP.PRESUNCAO").p["atividades"]
    lc224 = motor.tentar("LP.LC224.ACRESCIMO", data)
    alertas = []
    receita_tri = sum(D(r["valor"]) for r in dados.get("receitas", []))
    excesso_lc224 = ZERO
    if lc224:
        mem.regras[f"{lc224.codigo}@{lc224.versao}"] = lc224.ref()
        excesso_lc224 = max(receita_tri - D(lc224.p["limite_trimestral"]), ZERO)
    base_irpj = ZERO
    base_csll = ZERO
    for r in dados.get("receitas", []):
        at = r["atividade"]
        if at not in pres:
            raise ValueError(f"atividade desconhecida: {at}. Opções: {', '.join(pres)}")
        v = D(r["valor"])
        p_ir, p_cs = D(pres[at]["irpj"]), D(pres[at]["csll"])
        parte_exc = (excesso_lc224 * v / receita_tri) if (excesso_lc224 and receita_tri) else ZERO
        b_ir = v * p_ir + parte_exc * p_ir * D(lc224.p["acrescimo_relativo"] if lc224 else 0)
        aplica_csll = lc224 and data >= str(lc224.p.get("inicio_csll", data))
        b_cs = v * p_cs + (parte_exc * p_cs * D(lc224.p["acrescimo_relativo"]) if aplica_csll else ZERO)
        mem.passo(f"Presunção — {pres[at]['rotulo']}",
                  f"IRPJ {brl(v)} × {pct(p_ir, 2)}; CSLL {brl(v)} × {pct(p_cs, 2)}", regra="LP.PRESUNCAO")
        if parte_exc:
            mem.passo("Acréscimo LC 224/2025", f"parcela excedente {brl(parte_exc)} com presunção acrescida de "
                      f"{pct(lc224.p['acrescimo_relativo'], 0)} (CSLL {'sim' if aplica_csll else 'ainda não'})",
                      regra=lc224.codigo)
            alertas.append({"cor": "AMARELO", "texto": "Aplicado o acréscimo de presunção da LC 224/2025 sobre a receita "
                            "excedente: confirme parâmetros e forma de controle na regulamentação da RFB vigente."})
        base_irpj += b_ir
        base_csll += b_cs
    outras = D(dados.get("outras_receitas"))
    if outras:
        mem.passo("Outras receitas (adição integral à base)", brl(outras))
    base_irpj += outras
    base_csll += outras
    ir_n, ir_a = _irpj(mem, base_irpj, 3)
    cs_r = mem.regra("CSLL.ALIQUOTA")
    csll = base_csll * D(cs_r.p["aliquota"])
    mem.passo("CSLL", f"{brl(base_csll)} × {pct(cs_r.p['aliquota'], 2)} = {brl(csll)}", regra=cs_r.codigo)

    pc = dados.get("pis_cofins") or {}
    rb = D(pc.get("receita_bruta", receita_tri))
    excl = D(pc.get("exclusoes"))
    icms = D(pc.get("icms_destacado"))
    mono = D(pc.get("receita_monofasica_aliquota_zero"))
    base_pc = rb - excl - icms - mono
    if icms:
        mem.passo("Exclusão do ICMS da base de PIS/COFINS", brl(icms), regra="PISCOFINS.EXCLUSAO_ICMS")
        mem.regra("PISCOFINS.EXCLUSAO_ICMS")
    if mono:
        mem.passo("Receita de revenda de monofásicos (alíquota zero)", brl(mono), regra="MONOFASICO.NCM")
    pis_r, cof_r = mem.regra("PIS.CUMULATIVO"), mem.regra("COFINS.CUMULATIVO")
    pis, cofins = base_pc * D(pis_r.p["aliquota"]), base_pc * D(cof_r.p["aliquota"])
    mem.passo("PIS/COFINS cumulativos", f"base {brl(base_pc)} × {pct(pis_r.p['aliquota'], 2)} = {brl(pis)}; "
              f"× {pct(cof_r.p['aliquota'], 2)} = {brl(cofins)}", regra="PIS.CUMULATIVO")

    ret = {k: D(v) for k, v in (dados.get("retencoes") or {}).items()}
    trib = {"IRPJ": ir_n + ir_a, "CSLL": csll, "PIS": pis, "COFINS": cofins}
    devido = {k: money(max(v - ret.get(k, ZERO), ZERO)) for k, v in trib.items()}
    total = sum(devido.values(), ZERO)
    saida = {"tipo": "lucro_presumido", "ano": ano, "trimestre": tri, "receita_trimestre": s(money(receita_tri)),
             "base_irpj": s(money(base_irpj)), "base_csll": s(money(base_csll)), "base_pis_cofins": s(money(base_pc)),
             "irpj": s(money(ir_n)), "irpj_adicional": s(money(ir_a)), "csll": s(money(csll)),
             "pis": s(money(pis)), "cofins": s(money(cofins)),
             "retencoes": {k: s(money(v)) for k, v in ret.items()}, "a_recolher": {k: s(v) for k, v in devido.items()},
             "total": s(total), "carga_sobre_receita": s((total / receita_tri).quantize(D("0.000001"))) if receita_tri else "0",
             "alertas": alertas}
    _comparar_pago(saida, dados.get("pagos"), devido)
    return mem.fechar(saida)


def real(motor, dados: dict) -> dict:
    """``dados``: data_inicio 'AAAA-MM-DD', meses (3 trimestral / 12 anual);
    lucro_contabil, adicoes, exclusoes, prejuizo_fiscal_disponivel, base_negativa_disponivel;
    receita_tributavel (PIS/COFINS), receitas_nao_tributadas, icms_destacado;
    creditos: {categoria: base} (bases já sem ICMS desde 05/2023); retencoes; pagos."""
    data = dados.get("data_inicio") or f"{dados.get('ano')}-01-01"
    meses = int(dados.get("meses") or 12)
    mem = Memoria(motor, data)
    lucro = D(dados.get("lucro_contabil")) + D(dados.get("adicoes")) - D(dados.get("exclusoes"))
    mem.passo("Lucro líquido ajustado (LALUR/LACS)",
              f"{brl(dados.get('lucro_contabil'))} + adições {brl(dados.get('adicoes'))} − exclusões {brl(dados.get('exclusoes'))} = {brl(lucro)}")
    lim = D(mem.regra("LR.COMPENSACAO_PREJUIZO").p["limite"])
    comp_ir = min(D(dados.get("prejuizo_fiscal_disponivel")), max(lucro, ZERO) * lim)
    comp_cs = min(D(dados.get("base_negativa_disponivel")), max(lucro, ZERO) * lim)
    if comp_ir or comp_cs:
        mem.passo("Compensação (trava de 30%)", f"prejuízo fiscal {brl(comp_ir)}; base negativa {brl(comp_cs)}",
                  regra="LR.COMPENSACAO_PREJUIZO")
    base_ir = max(lucro - comp_ir, ZERO)
    base_cs = max(lucro - comp_cs, ZERO)
    ir_n, ir_a = _irpj(mem, base_ir, meses)
    cs_r = mem.regra("CSLL.ALIQUOTA")
    csll = base_cs * D(cs_r.p["aliquota"])
    mem.passo("CSLL", f"{brl(base_cs)} × {pct(cs_r.p['aliquota'], 2)} = {brl(csll)}", regra=cs_r.codigo)

    pis_r, cof_r = mem.regra("PIS.NAO_CUMULATIVO"), mem.regra("COFINS.NAO_CUMULATIVO")
    base_deb = D(dados.get("receita_tributavel")) - D(dados.get("icms_destacado"))
    if D(dados.get("icms_destacado")):
        mem.regra("PISCOFINS.EXCLUSAO_ICMS")
        mem.passo("Exclusão do ICMS da base de débito", brl(dados.get("icms_destacado")), regra="PISCOFINS.EXCLUSAO_ICMS")
    cred_base = sum((D(v) for v in (dados.get("creditos") or {}).values()), ZERO)
    mem.regra("CRED.PISCOFINS.NC")
    for cat, v in (dados.get("creditos") or {}).items():
        mem.passo(f"Base de crédito — {cat}", brl(v), regra="CRED.PISCOFINS.NC")
    pis_deb, cof_deb = base_deb * D(pis_r.p["aliquota"]), base_deb * D(cof_r.p["aliquota"])
    pis_cred, cof_cred = cred_base * D(pis_r.p["aliquota"]), cred_base * D(cof_r.p["aliquota"])
    pis, cofins = pis_deb - pis_cred, cof_deb - cof_cred
    mem.passo("PIS não cumulativo", f"débito {brl(pis_deb)} − crédito {brl(pis_cred)} = {brl(pis)}", regra=pis_r.codigo)
    mem.passo("COFINS não cumulativa", f"débito {brl(cof_deb)} − crédito {brl(cof_cred)} = {brl(cofins)}", regra=cof_r.codigo)
    ret = {k: D(v) for k, v in (dados.get("retencoes") or {}).items()}
    trib = {"IRPJ": ir_n + ir_a, "CSLL": csll, "PIS": pis, "COFINS": cofins}
    devido = {k: money(max(v - ret.get(k, ZERO), ZERO)) for k, v in trib.items()}
    saldo_credor = {k: s(money(-v)) for k, v in (("PIS", pis), ("COFINS", cofins)) if v < 0}
    total = sum(devido.values(), ZERO)
    receita = D(dados.get("receita_tributavel")) + D(dados.get("receitas_nao_tributadas"))
    saida = {"tipo": "lucro_real", "data_inicio": data, "meses": meses, "lucro_ajustado": s(money(lucro)),
             "base_irpj": s(money(base_ir)), "base_csll": s(money(base_cs)), "irpj": s(money(ir_n)),
             "irpj_adicional": s(money(ir_a)), "csll": s(money(csll)),
             "pis_debito": s(money(pis_deb)), "pis_credito": s(money(pis_cred)),
             "cofins_debito": s(money(cof_deb)), "cofins_credito": s(money(cof_cred)),
             "saldo_credor": saldo_credor, "a_recolher": {k: s(v) for k, v in devido.items()}, "total": s(total),
             "carga_sobre_receita": s((total / receita).quantize(D("0.000001"))) if receita else "0", "alertas": []}
    if saldo_credor:
        saida["alertas"].append({"cor": "AZUL", "texto": "Saldo credor de PIS/COFINS no período: avaliar manutenção, "
                                 "compensação ou ressarcimento (Lei 10.637, art. 5º; Lei 10.833, art. 6º; Lei 11.033, art. 17) conforme a origem."})
    _comparar_pago(saida, dados.get("pagos"), devido)
    return mem.fechar(saida)


def _comparar_pago(saida, pagos, devido):
    if not pagos:
        return
    dif = {}
    for k, v in pagos.items():
        d = money(v) - devido.get(k, ZERO)
        dif[k] = s(d)
        if d > D("0.01"):
            saida["alertas"].append({"cor": "AZUL", "texto": f"{k}: recolhido {brl(v)} > devido {brl(devido.get(k, 0))} — "
                                     f"possível pagamento indevido de {brl(d)} (PER/DCOMP após validação)."})
        elif d < D("-0.01"):
            saida["alertas"].append({"cor": "VERMELHO", "texto": f"{k}: recolhido {brl(v)} < devido {brl(devido.get(k, 0))}."})
    saida["diferenca_pago_menos_devido"] = dif


def reforma(motor, dados: dict) -> dict:
    """Projeção IBS/CBS por ano da transição. ``dados``: ano, base (valor das operações),
    creditos_base (aquisições com IBS/CBS), aliquota_cbs_referencia, aliquota_ibs_referencia (≥ 2027)."""
    ano = str(dados["ano"])
    mem = Memoria(motor, f"{ano}-01-01")
    r = mem.regra("REFORMA.TRANSICAO")
    cfg = r.p["anos"].get(ano)
    if not cfg:
        raise ValueError("ano fora do cronograma de transição (2026–2033)")
    base, cred = D(dados.get("base")), D(dados.get("creditos_base"))

    def aliq(nome, ref_key):
        v = cfg[nome]
        if isinstance(v, str) and v in ("referencia", "proporcional"):
            if dados.get(ref_key) in (None, ""):
                raise ValueError(f"informe '{ref_key}': a alíquota de {nome.upper()} para {ano} é fixada por resolução "
                                 "do Senado/ente e não é presumida pelo sistema")
            return D(dados[ref_key])
        return D(v)

    cbs, ibs = aliq("cbs", "aliquota_cbs_referencia"), aliq("ibs", "aliquota_ibs_referencia")
    deb_cbs, deb_ibs = base * cbs, base * ibs
    cr_cbs, cr_ibs = cred * cbs, cred * ibs
    mem.passo(f"Transição {ano}", cfg.get("nota") or "", regra=r.codigo)
    mem.passo("CBS", f"débito {brl(base)} × {pct(cbs)} = {brl(deb_cbs)}; crédito {brl(cred)} × {pct(cbs)} = {brl(cr_cbs)}")
    mem.passo("IBS", f"débito {brl(base)} × {pct(ibs)} = {brl(deb_ibs)}; crédito {brl(cred)} × {pct(ibs)} = {brl(cr_ibs)}")
    return mem.fechar({"tipo": "reforma", "ano": int(ano), "cronograma": cfg, "aliquota_cbs": s(cbs), "aliquota_ibs": s(ibs),
                       "cbs_debito": s(money(deb_cbs)), "cbs_credito": s(money(cr_cbs)), "cbs_liquida": s(money(deb_cbs - cr_cbs)),
                       "ibs_debito": s(money(deb_ibs)), "ibs_credito": s(money(cr_ibs)), "ibs_liquido": s(money(deb_ibs - cr_ibs)),
                       "alertas": [{"cor": "AMARELO", "texto": cfg.get("nota")}] if cfg.get("nota") else []})
