# Arquitetura

## Auditoria inicial do repositório

* O repositório `MEI-FACIL-360` tinha apenas o **Lampejo** (professor particular em Python stdlib, sem banco de dados).
* Não havia módulo fiscal, banco, cálculo ou importação para reaproveitar. O TAX INTELLIGENCE PRO foi criado numa pasta
  própria (`tax_intelligence_pro/`) e **nada do Lampejo foi alterado**.
* Do Lampejo veio a convenção de stack: Python com biblioteca padrão e servidor `http.server`, sem dependências de
  instalação. O banco escolhido foi o **SQLite**, que acompanha o Python e permite backup a quente. O esquema usa SQL
  padrão e valores monetários como texto decimal, o que facilita migrar para PostgreSQL.

## Camadas

```
web/ (dashboard JS puro + SVG)  ──HTTP/JSON──►  tip/servidor.py  (rotas, sessão, permissões, cabeçalhos de segurança)
                                                     │
               ┌─────────────────────────────────────┼────────────────────────────────────┐
         tip/calc/                             tip/importers/                       tip/analise/
   simples · presumido_real ·            base (validação/detecção) ·        creditos (avaliação por item)
   comparador · memoria                  sped · xml_fiscal · tabular        cruzamentos (13 verificações)
               │                          → modelo canônico                  achados (cores, a–g, status)
               └──────────────► tip/regras.py (motor de regras versionado) ◄──────────┘
                                         │
                tip/db.py (SQLite + migrações) · tip/seguranca.py (usuários, trilha, LGPD) · tip/servico.py · tip/relatorios.py
```

### Motor de regras (`tip/regras.py`, `regras/*.json`)

* Uma regra tem: `codigo`, `tributo`, `ente` (FEDERAL/ESTADUAL/MUNICIPAL/NACIONAL), `uf`/`municipio`, `regime`,
  `vigencia_inicio`/`vigencia_fim`, `fundamento`, `descricao`, `criterio` e `formula` (expressões), `parametros`
  (JSON), `situacao` (`vigente`/`validar`) e `hash`.
* `obter(codigo, data, uf, municipio)` devolve a regra **vigente na data da operação**, preferindo a mais específica
  (município, depois UF, depois nacional) e, dentro dela, a última versão ativa.
* Alterar uma regra gera a **versão N+1**. A anterior fica inativa mas consultável, o motivo é obrigatório e a mudança
  vai para a trilha de auditoria. Mudança de lei se registra como **nova vigência** do mesmo código.
* As fórmulas são avaliadas por um interpretador fechado (`tip/expr.py`): aritmética, comparações, `min`/`max`/`arred`.
  Não há atributos, importações nem chamadas arbitrárias, então o texto de uma regra nunca executa código.
* Toda simulação e toda análise gravam as regras usadas (código, versão, hash), o que garante rastreabilidade.

### Modelo canônico (padronização entre sistemas)

Todos os importadores produzem um `Lote` com:

* `documentos` + `itens`: chave, modelo, operação E/S, participantes, UF, CRT, totais, CFOP, NCM, CST/CSOSN, bases,
  alíquotas e valores de ICMS/ST/IPI/PIS/COFINS/ISS/IBS/CBS.
* `apuracoes`: tributo, período, campo e valor (E110, E116, E520, M100/M500, M200/M600, PGDAS-D, DCTFWeb, ECF).
* `saldos`: conta, período, saldo inicial, débitos, créditos e saldo final (ECD I155 ou balancete).

Cada registro guarda a `fonte` (`xml`, `efd_icms_ipi`, `efd_contribuicoes`, `planilha:<perfil>`, `pgdas`, `dctfweb`…),
o que permite comparar qualquer fonte com qualquer outra.

### Banco de dados (tabelas)

`usuarios`, `sessoes`, `empresas`, `regras`, `importacoes` (com SHA-256), `documentos`, `itens`, `apuracoes`,
`saldos_contabeis`, `mapa_contas`, `simulacoes` (entrada, resultado, regras e hash), `analises`, `achados` (com
histórico de validação) e `auditoria` (cadeia de hashes).

### Segurança e LGPD

* Senhas com PBKDF2-SHA256 (310 mil iterações). Os tokens de sessão ficam guardados só como hash e expiram em 8 h.
* Login limitado a 10 tentativas por IP a cada 5 minutos.
* Papéis: `admin`, `auditor`, `analista` e `leitura`, com permissões verificadas em todas as rotas.
* Trilha de auditoria: cada evento grava o hash do anterior, e `verificar_trilha` detecta alteração ou remoção.
* CPF é mascarado em trilha e relatórios. Há anonimização de participantes pessoa física e eliminação de dados por empresa.
* Pasta de dados com permissão 0700. Backups com 0600, manifesto SHA-256, cifragem opcional (Fernet) e restauração
  com `integrity_check`.
* Importação validada:
  * extensão e tamanho;
  * XML sem DTD/entidades (anti-XXE);
  * ZIP com limites contra zip-bomb e contra caminhos fora da pasta;
  * conferência do CNPJ do SPED;
  * descarte de arquivo duplicado por hash.
* Cabeçalhos HTTP: CSP sem script inline, `X-Frame-Options`, `nosniff`, `no-store`. O servidor ouve só em
  `127.0.0.1` por padrão.

## Etapas de implementação

1. Núcleo: aritmética `Decimal`, expressões seguras e banco.
2. Motor de regras com sementes fundamentadas.
3. Calculadoras e comparador.
4. Importadores e modelo canônico.
5. Motor de créditos e cruzamentos.
6. Segurança, serviços e relatórios.
7. API e dashboard.
8. Testes e documentação.
