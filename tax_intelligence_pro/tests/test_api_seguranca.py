"""Integração HTTP: autenticação, permissões, importação, análise, relatórios, auditoria e backup."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from tip import seguranca
from tip.servidor import criar_servidor


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("tip.db.DATA_DIR", tmp_path)
    srv, app = criar_servidor("127.0.0.1", 0, tmp_path / "tip.db")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def chamar(metodo, caminho, corpo=None, token=None, headers=None, raw=False):
        dados = corpo if isinstance(corpo, bytes) else (json.dumps(corpo).encode() if corpo is not None else None)
        req = urllib.request.Request(base + caminho, data=dados, method=metodo, headers=headers or {})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as r:
                b = r.read()
                return r.status, (b if raw else json.loads(b))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    chamar.app = app
    yield chamar
    srv.shutdown()


def test_fluxo_completo(api, exemplos):
    pasta, _ = exemplos
    st, r = api("POST", "/api/login", {"login": "admin", "senha": api.app.senha_inicial})
    assert st == 200
    tok = r["token"]
    assert api("GET", "/api/me")[0] == 401
    assert api("POST", "/api/login", {"login": "admin", "senha": "errada-errada"})[0] == 401

    st, emp = api("POST", "/api/empresas", {"cnpj": "11.222.333/0001-81", "razao_social": "Empresa A", "regime": "LUCRO_REAL",
                                             "uf": "SP"}, tok)
    assert st == 200
    assert api("POST", "/api/empresas", {"cnpj": "11.222.333/0001-82", "razao_social": "X", "regime": "LUCRO_REAL"}, tok)[0] == 400

    a = pasta / "empresa_a_lucro_real"
    for f in sorted((a / "xml").glob("*.xml"), key=lambda p: "cancel" in p.name):
        st, r = api("POST", f"/api/importar?empresa={emp['id']}", f.read_bytes(), tok, {"X-Filename": f.name})
        assert st == 200 and r["status"] == "concluida"
    st, r = api("POST", f"/api/importar?empresa={emp['id']}", (a / "efd_icms_ipi_2026_01.txt").read_bytes(), tok,
                {"X-Filename": "efd.txt"})
    assert r["tipo"] == "efd_icms_ipi"

    st, sim = api("POST", "/api/simular/simples", {"empresa_id": emp["id"], "dados": {"periodo": "2026-01", "rbt12": 1000000,
                                                                                    "parcelas": [{"anexo": "I", "valor": 100000}]}}, tok)
    assert st == 200 and sim["das"] == "8450" and sim["simulacao_id"]
    st, html = api("GET", f"/api/simulacoes/{sim['simulacao_id']}/memoria.html", token=tok, raw=True)
    assert b"Mem\xc3\xb3ria de c\xc3\xa1lculo" in html

    st, an = api("POST", "/api/analisar", {"empresa_id": emp["id"], "periodo_ini": "2026-01", "periodo_fim": "2026-01"}, tok)
    assert st == 200 and an["achados"]
    st, html = api("GET", f"/api/analises/{an['id']}/relatorio.html", token=tok, raw=True)
    assert b"Fundamenta" in html and b"Procedimento de valida" in html
    st, dash = api("GET", f"/api/dashboard?empresa={emp['id']}", token=tok)
    assert dash["ultima_analise"]["id"] == an["id"] and dash["cores"]["AZUL"]["quantidade"] > 0

    # permissões: papel leitura não importa nem simula
    st, _ = api("POST", "/api/usuarios", {"login": "leitor", "nome": "Leitor", "senha": "senha-do-leitor", "papel": "leitura"}, tok)
    assert st == 200
    tok2 = api("POST", "/api/login", {"login": "leitor", "senha": "senha-do-leitor"})[1]["token"]
    assert api("GET", "/api/dashboard", token=tok2)[0] == 200
    assert api("POST", "/api/simular/simples", {"dados": {}}, tok2)[0] == 403
    assert api("PUT", "/api/regras/1", {"mudancas": {}, "motivo": "x"}, tok2)[0] == 403
    assert api("GET", "/api/auditoria", token=tok2)[0] == 403

    # regras: alteração gera nova versão com histórico
    r = api("GET", "/api/regras?tributo=SIMPLES_NACIONAL", token=tok)[1]
    fr = next(x for x in r if x["codigo"] == "SN.FATOR_R")
    st, _ = api("PUT", f"/api/regras/{fr['id']}", {"mudancas": {"descricao": "revisada"}, "motivo": "revisão do texto"}, tok)
    assert st == 200 and len(api("GET", "/api/regras/historico/SN.FATOR_R", token=tok)[1]) == 2

    # auditoria íntegra; backup verificável
    st, aud = api("GET", "/api/auditoria", token=tok)
    assert aud["verificacao"]["integra"] and aud["verificacao"]["registros"] > 10
    st, bk = api("POST", "/api/backup", {}, tok)
    assert st == 200 and len(bk["sha256"]) == 64
    st, rs = api("POST", "/api/restaurar", {"arquivo": bk["arquivo"]}, tok)
    assert st == 200 and rs["integridade"] == "ok"
    assert api("GET", "/api/empresas", token=tok)[1][0]["cnpj"] == "11222333000181"


def test_trilha_detecta_adulteracao(con, usuario):
    seguranca.registrar(con, "x", "teste", None, {"a": 1})
    assert seguranca.verificar_trilha(con)["integra"]
    con.execute("UPDATE auditoria SET detalhe='{\"a\": 2}' WHERE acao='teste'")
    assert not seguranca.verificar_trilha(con)["integra"]


def test_senha_e_mascara():
    with pytest.raises(ValueError):
        seguranca.hash_senha("curta")
    h = seguranca.hash_senha("uma-senha-longa")
    assert seguranca.conferir_senha("uma-senha-longa", h) and not seguranca.conferir_senha("outra", h)
    assert seguranca.mascarar({"cpf": "123.456.789-09"})["cpf"].startswith("***")
