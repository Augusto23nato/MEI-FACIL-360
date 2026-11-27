# Funcionalidades em detalhe

## 1. Simuladores (`tip/calc`)

### Simples Nacional (`simples.simular`)
Entrada: `periodo`, `rbt12`, `folha12`, `meses_atividade`, `das_pago` e `parcelas`. Cada parcela tem `descricao`,
`anexo` (I a V ou `FATOR_R`), `valor` e `tipos` (`monofasico`, `icms_st`, `iss_retido`, `exportacao`).

* Alíquota efetiva = (RBT12 × Aliq − PD) / RBT12 (LC 123, art. 18, §1º-A), com as tabelas dos Anexos I a V.
* Repartição por tributo. No Anexo III/IV/V, o ISS acima de 5% é redistribuído aos tributos federais.
* Fator R ≥ 28% leva ao Anexo III; abaixo disso, ao Anexo V.
* No início de atividade, a RBT12 é proporcionalizada (art. 18, §2º).
* Alertas: sublimite de R$ 3,6 mi, limite de R$ 4,8 mi e DAS pago diferente do recalculado.

### Lucro Presumido (`presumido_real.presumido`)
* Presunção por atividade (Lei 9.249, arts. 15 e 20). IRPJ de 15% mais adicional de 10% sobre o que passar de
  R$ 60 mil no trimestre. CSLL de 9%.
* PIS 0,65% e COFINS 3% cumulativos, com exclusão do ICMS destacado e da receita monofásica.
* Retenções e comparação com o valor pago.
* Acréscimo de 10% na presunção sobre a receita acima de R$ 5 mi/ano (LC 224/2025): para a CSLL só a partir de
  04/2026, com alerta para validação.

### Lucro Real (`presumido_real.real`)
* Lucro ajustado = lucro contábil + adições − exclusões.
* Compensação de prejuízo fiscal e base negativa limitada a 30%.
* IRPJ com adicional proporcional ao número de meses.
* PIS 1,65% e COFINS 7,6% sobre a receita (sem o ICMS), menos os créditos. Mostra saldo credor quando houver.

### Comparativo (`comparador.comparar`) e Reforma (`presumido_real.reforma`)
* O comparativo projeta o ano nos três regimes, com premissas explícitas, aponta o melhor e calcula a economia em
  relação ao regime atual.
* A Reforma segue o cronograma 2026–2033. 2026 é o ano de teste (CBS 0,9% e IBS 0,1%). A partir de 2027, as
  alíquotas de referência precisam ser informadas: o sistema não as presume.

Toda simulação retorna `memoria` (passos legíveis), `regras_usadas` e `alertas`, e é salva com hash.

## 2. Importação (`tip/importers`)

| Arquivo | Leitura |
|---|---|
| NF-e/NFC-e XML | ide, emit, dest, itens (prod, ICMS/CSOSN, IPI, PIS, COFINS, ISSQN, IBSCBS), totais e protocolo (cStat) |
| Evento NF-e | cancelamento (110111), que marca a NF-e como cancelada |
| CT-e XML | tomador, emitente, valor da prestação e ICMS |
| NFS-e XML | padrão Nacional e ABRASF (por nome de tag): prestador, tomador, serviço, ISS, retenções |
| EFD ICMS/IPI | 0000, 0150, 0200, C100, C170, C190, D100, E110, E116, E520 e conferência do bloco 9 |
| EFD-Contribuições | 0000, 0110, C100, C170, M100/M500, M200/M600 |
| ECD | I050, I150, I155 (saldos por período) |
| ECF | leitura genérica de linhas de cálculo `|REG|CODIGO|DESCRICAO|VALOR|` |
| CSV/XLSX/JSON | `documentos`, `apuracao`, `balancete`, `pgdas`, `dctfweb`, `pagamentos`, com perfis em `regras/perfis_importacao.json` |

Colunas esperadas por tipo de planilha (nomes alternativos aceitos estão no arquivo de perfis):

* **pgdas**: `periodo`, `receita_bruta`, `rbt12`, `receita_monofasico`, `receita_st`, `receita_exportacao`,
  `valor_das`, `valor_pago`, `anexo`.
* **dctfweb**: `periodo`, `tributo`, `codigo_receita`, `valor_debito`, `valor_pago`.
* **balancete**: `competencia`, `conta`, `descricao`, `saldo_anterior`, `debito`, `credito`, `saldo_atual`.
* **documentos**: `chave`, `numero`, `serie`, `data`, `cfop`, `ncm`, `valor_contabil`, `base_icms`, `valor_icms`… (uma
  linha por documento ou por item).

## 3. Motor de créditos (`tip/analise/creditos.py`)

Cada item de entrada recebe a classificação **DIREITO**, **POTENCIAL** ou **SEM_DIREITO**, com motivo, fundamento e
grau de confiança. Nunca há crédito automático:

* **Regime do adquirente**:
  * Simples: não credita ICMS nem PIS/COFINS.
  * Presumido: só ICMS (PIS/COFINS cumulativos).
  * Real: ICMS e PIS/COFINS.
  * IPI só para contribuinte do IPI.
* **Finalidade pelo CFOP de entrada**:
  * Escriturado (C170) quando existir. Sem C170, é presumido pelo CFOP do emitente, com confiança reduzida.
  * Revenda, industrialização, energia, frete e devolução geram crédito.
  * Uso e consumo: ICMS só a partir de 2033; PIS/COFINS dependem do Tema 779.
  * Imobilizado: CIAP em 1/48 ou depreciação.
  * Remessas e bonificações: sem crédito.
  * ST: sem crédito do ICMS próprio do fornecedor.
* **Fornecedor**:
  * Pessoa física: sem crédito de PIS/COFINS.
  * CST 04/05/06/07/08/09: bem não sujeito ao pagamento.
  * CST 02/03 ou NCM monofásico na revenda: vedado.
  * Simples (CRT 1): ICMS somente pelo `vCredICMSSN`.
* **Base de PIS/COFINS**: produto − desconto + frete/seguro/outras + IPI não recuperável − ICMS (desde 05/2023).

## 4. Cruzamentos (`tip/analise/cruzamentos.py`)

| # | Verificação | Achados típicos |
|---|---|---|
| 1 | Integridade | XML duplicado, documento/crédito escriturado em duplicidade |
| 2 | XML × EFD ICMS/IPI e × EFD-Contribuições | saída não escriturada, entrada não escriturada, cancelada escriturada, divergência de valores, escriturado sem XML |
| 3 | Créditos | não aproveitado, indevido, potencial a validar, incompatível com o CFOP (ICMS por documento; PIS/COFINS por período × M100/M500) |
| 4 | Apuração do ICMS | E110 × C190/D100, aritmética do saldo, E116, saldo credor anterior × transportado, saldo credor acumulado |
| 5 | Apuração de PIS/COFINS | aritmética de M200/M600, saldo de créditos |
| 6 | Apuração × declarações × pagamentos | EFD × DCTFWeb, pagamento indevido (PER/DCOMP) ou a menor |
| 7 | Simples Nacional | receita PGDAS-D × notas, segregação monofásica/ST não aplicada (com recálculo do DAS), DAS recalculado, CRT |
| 8 | Alíquotas e tributação | interestadual (Res. SF 22/89 e 13/12), interna cadastrada, ICMS ≠ base × alíquota, base maior/reduzida, CST incompatível, ICMS debitado em ST, PIS/COFINS fora do regime, monofásico tributado, ICMS na base de PIS/COFINS (Tema 69), ISS fora de 2–5% |
| 9 | Contábil × fiscal | receita contábil × fiscal, ICMS/PIS/COFINS a recolher × apuração (com mapa de contas) |
| 10 | Sistemas | planilha de um software × XML/EFD × planilha de outro software |
| 11 | Retenções | PIS/COFINS/IR/CSLL retidos nas NFS-e × deduzidos na apuração |
| 12 | Reforma | NF-e de 2026 sem grupo IBS/CBS; IBS/CBS destacados nas aquisições |

Cada achado traz os itens a seguir. As oportunidades (cor AZUL) trazem sempre os sete itens a–g:

* a) origem (fontes, documentos, registros);
* b) fundamentação legal;
* c) memória de cálculo;
* d) valor estimado;
* e) grau de confiança;
* f) documentação necessária;
* g) procedimento de validação.

O fluxo de status é `pendente_validacao` → `validado_documental` → `validado_juridico` (ou `descartado`), com
justificativa e documentos obrigatórios.

## 5. API (principais rotas)

`POST /api/login` · `GET /api/dashboard?empresa=` · `POST /api/simular/{simples|presumido|real|comparativo|reforma}` ·
`GET /api/simples/curva` · `POST /api/importar?empresa=&tipo=&tipo_planilha=&perfil=` (corpo = arquivo, cabeçalho
`X-Filename`) · `POST /api/analisar` · `GET /api/analises/{id}` · `GET /api/analises/{id}/relatorio.html` ·
`GET /api/analises/{id}/achados.csv` · `POST /api/achados/{id}/validar` · `GET/POST/PUT /api/regras` ·
`GET /api/regras/historico/{codigo}` · `GET/POST/PUT /api/usuarios` · `GET /api/auditoria` · `POST /api/backup` ·
`POST /api/restaurar` · `POST /api/empresas/{id}/anonimizar` · `DELETE /api/empresas/{id}/dados`.

## 6. Testes (`tests/`)

43 testes. Os cálculos são validados com exemplos conferidos à mão contra a lei:

* **Simples Nacional**: alíquota efetiva nos 5 anexos, teto do ISS, Fator R, segregação, início de atividade.
* **Lucro Presumido**: serviços, comércio, retenções e a LC 224/2025.
* **Lucro Real**: adicional, trava de 30%, saldo credor.
* **Comparativo** e **IBS/CBS** 2026.

Os testes de integração geram arquivos fictícios com divergências plantadas (`exemplos/gerar.py`) e conferem cada
valor esperado. Também cobrem a API HTTP, as permissões, a adulteração da trilha e o backup/restauração.
