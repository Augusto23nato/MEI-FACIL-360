"""Gera um conjunto de arquivos fiscais FICTÍCIOS e coerentes, com divergências plantadas,
para demonstração e testes de integração.

    python exemplos/gerar.py [pasta_destino]

Empresa A — Lucro Real, comércio (SP), competência 2026-01.
Empresa B — Simples Nacional, comércio (SP), competência 2026-02.
CNPJs, nomes e valores são inventados para teste (CNPJs com DV válido).
"""
from __future__ import annotations

import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path


def cnpj(base12: str) -> str:
    def dv(nums, pesos):
        s = sum(int(n) * p for n, p in zip(nums, pesos)) % 11
        return "0" if s < 2 else str(11 - s)
    d1 = dv(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base12 + d1 + d2


EMP_A = cnpj("112223330001")
EMP_B = cnpj("445556660001")
F_MG, F_SP, F_SP2, F_FARMA, F_PR, F_BEB = (cnpj(x) for x in ("123456780001", "234567890001", "345678900001",
                                                             "456789010001", "567890120001", "678901230001"))
C_RJ, C_BA, C_SP, C_SP2 = (cnpj(x) for x in ("789012340001", "890123450001", "901234560001", "112233440001"))
UF_COD = {"SP": "35", "MG": "31", "PR": "41", "RJ": "33", "BA": "29"}


def q(v, casas=2):
    return Decimal(str(v)).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)


def chave(uf, aamm, cnpj_emit, numero, mod="55", serie=1):
    base = f"{UF_COD[uf]}{aamm}{cnpj_emit}{mod}{serie:03d}{numero:09d}1{numero:08d}"
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    s = sum(int(c) * pesos[i % 8] for i, c in enumerate(reversed(base)))
    dv = 11 - s % 11
    return base + str(0 if dv >= 10 else dv)


def nfe(numero, data, emit, uf_emit, dest, uf_dest, itens, crt="3", tp_nf="1", fin="1", nome_emit="Emitente Exemplo",
        nome_dest="Destinatario Exemplo"):
    """itens: dicts com ncm, cfop, vprod, cst (ou csosn), orig, p_icms, cst_pis, p_pis, p_cof, vbc_pis (opcional), v_st"""
    ch = chave(uf_emit, data[2:4] + data[5:7], emit, numero)
    dets, tot = [], {k: Decimal(0) for k in ("vProd", "vBC", "vICMS", "vST", "vPIS", "vCOFINS")}
    for i, it in enumerate(itens, 1):
        vprod = q(it["vprod"])
        p_icms = Decimal(str(it.get("p_icms", 0)))
        vbc = vprod if p_icms else Decimal(0)
        v_icms = q(vbc * p_icms / 100)
        v_st = q(it.get("v_st", 0))
        vbc_pis = q(it.get("vbc_pis", vprod))
        p_pis, p_cof = Decimal(str(it.get("p_pis", 0))), Decimal(str(it.get("p_cof", 0)))
        v_pis, v_cof = q(vbc_pis * p_pis / 100), q(vbc_pis * p_cof / 100)
        if "csosn" in it:
            icms = f"<ICMSSN102><orig>{it.get('orig', 0)}</orig><CSOSN>{it['csosn']}</CSOSN></ICMSSN102>"
        else:
            cst = it.get("cst", "00")
            icms = (f"<ICMS{cst}><orig>{it.get('orig', 0)}</orig><CST>{cst}</CST><modBC>3</modBC><vBC>{vbc}</vBC>"
                    f"<pICMS>{p_icms:.2f}</pICMS><vICMS>{v_icms}</vICMS>"
                    + (f"<vBCST>{q(vprod * Decimal('1.4'))}</vBCST><vICMSST>{v_st}</vICMSST>" if v_st else "") + f"</ICMS{cst}>")
        cst_pis = it.get("cst_pis", "01")
        if cst_pis in ("01", "02"):
            pis = f"<PISAliq><CST>{cst_pis}</CST><vBC>{vbc_pis}</vBC><pPIS>{p_pis:.4f}</pPIS><vPIS>{v_pis}</vPIS></PISAliq>"
            cof = f"<COFINSAliq><CST>{cst_pis}</CST><vBC>{vbc_pis}</vBC><pCOFINS>{p_cof:.4f}</pCOFINS><vCOFINS>{v_cof}</vCOFINS></COFINSAliq>"
        else:
            pis, cof, v_pis, v_cof = f"<PISNT><CST>{cst_pis}</CST></PISNT>", f"<COFINSNT><CST>{cst_pis}</CST></COFINSNT>", 0, 0
        dets.append(f"""<det nItem="{i}"><prod><cProd>P{i:03d}</cProd><xProd>{it.get('desc', 'Produto ' + str(i))}</xProd>
<NCM>{it['ncm']}</NCM><CFOP>{it['cfop']}</CFOP><uCom>UN</uCom><qCom>1</qCom><vUnCom>{vprod}</vUnCom><vProd>{vprod}</vProd>
<indTot>1</indTot></prod><imposto><ICMS>{icms}</ICMS><PIS>{pis}</PIS><COFINS>{cof}</COFINS></imposto></det>""")
        tot["vProd"] += vprod
        tot["vBC"] += vbc
        tot["vICMS"] += v_icms
        tot["vST"] += v_st
        tot["vPIS"] += Decimal(v_pis)
        tot["vCOFINS"] += Decimal(v_cof)
    vnf = tot["vProd"] + tot["vST"]
    return ch, f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{ch}" versao="4.00">
<ide><cUF>{UF_COD[uf_emit]}</cUF><natOp>Venda</natOp><mod>55</mod><serie>1</serie><nNF>{numero}</nNF>
<dhEmi>{data}T10:00:00-03:00</dhEmi><tpNF>{tp_nf}</tpNF><idDest>{'2' if uf_emit != uf_dest else '1'}</idDest><finNFe>{fin}</finNFe></ide>
<emit><CNPJ>{emit}</CNPJ><xNome>{nome_emit}</xNome><enderEmit><UF>{uf_emit}</UF></enderEmit><CRT>{crt}</CRT></emit>
<dest><CNPJ>{dest}</CNPJ><xNome>{nome_dest}</xNome><enderDest><UF>{uf_dest}</UF></enderDest><indIEDest>1</indIEDest></dest>
{''.join(dets)}
<total><ICMSTot><vBC>{tot['vBC']}</vBC><vICMS>{tot['vICMS']}</vICMS><vST>{tot['vST']}</vST><vProd>{tot['vProd']}</vProd>
<vIPI>0.00</vIPI><vPIS>{tot['vPIS']}</vPIS><vCOFINS>{tot['vCOFINS']}</vCOFINS><vNF>{vnf}</vNF></ICMSTot></total>
</infNFe></NFe><protNFe versao="4.00"><infProt><chNFe>{ch}</chNFe><cStat>100</cStat></infProt></protNFe></nfeProc>
""", {"vnf": vnf, **tot, "itens": itens}


C170 = ("REG NUM_ITEM COD_ITEM DESCR_COMPL QTD UNID VL_ITEM VL_DESC IND_MOV CST_ICMS CFOP COD_NAT VL_BC_ICMS ALIQ_ICMS "
        "VL_ICMS VL_BC_ICMS_ST ALIQ_ST VL_ICMS_ST IND_APUR CST_IPI COD_ENQ VL_BC_IPI ALIQ_IPI VL_IPI CST_PIS VL_BC_PIS "
        "ALIQ_PIS QUANT_BC_PIS ALIQ_PIS_QUANT VL_PIS CST_COFINS VL_BC_COFINS ALIQ_COFINS QUANT_BC_COFINS "
        "ALIQ_COFINS_QUANT VL_COFINS COD_CTA VL_ABAT_NT").split()


def br(v) -> str:
    return f"{q(v):.2f}".replace(".", ",")


def sped_icms(cnpj_emp, ini, fim, docs, e110, nome="EMPRESA A EXEMPLO LTDA"):
    """docs: lista (ind_oper, chave, numero, cod_part, data, vl_doc, vl_bc, vl_icms, itens[(n, cfop, cst, vl, aliq, vicms)])"""
    L = [f"|0000|019|0|{ini}|{fim}|{nome}|{cnpj_emp}||SP|111111111111|3550308||||A|1|", "|0001|0|"]
    parts = sorted({d[3] for d in docs})
    for p in parts:
        L.append(f"|0150|{p}|Participante {p}|01058|{p}||||||||||")
    L.append("|0990|%d|" % (len(L) + 1))
    L.append("|C001|0|")
    for ind, ch, num, part, data, vl, bc, icms, itens in docs:
        L.append(f"|C100|{ind}|{'0' if ind == '1' else '1'}|{part}|55|00|1|{num}|{ch}|{data}|{data}|{br(vl)}|0|0,00|0,00|{br(vl)}|"
                 f"0|0,00|0,00|0,00|{br(bc)}|{br(icms)}|0,00|0,00|0,00|0,00|0,00|0,00|0,00|")
        grupos = {}
        for n, cfop, cst, v, aliq, vi in itens:
            if ind == "0":
                c = {"REG": "C170", "NUM_ITEM": str(n), "COD_ITEM": f"P{n:03d}", "QTD": "1", "UNID": "UN", "VL_ITEM": br(v),
                     "VL_DESC": "0,00", "IND_MOV": "0", "CST_ICMS": cst, "CFOP": cfop, "VL_BC_ICMS": br(v if vi else 0),
                     "ALIQ_ICMS": br(aliq), "VL_ICMS": br(vi), "IND_APUR": "0"}
                L.append("|" + "|".join(c.get(k, "") for k in C170) + "|")
            g = grupos.setdefault((cst, cfop, aliq), [0, 0, 0])
            g[0] += v
            g[1] += v if vi else 0
            g[2] += vi
        for (cst, cfop, aliq), (v, b, vi) in grupos.items():
            L.append(f"|C190|{cst}|{cfop}|{br(aliq)}|{br(v)}|{br(b)}|{br(vi)}|0,00|0,00|0,00|0,00||")
    L.append("|C990|0|")
    L.append("|E001|0|")
    L.append(f"|E100|{ini}|{fim}|")
    L.append("|E110|" + "|".join(br(e110[k]) for k in ("deb", "aj_deb", "tot_aj_deb", "est_cred", "cred", "aj_cred", "tot_aj_cred",
                                                     "est_deb", "sld_ant", "sld_apur", "ded", "recolher", "transp", "deb_esp")) + "|")
    if e110["recolher"]:
        L.append(f"|E116|000|{br(e110['recolher'])}|10022026|046-2||||||012026|")
    L.append("|E990|0|")
    L.append("|9001|0|")
    L.append("|9999|%d|" % (len(L) + 1))
    return "\r\n".join(L) + "\r\n"


def gerar(destino: Path) -> dict:
    destino = Path(destino)
    a = destino / "empresa_a_lucro_real"
    b = destino / "empresa_b_simples"
    for p in (a / "xml", b / "xml"):
        p.mkdir(parents=True, exist_ok=True)
    info = {"empresa_a": EMP_A, "empresa_b": EMP_B}

    # ------------------------------------------------ EMPRESA A (Lucro Real, SP) — 2026-01
    xs = {}
    xs["E1"] = nfe(101, "2026-01-05", F_MG, "MG", EMP_A, "SP", [dict(ncm="84713012", cfop="6102", vprod=10000, p_icms=12, p_pis=1.65, p_cof=7.6)])
    xs["E2"] = nfe(202, "2026-01-08", F_SP, "SP", EMP_A, "SP", [dict(ncm="85171300", cfop="5102", vprod=5000, p_icms=18, p_pis=1.65, p_cof=7.6)])
    xs["E3"] = nfe(303, "2026-01-10", F_SP2, "SP", EMP_A, "SP", [dict(ncm="48201000", cfop="5102", vprod=2000, p_icms=18, p_pis=1.65, p_cof=7.6, desc="Material de escritorio")])
    xs["E4"] = nfe(404, "2026-01-12", F_FARMA, "SP", EMP_A, "SP", [dict(ncm="30049099", cfop="5405", vprod=1500, cst="60", cst_pis="04", desc="Medicamento")])
    xs["E5"] = nfe(505, "2026-01-15", F_PR, "PR", EMP_A, "SP", [dict(ncm="84713012", cfop="6102", vprod=3000, p_icms=12, p_pis=1.65, p_cof=7.6)])
    xs["S1"] = nfe(1, "2026-01-20", EMP_A, "SP", C_RJ, "RJ", [dict(ncm="84713012", cfop="6102", vprod=20000, p_icms=12, p_pis=1.65, p_cof=7.6)])
    xs["S2"] = nfe(2, "2026-01-21", EMP_A, "SP", C_BA, "BA", [dict(ncm="85171300", cfop="6102", vprod=8000, p_icms=12, p_pis=1.65, p_cof=7.6,
                                                                  vbc_pis=8000 - 960)])
    xs["S3"] = nfe(3, "2026-01-22", EMP_A, "SP", C_SP, "SP", [dict(ncm="30049099", cfop="5405", vprod=1000, cst="60", p_icms=0, p_pis=1.65, p_cof=7.6, desc="Medicamento")])
    xs["S4"] = nfe(4, "2026-01-23", EMP_A, "SP", C_SP2, "SP", [dict(ncm="85171300", cfop="5102", vprod=4000, p_icms=18, p_pis=1.65, p_cof=7.6, vbc_pis=4000 - 720)])
    xs["S5"] = nfe(5, "2026-01-24", EMP_A, "SP", C_SP, "SP", [dict(ncm="84713012", cfop="5102", vprod=10000, p_icms=18, p_pis=1.65, p_cof=7.6, vbc_pis=8200)])
    xs["S6"] = nfe(6, "2026-01-25", EMP_A, "SP", C_SP, "SP", [dict(ncm="84713012", cfop="5102", vprod=500, p_icms=18, p_pis=1.65, p_cof=7.6, vbc_pis=410)])
    for k, (ch, x, _) in xs.items():
        (a / "xml" / f"{k}-{ch}.xml").write_text(x, encoding="utf-8")
    ch6 = xs["S6"][0]
    (a / "xml" / f"cancelamento-{ch6}.xml").write_text(
        f'<?xml version="1.0"?><procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento><infEvento><chNFe>{ch6}</chNFe>'
        f'<dhEvento>2026-01-25T15:00:00-03:00</dhEvento><tpEvento>110111</tpEvento></infEvento></evento></procEventoNFe>', encoding="utf-8")
    # NFS-e emitida com PIS/COFINS retidos
    (a / "xml" / "nfse-0001.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS35503081{EMP_A}0000001"><nNFSe>1</nNFSe>
<emit><CNPJ>{EMP_A}</CNPJ><xNome>EMPRESA A</xNome></emit><DPS><infDPS><dhEmi>2026-01-28T09:00:00-03:00</dhEmi>
<prest><CNPJ>{EMP_A}</CNPJ></prest><toma><CNPJ>{C_SP}</CNPJ><xNome>Cliente Servico</xNome></toma>
<serv><cServ><cTribNac>010701</cTribNac><xDescServ>Suporte tecnico</xDescServ></cServ></serv>
<valores><vServPrest><vServ>10000.00</vServ></vServPrest><trib><tribMun><tpRetISSQN>1</tpRetISSQN><pAliq>2.00</pAliq></tribMun>
<tribFed><vRetIRRF>150.00</vRetIRRF><vRetCSLL>100.00</vRetCSLL><vPis>65.00</vPis><vCofins>300.00</vCofins></tribFed></trib></valores>
</infDPS></DPS><valores><vISSQN>200.00</vISSQN></valores></infNFSe></NFSe>""", encoding="utf-8")

    # EFD ICMS/IPI de A: E2 sem crédito, E3 com crédito indevido, E5 ausente, S4 ausente, S5 ICMS divergente, S6 normal
    def it_e(ch_key, cfop_ent, cst, aliq, credito=True):
        ch, _, t = xs[ch_key]
        v = t["vProd"]
        vi = t["vICMS"] if credito else Decimal(0)
        return (1, cfop_ent, cst, v, aliq if credito else 0, vi)
    docs = [
        ("0", xs["E1"][0], "101", F_MG, "05012026", xs["E1"][2]["vnf"], 10000, 1200, [it_e("E1", "2102", "000", 12)]),
        ("0", xs["E2"][0], "202", F_SP, "08012026", xs["E2"][2]["vnf"], 0, 0, [it_e("E2", "1102", "000", 18, credito=False)]),
        ("0", xs["E3"][0], "303", F_SP2, "10012026", xs["E3"][2]["vnf"], 2000, 360, [it_e("E3", "1556", "090", 18)]),
        ("0", xs["E4"][0], "404", F_FARMA, "12012026", xs["E4"][2]["vnf"], 0, 0, [(1, "1403", "060", Decimal(1500), 0, 0)]),
        ("1", xs["S1"][0], "1", C_RJ, "20012026", 20000, 20000, 2400, [(1, "6102", "000", Decimal(20000), 12, Decimal(2400))]),
        ("1", xs["S2"][0], "2", C_BA, "21012026", 8000, 8000, 960, [(1, "6102", "000", Decimal(8000), 12, Decimal(960))]),
        ("1", xs["S3"][0], "3", C_SP, "22012026", 1000, 0, 0, [(1, "5405", "060", Decimal(1000), 0, 0)]),
        ("1", xs["S5"][0], "5", C_SP, "24012026", 10000, 10000, 1500, [(1, "5102", "000", Decimal(10000), 15, Decimal(1500))]),
        ("1", xs["S6"][0], "6", C_SP, "25012026", 500, 500, 90, [(1, "5102", "000", Decimal(500), 18, Decimal(90))]),
    ]
    deb = Decimal(2400 + 960 + 1500 + 90)
    cred = Decimal(1200 + 360)
    e110 = dict(deb=deb, aj_deb=0, tot_aj_deb=0, est_cred=0, cred=cred, aj_cred=0, tot_aj_cred=0, est_deb=0, sld_ant=0,
                sld_apur=deb - cred, ded=0, recolher=deb - cred, transp=0, deb_esp=0)
    (a / "efd_icms_ipi_2026_01.txt").write_bytes(sped_icms(EMP_A, "01012026", "31012026", docs, e110).encode("latin-1"))

    # EFD-Contribuições de A: crédito de PIS/COFINS escriturado apenas sobre E1
    pis_deb = q((Decimal(20000) + Decimal(8000 - 960) + Decimal(1000) + Decimal(10000 - 1800)) * Decimal("0.0165"))
    cof_deb = q((Decimal(20000) + Decimal(8000 - 960) + Decimal(1000) + Decimal(10000 - 1800)) * Decimal("0.076"))
    pis_cred, cof_cred = q(8800 * Decimal("0.0165")), q(8800 * Decimal("0.076"))
    pis_rec, cof_rec = pis_deb - pis_cred, cof_deb - cof_cred
    contrib = [f"|0000|006|0|||01012026|31012026|EMPRESA A EXEMPLO LTDA|{EMP_A}|SP|3550308||00|1|", "|0001|0|",
               "|0110|1|1|1||", "|0990|4|", "|C001|0|", f"|C010|{EMP_A}|2|", "|C990|3|",
               "|M001|0|", f"|M100|101|0|{br(8800)}|1,6500|||{br(pis_cred)}|0,00|0,00|0,00|{br(pis_cred)}|0|{br(pis_cred)}|0,00|",
               f"|M200|{br(pis_deb)}|{br(pis_cred)}|0,00|{br(pis_rec)}|0,00|0,00|{br(pis_rec)}|0,00|0,00|0,00|0,00|{br(pis_rec)}|",
               f"|M500|101|0|{br(8800)}|7,6000|||{br(cof_cred)}|0,00|0,00|0,00|{br(cof_cred)}|0|{br(cof_cred)}|0,00|",
               f"|M600|{br(cof_deb)}|{br(cof_cred)}|0,00|{br(cof_rec)}|0,00|0,00|{br(cof_rec)}|0,00|0,00|0,00|0,00|{br(cof_rec)}|",
               "|M990|6|", "|9001|0|", "|9999|16|"]
    (a / "efd_contribuicoes_2026_01.txt").write_bytes(("\r\n".join(contrib) + "\r\n").encode("latin-1"))
    # DCTFWeb/pagamentos: PIS pago a maior; COFINS declarada a menor
    (a / "dctfweb_2026_01.csv").write_text(
        "periodo;tributo;codigo_receita;valor_debito;valor_pago\n"
        f"01/2026;PIS;6912;{br(pis_rec)};{br(pis_rec + 120)}\n"
        f"01/2026;COFINS;5856;{br(cof_rec - 500)};{br(cof_rec - 500)}\n", encoding="utf-8")
    # Balancete (Domínio) com receita contábil diferente da fiscal
    receita_fiscal = Decimal(20000 + 8000 + 1000 + 4000 + 10000)
    (a / "balancete_2026_01.csv").write_text(
        "competencia;conta;descricao;saldo_anterior;debito;credito;saldo_atual\n"
        f"01/2026;3.1.01;Receita de vendas;0;0;{br(receita_fiscal - 4000)};-{br(receita_fiscal - 4000)}\n"
        f"01/2026;2.1.05;ICMS a recolher;0;0;{br(e110['recolher'])};-{br(e110['recolher'])}\n", encoding="utf-8")
    # Exportação de livro de saídas do "sistema B" (perfil Domínio): S5 com valor contábil diferente
    linhas = ["chave;nota;serie;data;cfop;valor_contabil;base_calculo;valor_icms;cnpj"]
    for k in ("S1", "S2", "S3", "S4", "S5"):
        ch, _, t = xs[k]
        vnf = t["vnf"] + (100 if k == "S5" else 0)
        linhas.append(f"{ch};{int(ch[25:34])};1;{'2' + ch[2:4]}/01/2026;{t['itens'][0]['cfop']};{br(vnf)};{br(t['vBC'])};{br(t['vICMS'])};")
    linhas = [linhas[0]] + [ln.replace(ln.split(";")[3], "20/01/2026") for ln in linhas[1:]]
    (a / "dominio_livro_saidas_2026_01.csv").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    # ------------------------------------------------ EMPRESA B (Simples, SP) — 2026-02
    ys = {}
    ys["E1"] = nfe(901, "2026-02-02", F_FARMA, "SP", EMP_B, "SP", [dict(ncm="33049910", cfop="5102", vprod=4000, p_icms=18, cst_pis="04", desc="Cosmetico")])
    ys["E2"] = nfe(902, "2026-02-03", F_BEB, "SP", EMP_B, "SP", [dict(ncm="22021000", cfop="5401", vprod=3000, cst="10", p_icms=18, v_st=420, p_pis=0, p_cof=0, cst_pis="04", desc="Refrigerante")])
    ys["S1"] = nfe(11, "2026-02-10", EMP_B, "SP", C_SP, "SP", [dict(ncm="33049910", cfop="5102", vprod=8000, csosn="102", cst_pis="49", desc="Cosmetico"),
                                                              dict(ncm="61091000", cfop="5102", vprod=12000, csosn="102", cst_pis="49", desc="Camiseta")], crt="1")
    ys["S2"] = nfe(12, "2026-02-15", EMP_B, "SP", C_SP2, "SP", [dict(ncm="22021000", cfop="5102", vprod=5000, csosn="102", cst_pis="49", desc="Refrigerante"),
                                                               dict(ncm="61091000", cfop="5102", vprod=25000, csosn="102", cst_pis="49", desc="Camiseta")], crt="1")
    for k, (ch, x, _) in ys.items():
        (b / "xml" / f"{k}-{ch}.xml").write_text(x, encoding="utf-8")
    # PGDAS-D sem segregação: receita 50.000, RBT12 600.000, Anexo I faixa 3: (600000×9,5%−13860)/600000 = 7,19%
    das = q(Decimal(50000) * (Decimal(600000) * Decimal("0.095") - Decimal(13860)) / Decimal(600000))
    (b / "pgdas_2026_02.csv").write_text("periodo;receita_bruta;rbt12;receita_monofasico;receita_st;valor_das;valor_pago;anexo\n"
                                         f"02/2026;50000,00;600000,00;0;0;{br(das)};{br(das)};I\n", encoding="utf-8")
    info["das_b"] = das
    return info


if __name__ == "__main__":
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "dados")
    print(gerar(destino))
