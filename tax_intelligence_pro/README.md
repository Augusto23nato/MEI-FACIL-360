# TAX INTELLIGENCE PRO

Camada **independente de auditoria e inteligência tributária** para escritórios contábeis, departamentos fiscais e
consultorias. Simula regimes, cruza documentos fiscais com escriturações, apurações, declarações e contabilidade,
avalia créditos item a item e aponta divergências e oportunidades, sempre com origem, fundamento legal, memória de
cálculo e procedimento de validação.

> Nenhum crédito ou recuperação é classificado como definitivo: todo achado nasce **pendente de validação** e só muda
> de status por validação documental e jurídica registrada na trilha de auditoria.

## Como rodar no Windows (sem digitar comandos)

1. Instale o Python em https://www.python.org/downloads/ marcando **"Add Python to PATH"**.
2. Opcional: clique duas vezes em **`CARREGAR_DEMONSTRACAO.bat`** para criar 2 empresas fictícias de exemplo.
3. Clique duas vezes em **`INICIAR.bat`**. O navegador abre em http://127.0.0.1:8360 e a janela preta mostra a senha
   do primeiro acesso. Não feche a janela preta enquanto usar o sistema.

Esqueceu a senha? Clique duas vezes em **`RESETAR_SENHA.bat`** (ou rode `python -m tip.redefinir_senha`): é gerada
uma senha nova para o `admin`, sem perder dados, e o evento fica na trilha de auditoria.

## Como rodar (Mac/Linux ou pelo terminal)

Requisitos: Python 3.11+ (somente biblioteca padrão). Opcional: `openpyxl` para planilhas `.xlsx` e
`cryptography` para cifrar backups.

```bash
cd tax_intelligence_pro
./iniciar.sh demo      # opcional: carrega 2 empresas fictícias com arquivos de exemplo
./iniciar.sh           # http://127.0.0.1:8360
./iniciar.sh testes    # suíte de testes (unitários + integração)
```

No primeiro start é criado o usuário `admin`; a senha inicial fica em `data/SENHA_INICIAL_ADMIN.txt` (troque-a em
*Administração* e apague o arquivo). Variáveis: `TIP_DATA_DIR` (pasta de dados), `TIP_HOST`, `TIP_PORTA`,
`TIP_BACKUP_KEY` (chave Fernet para backups cifrados).

## O que o sistema faz

| Área | Funcionalidades |
|---|---|
| Simuladores | Simples Nacional (faixa, nominal, PD, efetiva, repartição, teto de ISS, Fator R, segregação monofásico/ST/ISS retido/exportação, início de atividade, sublimite), Lucro Presumido (presunção por atividade, adicional, exclusão do ICMS, monofásicos, retenções, LC 224/2025), Lucro Real (LALUR, trava de 30%, PIS/COFINS não cumulativos com créditos), comparativo de regimes e transição IBS/CBS |
| Importação | XML de NF-e/NFC-e (com grupo IBS/CBS), eventos de cancelamento, CT-e, NFS-e (Nacional e ABRASF), ZIP, EFD ICMS/IPI, EFD-Contribuições, ECD, ECF, CSV/XLSX (documentos, apuração, balancete, PGDAS-D, DCTFWeb, pagamentos) com perfis Fortes/Domínio/Alterdata/SCI |
| Motor de créditos | PIS/COFINS não cumulativos, ICMS e IPI, por item: regime, finalidade (CFOP), CST do fornecedor, PF×PJ, monofásico, ST, imobilizado (CIAP), uso e consumo, exclusão do ICMS da base (Lei 14.592/2023) |
| Cruzamentos | XML × EFD (ausências, divergências, canceladas), créditos registrados × permitidos, duplicados, incompatíveis, E110 × C190 × E116, saldo credor transportado, M200/M600, escrituração × DCTFWeb × pagamentos, PGDAS-D × notas, segregação não aplicada, alíquotas interestaduais, base de cálculo, Tema 69, monofásico tributado, contábil × fiscal, sistema × sistema, retenções, grupo IBS/CBS |
| Dashboard | Carga tributária, comparativo de regimes, gráfico de alíquotas, créditos identificados/utilizados/pendentes/indevidos, divergências, economia potencial, histórico, relatórios. Cores: VERDE conciliado · AMARELO análise · VERMELHO inconsistência · AZUL oportunidade |
| Regras | Tributo, ente, regime, vigência, fundamento, critério, fórmula e histórico; edição pelo dashboard gera nova versão, sem recompilar |
| Segurança | Usuários e papéis, sessões, trilha de auditoria encadeada por hash, mascaramento de CPF, anonimização/eliminação (LGPD), backup com SHA-256 e restauração verificada, validação de arquivos (tamanho, tipo, XXE, zip-bomb, CNPJ) |

Documentação técnica: [docs/ARQUITETURA.md](docs/ARQUITETURA.md) · [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md).

## Limites conhecidos (por desenho)

* **Alíquotas internas de ICMS e alíquotas de referência de IBS/CBS não vêm pré-carregadas**: o sistema não inventa
  alíquotas. Cadastre-as no motor de regras (por UF/município e vigência) a partir da legislação.
* A tabela de NCM monofásicos é **parcial** (prefixos para triagem) e está marcada como `validar`.
* A regra da **LC 224/2025** (acréscimo de presunção) está marcada como `validar` até a confirmação da regulamentação da RFB.
* Os perfis de importação de Fortes/Domínio/Alterdata/SCI são **de partida**: confira os nomes de coluna do relatório
  exportado e ajuste `regras/perfis_importacao.json`.
* O PGDAS-D e a DCTFWeb entram por planilha (CSV/XLSX) com as colunas descritas na documentação.
