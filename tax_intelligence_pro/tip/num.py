"""Aritmética fiscal exata.

Todo valor monetário e toda alíquota circula como ``Decimal`` — nunca ``float`` —
para que a memória de cálculo seja reproduzível centavo a centavo.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext

getcontext().prec = 34

ZERO = Decimal("0")
UM = Decimal("1")
CENT = Decimal("0.01")


def D(valor) -> Decimal:
    """Converte qualquer entrada em Decimal.

    Aceita: None/'' (→ 0), int, float (via str), Decimal e textos nos formatos
    '1234.56' (XML), '1234,56' (SPED) e '1.234,56' (planilhas brasileiras).
    """
    if valor is None:
        return ZERO
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool):
        return Decimal(int(valor))
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    s = str(valor).strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if s in ("", "-", "--"):
        return ZERO
    negativo = s.startswith("(") and s.endswith(")")
    if negativo:
        s = s[1:-1]
    if s.endswith("%"):
        s = s[:-1]
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        r = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"valor numérico inválido: {valor!r}") from e
    return -r if negativo else r


def money(valor) -> Decimal:
    """Arredonda para centavos (ROUND_HALF_UP, regra usual dos sistemas da RFB)."""
    return D(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def taxa(valor, casas: int = 6) -> Decimal:
    return D(valor).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)


def pct(valor, casas: int = 4) -> str:
    """Formata uma fração (0.0845) como percentual ('8,4500%')."""
    v = (D(valor) * 100).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    return f"{v:,.{casas}f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(valor) -> str:
    v = money(valor)
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def s(valor) -> str:
    """Serializa Decimal como texto canônico (para JSON/banco)."""
    return format(D(valor).normalize(), "f")


def iguais(a, b, tolerancia="0.01") -> bool:
    return abs(D(a) - D(b)) <= D(tolerancia)
