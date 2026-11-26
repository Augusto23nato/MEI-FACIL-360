import pytest

from tip import expr
from tip.calc import simples
from tip.regras import RegraInexistente


def test_expr_seguro():
    assert expr.avaliar("max(a - 10, 0) * 2", {"a": 15}) == 10
    for malicioso in ("__import__('os')", "a.__class__", "[x for x in a]", "open('x')", "lambda: 1"):
        with pytest.raises(expr.ErroFormula):
            expr.avaliar(malicioso, {"a": 1})


def test_semente_idempotente(motor):
    assert motor.semear() == 0


def test_vigencia(motor):
    assert motor.obter("SN.ANEXO.I", "2024-05-01").versao == 1
    with pytest.raises(RegraInexistente):
        motor.obter("SN.ANEXO.I", "2017-12-31")       # tabelas anteriores à LC 155/2016 não cadastradas
    assert motor.tentar("LP.LC224.ACRESCIMO", "2025-12-31") is None
    assert motor.obter("LP.LC224.ACRESCIMO", "2026-01-01").situacao == "validar"


def test_versionamento_e_historico(con, motor, usuario):
    r = motor.obter("SN.FATOR_R", "2025-01-01")
    with pytest.raises(ValueError):
        motor.atualizar(r.id, {"parametros": {"limiar": "0.30"}}, "auditor", "")      # motivo obrigatório
    novo = motor.atualizar(r.id, {"parametros": {"limiar": "0.30"}}, "auditor", "teste de alteração")
    assert motor.obter("SN.FATOR_R", "2025-01-01").versao == 2
    hist = motor.historico("SN.FATOR_R")
    assert [h["versao"] for h in hist] == [1, 2] and hist[0]["ativo"] == 0 and hist[1]["id"] == novo
    # cálculo passa a usar a nova versão sem reconstruir nada
    res = simples.simular(motor, {"periodo": "2025-06", "rbt12": 600000, "folha12": 174000,
                                  "parcelas": [{"anexo": "FATOR_R", "valor": 1000}]})
    assert res["parcelas"][0]["anexo"] == "V"            # 29% < 30%
    assert any(x["codigo"] == "SN.FATOR_R" and x["versao"] == 2 for x in res["regras_usadas"])
    trilha = con.execute("SELECT acao FROM auditoria WHERE acao='regra.atualizar'").fetchall()
    assert len(trilha) == 1


def test_nova_vigencia_e_especificidade_uf(motor):
    motor.criar({"codigo": "ICMS.INTERNA", "tributo": "ICMS", "ente": "ESTADUAL", "uf": "SP", "regime": "TODOS",
                 "vigencia_inicio": "2025-01-01", "fundamento": "RICMS/SP (cadastro de teste)", "parametros": {"padrao": "0.18"}},
                "auditor", "cadastro SP")
    assert str(motor.obter("ICMS.INTERNA", "2025-06-01", uf="SP").p["padrao"]) == "0.18"
    assert motor.obter("ICMS.INTERNA", "2025-06-01", uf="RJ").p["padrao"] is None     # genérica, sem alíquota presumida


def test_regra_invalida(motor):
    with pytest.raises(ValueError):
        motor.criar({"codigo": "X", "tributo": "X", "ente": "LUNAR", "regime": "TODOS", "vigencia_inicio": "2025-01-01",
                     "fundamento": "x"}, "a", "m")
    with pytest.raises(expr.ErroFormula):
        motor.criar({"codigo": "X", "tributo": "X", "ente": "FEDERAL", "regime": "TODOS", "vigencia_inicio": "2025-01-01",
                     "fundamento": "x", "formula": "__import__('os')"}, "a", "m")


def test_todas_as_regras_tem_fundamento(motor):
    for r in motor.listar():
        assert r["fundamento"] and len(r["fundamento"]) > 10, r["codigo"]
        assert r["vigencia_inicio"]
