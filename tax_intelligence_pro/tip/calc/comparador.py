"""Comparativo anual entre Simples Nacional, Lucro Presumido e Lucro Real.

É uma PROJEÇÃO com premissas explícitas (receita distribuída igualmente nos meses,
lucro contábil informado, créditos estimados). ICMS/ISS fora do Simples entram
como valores informados pelo usuário — o sistema não presume alíquotas estaduais
ou municipais.
"""
from __future__ import annotations

from ..num import D, ZERO, money, s
from . import presumido_real, simples


def comparar(motor, dados: dict) -> dict:
    """``dados``: ano; receita_anual; anexo ('I'..'V' ou 'FATOR_R'); folha_anual;
    tipos_receita (segregação Simples, opcional) e percentual_segregado;
    atividade_presumido; lucro_contabil_anual (Lucro Real); adicoes; exclusoes;
    creditos_pis_cofins_base (Real); icms_iss_fora_simples (anual, informado);
    icms_destacado_anual (exclusão da base de PIS/COFINS); cpp_fora_simples (Anexo IV / Presumido / Real, informado);
    regime_atual (para economia)."""
    ano = int(dados["ano"])
    receita = D(dados["receita_anual"])
    if receita <= 0:
        raise ValueError("receita anual deve ser positiva")
    mensal = receita / 12
    cenarios = []
    premissas = ["Receita distribuída igualmente nos 12 meses; RBT12 = receita anual informada."]

    # --- Simples Nacional
    try:
        perc_seg = D(dados.get("percentual_segregado"))
        parcelas = [{"descricao": "Receita", "anexo": dados.get("anexo") or "I", "valor": mensal * (1 - perc_seg)}]
        if perc_seg:
            parcelas.append({"descricao": "Receita segregada", "anexo": dados.get("anexo") or "I",
                             "valor": mensal * perc_seg, "tipos": dados.get("tipos_receita") or []})
        sn = simples.simular(motor, {"periodo": f"{ano}-12", "rbt12": receita, "folha12": dados.get("folha_anual"),
                                     "parcelas": parcelas})
        total_sn = D(sn["das"]) * 12
        extra = ZERO
        if sn["parcelas"][0]["anexo"] == "IV":
            extra = D(dados.get("cpp_fora_simples"))
            premissas.append("Anexo IV: CPP patronal recolhida fora do DAS (valor informado).")
        cenarios.append({"regime": "SIMPLES_NACIONAL", "total": s(money(total_sn + extra)), "detalhe": {
            "das_mensal": sn["das"], "das_anual": s(money(total_sn)), "cpp_fora": s(money(extra)),
            "aliquota_efetiva": sn["aliquota_efetiva_total"], "anexo": sn["parcelas"][0]["anexo"], "fator_r": sn["fator_r"]},
            "alertas": sn["alertas"], "regras": sn["regras_usadas"]})
    except Exception as e:  # noqa: BLE001 — cenário inviável é informação, não erro
        cenarios.append({"regime": "SIMPLES_NACIONAL", "total": None, "erro": str(e)})

    icms_iss = D(dados.get("icms_iss_fora_simples"))
    cpp = D(dados.get("cpp_fora_simples"))
    # --- Lucro Presumido (4 trimestres)
    try:
        tot = ZERO
        trimestres = []
        regras = {}
        for t in range(1, 5):
            r = presumido_real.presumido(motor, {"ano": ano, "trimestre": t,
                                                  "receitas": [{"atividade": dados.get("atividade_presumido") or "comercio",
                                                                "valor": receita / 4}],
                                                  "pis_cofins": {"receita_bruta": receita / 4,
                                                                 "icms_destacado": D(dados.get("icms_destacado_anual")) / 4}})
            tot += D(r["total"])
            trimestres.append(r["total"])
            regras.update({x["codigo"]: x for x in r["regras_usadas"]})
        cenarios.append({"regime": "LUCRO_PRESUMIDO", "total": s(money(tot + icms_iss + cpp)),
                         "detalhe": {"federais": s(money(tot)), "trimestres": trimestres, "icms_iss": s(money(icms_iss)),
                                     "cpp": s(money(cpp))}, "alertas": r["alertas"], "regras": list(regras.values())})
    except Exception as e:  # noqa: BLE001
        cenarios.append({"regime": "LUCRO_PRESUMIDO", "total": None, "erro": str(e)})

    # --- Lucro Real (anual)
    if dados.get("lucro_contabil_anual") not in (None, ""):
        try:
            r = presumido_real.real(motor, {"data_inicio": f"{ano}-01-01", "meses": 12,
                                            "lucro_contabil": dados["lucro_contabil_anual"], "adicoes": dados.get("adicoes"),
                                            "exclusoes": dados.get("exclusoes"), "receita_tributavel": receita,
                                            "icms_destacado": dados.get("icms_destacado_anual"),
                                            "creditos": {"estimados": dados.get("creditos_pis_cofins_base") or 0}})
            cenarios.append({"regime": "LUCRO_REAL", "total": s(money(D(r["total"]) + icms_iss + cpp)),
                             "detalhe": {"federais": r["total"], "icms_iss": s(money(icms_iss)), "cpp": s(money(cpp)),
                                         "pis_credito": r["pis_credito"], "cofins_credito": r["cofins_credito"]},
                             "alertas": r["alertas"], "regras": r["regras_usadas"]})
        except Exception as e:  # noqa: BLE001
            cenarios.append({"regime": "LUCRO_REAL", "total": None, "erro": str(e)})
    else:
        premissas.append("Lucro Real não simulado: informe o lucro contábil anual estimado.")
    if icms_iss or cpp:
        premissas.append("ICMS/ISS e CPP fora do Simples somados conforme valores informados.")

    validos = sorted((c for c in cenarios if c.get("total") is not None), key=lambda c: D(c["total"]))
    for c in cenarios:
        if c.get("total") is not None:
            c["carga_efetiva"] = s((D(c["total"]) / receita).quantize(D("0.000001")))
    out = {"tipo": "comparativo", "ano": ano, "receita_anual": s(money(receita)), "cenarios": cenarios,
           "melhor": validos[0]["regime"] if validos else None, "premissas": premissas,
           "regras_usadas": [r for c in cenarios for r in c.get("regras", [])]}
    atual = dados.get("regime_atual")
    if atual and validos:
        c_atual = next((c for c in validos if c["regime"] == atual), None)
        if c_atual:
            out["economia_potencial"] = s(money(D(c_atual["total"]) - D(validos[0]["total"])))
    return out
