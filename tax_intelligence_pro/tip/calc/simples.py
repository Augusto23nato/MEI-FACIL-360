"""Simulador do Simples Nacional (LC 123/2006).

Calcula, para cada parcela de receita do mês: anexo (inclusive via Fator R),
faixa, alíquota nominal, parcela a deduzir, alíquota efetiva, repartição por
tributo (com teto de 5% do ISS), exclusões por segregação (monofásico, ST, ISS
retido, exportação) e o valor do DAS. Tudo com memória de cálculo.
"""
from __future__ import annotations

from ..num import D, ZERO, money, pct, brl, s
from .memoria import Memoria


def faixa_de(regra_anexo, rbt12):
    for f in regra_anexo.p["faixas"]:
        if rbt12 <= D(f["ate"]):
            return f
    return regra_anexo.p["faixas"][-1]  # acima do limite: empresa excluída — tratado como alerta


def aliquota_efetiva(regra_anexo, rbt12):
    f = faixa_de(regra_anexo, rbt12)
    if rbt12 <= 0:
        return f, D(f["aliquota"])
    ef = regra_anexo.calcular({"rbt12": rbt12, "aliquota": D(f["aliquota"]), "deducao": D(f["deducao"])})
    return f, ef


def reparticao(regra_anexo, faixa, ef, teto_iss, mem: Memoria | None = None) -> dict:
    """Percentual efetivo por tributo, aplicando o teto do ISS quando cabível."""
    rep = {t: D(v) for t, v in faixa["reparticao"].items()}
    por_trib = {t: ef * v for t, v in rep.items()}
    if "ISS" in por_trib and por_trib["ISS"] > teto_iss:
        excesso = por_trib["ISS"] - teto_iss
        federais = [t for t in rep if t not in ("ISS", "ICMS")]
        soma_fed = sum(rep[t] for t in federais)
        for t in federais:
            por_trib[t] += excesso * rep[t] / soma_fed
        por_trib["ISS"] = teto_iss
        if mem:
            mem.passo("Teto do ISS", f"ISS efetivo {pct(ef * rep['ISS'])} > {pct(teto_iss)}: excesso de {pct(excesso)} "
                      "redistribuído proporcionalmente aos tributos federais", regra="SN.TETO_ISS")
    return por_trib


def simular(motor, dados: dict) -> dict:
    """``dados``:
    periodo 'AAAA-MM'; rbt12; folha12 (opcional); meses_atividade (opcional);
    parcelas: [{descricao, anexo ('I'..'V' ou 'FATOR_R'), valor, tipos: ['monofasico','icms_st',...]}]
    das_pago (opcional) — para apontar diferença em relação ao recolhido.
    """
    periodo = dados["periodo"]
    data = periodo + "-01"
    mem = Memoria(motor, data)
    parcelas = dados.get("parcelas") or []
    if not parcelas:
        raise ValueError("informe ao menos uma parcela de receita")
    receita_mes = sum(D(p["valor"]) for p in parcelas)
    rbt12 = D(dados.get("rbt12"))
    alertas = []

    lim = mem.regra("SN.LIMITES")
    meses_ativ = int(dados.get("meses_atividade") or 13)
    if rbt12 <= 0 or meses_ativ < 13:
        # LC 123, art. 18, §2º: no início de atividade, RBT12 proporcionalizada
        if meses_ativ <= 1 or rbt12 <= 0:
            rbt12_calc = receita_mes * 12
            mem.passo("RBT12 proporcional (1º mês de atividade)", f"{brl(receita_mes)} × 12 = {brl(rbt12_calc)}",
                      regra="SN.LIMITES")
        else:
            meses_ant = meses_ativ - 1
            rbt12_calc = rbt12 / meses_ant * 12
            mem.passo("RBT12 proporcional (início de atividade)",
                      f"{brl(rbt12)} / {meses_ant} meses × 12 = {brl(rbt12_calc)}", regra="SN.LIMITES")
        rbt12 = rbt12_calc
    else:
        mem.passo("Receita bruta dos 12 meses anteriores (RBT12)", brl(rbt12))

    if rbt12 > D(lim.p["limite_epp"]):
        alertas.append({"cor": "VERMELHO", "texto": f"RBT12 {brl(rbt12)} acima do limite de {brl(lim.p['limite_epp'])}: "
                        "verificar exclusão do Simples Nacional (LC 123, arts. 3º, §§ 9º a 12, e 30)."})
    if rbt12 > D(lim.p["sublimite_icms_iss"]):
        alertas.append({"cor": "AMARELO", "texto": f"RBT12 acima do sublimite de {brl(lim.p['sublimite_icms_iss'])}: ICMS e ISS "
                        "passam a ser recolhidos fora do DAS (LC 123, arts. 13-A e 20) — confira a receita acumulada no ano-calendário."})

    fr_regra = mem.regra("SN.FATOR_R")
    fator_r = None
    if any(p.get("anexo") == "FATOR_R" for p in parcelas):
        folha = D(dados.get("folha12"))
        fator_r = fr_regra.calcular({"folha12": folha, "rbt12": rbt12}) if rbt12 > 0 else ZERO
        mem.passo("Fator R", f"folha 12m {brl(folha)} / RBT12 {brl(rbt12)} = {pct(fator_r)} "
                  f"→ {'Anexo III' if fator_r >= D(fr_regra.p['limiar']) else 'Anexo V'}", regra="SN.FATOR_R")

    teto_iss = D(mem.regra("SN.TETO_ISS").p["teto"])
    seg = mem.regra("SN.SEGREGACAO").p["tipos"]
    resultado_parcelas = []
    total = ZERO
    total_sem_segregacao = ZERO
    por_tributo: dict = {}
    for p in parcelas:
        anexo = p.get("anexo") or "I"
        if anexo == "FATOR_R":
            anexo = "III" if fator_r >= D(fr_regra.p["limiar"]) else "V"
        regra = mem.regra(f"SN.ANEXO.{anexo}")
        f, ef = aliquota_efetiva(regra, rbt12)
        valor = D(p["valor"])
        mem.passo(f"{p.get('descricao') or 'Receita'} — Anexo {anexo}, {f['faixa']}ª faixa",
                  f"({brl(rbt12)} × {pct(f['aliquota'], 2)} − {brl(f['deducao'])}) / {brl(rbt12)} = {pct(ef)}",
                  regra=f"SN.ANEXO.{anexo}")
        reps = reparticao(regra, f, ef, teto_iss, mem)
        excluir = set()
        for t in p.get("tipos") or []:
            if t not in seg:
                raise ValueError(f"tipo de segregação desconhecido: {t}")
            excluir |= set(seg[t]["excluir"])
        if excluir:
            mem.passo("Segregação de receita", f"desconsiderados: {', '.join(sorted(excluir & set(reps)))}",
                      regra="SN.SEGREGACAO")
        linhas = {}
        ef_final = ZERO
        for t, perc in reps.items():
            if t in excluir:
                continue
            v = valor * perc
            linhas[t] = v
            ef_final += perc
            por_tributo[t] = por_tributo.get(t, ZERO) + v
        val = sum(linhas.values(), ZERO)
        total += val
        total_sem_segregacao += valor * ef
        mem.passo("Valor da parcela", f"{brl(valor)} × {pct(ef_final)} = {brl(val)}")
        resultado_parcelas.append({
            "descricao": p.get("descricao"), "anexo": anexo, "faixa": f["faixa"], "valor": s(money(valor)),
            "aliquota_nominal": s(f["aliquota"]), "parcela_deduzir": s(f["deducao"]),
            "aliquota_efetiva": s(ef.quantize(D("0.000001"))), "aliquota_efetiva_apos_segregacao": s(ef_final.quantize(D("0.000001"))),
            "tributos_excluidos": sorted(excluir & set(reps)),
            "reparticao": {t: s(v.quantize(D("0.000001"))) for t, v in reps.items()},
            "valores": {t: s(money(v)) for t, v in linhas.items()}, "das": s(money(val))})

    das = money(total)
    saida = {
        "tipo": "simples_nacional", "periodo": periodo, "rbt12_utilizada": s(money(rbt12)),
        "receita_mes": s(money(receita_mes)), "fator_r": s(fator_r.quantize(D("0.0001"))) if fator_r is not None else None,
        "parcelas": resultado_parcelas, "por_tributo": {t: s(money(v)) for t, v in sorted(por_tributo.items())},
        "das": s(das), "aliquota_efetiva_total": s((total / receita_mes).quantize(D("0.000001"))) if receita_mes else "0",
        "economia_segregacao": s(money(total_sem_segregacao) - das), "alertas": alertas}
    if dados.get("das_pago") not in (None, ""):
        pago = money(dados["das_pago"])
        dif = pago - das
        saida["das_pago"] = s(pago)
        saida["diferenca_pago_menos_devido"] = s(dif)
        if dif > D("0.01"):
            saida["alertas"].append({"cor": "AZUL", "texto": f"DAS pago {brl(pago)} maior que o recalculado {brl(das)}: "
                                     f"possível pagamento a maior de {brl(dif)} (restituição/compensação após retificação do PGDAS-D)."})
        elif dif < D("-0.01"):
            saida["alertas"].append({"cor": "VERMELHO", "texto": f"DAS pago {brl(pago)} menor que o recalculado {brl(das)}: "
                                     f"diferença de {brl(-dif)} a regularizar."})
    return mem.fechar(saida)


def curva(motor, anexo: str, data: str, pontos: int = 48) -> list[dict]:
    """Alíquota efetiva × RBT12 (gráfico de alíquotas)."""
    regra = motor.obter(f"SN.ANEXO.{anexo}", data)
    teto = D(regra.p["faixas"][-1]["ate"])
    out = []
    for i in range(1, pontos + 1):
        rbt = teto * i / pontos
        f, ef = aliquota_efetiva(regra, rbt)
        out.append({"rbt12": s(money(rbt)), "faixa": f["faixa"], "nominal": s(f["aliquota"]),
                    "efetiva": s(ef.quantize(D("0.000001")))})
    return out
