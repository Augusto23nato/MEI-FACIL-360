"""Avaliador seguro de fórmulas e critérios das regras tributárias.

As regras guardam fórmulas como texto (ex.: ``(rbt12 * aliquota - deducao) / rbt12``)
para que possam ser alteradas sem reconstruir o sistema. Este módulo avalia esse
texto com uma gramática fechada: aritmética, comparações, lógica, ``x if c else y``
e um punhado de funções puras. Não há acesso a atributos, importações, laços nem
chamadas arbitrárias — o texto de uma regra nunca executa código.
"""
from __future__ import annotations

import ast
from decimal import ROUND_HALF_UP, Decimal

from .num import D

_BIN = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}
_CMP = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _round(v, casas=2):
    return D(v).quantize(Decimal(1).scaleb(-int(casas)), rounding=ROUND_HALF_UP)


_FUNC = {
    "min": lambda *a: min(a),
    "max": lambda *a: max(a),
    "abs": lambda a: abs(a),
    "arred": _round,
    "round": _round,
}


class ErroFormula(ValueError):
    pass


def _ev(node, vars_):
    if isinstance(node, ast.Expression):
        return _ev(node.body, vars_)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or node.value is None:
            return node.value
        if isinstance(node.value, (int, float)):
            return D(str(node.value))
        if isinstance(node.value, str):
            return node.value
        raise ErroFormula(f"constante não permitida: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in vars_:
            v = vars_[node.id]
            return D(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
        if node.id in ("True", "False"):
            return node.id == "True"
        raise ErroFormula(f"variável não informada: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _ev(node.left, vars_), _ev(node.right, vars_)
        if isinstance(node.op, ast.Div) and D(b) == 0:
            raise ErroFormula("divisão por zero na fórmula")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp):
        v = _ev(node.operand, vars_)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.Not):
            return not v
    if isinstance(node, ast.BoolOp):
        vals = (_ev(v, vars_) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        esq = _ev(node.left, vars_)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise ErroFormula("comparação não permitida")
            dir_ = _ev(comp, vars_)
            if not _CMP[type(op)](esq, dir_):
                return False
            esq = dir_
        return True
    if isinstance(node, ast.IfExp):
        return _ev(node.body, vars_) if _ev(node.test, vars_) else _ev(node.orelse, vars_)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ev(e, vars_) for e in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNC and not node.keywords:
        return _FUNC[node.func.id](*[_ev(a, vars_) for a in node.args])
    raise ErroFormula(f"elemento não permitido na fórmula: {type(node).__name__}")


def avaliar(texto: str, variaveis: dict):
    """Avalia ``texto`` com ``variaveis``. Fórmula vazia → None."""
    if texto is None or not str(texto).strip():
        return None
    if len(texto) > 2000:
        raise ErroFormula("fórmula longa demais")
    try:
        arvore = ast.parse(str(texto), mode="eval")
    except SyntaxError as e:
        raise ErroFormula(f"sintaxe inválida: {e.msg}") from e
    return _ev(arvore, variaveis)


def validar(texto: str) -> list[str]:
    """Valida a gramática de uma fórmula sem avaliá-la; devolve as variáveis usadas."""
    if not texto or not texto.strip():
        return []
    arvore = ast.parse(texto, mode="eval")
    nomes = []
    for n in ast.walk(arvore):
        permitido = isinstance(n, (ast.Expression, ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.BoolOp,
                                   ast.Compare, ast.IfExp, ast.List, ast.Tuple, ast.Load, ast.And, ast.Or,
                                   ast.Not, ast.USub, ast.UAdd, *_BIN.keys(), *_CMP.keys()))
        if isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id in _FUNC) or n.keywords:
                raise ErroFormula("chamada de função não permitida")
            continue
        if not permitido:
            raise ErroFormula(f"elemento não permitido: {type(n).__name__}")
        if isinstance(n, ast.Name) and n.id not in _FUNC and n.id not in nomes:
            nomes.append(n.id)
    return nomes
