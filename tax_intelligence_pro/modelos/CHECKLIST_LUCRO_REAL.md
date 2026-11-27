# Checklist — análise de empresa do Lucro Real

Comece com **um mês**. Todos os arquivos devem ser **da mesma empresa e do mesmo mês**.

## 1. Cadastro (tela Empresas)
- [ ] CNPJ
- [ ] Razão social
- [ ] Regime: **Lucro Real**
- [ ] UF
- [ ] Marcar **Contribuinte do IPI** se for indústria ou equiparada

## 2. Arquivos (tela Importação → Detectar automaticamente)
| ✔ | Arquivo | Onde conseguir | Essencial? |
|---|---|---|---|
| [ ] | XMLs de **saída** do mês (NF-e) | Sistema emissor ou portal da SEFAZ | Sim |
| [ ] | XMLs de **entrada** do mês (NF-e e CT-e) | Portal da SEFAZ ou Ambiente Nacional (traz também as notas que não chegaram por e-mail) | Sim |
| [ ] | Eventos de **cancelamento** | Junto com os XMLs | Se houver |
| [ ] | **EFD ICMS/IPI** (.txt) | Exportado pelo sistema fiscal ou recibo do PVA | Sim |
| [ ] | **EFD-Contribuições** (.txt) | Exportado pelo sistema fiscal | Sim |
| [ ] | **NFS-e** emitidas e tomadas (XML) | Portal da prefeitura ou emissor nacional | Se presta ou contrata serviços |
| [ ] | **ECD** (.txt) | Sistema contábil | Opcional (substitui o balancete) |

Dica: os XMLs podem ir todos juntos num **arquivo ZIP**.

## 3. Planilhas (tela Importação → Planilha / CSV / XLSX)
| ✔ | Modelo | Conteúdo a escolher | Essencial? |
|---|---|---|---|
| [ ] | `modelo_dctfweb_pagamentos_lucro_real.xlsx` | dctfweb | Recomendado |
| [ ] | `modelo_balancete.xlsx` | balancete | Opcional (se não tiver a ECD) |
| [ ] | `modelo_livro_documentos_opcional.xlsx` | documentos | Opcional |

## 4. Depois de importar
- [ ] Se enviou balancete ou ECD: **Empresas → Mapeamento de contas** (receita, ICMS, PIS e COFINS a recolher) → Salvar
- [ ] Uma vez só: **Motor de regras → ICMS.INTERNA → Alterar**. Preencha a **UF** e o parâmetro `"padrao"` com a alíquota interna do seu estado, em fração (ex.: `0.18`), citando o RICMS no fundamento.
- [ ] **Cruzamentos e achados** → escolher o mês → **Cruzar informações**
- [ ] Revisar os **vermelhos** (riscos) e depois os **azuis** (oportunidades)
- [ ] Validar cada achado conferido e gerar o **Relatório técnico**

## O que cada arquivo libera
| Arquivos | Verificações |
|---|---|
| XMLs | Alíquota interestadual, base de cálculo, ICMS na base de PIS/COFINS (Tema 69), monofásico tributado, créditos possíveis |
| + EFD ICMS/IPI | Saída não escriturada, crédito de ICMS não aproveitado ou indevido, divergência XML × escrituração, apuração (E110) |
| + EFD-Contribuições | Crédito de PIS/COFINS não aproveitado, aritmética M200/M600, saldo credor, retenções não deduzidas |
| + DCTFWeb / pagamentos | Escrituração × declaração, pagamento indevido (PER/DCOMP) ou a menor |
| + Balancete / ECD | Receita e impostos a recolher: contabilidade × fiscal |
