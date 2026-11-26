"""Validação dos cálculos com exemplos tributários conhecidos (conferidos manualmente pela lei)."""
from decimal import Decimal as D

import pytest

from tip.calc import comparador, presumido_real, simples


# ---------------------------------------------------------------- Simples Nacional
@pytest.mark.parametrize("anexo,rbt12,efetiva", [
    # (RBT12 × Aliq − PD) / RBT12 — LC 123, art. 18, §1º-A
    ("I", 180000, D("0.04")),                       # 1ª faixa: efetiva = nominal
    ("I", 1000000, D("0.0845")),                    # (1.000.000×10,7% − 22.500)/1.000.000
    ("II", 500000, D("0.072280")),                  # (500.000×10% − 13.860)/500.000
    ("III", 500000, D("0.09972")),                  # (500.000×13,5% − 17.640)/500.000
    ("IV", 2000000, D("0.128110")),                 # (2.000.000×22% − 183.780)/2.000.000
    ("V", 300000, D("0.165")),                      # (300.000×18% − 4.500)/300.000
])
def test_aliquota_efetiva(motor, anexo, rbt12, efetiva):
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": rbt12, "parcelas": [{"anexo": anexo, "valor": 10000}]})
    assert D(r["parcelas"][0]["aliquota_efetiva"]) == efetiva.quantize(D("0.000001"))


def test_das_anexo_i_com_reparticao(motor):
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 1000000, "parcelas": [{"anexo": "I", "valor": 100000}]})
    assert r["das"] == "8450"
    # repartição da 4ª faixa do Anexo I: ICMS 33,5% de 8,45% × 100.000
    assert r["por_tributo"]["ICMS"] == "2830.75"
    assert sum(D(v) for v in r["por_tributo"].values()) == D("8450.00")


def test_teto_iss_anexo_iii_faixa5(motor):
    # efetiva (3.000.000×21% − 125.640)/3.000.000 = 16,812%; ISS 33,5% → 5,632% > 5% → ISS fixado em 5%
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 3000000, "parcelas": [{"anexo": "III", "valor": 250000}]})
    assert r["por_tributo"]["ISS"] == "12500"
    assert D(r["das"]) == D("42030")         # total preservado: só a repartição muda
    assert any("Teto do ISS" in p["titulo"] for p in r["memoria"])


def test_fator_r(motor):
    base = {"periodo": "2025-06", "rbt12": 600000, "parcelas": [{"anexo": "FATOR_R", "valor": 50000}]}
    r = simples.simular(motor, {**base, "folha12": 200000})            # 33% ≥ 28% → Anexo III
    assert r["parcelas"][0]["anexo"] == "III" and r["das"] == "5280"
    r = simples.simular(motor, {**base, "folha12": 100000})            # 16,7% → Anexo V
    assert r["parcelas"][0]["anexo"] == "V"
    # Anexo V, 3ª faixa: (600.000×19,5% − 9.900)/600.000 = 17,85% × 50.000
    assert r["das"] == "8925"


def test_segregacao_monofasico_e_st(motor):
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 1000000, "parcelas": [
        {"anexo": "I", "valor": 50000}, {"anexo": "I", "valor": 50000, "tipos": ["monofasico", "icms_st"]}]})
    # 2ª parcela: 8,45% × (1 − 12,74% − 2,76% − 33,5%) = 4,3095%
    assert r["parcelas"][1]["das"] == "2154.75"
    assert r["das"] == "6379.75"
    assert r["economia_segregacao"] == "2070.25"


def test_inicio_de_atividade(motor):
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 0, "meses_atividade": 1, "parcelas": [{"anexo": "I", "valor": 20000}]})
    assert r["rbt12_utilizada"] == "240000"          # receita do mês × 12 (art. 18, §2º)


def test_alertas_limites(motor):
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 4000000, "parcelas": [{"anexo": "I", "valor": 100}]})
    assert any(a["cor"] == "AMARELO" and "sublimite" in a["texto"] for a in r["alertas"])
    r = simples.simular(motor, {"periodo": "2025-06", "rbt12": 1000000, "das_pago": 9000, "parcelas": [{"anexo": "I", "valor": 100000}]})
    assert any(a["cor"] == "AZUL" for a in r["alertas"]) and r["diferenca_pago_menos_devido"] == "550"


def test_curva(motor):
    c = simples.curva(motor, "III", "2025-01-01", 12)
    assert len(c) == 12 and D(c[-1]["efetiva"]) > D(c[0]["efetiva"])


# ---------------------------------------------------------------- Lucro Presumido
def test_presumido_servicos(motor):
    r = presumido_real.presumido(motor, {"ano": 2025, "trimestre": 1, "receitas": [{"atividade": "servicos", "valor": 300000}]})
    # base 96.000: IRPJ 14.400 + adicional (96.000 − 60.000)×10% = 3.600; CSLL 8.640; PIS 1.950; COFINS 9.000
    assert r["a_recolher"] == {"IRPJ": "18000", "CSLL": "8640", "PIS": "1950", "COFINS": "9000"}
    assert r["total"] == "37590"


def test_presumido_comercio_sem_adicional_e_exclusao_icms(motor):
    r = presumido_real.presumido(motor, {"ano": 2025, "trimestre": 2, "receitas": [{"atividade": "comercio", "valor": 500000}],
                                         "pis_cofins": {"receita_bruta": 500000, "icms_destacado": 90000}})
    assert r["base_irpj"] == "40000" and r["irpj_adicional"] == "0"
    assert r["base_pis_cofins"] == "410000" and r["pis"] == "2665"


def test_presumido_retencoes_e_pagos(motor):
    r = presumido_real.presumido(motor, {"ano": 2025, "trimestre": 1, "receitas": [{"atividade": "servicos", "valor": 300000}],
                                         "retencoes": {"IRPJ": 4500}, "pagos": {"IRPJ": 15000}})
    assert r["a_recolher"]["IRPJ"] == "13500"
    assert any(a["cor"] == "AZUL" for a in r["alertas"])


def test_presumido_lc224_acrescimo(motor):
    r = presumido_real.presumido(motor, {"ano": 2026, "trimestre": 2, "receitas": [{"atividade": "servicos", "valor": 2000000}]})
    # 2.000.000×32% + (2.000.000 − 1.250.000)×32%×10% = 640.000 + 24.000
    assert r["base_irpj"] == "664000"
    assert any("LC 224" in a["texto"] for a in r["alertas"])
    r1 = presumido_real.presumido(motor, {"ano": 2026, "trimestre": 1, "receitas": [{"atividade": "servicos", "valor": 2000000}]})
    assert r1["base_csll"] == "640000"     # CSLL só após a noventena (abril/2026)
    r0 = presumido_real.presumido(motor, {"ano": 2025, "trimestre": 4, "receitas": [{"atividade": "servicos", "valor": 2000000}]})
    assert r0["base_irpj"] == "640000"     # antes da vigência


def test_presumido_atividade_invalida(motor):
    with pytest.raises(ValueError):
        presumido_real.presumido(motor, {"ano": 2025, "trimestre": 1, "receitas": [{"atividade": "xpto", "valor": 1}]})


# ---------------------------------------------------------------- Lucro Real
def test_real_anual(motor):
    r = presumido_real.real(motor, {"data_inicio": "2025-01-01", "meses": 12, "lucro_contabil": 1000000,
                                    "receita_tributavel": 5000000, "creditos": {"revenda": 3000000}})
    # IRPJ 150.000 + (1.000.000 − 240.000)×10% = 226.000; CSLL 90.000
    assert r["a_recolher"] == {"IRPJ": "226000", "CSLL": "90000", "PIS": "33000", "COFINS": "152000"}


def test_real_trava_30(motor):
    r = presumido_real.real(motor, {"data_inicio": "2025-01-01", "meses": 3, "lucro_contabil": 100000,
                                    "prejuizo_fiscal_disponivel": 500000, "base_negativa_disponivel": 10000})
    assert r["base_irpj"] == "70000"       # compensação limitada a 30.000
    assert r["base_csll"] == "90000"


def test_real_saldo_credor(motor):
    r = presumido_real.real(motor, {"data_inicio": "2025-01-01", "meses": 1, "lucro_contabil": 0,
                                    "receita_tributavel": 100000, "creditos": {"revenda": 150000}})
    assert r["saldo_credor"]["PIS"] == "825" and r["a_recolher"]["PIS"] == "0"


# ---------------------------------------------------------------- Comparativo e Reforma
def test_comparativo(motor):
    c = comparador.comparar(motor, {"ano": 2025, "receita_anual": 1200000, "anexo": "FATOR_R", "folha_anual": 400000,
                                    "atividade_presumido": "servicos", "lucro_contabil_anual": 300000, "regime_atual": "SIMPLES_NACIONAL"})
    tot = {x["regime"]: x["total"] for x in c["cenarios"]}
    assert tot["SIMPLES_NACIONAL"] == "156360"    # 12 × 13.030 (Anexo III, 4ª faixa)
    assert tot["LUCRO_PRESUMIDO"] == "150360"     # 4 × 37.590
    assert c["melhor"] == "LUCRO_PRESUMIDO" and c["economia_potencial"] == "6000"


def test_reforma_2026(motor):
    r = presumido_real.reforma(motor, {"ano": 2026, "base": 100000, "creditos_base": 40000})
    assert r["cbs_liquida"] == "540" and r["ibs_liquido"] == "60"


def test_reforma_nao_inventa_aliquota(motor):
    with pytest.raises(ValueError, match="não é presumida"):
        presumido_real.reforma(motor, {"ano": 2027, "base": 100000})
