"""Banco de dados (SQLite) e migrações.

SQLite foi escolhido por acompanhar o Python (o projeto não tem dependências de
servidor) e por permitir backup a quente. O esquema usa SQL padrão e valores
monetários como TEXTO decimal, o que facilita migrar para PostgreSQL depois.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TIP_DATA_DIR", RAIZ / "data"))

MIGRACOES = [
    # 1 — esquema base
    """
    CREATE TABLE usuarios (
        id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, nome TEXT NOT NULL,
        senha_hash TEXT NOT NULL, papel TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL, ultimo_login TEXT
    );
    CREATE TABLE sessoes (
        token_hash TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
        criado_em TEXT NOT NULL, expira_em TEXT NOT NULL, ip TEXT
    );
    CREATE TABLE empresas (
        id INTEGER PRIMARY KEY, cnpj TEXT UNIQUE NOT NULL, razao_social TEXT NOT NULL,
        uf TEXT, municipio TEXT, regime TEXT NOT NULL, cnae TEXT, anexo_padrao TEXT,
        atividade_presumido TEXT, contribuinte_ipi INTEGER NOT NULL DEFAULT 0,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE regras (
        id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, versao INTEGER NOT NULL,
        tributo TEXT NOT NULL, ente TEXT NOT NULL, uf TEXT, municipio TEXT, regime TEXT NOT NULL,
        vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT, fundamento TEXT NOT NULL,
        descricao TEXT, criterio TEXT, formula TEXT, parametros TEXT NOT NULL DEFAULT '{}',
        situacao TEXT NOT NULL DEFAULT 'vigente', ativo INTEGER NOT NULL DEFAULT 1,
        hash TEXT NOT NULL, motivo TEXT, criado_por TEXT NOT NULL, criado_em TEXT NOT NULL,
        UNIQUE (codigo, versao)
    );
    CREATE INDEX ix_regras_codigo ON regras(codigo, ativo);
    CREATE TABLE importacoes (
        id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL REFERENCES empresas(id),
        tipo TEXT NOT NULL, fonte TEXT NOT NULL, nome_arquivo TEXT NOT NULL, sha256 TEXT NOT NULL,
        tamanho INTEGER NOT NULL, status TEXT NOT NULL, mensagens TEXT NOT NULL DEFAULT '[]',
        registros INTEGER NOT NULL DEFAULT 0, periodo_ini TEXT, periodo_fim TEXT,
        usuario_id INTEGER, criado_em TEXT NOT NULL
    );
    CREATE INDEX ix_imp_emp ON importacoes(empresa_id, sha256);
    CREATE TABLE documentos (
        id INTEGER PRIMARY KEY, importacao_id INTEGER NOT NULL REFERENCES importacoes(id) ON DELETE CASCADE,
        empresa_id INTEGER NOT NULL, fonte TEXT NOT NULL, chave TEXT, modelo TEXT, operacao TEXT,
        numero TEXT, serie TEXT, data_emissao TEXT, periodo TEXT, situacao TEXT DEFAULT 'normal',
        cnpj_emit TEXT, cnpj_dest TEXT, uf_emit TEXT, uf_dest TEXT, nome_part TEXT, crt_emit TEXT,
        valor_total TEXT, vbc_icms TEXT, v_icms TEXT, v_st TEXT, v_ipi TEXT, v_pis TEXT,
        v_cofins TEXT, v_iss TEXT, v_ibs TEXT, v_cbs TEXT, extra TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX ix_doc_emp ON documentos(empresa_id, periodo, fonte);
    CREATE INDEX ix_doc_chave ON documentos(chave);
    CREATE TABLE itens (
        id INTEGER PRIMARY KEY, documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
        n_item INTEGER, codigo TEXT, descricao TEXT, ncm TEXT, cfop TEXT, cst_icms TEXT, orig TEXT,
        vprod TEXT, vdesc TEXT, vfrete TEXT, vseg TEXT, voutro TEXT,
        vbc_icms TEXT, p_icms TEXT, v_icms TEXT, vbc_st TEXT, v_st TEXT,
        cst_ipi TEXT, p_ipi TEXT, v_ipi TEXT,
        cst_pis TEXT, vbc_pis TEXT, p_pis TEXT, v_pis TEXT,
        cst_cofins TEXT, vbc_cofins TEXT, p_cofins TEXT, v_cofins TEXT,
        p_iss TEXT, v_iss TEXT, p_cred_sn TEXT, v_cred_sn TEXT,
        cst_ibscbs TEXT, v_ibs TEXT, v_cbs TEXT, extra TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX ix_itens_doc ON itens(documento_id);
    CREATE TABLE apuracoes (
        id INTEGER PRIMARY KEY, importacao_id INTEGER NOT NULL REFERENCES importacoes(id) ON DELETE CASCADE,
        empresa_id INTEGER NOT NULL, fonte TEXT NOT NULL, tributo TEXT NOT NULL, periodo TEXT NOT NULL,
        campo TEXT NOT NULL, valor TEXT NOT NULL
    );
    CREATE INDEX ix_apur ON apuracoes(empresa_id, periodo, fonte, tributo);
    CREATE TABLE saldos_contabeis (
        id INTEGER PRIMARY KEY, importacao_id INTEGER NOT NULL REFERENCES importacoes(id) ON DELETE CASCADE,
        empresa_id INTEGER NOT NULL, fonte TEXT NOT NULL, periodo TEXT NOT NULL, conta TEXT NOT NULL,
        descricao TEXT, saldo_ini TEXT, debitos TEXT, creditos TEXT, saldo_fim TEXT
    );
    CREATE TABLE mapa_contas (
        empresa_id INTEGER NOT NULL, conta TEXT NOT NULL, grupo TEXT NOT NULL,
        PRIMARY KEY (empresa_id, conta)
    );
    CREATE TABLE simulacoes (
        id INTEGER PRIMARY KEY, empresa_id INTEGER, tipo TEXT NOT NULL, titulo TEXT,
        entrada TEXT NOT NULL, resultado TEXT NOT NULL, regras_usadas TEXT NOT NULL,
        usuario_id INTEGER, criado_em TEXT NOT NULL, hash TEXT NOT NULL
    );
    CREATE TABLE analises (
        id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL, periodo_ini TEXT NOT NULL,
        periodo_fim TEXT NOT NULL, regime TEXT NOT NULL, resumo TEXT NOT NULL,
        regras_usadas TEXT NOT NULL DEFAULT '[]', usuario_id INTEGER, criado_em TEXT NOT NULL, hash TEXT NOT NULL
    );
    CREATE TABLE achados (
        id INTEGER PRIMARY KEY, analise_id INTEGER NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, tipo TEXT NOT NULL, cor TEXT NOT NULL, tributo TEXT, periodo TEXT,
        titulo TEXT NOT NULL, descricao TEXT NOT NULL, valor TEXT NOT NULL DEFAULT '0',
        confianca TEXT, origem TEXT NOT NULL DEFAULT '{}', fundamento TEXT, memoria TEXT NOT NULL DEFAULT '[]',
        documentacao TEXT, procedimento TEXT, referencia TEXT,
        status TEXT NOT NULL DEFAULT 'pendente_validacao', validacao TEXT NOT NULL DEFAULT '[]'
    );
    CREATE INDEX ix_achados ON achados(analise_id, cor);
    CREATE TABLE auditoria (
        id INTEGER PRIMARY KEY, usuario TEXT, acao TEXT NOT NULL, objeto TEXT, detalhe TEXT NOT NULL DEFAULT '{}',
        ip TEXT, criado_em TEXT NOT NULL, hash_anterior TEXT NOT NULL, hash TEXT NOT NULL
    );
    """,
]


def agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def conectar(caminho: str | os.PathLike | None = None) -> sqlite3.Connection:
    if caminho is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(DATA_DIR, 0o700)  # dados fiscais: só o dono do processo lê (LGPD)
        except OSError:
            pass
        caminho = DATA_DIR / "tip.db"
    con = sqlite3.connect(str(caminho), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if str(caminho) != ":memory:":
        con.execute("PRAGMA journal_mode = WAL")
    migrar(con)
    return con


def migrar(con: sqlite3.Connection) -> int:
    versao = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRACOES[versao:], start=versao + 1):
        con.executescript(sql)
        con.execute(f"PRAGMA user_version = {i}")
        con.commit()
    return con.execute("PRAGMA user_version").fetchone()[0]


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)


def row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("entrada", "resultado", "regras_usadas", "resumo", "parametros", "mensagens", "origem",
              "memoria", "detalhe", "extra", "validacao"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d
