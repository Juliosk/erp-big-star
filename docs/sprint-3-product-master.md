# Sprint 3 — M2 Product Master

Status: primeiro lote 030–032 implementado e validado tecnicamente; aguardando homologação
do usuário. Não constitui aprovação da Sprint 3.

Atualização: 030–032 homologados pelo usuário. Lote final 033–039 em execução.

### Commit 033 — consultas

GET `/api/v1/products?company_id=<uuid>&page=1&page_size=50&lifecycle=ATIVO` retorna
`data` e `meta` (page, page_size, has_more); page_size máximo 100, página máxima 100000.
GET `/api/v1/products/{id}?company_id=<uuid>` retorna produto e ETag. Respostas não são cacheáveis.
Ambas exigem `product.product.read`. M1 resolve empresas ativas por contrato público
`CompanyAccessService`; branch permite leitura da empresa ancestral, não escrita company-wide.
Empresa/produto fora do escopo retornam 404; permissão ausente 403; token ausente/inválido 401;
adapter de autenticação não configurado 503. Nenhum contexto é inferido de headers de permissões.

Validação 033: 212 testes aprovados; Ruff/format e mypy strict limpos. Identidade injetada nos
testes é um stub exclusivo da suíte, não um adapter entregue para produção.

## 1. Objetivo

Entregar o primeiro Product Master funcional, proprietário do cadastro oficial de produto.
Baseline: Etapa 10 §§58–61 e 146; README de governança §§18–22; Etapa 2 §§22 e 84;
Etapa 3 §33; Etapa 5 §51; Etapa 6 §58. A Sprint 2 foi homologada pelo usuário.

## 2. Escopo

Product, Product List, Product Detail, Product Create, Lifecycle e Barcode. Tipos oficiais:
PA, PI, MA, AUX, EMB e KIT. Estados: EM_DESENVOLVIMENTO, EM_HOMOLOGACAO, ATIVO e
FORA_DE_LINHA. Novos produtos iniciam em desenvolvimento, nunca ativos por padrão.

Primeiro lote: domínio puro, tabela e repositório por empresa com concorrência otimista.
Não expõe rotas ou comandos de negócio antes da composição de RBAC, Audit e Outbox.

## 3. Fora de escopo

BOM/revisões, fiscal, atributos avançados, variantes, mídia, marketplace, preços, estoque,
importação M23 e embalagens. Packaging pertence ao backlog geral W1-M02-003, mas não à
lista da Sprint 3 (§146); sua versão/evento será entregue em lote posterior explícito.
Ativação de produto não substitui gates de qualidade/regulatório/estoque dos outros módulos.

## 4. Dependências

PostgreSQL, M1 Company e contratos públicos de autorização; Error Contract, controle de versão,
Idempotency, Audit, Outbox/Inbox, RabbitMQ e observabilidade já existentes. Sem novas dependências
Python neste lote. As telas dependem do shell web e da autenticação efetiva: verificar prontidão
antes do commit 038; não declarar frontend entregue por existir apenas OpenAPI.

## 5. DoR Check e decisões explícitas

- [x] Owner M2, objetivo, tipos, estados, entidades e limites identificados.
- [x] Campos essenciais: id, company_id, code, sku, name, product_type, lifecycle, uom, version.
- [x] Tenant obrigatório neste lote; ausência de empresa nunca significa acesso global.
- [x] SKU canônico único no catálogo, conforme Etapa 2 §84; code único por empresa.
- [x] Identificadores ASCII em maiúsculas, 1–64 caracteres; uom 1–12; nome 1–200.
      Limites técnicos locais, não especificações adicionais atribuídas aos documentos.
- [x] Foundation FK para admin.company, RESTRICT; nenhuma escrita M2 em tabelas M1.
- [x] Critérios de teste e concorrência definidos para 030–032.
- [ ] Aplicabilidade global: §58 menciona company/global sem política detalhada de autorização.
      Este lote suporta somente company; habilitar global requer decisão registrada sobre owner,
      visibilidade e manutenção. Não inferir compartilhamento a partir de NULL ou role administrativa.
- [ ] Confirmar política de transições e pré-condições de ativação antes do commit 036.
- [ ] Definir unicidade/tipos de barcode e autorização de discontinue antes de expor comandos.
- [ ] Resolver adapter real de autenticação e prontidão do shell antes de homologar API/UI.

DoR do primeiro lote atendido; os itens pendentes bloqueiam suas próprias fatias, não o domínio base.

## 6. Backlog ordenado

030 domínio → 031 migration → 032 repositório → 033 consultas/RBAC/API → 034 criação atômica
→ 035 alteração concorrente → 036 lifecycle → 037 barcode → 038 telas → 039 E2E/operação.

## 7. Arquivos a criar/alterar

```text
erp/modules/product/
  README.md
  domain/product.py                  # 030: agregado, tipos, invariantes
  infrastructure/product_model.py    # 031: mapeamento do owner M2
  infrastructure/product_repository.py # 032: SQL filtrado por company_id
migrations/versions/0010_create_product_master.py
tests/unit/modules/product/test_product.py
tests/integration/test_product_persistence.py
docs/sprint-3-product-master.md
```

Nos lotes seguintes: application (DTOs, portas e serviços), api (schemas/rotas), events
(contratos/consumers), composição em erp/apps e testes espelhando as camadas. Imports de
domínio limitados à stdlib e ao próprio M2; tipos ORM não atravessam as portas.

## 8. Migrations

0010, após 0009: cria schema product e product.product, constraints de campos/enum/version,
FK company, índices de consulta por empresa/lifecycle e business keys. Não altera M1.
Downgrade remove apenas a tabela/schema novos: é destrutivo para produtos, exige backup e
autorização em ambiente com dados. Testar ida/volta apenas em banco descartável vazio.
Uma migration adicional para barcodes será definida no commit 037; não criar tabelas especulativas.

## 9. APIs planejadas (não implementadas no lote inicial)

GET/POST /api/v1/products; GET/PATCH /api/v1/products/{id};
POST /api/v1/products/{id}/activate e /discontinue;
GET/POST /api/v1/products/{id}/barcodes. Paginação limitada e determinística.
Empresa selecionada deve ser validada contra escopos autenticados por contrato M1.
Não aceitar headers de permissões, nem tratar UUID de empresa como autorização.

## 10. Events / Contracts

ProductCreated (product_id, sku, product_type); ProductUpdated (product_id, changed_fields, version);
ProductActivated (product_id, sku, effective_at); ProductDiscontinued (product_id, effective_at);
ProductBarcodeChanged (product_id, barcode_type, barcode). Envelope versionado da plataforma,
incluindo empresa, versão do agregado e correlation_id. Eventos somente via Outbox na mesma
transação do comando; consumidores não consultam tabelas internas de M2.

## 11. Permissions / Scope / SoD

product.product.read/create/update/activate são oficiais. Permissão de discontinue e manutenção
de barcode devem ser explicitamente mapeadas antes de publicação, sem criar bypass.
Scopes de grupo/filial são resolvidos por M1 para uma empresa autorizada: M2 não faz joins
em tabelas internas de M1. Repositório recebe empresa já autorizada; não substitui RBAC.
SoD BOM Editor ≠ Releaser fica fora do escopo, sem flexibilização futura implícita.

## 12. Audit

Comandos públicos exigirão ator, empresa, operação, before/after mascarados, request_id e
correlation_id; confirmação atômica com agregado, registro idempotente e Outbox.
Neste lote somente metadados created/updated_at/by são persistidos; não são o Audit framework.

## 13. Tests

Domínio sem I/O; fronteiras AST; round-trip PostgreSQL; constraints/FK/unicidade;
isolamento de lista/get/save/add; rollback sem commit implícito; duas sessões disputando a
mesma versão com exatamente um vencedor; metadados de ator. Fixtures M2 serão removidas
por seus IDs exatos. Testes futuros: RBAC negativo, 404 sem vazamento, paginação, replay,
idempotency mismatch, If-Match ausente/inválido/obsoleto, rollback Audit/Outbox e Inbox duplicado.

Gate: Ruff check/format, mypy strict e pytest --cov=erp (cobertura de código, com branches).
O piso existente é 80%; manter o novo M2 próximo de cobertura integral, sem medir testes
como se fossem código de produção. Não afrouxar o gate para obter verde.

## 14. Observability

Preservar logging JSON, request_id/correlation_id e Error Contract. Na API, registrar resultados
sem payload sensível, identificar VERSION_CONFLICT e rastrear eventos por empresa/aggregate_id.
O repositório não produz logs de sucesso antes do commit nem publica diretamente no broker.

## 15. Atomic Commit Plan

| Commit | Objetivo | Aceite principal |
| --- | --- | --- |
| 030 | feat(product): add product master aggregate | Invariantes e domínio puro |
| 031 | migration(product): add company-owned product master | Constraints e upgrade 0010 |
| 032 | feat(product): persist tenant-scoped products | Isolamento e CAS real PostgreSQL |
| 033 | feat(product): expose authorized product queries | List/detail paginados, RBAC, erros |
| 034 | feat(product): create products atomically | Idempotência, Audit e ProductCreated |
| 035 | feat(product): enforce versioned product updates | If-Match, 409 e ProductUpdated |
| 036 | feat(product): implement lifecycle commands | Transições aprovadas e eventos |
| 037 | feat(product): manage product barcodes | Migration, unicidade e evento |
| 038 | feat(web): add product master screens | List/detail/create funcionais |
| 039 | test(product): complete product master vertical slice | E2E, operação e evidências DoD |

## 16. DoD Check

Primeiro lote: domínio/repositório testados, migration revisada e aplicada para validação,
isolamento garantido nas consultas/escritas, conflitos atômicos, documentação e análise estática.
Sprint completa: todas as APIs, telas, permissões, Audit, Outbox/consumers, testes negativos/E2E,
contratos e runbook implementados e homologados. 030–032 não representam a Sprint completa.

## 17. Exit Criteria

Usuário autorizado cria produto, lista e consulta somente seu escopo, altera com concorrência
controlada, gerencia lifecycle/barcode e acompanha resultado nas telas; retries não duplicam
efeitos. Nenhum domínio acessa tabelas M2 diretamente. DoR pendente resolvido e validação
local pelo usuário antes de avançar à Sprint 4 (M23 Import Core).

## Evidências do lote 030–032 — 2026-09-07

- 030: `0a3f593`, agregado e plano; 031: `e290a6c`, schema/migration.
- 200 testes aprovados, incluindo PostgreSQL/RabbitMQ e fronteiras arquiteturais.
- Cobertura `--cov=erp`: 91,97%, com branches; M2: 100,00% (132 statements, 36 branches).
- Ruff check/format limpos; mypy strict: 150 arquivos sem erros.
- 0010 aplicada sobre 0009 no banco local; correspondência ORM/schema M2 verificada
  com `include_schemas=True`, constraints inspecionadas e valores inválidos rejeitados pelo banco.
- Em banco descartável: `base → 0010 → 0009 → 0010` aprovado; apenas esse banco temporário
  foi removido após o teste. O banco local homologado não sofreu downgrade.
- Teste concorrente real: duas sessões leem a mesma versão, uma grava versão 2 e a outra
  recebe VERSION_CONFLICT. Testes não deixam suas empresas/produtos de fixture persistidos.
- Um DeprecationWarning de terceiro (Starlette/AnyIO); sem falhas. Dependências não alteradas.

Reprodução dos gates locais:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\ruff.exe check erp tests migrations
.\.venv\Scripts\ruff.exe format --check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --cov=erp --cov-report=term-missing --cov-report=xml
.\.venv\Scripts\python.exe -m coverage report --include="erp/modules/product/*" --precision=2
```

O teste de metadados é restrito ao owner M2. Não equivale a afirmar ausência de drift em todos
os schemas antigos. O lote não contém RBAC de produto, rotas, Audit/Outbox de comandos ou telas:
esses itens continuam explicitamente no plano 033–039.
