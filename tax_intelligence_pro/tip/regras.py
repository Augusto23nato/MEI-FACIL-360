"""Motor de regras e legislação.

Cada regra tem: código, tributo, ente federativo (UF/município quando for o caso),
regime, vigência inicial/final, fundamentação legal, critério de aplicação
(expressão), fórmula de cálculo (expressão), parâmetros (tabelas, alíquotas) e
histórico de versões.

* **Vigência** é o tempo jurídico: a regra que vale na DATA DA OPERAÇÃO.
* **Versão** é o histórico de edição do registro: corrigir um parâmetro gera
  a versão N+1, e a versão anterior continua consultável (rastreabilidade).

As regras de partida ficam em ``regras/*.json`` e são carregadas no banco na
primeira execução. Depois disso, a fonte da verdade é o banco: atualizações são
feitas pela API/dashboard, sem reconstruir o sistema.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import expr
from .db import agora, js
from .seguranca import registrar

DIR_SEMENTES = Path(__file__).resolve().parent.parent / "regras"
CAMPOS = ("codigo", "tributo", "ente", "uf", "municipio", "regime", "vigencia_inicio", "vigencia_fim",
          "fundamento", "descricao", "criterio", "formula", "parametros", "situacao")
ENTES = {"FEDERAL", "ESTADUAL", "MUNICIPAL", "NACIONAL"}


class RegraInexistente(LookupError):
    pass


@dataclass
class Regra:
    id: int
    codigo: str
    versao: int
    tributo: str
    ente: str
    regime: str
    vigencia_inicio: str
    vigencia_fim: str | None
    fundamento: str
    parametros: dict
    criterio: str | None = None
    formula: str | None = None
    descricao: str | None = None
    uf: str | None = None
    municipio: str | None = None
    situacao: str = "vigente"
    hash: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def p(self) -> dict:
        return self.parametros

    def aplica(self, contexto: dict) -> bool:
        if not self.criterio:
            return True
        return bool(expr.avaliar(self.criterio, contexto))

    def calcular(self, contexto: dict):
        return expr.avaliar(self.formula, {**_planos(self.parametros), **contexto})

    def ref(self) -> dict:
        """Referência curta gravada junto de cada cálculo (rastreabilidade)."""
        return {"codigo": self.codigo, "versao": self.versao, "vigencia": [self.vigencia_inicio, self.vigencia_fim],
                "fundamento": self.fundamento, "hash": self.hash[:16], "situacao": self.situacao}


def _planos(params: dict) -> dict:
    """Parâmetros escalares disponíveis como variáveis da fórmula (texto numérico → Decimal)."""
    out = {}
    for k, v in params.items():
        if isinstance(v, str):
            try:
                v = Decimal(v)
            except ArithmeticError:
                pass
        if isinstance(v, (Decimal, int, float, str, bool)):
            out[k] = v
    return out


def _dec(obj):
    """Converte números de parâmetros em Decimal (JSON → Decimal sem passar por float)."""
    return json.loads(json.dumps(obj, default=str), parse_float=Decimal, parse_int=Decimal)


def _hash(d: dict) -> str:
    return hashlib.sha256(js({k: d.get(k) for k in CAMPOS}).encode()).hexdigest()


def _validar(d: dict):
    for obrig in ("codigo", "tributo", "ente", "regime", "vigencia_inicio", "fundamento"):
        if not d.get(obrig):
            raise ValueError(f"regra sem o campo obrigatório '{obrig}'")
    if d["ente"] not in ENTES:
        raise ValueError(f"ente inválido: {d['ente']}")
    if d.get("vigencia_fim") and d["vigencia_fim"] < d["vigencia_inicio"]:
        raise ValueError("vigência final anterior à inicial")
    for campo in ("criterio", "formula"):
        if d.get(campo):
            expr.validar(d[campo])


class MotorRegras:
    def __init__(self, con):
        self.con = con
        self._cache: dict = {}

    # ------------------------------------------------------------ carga
    def semear(self, diretorio: Path = DIR_SEMENTES) -> int:
        """Carrega regras de partida que ainda não existem no banco."""
        n = 0
        for arq in sorted(Path(diretorio).glob("*.json")):
            if arq.name.startswith("perfis_"):
                continue
            dados = json.loads(arq.read_text(encoding="utf-8"))
            for d in dados["regras"]:
                if not self.con.execute("SELECT 1 FROM regras WHERE codigo=? AND vigencia_inicio=?",
                                        (d["codigo"], d["vigencia_inicio"])).fetchone():
                    self._inserir(d, versao=1, por="semente:" + arq.name, motivo="carga inicial")
                    n += 1
        self._cache.clear()
        return n

    def _inserir(self, d: dict, versao: int, por: str, motivo: str) -> int:
        _validar(d)
        reg = {k: d.get(k) for k in CAMPOS}
        reg["situacao"] = reg.get("situacao") or "vigente"
        cur = self.con.execute(
            "INSERT INTO regras (codigo, versao, tributo, ente, uf, municipio, regime, vigencia_inicio, vigencia_fim,"
            " fundamento, descricao, criterio, formula, parametros, situacao, hash, motivo, criado_por, criado_em)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (reg["codigo"], versao, reg["tributo"], reg["ente"], reg["uf"], reg["municipio"], reg["regime"],
             reg["vigencia_inicio"], reg["vigencia_fim"], reg["fundamento"], reg["descricao"], reg["criterio"],
             reg["formula"], js(reg.get("parametros") or {}), reg["situacao"], _hash(reg), motivo, por, agora()))
        self.con.commit()
        return cur.lastrowid

    # ------------------------------------------------------------ consulta
    def obter(self, codigo: str, data: str, uf: str | None = None, municipio: str | None = None) -> Regra:
        """Regra vigente em ``data`` (AAAA-MM-DD), na última versão ativa."""
        chave = (codigo, data, uf, municipio)
        if chave in self._cache:
            return self._cache[chave]
        linhas = self.con.execute(
            "SELECT * FROM regras WHERE codigo=? AND ativo=1 AND vigencia_inicio<=? "
            "AND (vigencia_fim IS NULL OR vigencia_fim>=?) ORDER BY vigencia_inicio DESC, versao DESC",
            (codigo, data, data)).fetchall()
        escolhida = None
        for r in linhas:  # a mais específica (município > UF > nacional) vence
            if r["municipio"] and r["municipio"] != municipio:
                continue
            if r["uf"] and r["uf"] != uf:
                continue
            if escolhida is None or (bool(r["municipio"]), bool(r["uf"])) > (bool(escolhida["municipio"]), bool(escolhida["uf"])):
                escolhida = r
        if escolhida is None:
            raise RegraInexistente(f"nenhuma regra '{codigo}' vigente em {data}"
                                   + (f" para {uf}" if uf else "") + " — cadastre-a no motor de regras")
        regra = self._montar(escolhida)
        self._cache[chave] = regra
        return regra

    def tentar(self, codigo: str, data: str, **kw) -> Regra | None:
        try:
            return self.obter(codigo, data, **kw)
        except RegraInexistente:
            return None

    def _montar(self, r) -> Regra:
        return Regra(id=r["id"], codigo=r["codigo"], versao=r["versao"], tributo=r["tributo"], ente=r["ente"],
                     regime=r["regime"], vigencia_inicio=r["vigencia_inicio"], vigencia_fim=r["vigencia_fim"],
                     fundamento=r["fundamento"], parametros=_dec(json.loads(r["parametros"])), criterio=r["criterio"],
                     formula=r["formula"], descricao=r["descricao"], uf=r["uf"], municipio=r["municipio"],
                     situacao=r["situacao"], hash=r["hash"])

    def listar(self, tributo: str | None = None, regime: str | None = None, data: str | None = None) -> list[dict]:
        sql = "SELECT * FROM regras WHERE ativo=1"
        args: list = []
        if tributo:
            sql += " AND tributo=?"
            args.append(tributo)
        if regime:
            sql += " AND regime IN (?, 'TODOS')"
            args.append(regime)
        if data:
            sql += " AND vigencia_inicio<=? AND (vigencia_fim IS NULL OR vigencia_fim>=?)"
            args += [data, data]
        sql += " ORDER BY codigo, vigencia_inicio"
        out = []
        for r in self.con.execute(sql, args):
            d = dict(r)
            d["parametros"] = json.loads(d["parametros"])
            out.append(d)
        return out

    def historico(self, codigo: str) -> list[dict]:
        rows = self.con.execute("SELECT * FROM regras WHERE codigo=? ORDER BY vigencia_inicio, versao", (codigo,))
        out = []
        for r in rows:
            d = dict(r)
            d["parametros"] = json.loads(d["parametros"])
            out.append(d)
        return out

    # ------------------------------------------------------------ alteração
    def atualizar(self, regra_id: int, mudancas: dict, por: str, motivo: str) -> int:
        """Gera nova versão de um registro de regra; a anterior fica inativa, mas preservada."""
        if not motivo or len(motivo.strip()) < 5:
            raise ValueError("informe o motivo da alteração (histórico obrigatório)")
        atual = self.con.execute("SELECT * FROM regras WHERE id=?", (regra_id,)).fetchone()
        if not atual:
            raise RegraInexistente(f"regra id {regra_id} inexistente")
        if not atual["ativo"]:
            raise ValueError("só a versão ativa pode ser alterada")
        base = dict(atual)
        base["parametros"] = json.loads(base["parametros"])
        novo = {**{k: base.get(k) for k in CAMPOS}, **{k: v for k, v in mudancas.items() if k in CAMPOS}}
        novo["codigo"] = base["codigo"]
        _validar(novo)
        versao = self.con.execute("SELECT MAX(versao) FROM regras WHERE codigo=?", (base["codigo"],)).fetchone()[0] + 1
        self.con.execute("UPDATE regras SET ativo=0 WHERE id=?", (regra_id,))
        novo_id = self._inserir(novo, versao, por, motivo)
        registrar(self.con, por, "regra.atualizar", f"regra:{base['codigo']}",
                  {"de_versao": base["versao"], "para_versao": versao, "motivo": motivo,
                   "campos": sorted(k for k in mudancas if k in CAMPOS)})
        self._cache.clear()
        return novo_id

    def criar(self, dados: dict, por: str, motivo: str) -> int:
        """Nova regra (ou nova vigência de um código existente, p.ex. mudança de lei)."""
        ja = self.con.execute("SELECT MAX(versao) FROM regras WHERE codigo=?", (dados.get("codigo"),)).fetchone()[0]
        rid = self._inserir(dados, (ja or 0) + 1, por, motivo or "criação")
        registrar(self.con, por, "regra.criar", f"regra:{dados['codigo']}",
                  {"vigencia_inicio": dados.get("vigencia_inicio"), "motivo": motivo})
        self._cache.clear()
        return rid
