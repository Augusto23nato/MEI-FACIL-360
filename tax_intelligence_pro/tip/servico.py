"""Serviços de aplicação: empresas, simulações com histórico, dashboard e backup/restauração."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from . import db
from .calc import comparador, presumido_real, simples
from .db import agora, js, row
from .num import D, ZERO, money, s
from .seguranca import registrar

REGIMES = ("SIMPLES_NACIONAL", "LUCRO_PRESUMIDO", "LUCRO_REAL")
SIMULADORES = {
    "simples": simples.simular,
    "presumido": presumido_real.presumido,
    "real": presumido_real.real,
    "comparativo": comparador.comparar,
    "reforma": presumido_real.reforma,
}


def cnpj_valido(cnpj: str) -> bool:
    c = re.sub(r"\D", "", cnpj or "")
    if len(c) != 14 or c == c[0] * 14:
        return False
    for n in (12, 13):
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if n == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(c[i]) * pesos[i] for i in range(n))
        dv = 0 if soma % 11 < 2 else 11 - soma % 11
        if int(c[n]) != dv:
            return False
    return True


def criar_empresa(con, dados: dict, usuario: dict) -> dict:
    cnpj = re.sub(r"\D", "", dados.get("cnpj", ""))
    if not cnpj_valido(cnpj):
        raise ValueError("CNPJ inválido (dígitos verificadores)")
    if dados.get("regime") not in REGIMES:
        raise ValueError(f"regime inválido: use {', '.join(REGIMES)}")
    if not (dados.get("razao_social") or "").strip():
        raise ValueError("razão social obrigatória")
    cur = con.execute("INSERT INTO empresas (cnpj, razao_social, uf, municipio, regime, cnae, anexo_padrao, atividade_presumido,"
                      " contribuinte_ipi, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (cnpj, dados["razao_social"].strip(), (dados.get("uf") or "").upper()[:2] or None, dados.get("municipio"),
                       dados["regime"], dados.get("cnae"), dados.get("anexo_padrao"), dados.get("atividade_presumido"),
                       1 if dados.get("contribuinte_ipi") else 0, agora()))
    con.commit()
    registrar(con, usuario["login"], "empresa.criar", f"empresa:{cur.lastrowid}", {"cnpj": cnpj, "regime": dados["regime"]})
    return row(con.execute("SELECT * FROM empresas WHERE id=?", (cur.lastrowid,)).fetchone())


def atualizar_empresa(con, empresa_id: int, dados: dict, usuario: dict) -> dict:
    campos = {k: dados[k] for k in ("razao_social", "uf", "municipio", "regime", "cnae", "anexo_padrao", "atividade_presumido",
                                    "contribuinte_ipi") if k in dados}
    if "regime" in campos and campos["regime"] not in REGIMES:
        raise ValueError("regime inválido")
    if campos:
        con.execute(f"UPDATE empresas SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?", (*campos.values(), empresa_id))
        con.commit()
        registrar(con, usuario["login"], "empresa.atualizar", f"empresa:{empresa_id}", campos)
    return row(con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone())


def mapear_contas(con, empresa_id: int, mapa: dict, usuario: dict):
    grupos = {"RECEITA_BRUTA", "ICMS_A_RECOLHER", "PIS_A_RECOLHER", "COFINS_A_RECOLHER", "ICMS_A_RECUPERAR"}
    for conta, grupo in mapa.items():
        if grupo and grupo not in grupos:
            raise ValueError(f"grupo inválido: {grupo}")
    con.execute("DELETE FROM mapa_contas WHERE empresa_id=?", (empresa_id,))
    for conta, grupo in mapa.items():
        if grupo:
            con.execute("INSERT INTO mapa_contas VALUES (?,?,?)", (empresa_id, str(conta), grupo))
    con.commit()
    registrar(con, usuario["login"], "empresa.mapa_contas", f"empresa:{empresa_id}", {"contas": len(mapa)})


def simular(con, motor, tipo: str, dados: dict, usuario: dict, empresa_id=None, titulo=None, salvar=True) -> dict:
    if tipo not in SIMULADORES:
        raise ValueError(f"simulador desconhecido: {tipo}")
    res = SIMULADORES[tipo](motor, dados)
    if salvar:
        corpo = js({"tipo": tipo, "entrada": dados, "resultado": res})
        h = hashlib.sha256(corpo.encode()).hexdigest()
        cur = con.execute("INSERT INTO simulacoes (empresa_id, tipo, titulo, entrada, resultado, regras_usadas, usuario_id, criado_em, hash)"
                          " VALUES (?,?,?,?,?,?,?,?,?)", (empresa_id, tipo, titulo, js(dados), js(res),
                                                          js(res.get("regras_usadas", [])), usuario.get("id"), agora(), h))
        con.commit()
        res["simulacao_id"] = cur.lastrowid
        res["hash"] = h
        registrar(con, usuario.get("login"), "simular", f"simulacao:{cur.lastrowid}", {"tipo": tipo, "hash": h})
    return res


def dashboard(con, empresa_id: int | None) -> dict:
    filtro, args = ("WHERE empresa_id=?", [empresa_id]) if empresa_id else ("", [])
    ult = row(con.execute(f"SELECT * FROM analises {filtro} ORDER BY id DESC LIMIT 1", args).fetchone())
    out = {"empresa_id": empresa_id, "ultima_analise": None, "cores": {}, "categorias": [], "top_oportunidades": [],
           "top_riscos": [], "creditos": {}, "historico_analises": [], "historico_simulacoes": [], "carga": None, "importacoes": []}
    if ult:
        ach = [row(r) for r in con.execute("SELECT * FROM achados WHERE analise_id=?", (ult["id"],))]
        out["ultima_analise"] = {k: ult[k] for k in ("id", "periodo_ini", "periodo_fim", "regime", "criado_em", "hash")}
        out["cores"] = ult["resumo"]["por_cor"]
        out["economia_potencial"] = ult["resumo"]["economia_potencial"]
        out["exposicao_risco"] = ult["resumo"]["exposicao_risco"]
        out["categorias"] = ult["resumo"]["por_categoria"]
        out["top_oportunidades"] = sorted((a for a in ach if a["cor"] == "AZUL"), key=lambda a: -D(a["valor"]))[:8]
        out["top_riscos"] = sorted((a for a in ach if a["cor"] == "VERMELHO"), key=lambda a: -D(a["valor"]))[:8]
        cr = {"identificados": ZERO, "pendentes_validacao": ZERO, "validados": ZERO, "indevidos": ZERO}
        for a in ach:
            if a["categoria"] in ("credito", "credito_acumulado", "retencao", "simples", "monofasico", "oportunidade", "pagamento", "tributacao", "aliquota") and a["cor"] == "AZUL":
                cr["identificados"] += D(a["valor"])
                cr["validados" if a["status"].startswith("validado") else "pendentes_validacao"] += D(a["valor"]) if a["status"] != "descartado" else 0
            if a["tipo"] in ("CREDITO_INDEVIDO", "CREDITO_DUPLICADO", "CREDITO_INCOMPATIVEL"):
                cr["indevidos"] += D(a["valor"])
        out["creditos"] = {k: s(money(v)) for k, v in cr.items()}
        cred_usados = ZERO
        for r in con.execute("SELECT valor FROM apuracoes WHERE empresa_id=? AND periodo BETWEEN ? AND ? AND (campo='E110.VL_TOT_CREDITOS'"
                             " OR campo LIKE 'M100.%.VL_CRED_DESC' OR campo LIKE 'M500.%.VL_CRED_DESC')",
                             (ult["empresa_id"], ult["periodo_ini"], ult["periodo_fim"])):
            cred_usados += D(r["valor"])
        out["creditos"]["utilizados_escrituracao"] = s(money(cred_usados))
    out["historico_analises"] = [{k: r[k] for k in ("id", "periodo_ini", "periodo_fim", "criado_em")} | {
        "economia": json.loads(r["resumo"])["economia_potencial"], "risco": json.loads(r["resumo"])["exposicao_risco"]}
        for r in con.execute(f"SELECT * FROM analises {filtro} ORDER BY id DESC LIMIT 12", args)]
    out["historico_simulacoes"] = [{"id": r["id"], "tipo": r["tipo"], "titulo": r["titulo"], "criado_em": r["criado_em"],
                                    "total": _total_sim(json.loads(r["resultado"]))}
                                   for r in con.execute(f"SELECT * FROM simulacoes {filtro} ORDER BY id DESC LIMIT 15", args)]
    comp = con.execute(f"SELECT resultado FROM simulacoes {filtro + (' AND' if filtro else 'WHERE')} tipo='comparativo' "
                       "ORDER BY id DESC LIMIT 1", args).fetchone()
    if comp:
        out["carga"] = json.loads(comp["resultado"])
    out["importacoes"] = [dict(r) for r in con.execute(
        f"SELECT id, tipo, fonte, nome_arquivo, status, registros, periodo_ini, periodo_fim, criado_em FROM importacoes {filtro} "
        "ORDER BY id DESC LIMIT 15", args)]
    return out


def _total_sim(r: dict):
    return r.get("das") or r.get("total") or (r.get("cenarios") and r.get("melhor")) or r.get("cbs_liquida")


# ------------------------------------------------------------------ backup
def backup(con, usuario: dict, destino: Path | None = None) -> dict:
    pasta = Path(destino or db.DATA_DIR / "backups")
    pasta.mkdir(parents=True, exist_ok=True)
    nome = pasta / f"tip-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    alvo = sqlite3.connect(str(nome))
    with alvo:
        con.backup(alvo)
    alvo.close()
    os.chmod(nome, 0o600)
    h = hashlib.sha256(nome.read_bytes()).hexdigest()
    (nome.with_suffix(".sha256")).write_text(f"{h}  {nome.name}\n")
    chave = os.environ.get("TIP_BACKUP_KEY")
    cifrado = False
    if chave:  # cifragem opcional em repouso (Fernet/AES) — recomendada para cópias fora do servidor
        from cryptography.fernet import Fernet
        nome.with_suffix(".db.enc").write_bytes(Fernet(chave.encode()).encrypt(nome.read_bytes()))
        nome.unlink()
        cifrado = True
    registrar(con, usuario["login"], "backup", nome.name, {"sha256": h, "cifrado": cifrado})
    return {"arquivo": nome.name + (".enc" if cifrado else ""), "sha256": h, "cifrado": cifrado}


def listar_backups(destino: Path | None = None) -> list[dict]:
    pasta = Path(destino or db.DATA_DIR / "backups")
    if not pasta.exists():
        return []
    return [{"arquivo": p.name, "tamanho": p.stat().st_size} for p in sorted(pasta.glob("tip-*.db*"), reverse=True)
            if not p.name.endswith(".sha256")]


def restaurar(caminho_db: Path, arquivo: str, destino: Path | None = None) -> dict:
    """Restaura um backup verificando hash e integridade. O banco atual é preservado como .antes-restauracao."""
    pasta = Path(destino or db.DATA_DIR / "backups")
    if "/" in arquivo or ".." in arquivo:
        raise ValueError("nome de backup inválido")
    origem = pasta / arquivo
    if not origem.exists():
        raise LookupError("backup inexistente")
    dados = origem.read_bytes()
    if arquivo.endswith(".enc"):
        from cryptography.fernet import Fernet
        dados = Fernet(os.environ["TIP_BACKUP_KEY"].encode()).decrypt(dados)
        manifesto = pasta / arquivo.replace(".db.enc", ".sha256")
    else:
        manifesto = origem.with_suffix(".sha256")
    if manifesto.exists() and manifesto.read_text().split()[0] != hashlib.sha256(dados).hexdigest():
        raise ValueError("hash do backup não confere: arquivo alterado ou corrompido")
    tmp = Path(str(caminho_db) + ".restaurando")
    tmp.write_bytes(dados)
    t = sqlite3.connect(str(tmp))
    ok = t.execute("PRAGMA integrity_check").fetchone()[0]
    t.close()
    if ok != "ok":
        tmp.unlink()
        raise ValueError(f"backup corrompido: {ok}")
    if Path(caminho_db).exists():
        shutil.copy2(caminho_db, str(caminho_db) + ".antes-restauracao")
    os.replace(tmp, caminho_db)
    return {"restaurado": arquivo, "integridade": ok}
