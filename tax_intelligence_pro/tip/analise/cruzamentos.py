"""Motor de cruzamento: documentos fiscais × escriturações × apurações × declarações × contabilidade."""
from __future__ import annotations

import json
from collections import defaultdict

from ..num import D, ZERO, brl, money, pct, s
from . import creditos as cred
from .achados import Achados

TOL = D("0.01")
CFOP_RECEITA = {f"{i:03d}" for i in range(101, 126)} | {"401", "402", "403", "405", "501", "502", "933", "932"} | \
    {f"{i:03d}" for i in range(651, 668)}
CFOP_DEVOLUCAO_VENDA = {"201", "202", "410", "411"}


class Dados:
    """Carrega, para a empresa e o intervalo de períodos, tudo o que foi importado — por fonte."""

    def __init__(self, con, emp: dict, ini: str, fim: str):
        self.emp, self.ini, self.fim = emp, ini, fim
        docs = [dict(r) for r in con.execute(
            "SELECT * FROM documentos WHERE empresa_id=? AND periodo BETWEEN ? AND ? ORDER BY id", (emp["id"], ini, fim))]
        ids = [d["id"] for d in docs]
        itens = defaultdict(list)
        for i in range(0, len(ids), 900):
            lote = ids[i:i + 900]
            for it in con.execute(f"SELECT * FROM itens WHERE documento_id IN ({','.join('?' * len(lote))}) ORDER BY n_item", lote):
                it = dict(it)
                it["extra"] = json.loads(it["extra"] or "{}")
                itens[it["documento_id"]].append(it)
        cancel = {r["valor"] for r in con.execute("SELECT valor FROM apuracoes WHERE empresa_id=? AND tributo='EVENTO' "
                                                  "AND campo='cancelamento'", (emp["id"],))}
        self.fontes: dict = defaultdict(list)
        for d in docs:
            d["extra"] = json.loads(d["extra"] or "{}")
            d["itens"] = itens.get(d["id"], [])
            if d["fonte"] == "xml" and d["chave"] in cancel:
                d["situacao"] = "cancelada"
            self.fontes[d["fonte"]].append(d)
        self.apur = [dict(r) for r in con.execute(
            "SELECT * FROM apuracoes WHERE empresa_id=? AND periodo BETWEEN ? AND ?", (emp["id"], ini, fim))]
        self.saldos = [dict(r) for r in con.execute(
            "SELECT * FROM saldos_contabeis WHERE empresa_id=? AND periodo BETWEEN ? AND ?", (emp["id"], ini, fim))]
        self.mapa = {r["conta"]: r["grupo"] for r in con.execute("SELECT * FROM mapa_contas WHERE empresa_id=?", (emp["id"],))}
        self.periodos_fonte = defaultdict(set)
        for r in con.execute("SELECT fonte, periodo_ini, periodo_fim FROM importacoes WHERE empresa_id=? AND status='concluida'",
                             (emp["id"],)):
            if r["periodo_ini"]:
                for p in _meses(max(r["periodo_ini"], ini), min(r["periodo_fim"] or r["periodo_ini"], fim)):
                    self.periodos_fonte[r["fonte"]].add(p)

    def unicos(self, fonte: str) -> dict:
        out = {}
        for d in self.fontes.get(fonte, []):
            k = d["chave"] or f"{d['cnpj_emit']}-{d['serie']}-{d['numero']}"
            out.setdefault(k, d)
        return out

    def ap(self, fonte, tributo, periodo, campo):
        v = [D(a["valor"]) for a in self.apur if a["fonte"] == fonte and a["tributo"] == tributo
             and a["periodo"] == periodo and a["campo"] == campo]
        return sum(v, ZERO) if v else None

    def ap_prefixo(self, fonte, tributo, periodo, prefixo, sufixo=""):
        v = [D(a["valor"]) for a in self.apur if a["fonte"] == fonte and a["tributo"] == tributo and a["periodo"] == periodo
             and a["campo"].startswith(prefixo) and a["campo"].endswith(sufixo)]
        return sum(v, ZERO) if v else None


def _meses(ini: str, fim: str):
    a, m = int(ini[:4]), int(ini[5:7])
    while f"{a}-{m:02d}" <= fim:
        yield f"{a}-{m:02d}"
        m += 1
        if m > 12:
            a, m = a + 1, 1


def _ref(d):
    return {"fonte": d["fonte"], "chave": d["chave"], "numero": d["numero"], "serie": d["serie"], "data": d["data_emissao"],
            "participante": d["nome_part"], "documento_id": d["id"], "linha": d["extra"].get("linha")}


class Agregador:
    """Junta ocorrências repetitivas (ex.: alíquota divergente item a item) num achado por tipo/período."""

    def __init__(self):
        self.g = {}

    def add(self, chave, base: dict, valor=ZERO, doc=None, linha_memoria=None):
        if chave not in self.g:
            self.g[chave] = {**base, "valor": ZERO, "n": 0, "docs": [], "memoria": []}
        a = self.g[chave]
        a["valor"] += D(valor)
        a["n"] += 1
        if doc is not None and len(a["docs"]) < 50:
            a["docs"].append(_ref(doc))
        if linha_memoria and len(a["memoria"]) < 60:
            a["memoria"].append(linha_memoria)

    def emitir(self, A: Achados):
        for a in self.g.values():
            n, docs, mem, val = a.pop("n"), a.pop("docs"), a.pop("memoria"), a.pop("valor")
            a["descricao"] = a["descricao"] + f" ({n} ocorrência(s))."
            A.add(valor=val, origem={"documentos": docs, "ocorrencias": n, **a.pop("origem", {})}, memoria=mem, **a)


# =============================================================== 1. integridade
def integridade(dd: Dados, A: Achados):
    for fonte, docs in dd.fontes.items():
        cont = defaultdict(list)
        for d in docs:
            if d["chave"]:
                cont[d["chave"]].append(d)
        for chave, lst in cont.items():
            if len(lst) < 2:
                continue
            d = lst[0]
            if fonte == "xml":
                A.add(categoria="integridade", tipo="XML_DUPLICADO", cor="AMARELO", periodo=d["periodo"],
                      titulo=f"XML importado {len(lst)} vezes", descricao=f"A chave {chave} aparece em {len(lst)} arquivos; "
                      "considerada uma única vez nos cruzamentos.", origem={"documentos": [_ref(x) for x in lst]}, confianca="alta")
            else:
                cred_dup = sum((D(x["v_icms"]) for x in lst[1:]), ZERO) if d["operacao"] == "E" else ZERO
                A.add(categoria="credito" if cred_dup else "integridade",
                      tipo="CREDITO_DUPLICADO" if cred_dup else "DOCUMENTO_DUPLICADO", cor="VERMELHO", tributo="ICMS",
                      periodo=d["periodo"], valor=cred_dup, confianca="alta",
                      titulo="Documento escriturado em duplicidade" + (" — crédito duplicado" if cred_dup else ""),
                      descricao=f"A chave {chave} foi escriturada {len(lst)} vezes na fonte {fonte}.",
                      origem={"documentos": [_ref(x) for x in lst]},
                      fundamento="LC 87/1996, art. 23 (crédito condicionado à idoneidade e à escrituração única do documento)",
                      memoria=[f"crédito excedente = soma do ICMS das {len(lst) - 1} repetição(ões) = {brl(cred_dup)}"],
                      documentacao="Registros C100/C170 duplicados e XML da NF-e")


# =============================================================== 2. XML × escrituração
def xml_x_escrituracao(dd: Dados, A: Achados, fonte_esc: str, campos: tuple, tributo: str):
    esc = dd.unicos(fonte_esc)
    if not esc:
        return
    cobertos = dd.periodos_fonte.get(fonte_esc, set())
    xml = {k: d for k, d in dd.unicos("xml").items() if d["modelo"] in ("55", "57") and d["periodo"] in cobertos}
    if not xml:
        A.add(categoria="cruzamento", tipo="SEM_XML", cor="AMARELO", tributo=tributo, titulo="Sem XML para confronto",
              descricao=f"Há escrituração ({fonte_esc}) mas nenhum XML de NF-e/CT-e nos mesmos períodos.",
              documentacao="XMLs de entrada e saída do período (portal da SEFAZ / Ambiente Nacional)")
        return
    conc = 0
    for k, x in xml.items():
        e = esc.get(k)
        if e is None:
            if x["situacao"] != "normal":
                continue
            if x["operacao"] == "S":
                A.add(categoria="cruzamento", tipo="SAIDA_NAO_ESCRITURADA", cor="VERMELHO", tributo=tributo, periodo=x["periodo"],
                      valor=x["valor_total"], confianca="alta", titulo="Saída com XML autorizado e não escriturada",
                      descricao=f"NF-e {x['numero']}/{x['serie']} ({brl(x['valor_total'])}) não consta em {fonte_esc}: risco de omissão de receita/débito.",
                      origem={"documentos": [_ref(x)]}, fundamento="Ajuste SINIEF 02/2009 (EFD) e IN RFB 1.252/2012 (EFD-Contribuições): escrituração de todos os documentos",
                      documentacao="XML autorizado; relatório de saídas do sistema emissor", memoria=[f"valor do documento {brl(x['valor_total'])}"])
            else:
                A.add(categoria="cruzamento", tipo="ENTRADA_NAO_ESCRITURADA", cor="AMARELO", tributo=tributo, periodo=x["periodo"],
                      valor=0, confianca="alta", titulo="Entrada com XML e não escriturada",
                      descricao=f"NF-e {x['numero']}/{x['serie']} de {x['nome_part'] or x['cnpj_emit']} não consta em {fonte_esc}. "
                      "Verificar recebimento da mercadoria (ou manifestar desconhecimento) e eventual crédito.",
                      origem={"documentos": [_ref(x)]}, documentacao="XML, canhoto/comprovante de recebimento, manifestação do destinatário")
            continue
        if x["situacao"] == "cancelada" and e["situacao"] == "normal":
            A.add(categoria="cruzamento", tipo="CANCELADA_ESCRITURADA", cor="VERMELHO", tributo=tributo, periodo=x["periodo"],
                  valor=e["v_icms"] if tributo == "ICMS" else e["v_pis"], confianca="alta",
                  titulo="NF-e cancelada escriturada como documento regular",
                  descricao=f"A NF-e {x['numero']} tem evento de cancelamento mas está escriturada com situação normal.",
                  origem={"documentos": [_ref(x), _ref(e)]}, documentacao="Evento de cancelamento (110111) e registro C100")
            continue
        difs = [(c, D(x[c]), D(e[c])) for c in campos if abs(D(x[c]) - D(e[c])) > TOL]
        if not difs:
            conc += 1
            continue
        pior_saida = x["operacao"] == "S" and any(c in ("v_icms", "v_pis", "v_cofins") and ve < vx for c, vx, ve in difs)
        A.add(categoria="cruzamento", tipo="DIVERGENCIA_XML_ESCRITURACAO", cor="VERMELHO" if pior_saida else "AMARELO",
              tributo=tributo, periodo=x["periodo"], valor=max(abs(vx - ve) for _, vx, ve in difs), confianca="alta",
              titulo="Divergência entre XML e escrituração",
              descricao=f"NF-e {x['numero']}/{x['serie']} ({'saída' if x['operacao'] == 'S' else 'entrada'}): "
                        + "; ".join(f"{c}: XML {brl(vx)} × {fonte_esc} {brl(ve)}" for c, vx, ve in difs),
              origem={"documentos": [_ref(x), _ref(e)]}, memoria=[f"{c}: diferença {brl(vx - ve)}" for c, vx, ve in difs],
              documentacao="XML da NF-e e registros C100/C170/C190")
    xml_chaves = set(xml)
    sem_xml = [e for k, e in esc.items() if e["modelo"] == "55" and e["situacao"] == "normal" and k not in xml_chaves
               and e["periodo"] in {x["periodo"] for x in xml.values()}]
    for e in sem_xml[:200]:
        A.add(categoria="cruzamento", tipo="ESCRITURADO_SEM_XML", cor="AMARELO", tributo=tributo, periodo=e["periodo"],
              valor=0, confianca="media", titulo="Documento escriturado sem XML na base",
              descricao=f"Documento {e['numero']}/{e['serie']} consta em {fonte_esc} mas o XML não foi importado: "
              "confirmar existência e autorização (risco de crédito sem documento idôneo, se entrada).",
              origem={"documentos": [_ref(e)]}, documentacao="XML / consulta da chave no portal da NF-e")
    if conc:
        A.ok("cruzamento", "CONCILIADO_XML_ESCRITURACAO", f"XML × {fonte_esc} conciliados",
             f"{conc} documento(s) com valores idênticos entre XML e {fonte_esc}.", tributo=tributo,
             origem={"conciliados": conc})


# =============================================================== 3. créditos
def creditos(dd: Dados, A: Achados, motor):
    emp = dd.emp
    efd = {k: d for k, d in dd.unicos("efd_icms_ipi").items() if d["operacao"] == "E"}
    cob_icms = dd.periodos_fonte.get("efd_icms_ipi", set())
    cob_contrib = dd.periodos_fonte.get("efd_contribuicoes", set())
    entradas = [d for d in dd.unicos("xml").values() if d["operacao"] == "E" and d["situacao"] == "normal"]
    pot_periodo = defaultdict(lambda: defaultdict(lambda: ZERO))      # [periodo][tributo] → DIREITO
    potinc_periodo = defaultdict(lambda: defaultdict(lambda: ZERO))   # POTENCIAL
    memo_periodo = defaultdict(lambda: defaultdict(list))
    conciliados = 0
    for x in entradas:
        e = efd.get(x["chave"])
        esc_itens = {i["n_item"]: i for i in (e["itens"] if e else [])}
        cfops_esc = {i["cfop"] for i in esc_itens.values()}
        por_trib = defaultdict(lambda: {"DIREITO": ZERO, "POTENCIAL": ZERO, "motivos": [], "conf": set()})
        itens_x = x["itens"] or []
        if x["modelo"] == "57":  # CT-e de aquisição: frete
            itens_x = [{**i, "cfop": i.get("cfop") or "", "vprod": x["valor_total"]} for i in itens_x]
        for it in itens_x:
            ie = esc_itens.get(it["n_item"])
            cfop_esc = ie["cfop"] if ie else (next(iter(cfops_esc)) if len(cfops_esc) == 1 else None)
            for av in cred.avaliar(it, x, emp, motor, cfop_esc):
                t = por_trib[av["tributo"]]
                if av["classe"] in ("DIREITO", "POTENCIAL"):
                    t[av["classe"]] += av["valor"]
                t["motivos"].append(f"item {it['n_item']} ({(it.get('descricao') or '')[:40]}): {av['classe']} — "
                                    f"{av['motivo']} — {brl(av['valor'])}")
                t["conf"].add(av["confianca"])
                t["fundamento"] = av["fundamento"]
        for trib, t in por_trib.items():
            if trib in ("PIS", "COFINS"):
                pot_periodo[x["periodo"]][trib] += t["DIREITO"]
                potinc_periodo[x["periodo"]][trib] += t["POTENCIAL"]
                memo_periodo[x["periodo"]][trib].append((x, t))
                continue
            if x["periodo"] not in cob_icms:
                continue
            reg = D(e["v_icms"] if trib == "ICMS" else e["v_ipi"]) if e else ZERO
            pot, inc = t["DIREITO"], t["POTENCIAL"]
            conf = "baixa" if "baixa" in t["conf"] else ("media" if "media" in t["conf"] else "alta")
            base = dict(categoria="credito", tributo=trib, periodo=x["periodo"], origem={"documentos": [_ref(x)] + ([_ref(e)] if e else [])},
                        fundamento=t.get("fundamento"), memoria=t["motivos"] + [f"crédito registrado na escrituração: {brl(reg)}"],
                        documentacao="XML da NF-e, comprovante de entrada, registro C170 e, se imobilizado, controle CIAP")
            if reg - (pot + inc) > TOL:
                A.add(tipo="CREDITO_INDEVIDO", cor="VERMELHO", valor=reg - (pot + inc), confianca=conf,
                      titulo=f"Crédito de {trib} possivelmente indevido",
                      descricao=f"NF-e {x['numero']}: escriturado {brl(reg)}; permitido pelas regras {brl(pot + inc)}.", **base)
            elif pot - reg > TOL:
                A.add(tipo="CREDITO_NAO_APROVEITADO", cor="AZUL", valor=pot - reg, confianca=conf,
                      titulo=f"Crédito de {trib} não aproveitado",
                      descricao=f"NF-e {x['numero']} de {x['nome_part'] or x['cnpj_emit']}: crédito permitido {brl(pot)}, escriturado {brl(reg)}"
                                + ("" if e else " (documento não escriturado)") + ".",
                      **{**base, "procedimento": "1) Confirmar a entrada física e a finalidade da mercadoria; 2) confirmar que não houve "
                         "saída isenta que exija estorno; 3) apropriar como crédito extemporâneo conforme o RICMS da UF "
                         "(prazo de 5 anos — LC 87/96, art. 23, parágrafo único)."})
            elif inc > TOL and reg < pot + inc - TOL:
                A.add(tipo="CREDITO_POTENCIAL", cor="AZUL", valor=pot + inc - reg, confianca="baixa",
                      titulo=f"Crédito potencial de {trib} (depende de validação)",
                      descricao=f"NF-e {x['numero']}: itens com enquadramento a confirmar.", **base)
            else:
                conciliados += 1
    if conciliados:
        A.ok("credito", "CREDITOS_CONCILIADOS", "Créditos de ICMS/IPI conciliados",
             f"{conciliados} combinação(ões) documento × tributo com crédito escriturado igual ao permitido.")

    # PIS/COFINS: confronto por período com M100/M500 (crédito efetivamente apurado)
    for per in sorted(set(pot_periodo) | set(potinc_periodo)):
        for trib, reg_prefixo in (("PIS", "M100."), ("COFINS", "M500.")):
            pot, inc = pot_periodo[per][trib], potinc_periodo[per][trib]
            if per not in cob_contrib:
                if pot + inc > TOL:
                    A.add(categoria="credito", tipo="CREDITO_SEM_ESCRITURACAO", cor="AMARELO", tributo=trib, periodo=per,
                          valor=pot + inc, confianca="baixa", titulo=f"Créditos de {trib} calculados sem EFD-Contribuições",
                          descricao=f"Créditos calculados a partir dos XML ({brl(pot)} com direito + {brl(inc)} potenciais); "
                          "importe a EFD-Contribuições do período para confrontar com o apurado.")
                continue
            reg = dd.ap_prefixo("efd_contribuicoes", trib, per, reg_prefixo, ".VL_CRED") or ZERO
            mem = []
            for x, t in memo_periodo[per][trib][:40]:
                mem += [f"NF-e {x['numero']}: " + m for m in t["motivos"][:5]]
            mem.append(f"crédito com direito {brl(pot)} + potencial {brl(inc)}; apurado em {reg_prefixo[:-1]} {brl(reg)}")
            base = dict(categoria="credito", tributo=trib, periodo=per, memoria=mem,
                        fundamento="Lei 10.637/2002 e Lei 10.833/2003, art. 3º; STJ Tema 779",
                        origem={"fontes": ["xml", "efd_contribuicoes"], "registro": reg_prefixo[:-1]},
                        documentacao="XMLs de entrada, registros C170/M100/M500, laudo/descrição do processo para insumos")
            if pot - reg > TOL:
                A.add(tipo="CREDITO_NAO_APROVEITADO", cor="AZUL", valor=pot - reg, confianca="media",
                      titulo=f"Crédito de {trib} não cumulativo não aproveitado",
                      descricao=f"{per}: créditos com direito pelos XML {brl(pot)} × apurado {brl(reg)}.",
                      **{**base, "procedimento": "1) Conferir a classificação de cada item (finalidade e CST do fornecedor); 2) excluir "
                         "itens monofásicos/alíquota zero; 3) retificar a EFD-Contribuições (crédito extemporâneo em até 5 anos) "
                         "e a DCTFWeb; 4) PER/DCOMP somente após a retificação."})
            elif reg - (pot + inc) > TOL:
                A.add(tipo="CREDITO_INDEVIDO", cor="VERMELHO", valor=reg - (pot + inc), confianca="media",
                      titulo=f"Crédito de {trib} apurado acima do suportado pelos documentos",
                      descricao=f"{per}: apurado {brl(reg)} × suportado pelos XML {brl(pot + inc)}.", **base)
            elif inc > TOL and reg < pot + inc - TOL:
                A.add(tipo="CREDITO_POTENCIAL", cor="AZUL", valor=pot + inc - reg, confianca="baixa",
                      titulo=f"Crédito potencial de {trib} a validar (insumos/imobilizado)",
                      descricao=f"{per}: {brl(inc)} em itens que dependem de análise de essencialidade/imobilização.", **base)
            else:
                A.ok("credito", "CREDITOS_CONCILIADOS", f"Créditos de {trib} conciliados ({per})",
                     f"Apurado {brl(reg)} compatível com os documentos.", tributo=trib, periodo=per)

    # Créditos incompatíveis com a natureza da operação (item a item na escrituração)
    if emp["regime"] in ("LUCRO_PRESUMIDO", "LUCRO_REAL"):
        ag = Agregador()
        com_xml = {d["chave"] for d in entradas}   # esses já foram confrontados documento a documento acima
        for e in dd.unicos("efd_icms_ipi").values():
            if e["operacao"] != "E" or e["chave"] in com_xml:
                continue
            r = motor.obter("CRED.ICMS", e["data_emissao"] or e["periodo"] + "-01")
            for it in e["itens"]:
                fin = cred.finalidade(it["cfop"], r.p["cfop"])
                if D(it["v_icms"]) > 0 and fin in ("uso_consumo", "st", "sem_credito"):
                    ag.add(("INCOMP_ICMS", e["periodo"], fin), dict(
                        categoria="credito", tipo="CREDITO_INCOMPATIVEL", cor="VERMELHO", tributo="ICMS", periodo=e["periodo"],
                        titulo=f"Crédito de ICMS em CFOP de {fin.replace('_', ' ')}",
                        descricao=f"Itens escriturados com crédito de ICMS em CFOP incompatível ({fin.replace('_', ' ')})",
                        confianca="alta", fundamento=r.fundamento, documentacao="Registros C170 e XML correspondente"),
                        it["v_icms"], e, f"NF {e['numero']} item {it['n_item']} CFOP {it['cfop']}: ICMS {brl(it['v_icms'])}")
        for e in dd.unicos("efd_contribuicoes").values():   # PIS/COFINS: confronto por período, então item a item sempre
            if e["operacao"] != "E":
                continue
            r = motor.obter("CRED.PISCOFINS.NC", e["data_emissao"] or e["periodo"] + "-01")
            for it in e["itens"]:
                fin = cred.finalidade(it["cfop"], r.p["cfop"])
                if (it["cst_pis"] or "")[:1] in ("5", "6") and fin in ("uso_consumo", "sem_credito"):
                    ag.add(("INCOMP_PIS", e["periodo"], fin), dict(
                        categoria="credito", tipo="CREDITO_INCOMPATIVEL", cor="AMARELO" if fin == "uso_consumo" else "VERMELHO",
                        tributo="PIS/COFINS", periodo=e["periodo"], titulo=f"Crédito de PIS/COFINS em CFOP de {fin.replace('_', ' ')}",
                        descricao="Crédito tomado (CST 50–66) em aquisição de " + fin.replace("_", " ")
                                  + (": exige comprovação de essencialidade/relevância (Tema 779)" if fin == "uso_consumo" else ""),
                        confianca="media", fundamento=r.fundamento, documentacao="C170, laudo técnico do processo produtivo"),
                        D(it["v_pis"]) + D(it["v_cofins"]), e, f"NF {e['numero']} item {it['n_item']} CFOP {it['cfop']} CST {it['cst_pis']}")
        ag.emitir(A)


# =============================================================== 4. apurações
def apuracao_icms(dd: Dados, A: Achados):
    per_e110 = sorted({a["periodo"] for a in dd.apur if a["fonte"] == "efd_icms_ipi" and a["campo"].startswith("E110.")})
    docs = dd.unicos("efd_icms_ipi").values()
    ant_transp = None
    for per in per_e110:
        g = lambda c: dd.ap("efd_icms_ipi", "ICMS", per, "E110." + c) or ZERO  # noqa: E731
        deb_doc = sum((D(c["VL_ICMS"]) for d in docs if d["periodo"] == per and d["operacao"] == "S" and d["situacao"] == "normal"
                       for c in d["extra"].get("c190", [])), ZERO)
        cred_doc = sum((D(c["VL_ICMS"]) for d in docs if d["periodo"] == per and d["operacao"] == "E" and d["situacao"] == "normal"
                        for c in d["extra"].get("c190", [])), ZERO)
        cred_doc += sum((D(d["v_icms"]) for d in docs if d["periodo"] == per and d["operacao"] == "E" and d["modelo"] in ("57", "67")), ZERO)
        problemas = []
        if abs(deb_doc - g("VL_TOT_DEBITOS")) > TOL:
            problemas.append(("débitos", f"C190 saídas {brl(deb_doc)} × E110 VL_TOT_DEBITOS {brl(g('VL_TOT_DEBITOS'))}", deb_doc - g("VL_TOT_DEBITOS")))
        if abs(cred_doc - g("VL_TOT_CREDITOS")) > TOL:
            problemas.append(("créditos", f"C190/D100 entradas {brl(cred_doc)} × E110 VL_TOT_CREDITOS {brl(g('VL_TOT_CREDITOS'))}",
                              g("VL_TOT_CREDITOS") - cred_doc))
        sld = (g("VL_TOT_DEBITOS") + g("VL_AJ_DEBITOS") + g("VL_TOT_AJ_DEBITOS") + g("VL_ESTORNOS_CRED")) - \
              (g("VL_TOT_CREDITOS") + g("VL_AJ_CREDITOS") + g("VL_TOT_AJ_CREDITOS") + g("VL_ESTORNOS_DEB") + g("VL_SLD_CREDOR_ANT"))
        esperado_rec = max(sld, ZERO) - g("VL_TOT_DED")
        esperado_transp = max(-sld, ZERO)
        if abs(max(sld, ZERO) - g("VL_SLD_APURADO")) > TOL or abs(esperado_rec - g("VL_ICMS_RECOLHER")) > TOL \
                or abs(esperado_transp - g("VL_SLD_CREDOR_TRANSPORTAR")) > TOL:
            problemas.append(("aritmética", f"saldo recalculado {brl(sld)}; a recolher esperado {brl(esperado_rec)} × informado "
                              f"{brl(g('VL_ICMS_RECOLHER'))}; credor a transportar esperado {brl(esperado_transp)} × "
                              f"{brl(g('VL_SLD_CREDOR_TRANSPORTAR'))}", esperado_rec - g("VL_ICMS_RECOLHER")))
        e116 = dd.ap("efd_icms_ipi", "ICMS", per, "E116.VL_OR")
        if e116 is not None and abs(e116 - (g("VL_ICMS_RECOLHER") + g("DEB_ESP"))) > TOL:
            problemas.append(("obrigações a recolher", f"E116 {brl(e116)} × E110 a recolher + débitos especiais "
                              f"{brl(g('VL_ICMS_RECOLHER') + g('DEB_ESP'))}", g("VL_ICMS_RECOLHER") + g("DEB_ESP") - e116))
        if ant_transp is not None and ant_transp[0] == _anterior(per) and abs(ant_transp[1] - g("VL_SLD_CREDOR_ANT")) > TOL:
            problemas.append(("saldo credor anterior", f"transportado em {ant_transp[0]} {brl(ant_transp[1])} × saldo anterior "
                              f"informado {brl(g('VL_SLD_CREDOR_ANT'))}", g("VL_SLD_CREDOR_ANT") - ant_transp[1]))
        ant_transp = (per, g("VL_SLD_CREDOR_TRANSPORTAR"))
        for nome, det, val in problemas:
            vermelho = nome in ("débitos", "saldo credor anterior", "aritmética") and val > 0 or (nome == "créditos" and val > 0)
            A.add(categoria="apuracao", tipo="APURACAO_ICMS_DIVERGENTE", cor="VERMELHO" if vermelho else "AMARELO",
                  tributo="ICMS", periodo=per, valor=abs(val), confianca="alta",
                  titulo=f"Apuração do ICMS — divergência de {nome}", descricao=det,
                  origem={"fonte": "efd_icms_ipi", "registros": ["C190", "E110", "E116"]}, memoria=[det],
                  fundamento="Guia Prático da EFD ICMS/IPI — regras de validação do registro E110",
                  documentacao="Livro de apuração (registro E110), registros C190/D190 e guias de recolhimento")
        if not problemas:
            A.ok("apuracao", "APURACAO_ICMS_OK", f"Apuração do ICMS consistente ({per})",
                 "E110 bate com os documentos (C190), com a aritmética do saldo e com o E116.", tributo="ICMS", periodo=per)
    if ant_transp and ant_transp[1] > TOL:
        A.add(categoria="credito_acumulado", tipo="SALDO_CREDOR_ICMS", cor="AZUL", tributo="ICMS", periodo=ant_transp[0],
              valor=ant_transp[1], confianca="baixa", titulo="Saldo credor de ICMS acumulado",
              descricao=f"Saldo credor a transportar de {brl(ant_transp[1])} em {ant_transp[0]}. Avaliar a origem (exportação, "
              "diferimento, alíquota de entrada > saída) e as hipóteses de transferência/utilização previstas no RICMS da UF.",
              fundamento="LC 87/1996, art. 25 (créditos acumulados — utilização conforme legislação estadual)",
              documentacao="Demonstrativo da origem do saldo credor; RICMS da UF (crédito acumulado)",
              origem={"fonte": "efd_icms_ipi", "registro": "E110.VL_SLD_CREDOR_TRANSPORTAR"},
              memoria=[f"E110.VL_SLD_CREDOR_TRANSPORTAR {ant_transp[0]} = {brl(ant_transp[1])}"])


def _anterior(per: str) -> str:
    a, m = int(per[:4]), int(per[5:7]) - 1
    return f"{a - 1}-12" if m == 0 else f"{a}-{m:02d}"


def apuracao_contribuicoes(dd: Dados, A: Achados):
    for per in sorted({a["periodo"] for a in dd.apur if a["fonte"] == "efd_contribuicoes" and a["campo"].startswith(("M200.", "M600."))}):
        for trib, reg in (("PIS", "M200"), ("COFINS", "M600")):
            g = lambda c: dd.ap("efd_contribuicoes", trib, per, f"{reg}.{c}") or ZERO  # noqa: E731
            if dd.ap("efd_contribuicoes", trib, per, f"{reg}.VL_TOT_CONT_REC") is None:
                continue
            dev = g("VL_TOT_CONT_NC_PER") - g("VL_TOT_CRED_DESC") - g("VL_TOT_CRED_DESC_ANT")
            rec_nc = dev - g("VL_RET_NC") - g("VL_OUT_DED_NC")
            rec_cum = g("VL_TOT_CONT_CUM_PER") - g("VL_RET_CUM") - g("VL_OUT_DED_CUM")
            tot = rec_nc + rec_cum
            if abs(dev - g("VL_TOT_CONT_NC_DEV")) > TOL or abs(rec_nc - g("VL_CONT_NC_REC")) > TOL or abs(tot - g("VL_TOT_CONT_REC")) > TOL:
                A.add(categoria="apuracao", tipo="APURACAO_CONTRIB_DIVERGENTE", cor="VERMELHO", tributo=trib, periodo=per,
                      valor=abs(tot - g("VL_TOT_CONT_REC")), confianca="alta", titulo=f"Apuração de {trib} ({reg}) inconsistente",
                      descricao=f"Total a recolher recalculado {brl(tot)} × informado {brl(g('VL_TOT_CONT_REC'))}.",
                      memoria=[f"NC devida = {brl(g('VL_TOT_CONT_NC_PER'))} − créditos {brl(g('VL_TOT_CRED_DESC'))} − anteriores "
                               f"{brl(g('VL_TOT_CRED_DESC_ANT'))} = {brl(dev)}", f"a recolher NC {brl(rec_nc)} + cumulativo {brl(rec_cum)} = {brl(tot)}"],
                      fundamento="Guia Prático da EFD-Contribuições — registros M200/M600", origem={"fonte": "efd_contribuicoes", "registro": reg})
            else:
                A.ok("apuracao", "APURACAO_CONTRIB_OK", f"Apuração de {trib} consistente ({per})", f"{reg} aritmeticamente correto.",
                     tributo=trib, periodo=per)
            sld = dd.ap_prefixo("efd_contribuicoes", trib, per, "M100." if trib == "PIS" else "M500.", ".SLD_CRED")
            if sld and sld > TOL:
                A.add(categoria="credito_acumulado", tipo="SALDO_CREDOR_CONTRIB", cor="AZUL", tributo=trib, periodo=per, valor=sld,
                      confianca="media", titulo=f"Saldo de crédito de {trib} a utilizar",
                      descricao="Créditos não descontados no período: verificar origem (mercado interno, exportação, vendas com "
                      "suspensão/alíquota zero) e possibilidade de compensação/ressarcimento.",
                      fundamento="Lei 10.637/2002, art. 5º; Lei 10.833/2003, art. 6º; Lei 11.033/2004, art. 17; Lei 11.116/2005, art. 16",
                      documentacao="Registros 1100/1500 da EFD-Contribuições, demonstrativo da origem dos créditos",
                      origem={"fonte": "efd_contribuicoes"}, memoria=[f"saldo de crédito (SLD_CRED) {brl(sld)}"])


# =============================================================== 5. apuração × obrigações acessórias / pagamentos
def _trib_norm(t: str) -> str:
    t = (t or "").upper()
    for k in ("COFINS", "PIS", "IRPJ", "CSLL", "ICMS", "IPI", "ISS"):
        if k in t:
            return k
    return "CP" if ("INSS" in t or "PREVID" in t or t == "CP") else t


def apuracao_x_declaracoes(dd: Dados, A: Achados):
    decl = defaultdict(lambda: {"debito": None, "pago": None})
    for a in dd.apur:
        if a["fonte"] in ("dctfweb", "pagamentos"):
            k = (a["periodo"], _trib_norm(a["tributo"]))
            campo = a["campo"].split("#")[0]
            alvo = "debito" if campo == "valor_debito" else "pago"
            decl[k][alvo] = (decl[k][alvo] or ZERO) + D(a["valor"])
    for (per, trib), v in sorted(decl.items()):
        apurado = None
        origem = None
        if trib in ("PIS", "COFINS"):
            apurado = dd.ap("efd_contribuicoes", trib, per, ("M200" if trib == "PIS" else "M600") + ".VL_TOT_CONT_REC")
            origem = "EFD-Contribuições"
        elif trib == "ICMS":
            apurado = dd.ap("efd_icms_ipi", "ICMS", per, "E110.VL_ICMS_RECOLHER")
            origem = "EFD ICMS/IPI (E110)"
        elif trib == "IPI":
            apurado = dd.ap("efd_icms_ipi", "IPI", per, "E520.VL_SD_IPI")
            origem = "EFD ICMS/IPI (E520)"
        if apurado is not None and v["debito"] is not None and abs(apurado - v["debito"]) > TOL:
            A.add(categoria="obrigacoes", tipo="APURACAO_X_DECLARACAO", cor="VERMELHO" if v["debito"] < apurado else "AMARELO",
                  tributo=trib, periodo=per, valor=abs(apurado - v["debito"]), confianca="alta",
                  titulo=f"{trib}: escrituração × declaração divergentes",
                  descricao=f"Apurado na {origem} {brl(apurado)} × declarado (DCTFWeb/declaração) {brl(v['debito'])}.",
                  fundamento="IN RFB 2.005/2021 (DCTFWeb) e IN RFB 1.252/2012 (EFD-Contribuições): débitos declarados devem refletir a escrituração",
                  memoria=[f"diferença {brl(apurado - v['debito'])}"], origem={"fontes": [origem, "dctfweb"]},
                  documentacao="Recibo da DCTFWeb, EFD do período")
        devido = v["debito"] if v["debito"] is not None else apurado
        if devido is not None and v["pago"] is not None:
            dif = v["pago"] - devido
            if dif > TOL:
                A.add(categoria="pagamento", tipo="PAGAMENTO_INDEVIDO", cor="AZUL", tributo=trib, periodo=per, valor=dif,
                      confianca="media", titulo=f"{trib}: pagamento maior que o débito",
                      descricao=f"Pago {brl(v['pago'])} × devido {brl(devido)} — possível indébito de {brl(dif)}.",
                      fundamento="CTN, arts. 165 e 168; Lei 9.430/1996, art. 74 (compensação via PER/DCOMP)",
                      memoria=[f"{brl(v['pago'])} − {brl(devido)} = {brl(dif)}"], origem={"fontes": ["dctfweb/pagamentos"]},
                      documentacao="DARFs/DAEs, recibos da declaração, extrato de pagamentos no e-CAC",
                      procedimento="1) Confirmar que o pagamento não está vinculado a outro débito; 2) retificar a declaração se o débito "
                                   "estiver errado; 3) transmitir PER/DCOMP dentro de 5 anos do pagamento.")
            elif dif < -TOL:
                A.add(categoria="pagamento", tipo="PAGAMENTO_A_MENOR", cor="VERMELHO", tributo=trib, periodo=per, valor=-dif,
                      confianca="media", titulo=f"{trib}: pagamento menor que o débito", descricao=f"Pago {brl(v['pago'])} × devido {brl(devido)}.",
                      memoria=[f"{brl(devido)} − {brl(v['pago'])} = {brl(-dif)}"], origem={"fontes": ["dctfweb/pagamentos"]})
            else:
                A.ok("pagamento", "PAGAMENTO_OK", f"{trib} {per}: pago = devido", f"{brl(v['pago'])}", tributo=trib, periodo=per)


# =============================================================== 6. Simples Nacional
def simples(dd: Dados, A: Achados, motor):
    from ..calc import simples as sn
    emp = dd.emp
    saidas = [d for d in dd.unicos("xml").values() if d["operacao"] == "S" and d["situacao"] == "normal" and d["cnpj_emit"] == emp["cnpj"]]
    entradas = [d for d in dd.unicos("xml").values() if d["operacao"] == "E" and d["situacao"] == "normal"]
    ev_st = motor.obter("ICMS.ST.EVIDENCIAS", dd.ini + "-01")
    mono_r = motor.tentar("MONOFASICO.NCM", dd.ini + "-01")
    ncm_mono_entrada, ncm_st_entrada = set(), set()
    for d in entradas:
        for it in d["itens"]:
            if mono_r and (it["cst_pis"] or "") in mono_r.p["cst_entrada_monofasico"]:
                ncm_mono_entrada.add(it["ncm"])
            if (it["cst_icms"] or "") in ev_st.p["cst_entrada_st"] + ev_st.p["csosn_entrada_st"] or D(it["v_st"]) > 0 \
                    or cred.cfop_entrada(it["cfop"] or "") in ev_st.p["cfop_entrada_st"]:
                ncm_st_entrada.add(it["ncm"])
    receita = defaultdict(lambda: ZERO)
    rec_mono, rec_st = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    ev_mono, ev_stv = defaultdict(list), defaultdict(list)
    crt_errado = []
    for d in saidas:
        if d["crt_emit"] and d["crt_emit"] not in ("1", "4"):
            crt_errado.append(d)
        for it in d["itens"]:
            suf = (it["cfop"] or "")[1:]
            if d["modelo"] != "NFSE" and suf not in CFOP_RECEITA:
                continue
            v = D(it["vprod"]) - D(it["vdesc"])
            receita[d["periodo"]] += v
            mono = (cred.eh_monofasico(it["ncm"], mono_r) is not None) or it["ncm"] in ncm_mono_entrada
            st = (it["cst_icms"] in ev_st.p["csosn_saida_st"] + ev_st.p["cst_saida_st"] or it["cfop"] in ev_st.p["cfop_saida_st"]
                  or it["ncm"] in ncm_st_entrada)
            if mono and it["ncm"]:
                rec_mono[d["periodo"]] += v
                ev_mono[d["periodo"]].append(f"NF {d['numero']} item {it['n_item']} NCM {it['ncm']} {brl(v)}"
                                             + (" (comprado com CST monofásico)" if it["ncm"] in ncm_mono_entrada else " (lista de NCM)"))
            if st and it["ncm"]:
                rec_st[d["periodo"]] += v
                ev_stv[d["periodo"]].append(f"NF {d['numero']} item {it['n_item']} NCM {it['ncm']} CSOSN {it['cst_icms']} CFOP {it['cfop']} {brl(v)}")
    for d in dd.unicos("xml").values():   # devoluções de venda reduzem a receita
        if d["operacao"] == "E" and d["situacao"] == "normal":
            for it in d["itens"]:
                if cred.cfop_entrada(it["cfop"] or "")[1:] in CFOP_DEVOLUCAO_VENDA:
                    receita[d["periodo"]] -= D(it["vprod"]) - D(it["vdesc"])
    for d in crt_errado[:1]:
        A.add(categoria="simples", tipo="CRT_INCOMPATIVEL", cor="AMARELO", periodo=d["periodo"], confianca="alta",
              titulo="NF-e emitida com CRT de regime normal por optante do Simples",
              descricao=f"{len(crt_errado)} nota(s) com CRT {d['crt_emit']}: conferir o cadastro do emissor (CRT 1 = Simples Nacional).",
              origem={"documentos": [_ref(x) for x in crt_errado[:50]]}, documentacao="Cadastro do emissor de NF-e")
    pers = sorted({a["periodo"] for a in dd.apur if a["tributo"] == "SIMPLES_NACIONAL"} | set(receita))
    for per in pers:
        g = lambda c: dd.ap("pgdas", "SIMPLES_NACIONAL", per, c)  # noqa: E731
        decl = g("receita_bruta")
        if decl is None:
            if receita[per] > 0:
                A.add(categoria="simples", tipo="PGDAS_AUSENTE", cor="AMARELO", periodo=per, valor=0, confianca="alta",
                      titulo="PGDAS-D do período não importado", descricao=f"Receita pelos XML {brl(receita[per])}; importe o PGDAS-D para cruzar.")
            continue
        if receita[per] and abs(receita[per] - decl) > max(TOL, decl * D("0.005")):
            omissao = receita[per] > decl
            A.add(categoria="simples", tipo="RECEITA_DIVERGENTE", cor="VERMELHO" if omissao else "AMARELO", periodo=per,
                  valor=abs(receita[per] - decl), confianca="media",
                  titulo="Receita do PGDAS-D × notas fiscais emitidas",
                  descricao=f"Notas de saída {brl(receita[per])} × declarado {brl(decl)}" + (" — possível receita não declarada." if omissao else "."),
                  fundamento="LC 123/2006, art. 18, §3º (regime de competência/caixa) e art. 25 (declaração)",
                  memoria=["receita = Σ (vProd − vDesc) dos itens com CFOP de venda/serviço − devoluções"],
                  origem={"fontes": ["xml", "pgdas"]}, documentacao="XMLs de saída e devolução, extrato do PGDAS-D")
        rbt12 = g("rbt12")
        anexo_cod = next((a["valor"] for a in dd.apur if a["tributo"] == "SIMPLES_NACIONAL" and a["periodo"] == per and a["campo"] == "anexo"), None)
        anexo = (anexo_cod or emp.get("anexo_padrao") or "I").strip()
        if rbt12 is None:
            A.add(categoria="simples", tipo="RBT12_AUSENTE", cor="AMARELO", periodo=per, titulo="RBT12 não informada no PGDAS-D importado",
                  descricao="Sem a RBT12 não é possível recalcular a alíquota efetiva e a economia da segregação.", confianca="alta")
            continue
        decl_mono, decl_st = g("receita_monofasico") or ZERO, g("receita_icms_st") or ZERO
        falta_mono = max(min(rec_mono[per], decl) - decl_mono, ZERO)
        falta_st = max(min(rec_st[per], decl) - decl_st, ZERO)
        for tipo_seg, falta, evid, rot, fund in (
                ("monofasico", falta_mono, ev_mono[per], "monofásica (PIS/COFINS)",
                 "LC 123/2006, art. 18, §4º-A, I; Lei 10.147/2000, Lei 10.485/2002 e Lei 13.097/2015 (conforme o produto)"),
                ("icms_st", falta_st, ev_stv[per], "com ICMS-ST (ICMS)", "LC 123/2006, art. 18, §4º-A, I e art. 13, §1º, XIII, 'a'")):
            if falta <= TOL:
                continue
            try:
                sim = sn.simular(motor, {"periodo": per, "rbt12": rbt12, "parcelas": [
                    {"descricao": "Receita não segregada", "anexo": anexo, "valor": falta},
                    {"descricao": "Mesma receita segregada", "anexo": anexo, "valor": falta, "tipos": [tipo_seg]}]})
            except Exception as e:  # noqa: BLE001
                A.add(categoria="simples", tipo="SIMULACAO_FALHOU", cor="AMARELO", periodo=per, titulo="Não foi possível recalcular o DAS",
                      descricao=str(e), confianca="alta")
                continue
            sem_seg, com_seg = D(sim["parcelas"][0]["das"]), D(sim["parcelas"][1]["das"])
            A.add(categoria="simples", tipo="SEGREGACAO_NAO_APLICADA", cor="AZUL", tributo="SIMPLES_NACIONAL", periodo=per,
                  valor=sem_seg - com_seg, confianca="media",
                  titulo=f"Receita {rot} não segregada no PGDAS-D",
                  descricao=f"{brl(falta)} de receita com evidências de tributação {rot} não foi segregada (declarado {brl(decl_mono if tipo_seg == 'monofasico' else decl_st)}). "
                            f"DAS pago a maior estimado: {brl(sem_seg - com_seg)}.",
                  fundamento=fund, origem={"fontes": ["xml", "pgdas"], "evidencias": evid[:50]},
                  memoria=[p["titulo"] + ": " + p["detalhe"] for p in sim["memoria"]] + [f"economia = {brl(sem_seg)} − {brl(com_seg)}"],
                  documentacao="XMLs de saída e de compra (CST do fornecedor), NCM conferido no anexo da lei / protocolo de ST da UF, PGDAS-D original",
                  procedimento="1) Confirmar NCM/CEST de cada produto na lei do monofásico ou no convênio/protocolo de ST da UF; "
                               "2) retificar o PGDAS-D dos períodos (prazo de 5 anos); 3) pedir restituição do DAS pago a maior no portal do Simples Nacional.")
        das_decl, pago = g("valor_das"), g("valor_pago")
        if das_decl is not None:
            parcelas = [{"descricao": "Receita", "anexo": anexo, "valor": decl - decl_mono - decl_st}] + \
                ([{"descricao": "Monofásico", "anexo": anexo, "valor": decl_mono, "tipos": ["monofasico"]}] if decl_mono else []) + \
                ([{"descricao": "ICMS-ST", "anexo": anexo, "valor": decl_st, "tipos": ["icms_st"]}] if decl_st else [])
            parcelas = [p for p in parcelas if D(p["valor"]) > 0] or [{"descricao": "Receita", "anexo": anexo, "valor": decl}]
            sim = sn.simular(motor, {"periodo": per, "rbt12": rbt12, "parcelas": parcelas})
            dif = das_decl - D(sim["das"])
            if abs(dif) > D("1.00"):
                A.add(categoria="simples", tipo="DAS_RECALCULO_DIVERGENTE", cor="AMARELO", tributo="SIMPLES_NACIONAL", periodo=per,
                      valor=abs(dif), confianca="media", titulo="DAS declarado difere do recalculado",
                      descricao=f"Declarado {brl(das_decl)} × recalculado {brl(sim['das'])} (Anexo {anexo}, RBT12 {brl(rbt12)}). "
                      "Pode haver mais de um anexo, ISS retido ou fator R não importados.",
                      memoria=[p["titulo"] + ": " + p["detalhe"] for p in sim["memoria"]], origem={"fontes": ["pgdas"]})
            else:
                A.ok("simples", "DAS_OK", f"DAS {per} confere com o recálculo", f"{brl(das_decl)}", periodo=per)
            if pago is not None and pago - das_decl > TOL:
                A.add(categoria="pagamento", tipo="PAGAMENTO_INDEVIDO", cor="AZUL", tributo="SIMPLES_NACIONAL", periodo=per,
                      valor=pago - das_decl, confianca="media", titulo="DAS pago a maior que o declarado",
                      descricao=f"Pago {brl(pago)} × declarado {brl(das_decl)}.", fundamento="LC 123/2006, art. 21, §5º; Resolução CGSN 140/2018, arts. 131 a 140",
                      origem={"fontes": ["pgdas"]}, memoria=[f"{brl(pago)} − {brl(das_decl)}"], documentacao="Comprovante de pagamento do DAS")


# =============================================================== 7. alíquotas, base e compatibilidade da tributação
def aliquotas(dd: Dados, A: Achados, motor):
    emp = dd.emp
    ag = Agregador()
    saidas = [d for d in dd.unicos("xml").values() if d["operacao"] == "S" and d["situacao"] == "normal"]
    for d in saidas:
        data = d["data_emissao"] or d["periodo"] + "-01"
        inter = motor.obter("ICMS.INTERESTADUAL", data)
        interna = motor.tentar("ICMS.INTERNA", data, uf=d["uf_emit"])
        mono_r = motor.tentar("MONOFASICO.NCM", data)
        iss = motor.obter("ISS.LIMITES", data)
        for it in d["itens"]:
            cfop, cst = it["cfop"] or "", it["cst_icms"] or ""
            p_icms, v_icms, vbc = D(it["p_icms"]), D(it["v_icms"]), D(it["vbc_icms"])
            valor_op = D(it["vprod"]) - D(it["vdesc"]) + D(it["vfrete"]) + D(it["vseg"]) + D(it["voutro"])
            ref = f"NF {d['numero']} item {it['n_item']} (NCM {it['ncm']}, CFOP {cfop}, CST {cst})"
            # ICMS interestadual
            if d["modelo"] == "55" and cfop[:1] == "6" and d["uf_emit"] and d["uf_dest"] and d["uf_emit"] != d["uf_dest"] and p_icms > 0:
                if (it["orig"] or "") in inter.p["origens_importado"]:
                    esperado = D(inter.p["aliquota_importado"])
                elif d["uf_emit"] in inter.p["sul_sudeste_exceto_es"] and d["uf_dest"] in inter.p["destinos_7"]:
                    esperado = D(inter.p["aliquota_7"])
                else:
                    esperado = D(inter.p["aliquota_12"])
                if abs(p_icms - esperado) > D("0.0001"):
                    maior = p_icms > esperado
                    ag.add(("ALIQ_INTER", d["periodo"], maior), dict(
                        categoria="aliquota", tipo="ALIQUOTA_INTERESTADUAL_DIVERGENTE", cor="AZUL" if maior else "VERMELHO",
                        tributo="ICMS", periodo=d["periodo"], confianca="alta" if (it["orig"] or "") else "media",
                        titulo="Alíquota interestadual de ICMS " + ("acima" if maior else "abaixo") + " da legal",
                        descricao=("Destaque acima da alíquota interestadual: débito a maior (avaliar estorno/recuperação "
                                   "conforme RICMS, observado o art. 166 do CTN)") if maior else "Destaque abaixo da alíquota interestadual: débito a menor",
                        fundamento=inter.fundamento, documentacao="XML, cadastro de origem da mercadoria (FCI para conteúdo de importação)"),
                        abs(vbc * (p_icms - esperado)), d, f"{ref}: {d['uf_emit']}→{d['uf_dest']} orig {it['orig']}: aplicada {pct(p_icms, 2)}, legal {pct(esperado, 2)}")
            # ICMS interna (somente se a UF tiver alíquota cadastrada no motor)
            elif cfop[:1] == "5" and p_icms > 0 and interna is not None:
                esperado = interna.p.get("por_ncm", {}).get(it["ncm"] or "") or interna.p.get("padrao")
                if esperado is not None and abs(p_icms - D(esperado)) > D("0.0001"):
                    ag.add(("ALIQ_INTERNA", d["periodo"]), dict(
                        categoria="aliquota", tipo="ALIQUOTA_INTERNA_DIVERGENTE", cor="AMARELO", tributo="ICMS", periodo=d["periodo"],
                        confianca="media", titulo="Alíquota interna de ICMS diferente da cadastrada",
                        descricao="Alíquota aplicada difere da regra cadastrada para a UF (pode haver benefício/redução específica)",
                        fundamento=interna.fundamento), vbc * abs(p_icms - D(esperado)), d,
                        f"{ref}: aplicada {pct(p_icms, 2)}, cadastrada {pct(esperado, 2)}")
            # valor do imposto × base × alíquota
            if vbc > 0 and p_icms > 0 and abs(money(vbc * p_icms) - v_icms) > D("0.02"):
                ag.add(("ICMS_CALC", d["periodo"]), dict(categoria="base", tipo="VALOR_IMPOSTO_INCONSISTENTE", cor="AMARELO", tributo="ICMS",
                       periodo=d["periodo"], confianca="alta", titulo="ICMS destacado ≠ base × alíquota",
                       descricao="Valor do ICMS do item não corresponde à base × alíquota", documentacao="XML"),
                       abs(money(vbc * p_icms) - v_icms), d, f"{ref}: {brl(vbc)} × {pct(p_icms, 2)} = {brl(vbc * p_icms)} × destacado {brl(v_icms)}")
            # base de cálculo
            teto = valor_op + D(it["v_ipi"]) + D("0.05")
            if vbc > teto and cst not in ("10", "30", "70", "201", "202", "203"):
                ag.add(("BASE_MAIOR", d["periodo"]), dict(categoria="base", tipo="BASE_INCONSISTENTE", cor="AMARELO", tributo="ICMS",
                       periodo=d["periodo"], confianca="media", titulo="Base de cálculo do ICMS maior que o valor da operação",
                       descricao="Base superior a produto − desconto + frete + seguro + outras + IPI",
                       fundamento="LC 87/1996, art. 13", documentacao="XML"), ZERO, d, f"{ref}: base {brl(vbc)} × operação {brl(teto)}")
            elif vbc > 0 and vbc < valor_op - D("0.05") and cst in ("00", "10") and not (it["extra"] or {}).get("pRedBC"):
                ag.add(("BASE_REDUZIDA", d["periodo"]), dict(categoria="base", tipo="BASE_INCONSISTENTE", cor="AMARELO", tributo="ICMS",
                       periodo=d["periodo"], confianca="media", titulo="Base reduzida sem CST de redução",
                       descricao="Base menor que o valor da operação com CST 00/10 (sem redução de base informada)",
                       fundamento="Ajuste SINIEF 07/2005 e tabela de CST (CST 20/70 para redução de base)"),
                       (valor_op - vbc) * p_icms, d, f"{ref}: base {brl(vbc)} × operação {brl(valor_op)}")
            # tributação incompatível com a operação
            suf = cfop[1:]
            if suf in ("101", "102") and cst in ("40", "41") and emp["regime"] != "SIMPLES_NACIONAL":
                ag.add(("ISENTA", d["periodo"]), dict(categoria="tributacao", tipo="TRIBUTACAO_INCOMPATIVEL", cor="AMARELO", tributo="ICMS",
                       periodo=d["periodo"], confianca="media", titulo="Venda com CST de isenção/não incidência",
                       descricao="Venda comum com CST 40/41: confirmar o dispositivo de isenção no RICMS e o estorno de créditos (LC 87/96, art. 21)",
                       documentacao="Dispositivo legal do benefício (cBenef)"), ZERO, d, ref)
            if cfop in ("5405", "6404") and cst in ("00", "20") and v_icms > 0:
                ag.add(("ST_DEBITADO", d["periodo"]), dict(categoria="tributacao", tipo="ICMS_DEBITADO_EM_ST", cor="AZUL", tributo="ICMS",
                       periodo=d["periodo"], confianca="media", titulo="ICMS próprio debitado em mercadoria com ST já retida",
                       descricao="CFOP de mercadoria com ST retida anteriormente, mas com débito de ICMS próprio: possível pagamento em duplicidade",
                       fundamento="LC 87/1996, arts. 6º e 9º (encerramento da tributação pela ST)",
                       documentacao="XMLs de entrada com ICMS-ST retido, protocolo/convênio do produto"), v_icms, d, f"{ref}: ICMS {brl(v_icms)}")
            if emp["regime"] != "SIMPLES_NACIONAL" and len(cst) == 3 and d["cnpj_emit"] == emp["cnpj"]:
                ag.add(("CSOSN_RN", d["periodo"]), dict(categoria="tributacao", tipo="TRIBUTACAO_INCOMPATIVEL", cor="AMARELO", tributo="ICMS",
                       periodo=d["periodo"], confianca="alta", titulo="CSOSN usado por empresa do regime normal",
                       descricao="Notas emitidas com CSOSN (exclusivo do Simples) por empresa de regime normal"), ZERO, d, ref)
            # PIS/COFINS sobre a receita
            if emp["regime"] in ("LUCRO_PRESUMIDO", "LUCRO_REAL") and d["cnpj_emit"] == emp["cnpj"]:
                p_pis, p_cof, v_pis, v_cof = D(it["p_pis"]), D(it["p_cofins"]), D(it["v_pis"]), D(it["v_cofins"])
                esp = (D("0.0065"), D("0.03")) if emp["regime"] == "LUCRO_PRESUMIDO" else (D("0.0165"), D("0.076"))
                if it["cst_pis"] == "01" and (abs(p_pis - esp[0]) > D("0.00001") or abs(p_cof - esp[1]) > D("0.00001")):
                    ag.add(("PISCOF_ALIQ", d["periodo"]), dict(categoria="aliquota", tipo="ALIQUOTA_PIS_COFINS_DIVERGENTE", cor="AMARELO",
                           tributo="PIS/COFINS", periodo=d["periodo"], confianca="alta", titulo="Alíquota de PIS/COFINS incompatível com o regime",
                           descricao=f"CST 01 com alíquota diferente de {pct(esp[0], 2)}/{pct(esp[1], 2)} ({emp['regime'].replace('_', ' ').lower()})",
                           fundamento="Lei 9.718/1998 (cumulativo); Leis 10.637/2002 e 10.833/2003 (não cumulativo)"),
                           ZERO, d, f"{ref}: {pct(p_pis, 2)}/{pct(p_cof, 2)}")
                mono = cred.eh_monofasico(it["ncm"], mono_r)
                if mono and it["cst_pis"] == "01" and v_pis + v_cof > 0 and suf in CFOP_RECEITA:
                    ag.add(("MONO_TRIBUTADO", d["periodo"]), dict(categoria="monofasico", tipo="MONOFASICO_TRIBUTADO", cor="AZUL",
                           tributo="PIS/COFINS", periodo=d["periodo"], confianca="media", titulo="PIS/COFINS sobre revenda de produto monofásico",
                           descricao="Revenda de produto com tributação concentrada (alíquota zero para o revendedor) tributada com CST 01",
                           fundamento=mono["lei"] + "; art. 2º, §1º-A da Lei 10.147/2000 e correlatos (alíquota zero na revenda)",
                           documentacao="XMLs de saída, confirmação do NCM no anexo da lei, EFD-Contribuições",
                           procedimento="1) Confirmar que a empresa é revendedora (não fabricante/importadora) e o NCM na lei; "
                                        "2) retificar a EFD-Contribuições e a DCTFWeb; 3) PER/DCOMP do indébito (5 anos)."),
                           v_pis + v_cof, d, f"{ref} [{mono['grupo']}]: PIS {brl(v_pis)} + COFINS {brl(v_cof)}")
                vbc_pis = D(it["vbc_pis"])
                if v_pis > 0 and v_icms > 0 and vbc_pis > D(it["vprod"]) - D(it["vdesc"]) - v_icms + D("0.05"):
                    excesso = min(v_icms, vbc_pis - (D(it["vprod"]) - D(it["vdesc"]) - v_icms))
                    ag.add(("TEMA69", d["periodo"]), dict(categoria="oportunidade", tipo="ICMS_NA_BASE_PIS_COFINS", cor="AZUL",
                           tributo="PIS/COFINS", periodo=d["periodo"], confianca="alta", titulo="ICMS incluído na base de PIS/COFINS (Tema 69)",
                           descricao="A base de PIS/COFINS das saídas inclui o ICMS destacado",
                           fundamento="STF, RE 574.706 (Tema 69) — exclusão do ICMS destacado; modulação: efeitos a partir de 15/03/2017, "
                                      "ressalvadas ações ajuizadas até essa data",
                           documentacao="XMLs de saída, EFD-Contribuições (C170/C181/C185), DCTFWeb",
                           procedimento="1) Confirmar que a apuração (EFD-Contribuições) usou a mesma base dos XML; 2) recalcular a base "
                                        "excluindo o ICMS destacado; 3) retificar EFD-Contribuições/DCTFWeb e compensar via PER/DCOMP "
                                        "(prazo de 5 anos)."), excesso * (p_pis + p_cof), d,
                           f"{ref}: base PIS {brl(vbc_pis)} contém ICMS {brl(v_icms)} → {brl(excesso)} × {pct(p_pis + p_cof, 2)}")
    # ISS das NFS-e emitidas
    for d in [d for d in dd.unicos("xml").values() if d["modelo"] == "NFSE" and d["operacao"] == "S"]:
        iss = motor.obter("ISS.LIMITES", d["data_emissao"] or d["periodo"] + "-01")
        for it in d["itens"]:
            p = D(it["p_iss"])
            if p and dd.emp["regime"] != "SIMPLES_NACIONAL" and (p < D(iss.p["minima"]) or p > D(iss.p["maxima"])):
                ag.add(("ISS_FAIXA", d["periodo"]), dict(categoria="aliquota", tipo="ALIQUOTA_ISS_FORA_DA_FAIXA", cor="AMARELO", tributo="ISS",
                       periodo=d["periodo"], confianca="alta", titulo="Alíquota de ISS fora do intervalo de 2% a 5%",
                       descricao="Alíquota de ISS fora dos limites da LC 116/2003", fundamento=iss.fundamento), ZERO, d,
                       f"NFS-e {d['numero']}: {pct(p, 2)}")
    ag.emitir(A)


# =============================================================== 8. contábil × fiscal
def contabil_x_fiscal(dd: Dados, A: Achados):
    if not dd.saldos:
        return
    if not dd.mapa:
        A.add(categoria="contabil", tipo="MAPA_CONTAS_AUSENTE", cor="AMARELO", confianca="alta", titulo="Contas contábeis não mapeadas",
              descricao="Há saldos contábeis importados, mas nenhuma conta foi associada aos grupos RECEITA_BRUTA, ICMS_A_RECOLHER, "
              "PIS_A_RECOLHER, COFINS_A_RECOLHER. Mapeie no cadastro da empresa para ativar o cruzamento contábil × fiscal.")
        return
    por = defaultdict(lambda: defaultdict(lambda: {"mov": ZERO, "saldo": ZERO}))
    for sd in dd.saldos:
        grupo = dd.mapa.get(sd["conta"])
        if grupo:
            por[sd["periodo"]][grupo]["mov"] += D(sd["creditos"]) - D(sd["debitos"])
            por[sd["periodo"]][grupo]["saldo"] += -D(sd["saldo_fim"])   # saldo credor positivo
    receita_fiscal = defaultdict(lambda: ZERO)
    fonte_rec = "xml" if dd.fontes.get("xml") else "efd_icms_ipi"
    for d in dd.unicos(fonte_rec).values():
        if d["operacao"] == "S" and d["situacao"] == "normal":
            receita_fiscal[d["periodo"]] += sum((D(i["vprod"]) - D(i["vdesc"]) for i in d["itens"]
                                                 if (i["cfop"] or "")[1:] in CFOP_RECEITA or d["modelo"] == "NFSE"), ZERO)
    for per, grupos in sorted(por.items()):
        comps = []
        if "RECEITA_BRUTA" in grupos and receita_fiscal.get(per):
            comps.append(("Receita bruta", grupos["RECEITA_BRUTA"]["mov"], receita_fiscal[per], f"documentos ({fonte_rec})"))
        for g, trib, campo, fonte in (("ICMS_A_RECOLHER", "ICMS", "E110.VL_ICMS_RECOLHER", "efd_icms_ipi"),
                                      ("PIS_A_RECOLHER", "PIS", "M200.VL_TOT_CONT_REC", "efd_contribuicoes"),
                                      ("COFINS_A_RECOLHER", "COFINS", "M600.VL_TOT_CONT_REC", "efd_contribuicoes")):
            v = dd.ap(fonte, trib, per, campo)
            if g in grupos and v is not None:
                comps.append((g.replace("_", " ").title(), grupos[g]["saldo"], v, campo))
        for nome, cont, fisc, ref in comps:
            dif = cont - fisc
            rel = abs(dif) / fisc if fisc else D(1)
            if abs(dif) <= D("1.00"):
                A.ok("contabil", "CONTABIL_FISCAL_OK", f"{nome} {per}: contábil = fiscal", f"{brl(cont)}", periodo=per)
                continue
            A.add(categoria="contabil", tipo="CONTABIL_X_FISCAL", cor="VERMELHO" if rel > D("0.05") else "AMARELO", periodo=per,
                  valor=abs(dif), confianca="media", titulo=f"{nome}: contabilidade × fiscal",
                  descricao=f"Contábil {brl(cont)} × fiscal {brl(fisc)} ({ref}) — diferença {brl(dif)} ({pct(rel, 2)}).",
                  memoria=[f"contas mapeadas: {', '.join(c for c, g in dd.mapa.items())}", f"fiscal: {ref}"],
                  origem={"fontes": ["ecd/balancete", ref]}, fundamento="NBC TG/ITG 2000 e Decreto-Lei 1.598/1977, art. 7º (escrituração "
                  "contábil deve refletir as operações fiscais)", documentacao="Razão das contas mapeadas, ECD, EFD do período")


# =============================================================== 9. comparação entre sistemas
def sistemas(dd: Dados, A: Achados):
    planilhas = [f for f in dd.fontes if f.startswith("planilha:")]
    if not planilhas:
        return
    ref_fonte = "xml" if dd.fontes.get("xml") else ("efd_icms_ipi" if dd.fontes.get("efd_icms_ipi") else None)
    pares = [(p, ref_fonte) for p in planilhas if ref_fonte] + [(planilhas[i], planilhas[j]) for i in range(len(planilhas))
                                                               for j in range(i + 1, len(planilhas))]

    def chave_alt(d):
        return f"{d['cnpj_emit']}|{(d['numero'] or '').lstrip('0')}"
    for a, b in pares:
        da, db = dd.fontes[a], dd.fontes[b]
        ia = {d["chave"] or chave_alt(d): d for d in da}
        ib = {}
        for d in db:
            ib[d["chave"] or chave_alt(d)] = d
            ib.setdefault(chave_alt(d), d)
        conc, difs, falt = 0, [], []
        for k, d in ia.items():
            o = ib.get(k) or ib.get(chave_alt(d))
            if o is None:
                falt.append(d)
                continue
            # compara o valor total sempre; os tributos só quando a planilha os informa (colunas ausentes ficam zeradas)
            dd_ = [(c, D(d[c]), D(o[c])) for c in ("valor_total", "v_icms", "v_st", "v_ipi", "v_pis", "v_cofins")
                   if abs(D(d[c]) - D(o[c])) > TOL and (c == "valor_total" or D(d[c]))]
            if dd_:
                difs.append((d, o, dd_))
            else:
                conc += 1
        for d, o, lst in difs[:200]:
            A.add(categoria="sistemas", tipo="DIFERENCA_ENTRE_SISTEMAS", cor="AMARELO", periodo=d["periodo"],
                  valor=max(abs(x - y) for _, x, y in lst), confianca="alta", titulo=f"Diferença entre sistemas: {a} × {b}",
                  descricao=f"Documento {d['numero']}: " + "; ".join(f"{c} {brl(x)} × {brl(y)}" for c, x, y in lst),
                  origem={"documentos": [_ref(d), _ref(o)]}, documentacao="Relatórios dos dois sistemas e XML")
        if falt:
            A.add(categoria="sistemas", tipo="DOCUMENTO_AUSENTE_EM_SISTEMA", cor="AMARELO", confianca="alta",
                  valor=sum((D(d["valor_total"]) for d in falt), ZERO), titulo=f"Documentos de {a} ausentes em {b}",
                  descricao=f"{len(falt)} documento(s) constam em {a} e não em {b}.",
                  origem={"documentos": [_ref(d) for d in falt[:50]]})
        if conc:
            A.ok("sistemas", "SISTEMAS_CONCILIADOS", f"{a} × {b} conciliados", f"{conc} documento(s) idênticos nas duas fontes.")


# =============================================================== 10. retenções
def retencoes(dd: Dados, A: Achados):
    ret = defaultdict(lambda: defaultdict(lambda: ZERO))
    docs_ret = defaultdict(list)
    for d in dd.unicos("xml").values():
        if d["modelo"] == "NFSE" and d["operacao"] == "S" and d["situacao"] == "normal":
            for t, v in (d["extra"].get("retencoes") or {}).items():
                if D(v) > 0:
                    ret[d["periodo"]][t] += D(v)
                    docs_ret[(d["periodo"], t)].append(d)
    for per, ts in sorted(ret.items()):
        for t, v in ts.items():
            deduzido = None
            if t in ("PIS", "COFINS"):
                reg = "M200" if t == "PIS" else "M600"
                a = dd.ap("efd_contribuicoes", t, per, f"{reg}.VL_RET_NC")
                b = dd.ap("efd_contribuicoes", t, per, f"{reg}.VL_RET_CUM")
                if a is not None or b is not None:
                    deduzido = (a or ZERO) + (b or ZERO)
            base = dict(categoria="retencao", tributo=t, periodo=per, origem={"documentos": [_ref(x) for x in docs_ret[(per, t)][:50]]},
                        fundamento="Lei 10.833/2003, arts. 30 a 36 (CSRF); Lei 9.430/1996, art. 64; IN RFB 1.234/2012 (órgãos públicos); "
                                   "Decreto 9.580/2018 (IRRF sobre serviços)",
                        documentacao="NFS-e emitidas com retenção, comprovantes/informes de retenção do tomador (DIRF/EFD-Reinf)")
            if deduzido is not None and v - deduzido > TOL:
                A.add(tipo="RETENCAO_NAO_DEDUZIDA", cor="AZUL", valor=v - deduzido, confianca="media",
                      titulo=f"Retenção de {t} sofrida e não deduzida", descricao=f"{per}: retido nas NFS-e {brl(v)} × deduzido na apuração {brl(deduzido)}.",
                      memoria=[f"{brl(v)} − {brl(deduzido)} = {brl(v - deduzido)}"], **base)
            elif deduzido is None:
                A.add(tipo="RETENCAO_A_CONFIRMAR", cor="AZUL" if t in ("IR", "CSLL") else "AMARELO", valor=v, confianca="baixa",
                      titulo=f"Retenção de {t} a confirmar na apuração",
                      descricao=f"{per}: {brl(v)} retidos pelos tomadores. Confirmar a dedução na apuração (IRPJ/CSLL trimestral, "
                                "EFD-Contribuições, DCTFWeb/EFD-Reinf) — se não deduzida, é crédito a recuperar.",
                      memoria=[f"Σ retenções de {t} nas NFS-e = {brl(v)}"], **base)
            else:
                A.ok("retencao", "RETENCAO_OK", f"Retenções de {t} deduzidas ({per})", brl(v), tributo=t, periodo=per)


# =============================================================== 11. Reforma Tributária (IBS/CBS)
def reforma(dd: Dados, A: Achados):
    sem_grupo, cred_ibs, cred_cbs, docs_cred = [], ZERO, ZERO, []
    for d in dd.unicos("xml").values():
        if (d["data_emissao"] or "") < "2026-01-01" or d["situacao"] != "normal" or d["modelo"] not in ("55", "65"):
            continue
        tem = any(i.get("cst_ibscbs") for i in d["itens"]) or d.get("v_ibs") is not None
        if d["operacao"] == "S" and d["cnpj_emit"] == dd.emp["cnpj"] and d["crt_emit"] == "3" and not tem:
            sem_grupo.append(d)
        if d["operacao"] == "E" and tem:
            cred_ibs += sum((D(i.get("v_ibs")) for i in d["itens"]), ZERO)
            cred_cbs += sum((D(i.get("v_cbs")) for i in d["itens"]), ZERO)
            docs_cred.append(d)
    if sem_grupo:
        A.add(categoria="reforma", tipo="GRUPO_IBS_CBS_AUSENTE", cor="AMARELO", tributo="IBS/CBS", confianca="media",
              titulo="NF-e de 2026 sem grupo IBS/CBS", descricao=f"{len(sem_grupo)} NF-e emitidas a partir de 2026 por empresa do regime "
              "normal sem o grupo IBSCBS. Verificar a obrigatoriedade na Nota Técnica vigente e a parametrização do emissor.",
              fundamento="LC 214/2025 e EC 132/2023 (ADCT, art. 125); NT 2025.002 do Projeto NF-e e alterações",
              origem={"documentos": [_ref(d) for d in sem_grupo[:50]]}, documentacao="XMLs e configuração do emissor")
    if cred_ibs + cred_cbs > 0:
        A.add(categoria="reforma", tipo="CREDITO_IBS_CBS", cor="AZUL", tributo="IBS/CBS", valor=cred_ibs + cred_cbs, confianca="baixa",
              titulo="IBS/CBS destacados nas aquisições (fase de transição)",
              descricao=f"IBS {brl(cred_ibs)} + CBS {brl(cred_cbs)} destacados em {len(docs_cred)} entrada(s). Em 2026 os valores são "
              "de teste e compensáveis com PIS/COFINS conforme regulamentação; controlar para apropriação correta.",
              fundamento="EC 132/2023, ADCT art. 125; LC 214/2025 (créditos de IBS/CBS e regras de transição)",
              origem={"documentos": [_ref(d) for d in docs_cred[:50]]}, documentacao="XMLs de entrada com grupo IBSCBS")
