"""Memória de cálculo: passos legíveis + regras (com versão e hash) efetivamente usadas."""
from __future__ import annotations


class Memoria:
    def __init__(self, motor, data: str, uf: str | None = None):
        self.motor = motor
        self.data = data
        self.uf = uf
        self.passos: list[dict] = []
        self.regras: dict = {}

    def regra(self, codigo: str, **kw):
        r = self.motor.obter(codigo, kw.pop("data", self.data), **kw)
        self.regras[f"{r.codigo}@{r.versao}"] = r.ref()
        if r.situacao == "validar":
            self.passos.append({"titulo": "Atenção", "detalhe": f"A regra {r.codigo} está marcada para validação "
                                "profissional (legislação recente ou lista parcial).", "regra": r.codigo})
        return r

    def passo(self, titulo: str, detalhe: str, regra: str | None = None):
        self.passos.append({"titulo": titulo, "detalhe": detalhe, "regra": regra})

    def fechar(self, resultado: dict) -> dict:
        resultado["memoria"] = self.passos
        resultado["regras_usadas"] = list(self.regras.values())
        resultado["data_referencia"] = self.data
        return resultado
