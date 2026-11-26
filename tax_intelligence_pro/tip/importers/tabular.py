"""Importação de planilhas (CSV/XLSX/JSON) com padronização por perfil de software.

Cada perfil (Fortes, Domínio, Alterdata, SCI ou genérico) traduz os nomes de
colunas exportados para os campos canônicos. Quando o arquivo tem uma linha por
ITEM, as linhas com a mesma chave/número são agrupadas num documento.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path

from ..num import D, s
from .base import ArquivoInvalido, Lote, texto

PERFIS = Path(__file__).resolve().parent.parent.parent / "regras" / "perfis_importacao.json"
TIPOS = ("documentos", "apuracao", "balancete", "pgdas", "dctfweb", "pagamentos")


def norm(nome: str) -> str:
    n = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", n).strip("_")


def perfis() -> dict:
    return json.loads(PERFIS.read_text(encoding="utf-8"))


def _aliases(perfil: str, tipo: str) -> dict:
    p = perfis()
    base = {k: list(v) for k, v in p["generico"].get(tipo, {}).items()}
    for k, v in p.get(perfil, {}).get(tipo, {}).items():
        base[k] = list(v) + base.get(k, [])
    return base


def linhas(nome: str, dados: bytes) -> list[dict]:
    n = nome.lower()
    if n.endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError as e:
            raise ArquivoInvalido("leitura de .xlsx requer o pacote openpyxl (pip install openpyxl); ou exporte em CSV") from e
        wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        cab = None
        out = []
        for row in it:
            if cab is None:
                if row and sum(1 for c in row if c not in (None, "")) >= 2:
                    cab = [str(c or "") for c in row]
                continue
            if any(c not in (None, "") for c in row):
                out.append({cab[i]: row[i] for i in range(min(len(cab), len(row)))})
        return out
    if n.endswith(".json"):
        d = json.loads(texto(dados))
        return d if isinstance(d, list) else d.get("linhas", [])
    t = texto(dados)
    amostra = t[:5000]
    delim = ";" if amostra.count(";") > amostra.count(",") else ("\t" if amostra.count("\t") > amostra.count(",") else ",")
    return list(csv.DictReader(io.StringIO(t), delimiter=delim))


def mapear(row: dict, aliases: dict) -> dict:
    nrow = {norm(k): v for k, v in row.items() if k is not None}
    out = {}
    for campo, opcoes in aliases.items():
        for o in [campo] + opcoes:
            if norm(o) in nrow and nrow[norm(o)] not in (None, ""):
                out[campo] = nrow[norm(o)]
                break
    return out


def _data(v) -> str:
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    v = str(v or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return m.group(0)
    m = re.match(r"(\d{2})/(\d{4})$", v)
    if m:
        return f"{m.group(2)}-{m.group(1)}-01"
    m = re.match(r"(\d{4})-?(\d{2})$", v)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    m = re.match(r"(\d{2})(\d{4})$", v)
    if m:
        return f"{m.group(2)}-{m.group(1)}-01"
    raise ValueError(f"data/período inválido: {v!r}")


def _cnpj(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def ler(nome: str, dados: bytes, tipo: str, perfil: str, cnpj_empresa: str) -> Lote:
    if tipo not in TIPOS:
        raise ArquivoInvalido(f"tipo de planilha inválido: {tipo}. Use: {', '.join(TIPOS)}")
    if perfil not in perfis() or perfil.startswith("_"):
        raise ArquivoInvalido(f"perfil desconhecido: {perfil}")
    fonte = f"planilha:{perfil}" if tipo == "documentos" else tipo
    lote = Lote(tipo=f"planilha_{tipo}", fonte=fonte)
    rows = linhas(nome, dados)
    if not rows:
        raise ArquivoInvalido("planilha sem linhas de dados")
    al = _aliases(perfil, tipo)
    faltando = [c for c in {"documentos": ["valor_total"], "apuracao": ["periodo", "tributo", "valor"],
                            "balancete": ["conta"], "pgdas": ["periodo", "receita_bruta"],
                            "dctfweb": ["periodo", "tributo", "valor_debito"], "pagamentos": ["periodo", "tributo", "valor_pago"]}[tipo]
                if not any(norm(o) in {norm(k) for k in rows[0]} for o in [c] + al.get(c, []))]
    if faltando:
        raise ArquivoInvalido(f"colunas obrigatórias não encontradas: {', '.join(faltando)}. Cabeçalho lido: "
                              f"{', '.join(list(rows[0])[:15])}. Ajuste o perfil em regras/perfis_importacao.json")
    periodos = []
    docs: dict = {}
    for i, row in enumerate(rows, 2):
        r = mapear(row, al)
        try:
            if tipo == "documentos":
                dt = _data(r.get("data_emissao")) if r.get("data_emissao") else None
                op = str(r.get("operacao", "")).strip().upper()[:1]
                op = {"0": "E", "1": "S"}.get(op, op if op in ("E", "S") else "")
                emit, dest, part = _cnpj(r.get("cnpj_emit")), _cnpj(r.get("cnpj_dest")), _cnpj(r.get("cnpj_part"))
                if not op:
                    cfop = str(r.get("cfop") or "")
                    op = "E" if cfop[:1] in ("1", "2", "3") else ("S" if cfop[:1] in ("5", "6", "7") else "")
                if not op:
                    lote.aviso(f"linha {i}: operação (entrada/saída) não identificada — linha ignorada")
                    continue
                if not emit and not dest:
                    emit, dest = (part, cnpj_empresa) if op == "E" else (cnpj_empresa, part)
                k = str(r.get("chave") or "").strip() or f"{emit}-{r.get('serie', '')}-{str(r.get('numero', '')).lstrip('0')}"
                doc = docs.get(k)
                if doc is None:
                    doc = {"fonte": fonte, "chave": k if len(k) == 44 else None, "modelo": "55", "operacao": op,
                           "numero": str(r.get("numero", "")).lstrip("0"), "serie": str(r.get("serie", "")),
                           "data_emissao": dt, "periodo": dt[:7] if dt else None, "situacao": "normal",
                           "cnpj_emit": emit, "cnpj_dest": dest, "uf_emit": r.get("uf_emit"), "uf_dest": r.get("uf_dest"),
                           "nome_part": r.get("nome_part"), "valor_total": "0", "vbc_icms": "0", "v_icms": "0", "v_st": "0",
                           "v_ipi": "0", "v_pis": "0", "v_cofins": "0", "v_iss": "0", "extra": {"linha": i, "chave_agrup": k},
                           "itens": []}
                    docs[k] = doc
                for c in ("valor_total", "vbc_icms", "v_icms", "v_st", "v_ipi", "v_pis", "v_cofins", "v_iss"):
                    doc[c] = s(D(doc[c]) + D(r.get(c)))
                if r.get("cfop") or r.get("ncm") or r.get("vprod"):
                    p_icms = D(r.get("p_icms"))
                    doc["itens"].append({"n_item": int(D(r.get("n_item") or len(doc["itens"]) + 1)), "cfop": str(r.get("cfop", "")),
                                         "ncm": str(r.get("ncm", "")), "descricao": r.get("descricao"), "cst_icms": str(r.get("cst_icms", "")),
                                         "vprod": s(D(r.get("vprod") or r.get("valor_total"))), "vbc_icms": s(D(r.get("vbc_icms"))),
                                         "p_icms": s(p_icms / 100 if p_icms > 1 else p_icms), "v_icms": s(D(r.get("v_icms"))),
                                         "v_st": s(D(r.get("v_st"))), "v_ipi": s(D(r.get("v_ipi"))), "cst_pis": str(r.get("cst_pis", "")),
                                         "v_pis": s(D(r.get("v_pis"))), "cst_cofins": str(r.get("cst_cofins", "")),
                                         "v_cofins": s(D(r.get("v_cofins"))), "extra": {"linha": i}})
                if dt:
                    periodos.append(dt[:7])
            elif tipo == "balancete":
                per = _data(r["periodo"])[:7] if r.get("periodo") else None
                lote.saldos.append({"periodo": per, "conta": str(r["conta"]), "descricao": r.get("descricao"),
                                    "saldo_ini": s(D(r.get("saldo_ini"))), "debitos": s(D(r.get("debitos"))),
                                    "creditos": s(D(r.get("creditos"))), "saldo_fim": s(D(r.get("saldo_fim")))})
                if per:
                    periodos.append(per)
            else:
                per = _data(r["periodo"])[:7]
                periodos.append(per)
                if tipo == "apuracao":
                    lote.apuracoes.append({"tributo": str(r["tributo"]).upper(), "periodo": per,
                                           "campo": str(r.get("campo") or "valor"), "valor": s(D(r["valor"]))})
                elif tipo == "pgdas":
                    for c in ("receita_bruta", "rbt12", "receita_monofasico", "receita_icms_st", "receita_exportacao",
                              "valor_das", "valor_pago"):
                        if r.get(c) not in (None, ""):
                            lote.apuracoes.append({"tributo": "SIMPLES_NACIONAL", "periodo": per, "campo": c, "valor": s(D(r[c]))})
                    if r.get("anexo"):
                        lote.apuracoes.append({"tributo": "SIMPLES_NACIONAL", "periodo": per, "campo": "anexo",
                                               "valor": str(r["anexo"]).upper().replace("ANEXO", "").strip()})
                else:  # dctfweb / pagamentos
                    trib = str(r["tributo"]).upper()
                    for c in ("valor_debito", "valor_pago"):
                        if r.get(c) not in (None, ""):
                            lote.apuracoes.append({"tributo": trib, "periodo": per, "campo": c, "valor": s(D(r[c])),
                                                   "codigo_receita": r.get("codigo_receita")})
        except (ValueError, KeyError) as e:
            lote.aviso(f"linha {i}: {e} — linha ignorada")
    lote.documentos = list(docs.values())
    if periodos:
        lote.periodo_ini, lote.periodo_fim = min(periodos), max(periodos)
    lote.cnpj = cnpj_empresa
    lote.info(f"{len(rows)} linhas lidas; {len(lote.documentos)} documentos, {len(lote.apuracoes)} valores, "
              f"{len(lote.saldos)} saldos (perfil {perfil})")
    return lote
