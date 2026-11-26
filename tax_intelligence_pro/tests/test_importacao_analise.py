"""Integração: importação de arquivos reais (gerados) → cruzamentos → achados com valores conhecidos."""
import io
import zipfile
from decimal import Decimal as D

import pytest

from tip import analise, servico
from tip.analise.creditos import avaliar
from tip.importers import importar
from tip.importers.base import ArquivoInvalido, detectar


def _importar_a(con, emp, usuario, pasta):
    a = pasta / "empresa_a_lucro_real"
    xmls = sorted((a / "xml").glob("*.xml"), key=lambda p: "cancel" in p.name)
    for f in xmls:
        assert importar(con, emp["id"], f.name, f.read_bytes(), usuario)["status"] == "concluida"
    for f, op in [("efd_icms_ipi_2026_01.txt", {}), ("efd_contribuicoes_2026_01.txt", {}),
                  ("dctfweb_2026_01.csv", {"tipo_planilha": "dctfweb"}), ("balancete_2026_01.csv", {"tipo_planilha": "balancete"}),
                  ("dominio_livro_saidas_2026_01.csv", {"tipo_planilha": "documentos", "perfil": "dominio"})]:
        r = importar(con, emp["id"], f, (a / f).read_bytes(), usuario, opcoes=op)
        assert r["status"] == "concluida", r
    servico.mapear_contas(con, emp["id"], {"3.1.01": "RECEITA_BRUTA", "2.1.05": "ICMS_A_RECOLHER"}, usuario)


def _por_tipo(res):
    out = {}
    for a in res["achados"]:
        out.setdefault(a["tipo"], []).append(a)
    return out


def test_deteccao(exemplos):
    pasta, _ = exemplos
    a = pasta / "empresa_a_lucro_real"
    assert detectar("x.txt", (a / "efd_icms_ipi_2026_01.txt").read_bytes()) == "efd_icms_ipi"
    assert detectar("x.txt", (a / "efd_contribuicoes_2026_01.txt").read_bytes()) == "efd_contribuicoes"
    assert detectar("n.xml", next((a / "xml").glob("S1-*.xml")).read_bytes()) == "nfe"
    assert detectar("n.xml", next((a / "xml").glob("cancel*.xml")).read_bytes()) == "evento_nfe"
    assert detectar("n.xml", (a / "xml" / "nfse-0001.xml").read_bytes()) == "nfse"


def test_validacao_de_arquivos(con, empresas, usuario):
    emp = empresas[0]
    with pytest.raises(ArquivoInvalido):
        importar(con, emp["id"], "x.exe", b"MZ", usuario)
    with pytest.raises(ArquivoInvalido, match="DTD"):
        importar(con, emp["id"], "x.xml", b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY b "c">]><a>&b;</a>', usuario)
    with pytest.raises(ArquivoInvalido):
        importar(con, emp["id"], "x.xml", b"", usuario)


def test_duplicidade_e_zip(con, empresas, usuario, exemplos):
    pasta, _ = exemplos
    emp = empresas[0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in (pasta / "empresa_a_lucro_real" / "xml").glob("E*.xml"):
            z.writestr("lote/" + f.name, f.read_bytes())
    r = importar(con, emp["id"], "lote.zip", buf.getvalue(), usuario)
    assert r["status"] == "concluida" and r["registros"] == 5
    assert importar(con, emp["id"], "lote.zip", buf.getvalue(), usuario)["status"] == "duplicado"


def test_cnpj_de_outra_empresa(con, empresas, usuario, exemplos):
    pasta, _ = exemplos
    with pytest.raises(ArquivoInvalido, match="pertence"):
        importar(con, empresas[1]["id"], "efd.txt", (pasta / "empresa_a_lucro_real" / "efd_icms_ipi_2026_01.txt").read_bytes(), usuario)


def test_analise_lucro_real(con, motor, empresas, usuario, exemplos):
    pasta, _ = exemplos
    emp = empresas[0]
    _importar_a(con, emp, usuario, pasta)
    res = analise.executar(con, motor, emp["id"], "2026-01", "2026-01", usuario)
    assert all(v["status"] == "ok" for v in res["resumo"]["verificacoes"]), res["resumo"]["verificacoes"]
    t = _por_tipo(res)
    val = lambda tipo, trib=None: sorted(D(a["valor"]) for a in t.get(tipo, []) if trib is None or a["tributo"] == trib)  # noqa: E731

    # créditos
    assert val("CREDITO_NAO_APROVEITADO", "ICMS") == [D("360"), D("900")]       # E5 não escriturada; E2 sem crédito
    assert val("CREDITO_INDEVIDO", "ICMS") == [D("360")]                         # E3 uso e consumo creditado
    assert val("CREDITO_NAO_APROVEITADO", "PIS") == [D("111.21")]                # 256,41 permitido − 145,20 apurado
    assert val("CREDITO_NAO_APROVEITADO", "COFINS") == [D("512.24")]
    # cruzamentos XML × EFD
    assert val("SAIDA_NAO_ESCRITURADA") == [D("4000")]
    assert val("DIVERGENCIA_XML_ESCRITURACAO")[-1] == D("5000") and D("300") in val("DIVERGENCIA_XML_ESCRITURACAO")
    assert t["CANCELADA_ESCRITURADA"][0]["cor"] == "VERMELHO"
    # alíquotas e oportunidades
    assert val("ALIQUOTA_INTERESTADUAL_DIVERGENTE") == [D("400")]                # SP→BA a 12% em vez de 7%
    assert val("ICMS_NA_BASE_PIS_COFINS") == [D("222")]                          # 2.400 × 9,25%
    assert val("MONOFASICO_TRIBUTADO") == [D("92.5")]
    # apuração × declaração × pagamento
    assert val("PAGAMENTO_INDEVIDO", "PIS") == [D("120")]
    assert t["APURACAO_X_DECLARACAO"][0]["tributo"] == "COFINS" and t["APURACAO_X_DECLARACAO"][0]["cor"] == "VERMELHO"
    # retenções, sistemas, contábil, reforma
    assert val("RETENCAO_NAO_DEDUZIDA", "PIS") == [D("65")]
    assert val("DIFERENCA_ENTRE_SISTEMAS") == [D("100")]
    assert "CONTABIL_X_FISCAL" in t and "GRUPO_IBS_CBS_AUSENTE" in t
    assert "APURACAO_ICMS_OK" in t
    # toda oportunidade traz os 7 elementos exigidos (a–g) e nasce pendente de validação
    for a in res["achados"]:
        assert a["status"] == "pendente_validacao"
        if a["cor"] == "AZUL":
            assert a["origem"] and a["fundamento"] and a["memoria"] and a["confianca"] and a["documentacao"] and a["procedimento"]


def test_analise_simples_segregacao(con, motor, empresas, usuario, exemplos):
    pasta, _ = exemplos
    emp = empresas[1]
    b = pasta / "empresa_b_simples"
    for f in (b / "xml").glob("*.xml"):
        importar(con, emp["id"], f.name, f.read_bytes(), usuario)
    importar(con, emp["id"], "pgdas.csv", (b / "pgdas_2026_02.csv").read_bytes(), usuario, opcoes={"tipo_planilha": "pgdas"})
    res = analise.executar(con, motor, emp["id"], "2026-02", "2026-02", usuario)
    seg = {a["titulo"]: D(a["valor"]) for a in res["achados"] if a["tipo"] == "SEGREGACAO_NAO_APLICADA"}
    # monofásico: 13.000 × 7,19% × (12,74% + 2,76%) ; ST: 5.000 × 7,19% × 33,5%
    assert sorted(seg.values()) == [D("120.43"), D("144.88")]
    assert any(a["tipo"] == "DAS_OK" for a in res["achados"])


def test_validacao_de_achado(con, motor, empresas, usuario, exemplos):
    pasta, _ = exemplos
    _importar_a(con, empresas[0], usuario, pasta)
    res = analise.executar(con, motor, empresas[0]["id"], "2026-01", "2026-01", usuario)
    az = next(a for a in res["achados"] if a["cor"] == "AZUL")
    with pytest.raises(ValueError, match="documental prévia"):
        analise.validar(con, az["id"], "validado_juridico", "parecer jurídico favorável", "parecer 1", usuario)
    with pytest.raises(ValueError, match="documentos"):
        analise.validar(con, az["id"], "validado_documental", "conferido com o XML", "", usuario)
    analise.validar(con, az["id"], "validado_documental", "conferido com o XML e o C170", "XML + EFD", usuario)
    r = analise.validar(con, az["id"], "validado_juridico", "fundamento confirmado pelo jurídico", "parecer 12/2026", usuario)
    assert r["status"] == "validado_juridico" and len(r["validacao"]) == 2


def test_credito_nao_e_automatico(motor):
    """Uma mesma compra gera ou não crédito conforme regime, finalidade e fornecedor."""
    item = {"n_item": 1, "cfop": "5102", "vprod": "1000", "v_icms": "180", "vbc_icms": "1000", "cst_pis": "01", "ncm": "84713012"}
    doc = {"fonte": "xml", "data_emissao": "2026-01-10", "cnpj_emit": "12345678000195", "crt_emit": "3"}
    real = {"regime": "LUCRO_REAL"}
    c = {a["tributo"]: a for a in avaliar(item, doc, real, motor, "1102")}
    assert c["ICMS"]["classe"] == "DIREITO" and c["PIS"]["classe"] == "DIREITO"
    assert D(c["PIS"]["valor"]) == D("13.53")                            # (1.000 − 180 ICMS) × 1,65%
    c = {a["tributo"]: a for a in avaliar(item, doc, real, motor, "1556")}
    assert c["ICMS"]["classe"] == "SEM_DIREITO" and c["PIS"]["classe"] == "POTENCIAL"
    c = {a["tributo"]: a for a in avaliar(item, {**doc, "cnpj_emit": "12345678901"}, real, motor, "1102")}
    assert c["PIS"]["classe"] == "SEM_DIREITO"                           # fornecedor pessoa física
    c = {a["tributo"]: a for a in avaliar({**item, "ncm": "30049099"}, doc, real, motor, "1102")}
    assert c["PIS"]["classe"] == "SEM_DIREITO"                           # revenda de monofásico
    assert avaliar(item, doc, {"regime": "SIMPLES_NACIONAL"}, motor, "1102") == []
    c = {a["tributo"]: a for a in avaliar(item, doc, {"regime": "LUCRO_PRESUMIDO"}, motor, "1102")}
    assert set(c) == {"ICMS"}                                            # presumido: PIS/COFINS cumulativos, sem crédito
