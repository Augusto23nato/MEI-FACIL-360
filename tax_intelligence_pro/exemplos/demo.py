"""Carrega a base de demonstração: 2 empresas fictícias, arquivos de exemplo, análises e simulações.

    python exemplos/demo.py            # usa data/tip.db (ou TIP_DATA_DIR)
"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "exemplos"))

import gerar  # noqa: E402
from tip import analise, db, regras, seguranca, servico  # noqa: E402
from tip.importers import importar  # noqa: E402


def main():
    con = db.conectar()
    motor = regras.MotorRegras(con)
    motor.semear()
    senha = seguranca.garantir_admin(con)
    if senha:
        arq = db.DATA_DIR / "SENHA_INICIAL_ADMIN.txt"
        arq.write_text(f"login: admin\nsenha: {senha}\nTroque após o primeiro acesso e apague este arquivo.\n")
        arq.chmod(0o600)
    u = dict(con.execute("SELECT * FROM usuarios WHERE login='admin'").fetchone())
    pasta = Path(tempfile.mkdtemp())
    gerar.gerar(pasta)
    existentes = {r["cnpj"]: r["id"] for r in con.execute("SELECT id, cnpj FROM empresas")}

    def empresa(dados):
        return existentes.get(dados["cnpj"]) or servico.criar_empresa(con, dados, u)["id"]
    ea = empresa({"cnpj": gerar.EMP_A, "razao_social": "Comercial Exemplo A Ltda (fictícia)", "regime": "LUCRO_REAL", "uf": "SP"})
    eb = empresa({"cnpj": gerar.EMP_B, "razao_social": "Loja Exemplo B ME (fictícia)", "regime": "SIMPLES_NACIONAL", "uf": "SP",
                  "anexo_padrao": "I"})
    a = pasta / "empresa_a_lucro_real"
    for f in sorted((a / "xml").glob("*.xml"), key=lambda p: "cancel" in p.name):
        importar(con, ea, f.name, f.read_bytes(), u)
    for f, op in [("efd_icms_ipi_2026_01.txt", {}), ("efd_contribuicoes_2026_01.txt", {}), ("dctfweb_2026_01.csv", {"tipo_planilha": "dctfweb"}),
                  ("balancete_2026_01.csv", {"tipo_planilha": "balancete"}),
                  ("dominio_livro_saidas_2026_01.csv", {"tipo_planilha": "documentos", "perfil": "dominio"})]:
        importar(con, ea, f, (a / f).read_bytes(), u, opcoes=op)
    servico.mapear_contas(con, ea, {"3.1.01": "RECEITA_BRUTA", "2.1.05": "ICMS_A_RECOLHER"}, u)
    b = pasta / "empresa_b_simples"
    for f in (b / "xml").glob("*.xml"):
        importar(con, eb, f.name, f.read_bytes(), u)
    importar(con, eb, "pgdas_2026_02.csv", (b / "pgdas_2026_02.csv").read_bytes(), u, opcoes={"tipo_planilha": "pgdas"})
    analise.executar(con, motor, ea, "2026-01", "2026-01", u)
    analise.executar(con, motor, eb, "2026-02", "2026-02", u)
    servico.simular(con, motor, "comparativo", {"ano": 2026, "receita_anual": 4200000, "anexo": "I", "atividade_presumido": "comercio",
                                                "lucro_contabil_anual": 210000, "creditos_pis_cofins_base": 2600000,
                                                "icms_iss_fora_simples": 180000, "regime_atual": "LUCRO_REAL"}, u, ea, "Comparativo 2026")
    servico.simular(con, motor, "comparativo", {"ano": 2026, "receita_anual": 600000, "anexo": "I", "atividade_presumido": "comercio",
                                                "lucro_contabil_anual": 60000, "icms_iss_fora_simples": 54000,
                                                "regime_atual": "SIMPLES_NACIONAL"}, u, eb, "Comparativo 2026")
    print(f"Base de demonstração pronta em {db.DATA_DIR}. Empresas: {ea}, {eb}.")
    if senha:
        print(f"Usuário admin — senha inicial em {db.DATA_DIR / 'SENHA_INICIAL_ADMIN.txt'}")


if __name__ == "__main__":
    main()
