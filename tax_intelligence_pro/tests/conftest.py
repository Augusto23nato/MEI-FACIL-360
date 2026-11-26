import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "exemplos"))

from tip import db, regras, seguranca, servico  # noqa: E402


@pytest.fixture
def con():
    c = db.conectar(":memory:")
    yield c
    c.close()


@pytest.fixture
def motor(con):
    m = regras.MotorRegras(con)
    m.semear()
    return m


@pytest.fixture
def usuario(con):
    uid = seguranca.criar_usuario(con, "auditor", "Auditor Teste", "senha-muito-forte", "admin")
    return {"id": uid, "login": "auditor", "nome": "Auditor Teste", "papel": "admin"}


@pytest.fixture(scope="session")
def exemplos(tmp_path_factory):
    import gerar
    pasta = tmp_path_factory.mktemp("exemplos")
    info = gerar.gerar(pasta)
    return pasta, info


@pytest.fixture
def empresas(con, usuario):
    a = servico.criar_empresa(con, {"cnpj": "11222333000181", "razao_social": "Empresa A", "regime": "LUCRO_REAL", "uf": "SP"}, usuario)
    b = servico.criar_empresa(con, {"cnpj": "44555666000181", "razao_social": "Empresa B", "regime": "SIMPLES_NACIONAL", "uf": "SP",
                                    "anexo_padrao": "I"}, usuario)
    return a, b
