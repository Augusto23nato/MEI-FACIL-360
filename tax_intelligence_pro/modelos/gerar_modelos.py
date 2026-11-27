"""Gera as planilhas modelo para análise de empresa do LUCRO REAL.

    python modelos/gerar_modelos.py

A primeira aba de cada arquivo é a que o sistema importa; a aba "Instruções" é ignorada.
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

PASTA = Path(__file__).resolve().parent
AZUL = PatternFill("solid", fgColor="1F3A5F")
CINZA = PatternFill("solid", fgColor="EEF2F7")
AMARELO = PatternFill("solid", fgColor="FFF4D6")
BRANCO = Font(color="FFFFFF", bold=True)
NEGRITO = Font(bold=True)


def cabecalho(ws, colunas, larguras):
    for i, (c, w) in enumerate(zip(colunas, larguras), 1):
        cel = ws.cell(row=1, column=i, value=c)
        cel.fill, cel.font = AZUL, BRANCO
        ws.column_dimensions[cel.column_letter].width = w
    ws.freeze_panes = "A2"


def instrucoes(wb, titulo, linhas):
    ws = wb.create_sheet("Instruções")
    ws.column_dimensions["A"].width = 120
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=14)
    for i, t in enumerate(linhas, 3):
        c = ws.cell(row=i, column=1, value=t)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if t.isupper() or t.endswith(":"):
            c.font = NEGRITO


def texto(ws, coluna, ate=200):
    for r in range(2, ate + 1):
        ws[f"{coluna}{r}"].number_format = "@"


def dinheiro(ws, colunas, ate=200):
    for col in colunas:
        for r in range(2, ate + 1):
            ws[f"{col}{r}"].number_format = "#,##0.00"


# ------------------------------------------------------------------ DCTFWeb / pagamentos
def dctfweb():
    wb = Workbook()
    ws = wb.active
    ws.title = "Preencher"
    cabecalho(ws, ["periodo", "tributo", "codigo_receita", "valor_debito", "valor_pago"], [12, 14, 16, 18, 18])
    texto(ws, "A")
    texto(ws, "C")
    dinheiro(ws, ["D", "E"])
    # tributos do Lucro Real já listados: falta só o período e os valores
    linhas = [("PIS", "6912"), ("COFINS", "5856"), ("IRPJ", "2362"), ("CSLL", "2484"), ("ICMS", "")]
    for i, (t, cod) in enumerate(linhas, 2):
        ws.cell(row=i, column=2, value=t)
        ws.cell(row=i, column=3, value=cod)
        for c in (1, 4, 5):
            ws.cell(row=i, column=c).fill = AMARELO
    dv = DataValidation(type="list", formula1='"PIS,COFINS,IRPJ,CSLL,ICMS,IPI,CP"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("B2:B200")
    instrucoes(wb, "DCTFWeb e pagamentos — Lucro Real", [
        "PARA QUE SERVE:",
        "O sistema compara o débito apurado na escrituração (EFD-Contribuições e EFD ICMS/IPI) com o declarado na DCTFWeb e com o "
        "efetivamente pago. Aponta pagamento a maior (oportunidade de restituição/compensação) ou a menor (risco).",
        "COMO PREENCHER (aba 'Preencher', células amarelas):",
        "periodo — mês da competência no formato MM/AAAA (ex.: 10/2026).",
        "tributo — já vem preenchido: PIS, COFINS, IRPJ, CSLL e ICMS. Acrescente outras linhas se precisar (IPI, CP).",
        "codigo_receita — já vem com os códigos usuais do Lucro Real com estimativa mensal: PIS 6912, COFINS 5856, IRPJ 2362, CSLL 2484. "
        "Se a empresa apura IRPJ/CSLL trimestralmente, use os códigos da apuração trimestral. Confira sempre no DARF/DCTFWeb da empresa.",
        "valor_debito — valor declarado na DCTFWeb (débito apurado) do tributo no mês. Para o ICMS, use o valor da guia estadual (GIA/apuração).",
        "valor_pago — valor efetivamente pago (principal, sem multa e juros), conforme o DARF / guia / extrato do e-CAC.",
        "Vários meses: copie o bloco de linhas e mude o período. Linhas sem período ou sem valores são ignoradas na importação.",
        "ONDE ENCONTRAR:",
        "e-CAC → Declarações e Demonstrativos → DCTFWeb (débitos) e Pagamentos e Parcelamentos → Consulta comprovante de pagamento (DARF).",
        "COMO IMPORTAR:",
        "Tela Importação → Tipo: Planilha / CSV / XLSX → Conteúdo da planilha: dctfweb → Perfil: generico → arraste este arquivo.",
    ])
    wb.save(PASTA / "modelo_dctfweb_pagamentos_lucro_real.xlsx")


# ------------------------------------------------------------------ balancete
def balancete():
    wb = Workbook()
    ws = wb.active
    ws.title = "Preencher"
    cabecalho(ws, ["competencia", "conta", "descricao", "saldo_anterior", "debito", "credito", "saldo_atual"], [13, 16, 34, 16, 16, 16, 16])
    texto(ws, "A")
    texto(ws, "B")
    dinheiro(ws, ["D", "E", "F", "G"])
    for i, d in enumerate(["Receita bruta de vendas de mercadorias", "Receita bruta de prestação de serviços", "ICMS a recolher",
                           "PIS a recolher", "COFINS a recolher", "ICMS a recuperar"], 2):
        ws.cell(row=i, column=3, value=d)
        for c in (1, 2, 4, 5, 6, 7):
            ws.cell(row=i, column=c).fill = AMARELO
    instrucoes(wb, "Balancete — contabilidade × fiscal", [
        "PARA QUE SERVE:",
        "O sistema compara a contabilidade com o fiscal: receita contábil × notas de saída, e ICMS/PIS/COFINS a recolher × apuração da "
        "EFD. Se você tiver a ECD (arquivo SPED Contábil), pode importá-la no lugar desta planilha.",
        "COMO PREENCHER (aba 'Preencher', células amarelas):",
        "competencia — mês no formato MM/AAAA (ex.: 10/2026).",
        "conta — código da conta no seu plano de contas (ex.: 3.1.01). A descrição já sugere as contas que importam; ajuste ao seu plano.",
        "saldo_anterior, debito, credito, saldo_atual — valores do balancete do mês. Contas de saldo credor (receitas, impostos a recolher) "
        "podem vir com sinal negativo no saldo, como em muitos sistemas: o sistema entende os dois jeitos para receita e usa o valor absoluto.",
        "Pode colar o balancete inteiro do sistema contábil, desde que mantenha estes nomes de coluna.",
        "DEPOIS DE IMPORTAR (obrigatório para o cruzamento):",
        "Tela Empresas → Mapeamento de contas: escolha o grupo de cada conta — RECEITA_BRUTA, ICMS_A_RECOLHER, PIS_A_RECOLHER, "
        "COFINS_A_RECOLHER, ICMS_A_RECUPERAR — e clique em Salvar mapeamento.",
        "COMO IMPORTAR:",
        "Tela Importação → Tipo: Planilha / CSV / XLSX → Conteúdo da planilha: balancete → Perfil: generico → arraste este arquivo.",
    ])
    wb.save(PASTA / "modelo_balancete.xlsx")


# ------------------------------------------------------------------ livro de saídas/entradas de outro sistema (opcional)
def livro_documentos():
    wb = Workbook()
    ws = wb.active
    ws.title = "Preencher"
    cols = ["chave", "numero", "serie", "data", "operacao", "cfop", "cnpj", "valor_contabil", "base_calculo", "valor_icms",
            "valor_ipi", "valor_pis", "valor_cofins"]
    cabecalho(ws, cols, [48, 10, 7, 12, 10, 8, 18, 15, 15, 13, 12, 12, 12])
    for c in ("A", "B", "C", "D", "E", "F", "G"):
        texto(ws, c)
    dinheiro(ws, ["H", "I", "J", "K", "L", "M"])
    dv = DataValidation(type="list", formula1='"E,S"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("E2:E5000")
    instrucoes(wb, "Livro de entradas/saídas de outro sistema (opcional)", [
        "PARA QUE SERVE:",
        "Comparar o que o seu sistema fiscal registrou (Fortes, Domínio, Alterdata, SCI…) com os XMLs. Útil quando você ainda não tem a EFD "
        "ou quer conferir um segundo sistema. Se já vai importar a EFD ICMS/IPI, este arquivo é opcional.",
        "COMO PREENCHER:",
        "Uma linha por nota (ou por item). chave = chave de acesso de 44 dígitos (a melhor forma de casar com o XML). "
        "operacao = E (entrada) ou S (saída); se ficar em branco, o sistema deduz pelo CFOP. cnpj = do fornecedor/cliente.",
        "Pode colar o relatório exportado do seu sistema: se os nomes das colunas forem diferentes, escolha o perfil do sistema na importação "
        "(fortes, dominio, alterdata, sci) ou renomeie as colunas para as deste modelo.",
        "COMO IMPORTAR:",
        "Tela Importação → Tipo: Planilha / CSV / XLSX → Conteúdo da planilha: documentos → Perfil: generico (ou o do seu sistema).",
    ])
    wb.save(PASTA / "modelo_livro_documentos_opcional.xlsx")


if __name__ == "__main__":
    dctfweb()
    balancete()
    livro_documentos()
    print("Modelos gerados em", PASTA)
