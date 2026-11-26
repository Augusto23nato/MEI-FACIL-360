"""Estrutura dos achados (divergências, inconsistências e oportunidades).

Cores: VERDE conciliado · AMARELO precisa de análise · VERMELHO inconsistência
relevante · AZUL oportunidade tributária.

Nenhum achado nasce como definitivo: o status inicial é sempre
'pendente_validacao' e só muda por validação documental e jurídica registrada.
"""
from __future__ import annotations

from ..num import D, ZERO, money, s

CORES = ("VERDE", "AMARELO", "VERMELHO", "AZUL")
STATUS = ("pendente_validacao", "validado_documental", "validado_juridico", "descartado")

PROCEDIMENTO_PADRAO = {
    "AZUL": "1) Conferir os documentos de origem listados; 2) confirmar o enquadramento legal na legislação vigente na data "
            "da operação; 3) verificar prazo decadencial/prescricional (5 anos — CTN, arts. 150, §4º, 165 e 168); "
            "4) só então retificar a escrituração/declaração e formalizar o pedido (PER/DCOMP, restituição ou crédito extemporâneo).",
    "VERMELHO": "1) Conferir o documento fiscal e o lançamento na escrituração; 2) identificar a causa (cadastro, parametrização, "
                "lançamento manual); 3) avaliar retificação e eventual recolhimento complementar com acréscimos (denúncia espontânea, CTN art. 138).",
    "AMARELO": "Revisar com o responsável pela escrituração e documentar a justificativa ou a correção.",
    "VERDE": "Nenhuma ação: informação conciliada entre as fontes.",
}


class Achados:
    def __init__(self):
        self.lista: list[dict] = []

    def add(self, *, categoria, tipo, cor, titulo, descricao, tributo=None, periodo=None, valor=ZERO, confianca="media",
            origem=None, fundamento=None, memoria=None, documentacao=None, procedimento=None, referencia=None):
        assert cor in CORES
        self.lista.append({
            "categoria": categoria, "tipo": tipo, "cor": cor, "tributo": tributo, "periodo": periodo, "titulo": titulo,
            "descricao": descricao, "valor": s(money(D(valor))), "confianca": confianca, "origem": origem or {},
            "fundamento": fundamento, "memoria": memoria or [], "documentacao": documentacao,
            "procedimento": procedimento or PROCEDIMENTO_PADRAO[cor], "referencia": referencia,
            "status": "pendente_validacao"})

    def ok(self, categoria, tipo, titulo, descricao, **kw):
        self.add(categoria=categoria, tipo=tipo, cor="VERDE", titulo=titulo, descricao=descricao, confianca="alta", **kw)

    def resumo(self) -> dict:
        r = {c: {"quantidade": 0, "valor": ZERO} for c in CORES}
        por_cat: dict = {}
        for a in self.lista:
            r[a["cor"]]["quantidade"] += 1
            r[a["cor"]]["valor"] += D(a["valor"])
            k = (a["categoria"], a["cor"])
            por_cat[k] = por_cat.get(k, 0) + 1
        return {"por_cor": {c: {"quantidade": v["quantidade"], "valor": s(money(v["valor"]))} for c, v in r.items()},
                "por_categoria": [{"categoria": c, "cor": cor, "quantidade": n} for (c, cor), n in sorted(por_cat.items())],
                "economia_potencial": s(money(r["AZUL"]["valor"])), "exposicao_risco": s(money(r["VERMELHO"]["valor"]))}
