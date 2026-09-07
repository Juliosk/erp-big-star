# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 6 — Mapa Consolidado de APIs M1–M23

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Superfície consolidada de APIs REST, contratos internos de aplicação e callbacks de integração dos módulos M1–M23  
**Objetivo:** Definir a baseline oficial de APIs do ERP, incluindo convenções REST, versionamento, autenticação/autorização, idempotência, optimistic locking, paginação, filtros, tratamento de erros, uploads/downloads, jobs assíncronos, OpenAPI, contract testing, observabilidade e ownership por domínio.

---

# 1. Objetivo da Etapa 6

A Etapa 6 transforma os Bounded Contexts, o modelo de dados, o catálogo de eventos, a matriz de integrações e o modelo global de RBAC/SoD em uma superfície de APIs única, previsível e implementável.

A etapa responde:

```text
Qual endpoint representa cada recurso?
Qual módulo é dono dele?
Qual método HTTP utilizar?
Qual permissão é necessária?
Como paginar?
Como filtrar?
Como tratar concorrência?
Como garantir idempotência?
Como representar erros?
Como enviar arquivos?
Como lidar com jobs assíncronos?
Como versionar contratos?
Como depreciar uma API?
```

A API oficial obedecerá simultaneamente:

```text
REST
+
API FIRST
+
DOMAIN OWNERSHIP
+
RBAC
+
OPTIMISTIC LOCKING
+
IDEMPOTENCY
+
AUDITABILITY
```

---

# 2. API não Substitui Fronteiras de Domínio

Mesmo existindo endpoints REST:

```text
/api/v1/inventory/...
```

isso não significa que módulos internos do Monólito Modular devam se integrar via HTTP.

Dentro do monólito:

```text
M4
→ Application Contract
→ M5
```

é preferível a:

```text
M4
→ HTTP localhost
→ M5
```

A API REST é prioritariamente fronteira para:

- frontend web/PWA;
- integrações externas autorizadas;
- automação;
- parceiros;
- ferramentas administrativas.

---

# 3. Três Superfícies de Contrato

```text
PUBLIC / FRONTEND API
INTERNAL APPLICATION CONTRACT
INTEGRATION CALLBACK API
```

## 3.1 Public / Frontend API

```text
/api/v1/...
```

Usada pelo frontend web/PWA e integrações autorizadas.

## 3.2 Internal Application Contract

Interfaces Python versionadas conceitualmente:

```text
contracts.inventory
contracts.pricing
contracts.finance
```

Sem HTTP dentro do monólito por padrão.

## 3.3 Integration Callback API

```text
/integrations/v1/marketplaces/...
/integrations/v1/fiscal-provider/...
```

Usada por webhooks/callbacks externos.

---

# 4. Base Path

Padrão:

```text
/api/v1
```

Exemplos:

```text
/api/v1/products
/api/v1/orders
/api/v1/inventory/balances
```

Callbacks:

```text
/integrations/v1
```

---

# 5. Versionamento

Versão major na URL:

```text
/api/v1
/api/v2
```

Mudança compatível:

```text
v1 permanece
```

Breaking change:

```text
v2
```

Não usar:

```text
/api/v1.4
```

---

# 6. Compatibilidade Dentro da Mesma Versão

Permitido sem mudar major:

- adicionar campo opcional;
- adicionar endpoint;
- adicionar filtro opcional;
- adicionar valor de enum quando consumidores estiverem preparados;
- adicionar metadata.

Breaking:

- remover campo;
- mudar semântica;
- mudar tipo;
- renomear campo obrigatório;
- mudar cardinalidade.

---

# 7. Convenção de URLs

Recursos no plural:

```text
/products
/orders
/customers
/purchase-orders
```

Relacionamentos:

```text
/products/{id}/barcodes
/orders/{id}/items
```

Comandos de domínio:

```text
/orders/{id}/cancel
/purchase-orders/{id}/submit
/fiscal-documents/{id}/cancel
```

---

# 8. Verbos HTTP

| Método | Uso |
|---|---|
| `GET` | consultar |
| `POST` | criar ou executar comando |
| `PATCH` | alteração parcial |
| `PUT` | substituição integral rara |
| `DELETE` | somente recursos tecnicamente deletáveis |
| `HEAD` | quando útil |
| `OPTIONS` | infraestrutura |

Dados empresariais históricos quase nunca usarão `DELETE`.

---

# 9. CRUD não Governa Todos os Estados

Não fazer:

```text
PATCH /purchase-orders/{id}
{
  "status": "APPROVED"
}
```

Correto:

```text
POST /purchase-orders/{id}/submit
```

O estado é consequência da máquina de estados.

---

# 10. HTTP Status Codes

Baseline:

```text
200 OK
201 Created
202 Accepted
204 No Content

400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found

409 Conflict
422 Unprocessable Entity
428 Precondition Required

429 Too Many Requests

500 Internal Server Error
502 Bad Gateway
503 Service Unavailable
504 Gateway Timeout
```

---

# 11. `201 Created`

Criação síncrona concluída:

```text
POST /customers
→ 201
```

Header:

```text
Location: /api/v1/customers/{id}
```

---

# 12. `202 Accepted`

Processamento assíncrono:

```text
POST /exports
→ 202
```

Resposta:

```json
{
  "job_id": "uuid",
  "status": "QUEUED"
}
```

---

# 13. Error Contract

Formato padrão:

```json
{
  "error": {
    "code": "INVENTORY_INSUFFICIENT",
    "message": "Saldo insuficiente para a operação.",
    "details": [],
    "correlation_id": "uuid"
  }
}
```

---

# 14. Error Code Estável

Frontend decide pelo código:

```text
INVENTORY_INSUFFICIENT
```

e não pelo texto da mensagem.

---

# 15. Validation Errors

Exemplo:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Existem campos inválidos.",
    "details": [
      {
        "field": "tax_id",
        "code": "INVALID_CNPJ"
      }
    ]
  }
}
```

---

# 16. Autenticação

API protegida:

```text
Authorization: Bearer <token>
```

Token identifica:

```text
user_id
session_id
authentication_level
```

---

# 17. Autorização

Cada endpoint declara:

```text
required_permission
scope_resolver
step_up_requirement
```

quando aplicável.

---

# 18. Contexto Multiempresa

Operações persistem explicitamente:

```text
company_id
branch_id
```

quando aplicável.

O contexto jurídico não depende apenas da sessão.

---

# 19. Correlation ID

Cliente pode enviar:

```text
X-Correlation-ID
```

Se ausente, backend gera.

Resposta pode devolver:

```text
X-Correlation-ID
```

---

# 20. Request ID

Cada chamada recebe:

```text
X-Request-ID
```

gerado no ingresso.

---

# 21. Idempotency Key

Comandos críticos repetíveis exigem:

```text
Idempotency-Key
```

Exemplos:

- criar pedido externo;
- emitir intenção fiscal;
- solicitar/transmitir pagamento;
- commit de importação.

---

# 22. Semântica de Idempotência

Mesma chave + mesmo payload:

```text
retorna resultado original
```

Mesma chave + payload diferente:

```text
409 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD
```

---

# 23. Optimistic Locking

Entidades mutáveis retornam:

```text
version
```

Exemplo:

```json
{
  "id": "...",
  "status": "DRAFT",
  "version": 7
}
```

---

# 24. `If-Match`

APIs críticas podem exigir:

```text
If-Match: "7"
```

Conflito:

```text
409 VERSION_CONFLICT
```

---

# 25. `428 Precondition Required`

Se atualização exigir versão e cliente não informar:

```text
428 PRECONDITION_REQUIRED
```

---

# 26. Paginação

Padrão para listas grandes:

```text
cursor pagination
```

Exemplo:

```text
GET /orders?limit=50&cursor=...
```

Resposta:

```json
{
  "items": [],
  "page": {
    "next_cursor": "...",
    "has_more": true
  }
}
```

---

# 27. Offset Pagination

Permitida em cadastros pequenos/admin:

```text
?page=1&page_size=50
```

---

# 28. Limite Máximo

A API impõe:

```text
max_page_size
```

Exemplo:

```text
200
```

---

# 29. Filtering

Filtros explícitos:

```text
?status=OPEN
?company_id=...
?created_from=...
?created_to=...
```

Não oferecer linguagem SQL genérica.

---

# 30. Sorting

Padrão:

```text
?sort=-created_at,order_number
```

somente para campos autorizados.

---

# 31. Busca Textual

```text
?q=...
```

quando houver contrato de busca.

---

# 32. Field Selection

Quando útil:

```text
?fields=id,sku,name,status
```

sempre respeitando Field-Level Security.

---

# 33. Expansões

Relacionamentos opcionais:

```text
?include=items,customer
```

Somente includes documentados.

---

# 34. Bulk Endpoints

Não criar endpoints genéricos de bulk update para mudanças massivas ordinárias.

Bulk oficial:

```text
M23
```

---

# 35. Exportação

Todas as exportações relevantes passam pelo M23:

```text
POST /api/v1/data-exports
```

---

# 36. Importação

```text
POST /api/v1/data-imports
```

M23 orquestra validação e commit.

---

# 37. Upload de Arquivos

Preferência:

```text
multipart/form-data
```

Arquivos grandes:

```text
pre-signed upload
```

para Object Storage.

---

# 38. Download de Arquivos

Quando adequado:

```text
short-lived signed URL
```

sempre após autorização.

---

# 39. Job Resource

Jobs assíncronos:

```text
GET /api/v1/jobs/{id}
```

Estados:

```text
QUEUED
PROCESSING
COMPLETED
FAILED
CANCELLED
```

---

# 40. Cancelamento de Job

Quando tecnicamente seguro:

```text
POST /jobs/{id}/cancel
```

---

# 41. Polling

Frontend pode consultar status de job.

Futuramente:

- WebSocket;
- SSE;
- push notification.

---

# 42. OpenAPI

FastAPI gera OpenAPI automaticamente.

Schemas e descrições são parte do contrato oficial.

---

# 43. OpenAPI por Ambiente

```text
/docs
/openapi.json
```

podem ser restritos em produção.

---

# 44. Operation ID

Exemplos:

```text
create_customer
reserve_inventory
transmit_payment_batch
```

Operation IDs devem ser estáveis.

---

# 45. Tags

Organização por domínio:

```text
Admin
Products
Orders
Inventory
Finance
...
```

---

# 46. Depreciação

Endpoint obsoleto será marcado como deprecated e documentará substituto.

---

# 47. Sunset

Pode ser utilizado com janela de migração.

Nunca remover API usada sem período controlado.

---

# 48. Rate Limiting

Aplicável principalmente a:

- login;
- webhooks;
- consultas caras;
- integrações externas;
- exports.

Redis pode apoiar rate limits.

---

# 49. Limites Diferenciados

Categorias:

```text
interactive user
service account
external integration
```

podem possuir quotas distintas.

---

# 50. Timeout

Chamadas síncronas terão timeout explícito.

Processamento longo:

```text
202 + job
```

---

# 51. Observabilidade

Cada request registra:

```text
request_id
correlation_id

user_id / system_actor

route
method

status_code

duration_ms

company_id
branch_id quando aplicável
```

sem segredos.

---

# 52. Métricas por Endpoint

```text
request_count
error_count
p50
p95
p99
```

---

# 53. API Audit

Ações sensíveis registram:

```text
permission
actor
resource
workflow_reference
step_up_level
reason_code
```

---

# 54. API Contract Tests

Obrigatórios para:

- request schema;
- response schema;
- erros;
- permissions;
- idempotency;
- optimistic locking;
- compatibility.

---

# 55. API e Eventos

A API executa comando local.

Exemplo:

```text
POST /orders/{id}/cancel
```

M4 grava:

```text
transaction
+
OrderCancelled Outbox Event
```

A camada HTTP não publica diretamente no RabbitMQ.

---

# 56. M1 — Administração / Segurança

Base:

```text
/api/v1/admin
```

Principais endpoints:

```text
GET    /economic-groups
POST   /economic-groups

GET    /companies
POST   /companies
GET    /companies/{id}
PATCH  /companies/{id}

GET    /branches
POST   /branches
PATCH  /branches/{id}

GET    /users
POST   /users
GET    /users/{id}
PATCH  /users/{id}
POST   /users/{id}/disable
POST   /users/{id}/enable

GET    /roles
POST   /roles
PATCH  /roles/{id}

GET    /permissions

POST   /users/{id}/roles
DELETE /users/{id}/roles/{role_id}

GET    /users/{id}/scopes
POST   /users/{id}/scopes

GET    /service-accounts
POST   /service-accounts

GET    /access-reviews
POST   /access-reviews
```

---

# 57. Autenticação

```text
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout

POST /api/v1/auth/step-up
POST /api/v1/auth/mfa/verify
```

---

# 58. M2 — Product Master

```text
/api/v1/products
```

```text
GET    /products
POST   /products
GET    /products/{id}
PATCH  /products/{id}

POST   /products/{id}/activate
POST   /products/{id}/discontinue

GET    /products/{id}/barcodes
POST   /products/{id}/barcodes

GET    /products/{id}/packaging
POST   /products/{id}/packaging

GET    /boms
POST   /boms
GET    /boms/{id}

POST   /boms/{id}/revisions
GET    /bom-revisions/{id}
PATCH  /bom-revisions/{id}
POST   /bom-revisions/{id}/release
POST   /bom-revisions/{id}/obsolete
```

---

# 59. M3 — Marketplace Hub

Base:

```text
/api/v1/marketplaces
```

```text
GET    /marketplaces/accounts
POST   /marketplaces/accounts/{channel}/connect
POST   /marketplaces/accounts/{id}/disconnect

GET    /marketplaces/listings
GET    /marketplaces/listings/{id}
POST   /marketplaces/listings/{id}/map-product

GET    /marketplaces/sync-jobs
POST   /marketplaces/sync-jobs
POST   /marketplaces/sync-jobs/{id}/retry

GET    /marketplaces/orders/{external_order_id}/snapshot
```

Callbacks:

```text
POST /integrations/v1/marketplaces/{channel}/webhooks/{account_ref}
```

---

# 60. M4 — Orders / Fulfillment

```text
/api/v1/orders
```

```text
GET    /orders
POST   /orders
GET    /orders/{id}
PATCH  /orders/{id}

POST   /orders/{id}/approve
POST   /orders/{id}/hold
POST   /orders/{id}/release-hold
POST   /orders/{id}/cancel

GET    /orders/{id}/items

GET    /fulfillments
GET    /fulfillments/{id}
POST   /orders/{id}/fulfillments

POST   /fulfillments/{id}/request-billing
```

---

# 61. M5 — Inventory

Base:

```text
/api/v1/inventory
```

```text
GET    /inventory/balances
GET    /inventory/lots

GET    /inventory/reservations
POST   /inventory/reservations
POST   /inventory/reservations/{id}/release

GET    /inventory/transfers
POST   /inventory/transfers
POST   /inventory/transfers/{id}/dispatch
POST   /inventory/transfers/{id}/receive

GET    /inventory/discrepancies
POST   /inventory/discrepancies/{id}/resolve

GET    /inventory/cycle-counts
POST   /inventory/cycle-counts
POST   /inventory/cycle-counts/{id}/confirm
```

Ajustes:

```text
POST /inventory/adjustments
```

---

# 62. M6 — Procurement

Base:

```text
/api/v1/procurement
```

```text
GET/POST /suppliers
GET/PATCH /suppliers/{id}

GET/POST /purchase-requisitions
POST     /purchase-requisitions/{id}/submit

GET/POST /rfqs
POST     /rfqs/{id}/close

GET/POST /supplier-quotes

GET/POST /purchase-orders
GET      /purchase-orders/{id}
PATCH    /purchase-orders/{id}
POST     /purchase-orders/{id}/submit
POST     /purchase-orders/{id}/short-close

GET/POST /goods-receipts
POST     /goods-receipts/{id}/confirm-physical

GET      /three-way-matches/{id}
POST     /three-way-matches/{id}/confirm
```

---

# 63. M7 — Manufacturing

Base:

```text
/api/v1/manufacturing
```

```text
GET/POST /work-centers
GET/POST /resources

GET/POST /routings
POST     /routings/{id}/revisions

GET/POST /production-versions
POST     /production-versions/{id}/activate

GET/POST /production-orders
GET      /production-orders/{id}

POST /production-orders/{id}/release
POST /production-orders/{id}/start
POST /production-orders/{id}/material-issues
POST /production-orders/{id}/yield
POST /production-orders/{id}/scrap
POST /production-orders/{id}/rework
POST /production-orders/{id}/close

GET /lots/{lot_id}/genealogy
```

---

# 64. M8 — Industrial Costing

Base:

```text
/api/v1/costing
```

```text
GET/POST /standard-costs
GET      /standard-costs/{id}
POST     /standard-costs/{id}/submit
POST     /standard-costs/{id}/activate

GET /production-order-costs
GET /production-order-costs/{production_order_id}

GET /cost-variances

GET/POST /costing-periods
POST     /costing-periods/{id}/close
POST     /costing-periods/{id}/reopen

GET /moving-average-costs
```

---

# 65. M9 — Pricing

Base:

```text
/api/v1/pricing
```

```text
GET/POST /price-lists
POST     /price-lists/{id}/versions
POST     /price-list-versions/{id}/activate

GET/POST /pricing-policies

POST /pricing/simulations

GET/POST /pricing-batches
POST     /pricing-batches/{id}/activate

GET /price-reviews
POST /price-reviews/{id}/resolve
```

Resolução externa autorizada:

```text
POST /pricing/resolve
```

---

# 66. M10 — WMS / Expedição

Base:

```text
/api/v1/wms
```

```text
GET/POST /picking-waves
POST     /picking-waves/{id}/release

GET      /picking-tasks
GET      /picking-tasks/{id}
POST     /picking-tasks/{id}/scan
POST     /picking-tasks/{id}/complete

GET/POST /packages
POST     /packages/{id}/verify
POST     /packages/{id}/finalize

POST /labels/{id}/reprint

GET/POST /shipments
POST     /shipments/{id}/dispatch
POST     /shipments/{id}/confirm-delivery
```

---

# 67. M11 — Fiscal

Base:

```text
/api/v1/fiscal
```

```text
GET/POST /fiscal-establishments

GET/POST /tax-rules
POST     /tax-rules/{id}/versions
POST     /tax-rule-versions/{id}/activate

POST /fiscal-document-intents

GET /fiscal-documents
GET /fiscal-documents/{id}

POST /fiscal-documents/{id}/submit
POST /fiscal-documents/{id}/cancel
POST /fiscal-documents/{id}/corrections

GET/POST /fiscal-series
POST     /fiscal-series/{id}/invalidate-range
```

---

# 68. M12 — Finance

Base:

```text
/api/v1/finance
```

```text
GET /receivables
GET /receivables/{id}

GET /payables
GET /payables/{id}

POST /settlements
POST /settlements/{id}/reverse

GET/POST /payment-requests

GET/POST /payment-batches
POST     /payment-batches/{id}/submit
POST     /payment-batches/{id}/transmit

GET/POST /financial-accounts

GET/POST /bank-statement-imports
GET      /bank-movements
POST     /bank-movements/{id}/reconcile

GET /marketplace-settlements
POST /marketplace-settlements/import

GET /credit-exposures/{customer_or_group_id}
```

---

# 69. M13 — Accounting

Base:

```text
/api/v1/accounting
```

```text
GET/POST /accounts

GET/POST /accounting-rules
POST     /accounting-rules/{id}/versions
POST     /accounting-rule-versions/{id}/activate

GET/POST /journal-entries
POST     /journal-entries/{id}/post
POST     /journal-entries/{id}/reverse

GET /accounting-periods
POST /accounting-periods/{id}/soft-close
POST /accounting-periods/{id}/close
POST /accounting-periods/{id}/reopen

GET /reconciliations
POST /reconciliations/{id}/resolve

GET /reports/trial-balance
GET /reports/general-ledger
GET /reports/income-statement
GET /reports/balance-sheet
```

---

# 70. M14 — CRM / Customers

Base:

```text
/api/v1/customers
```

```text
GET/POST /customers
GET/PATCH /customers/{id}

GET/POST /customer-groups

GET/POST /customers/{id}/contacts
GET/POST /customers/{id}/addresses

GET/POST /customers/{id}/interactions
GET/POST /customers/{id}/tasks

GET/POST /customers/{id}/consents

GET /customers/{id}/360

POST /customers/{id}/merge-requests
```

---

# 71. M15 — Comercial B2B

Base:

```text
/api/v1/sales
```

```text
GET/POST /quotes
GET      /quotes/{id}

POST /quotes/{id}/revisions
POST /quotes/{id}/send
POST /quotes/{id}/accept
POST /quotes/{id}/partial-accept
POST /quotes/{id}/mark-lost
POST /quotes/{id}/convert

GET/POST /sales-portfolios

GET/POST /commercial-policies

GET/POST /delivery-schedules

GET /payment-terms
GET /freight-terms

POST /orders/{id}/change-requests
```

---

# 72. M16 — Commissions

Base:

```text
/api/v1/commissions
```

```text
GET/POST /beneficiaries
GET/POST /assignments

GET/POST /commission-rules
POST     /commission-rules/{id}/versions

GET /commission-origins
GET /commission-accruals
GET /commission-earnings

GET/POST /commission-adjustments

GET /commission-periods
POST /commission-periods/{id}/close

GET /commission-statements
GET /commission-statements/{id}
```

---

# 73. M17 — Quality

Base:

```text
/api/v1/quality
```

```text
GET/POST /inspection-plans
POST     /inspection-plans/{id}/versions

GET/POST /inspections
POST     /inspections/{id}/start
POST     /inspections/{id}/complete

POST /quality-holds
POST /quality-holds/{id}/release

GET/POST /nonconformities

GET/POST /capas
POST     /capas/{id}/close

GET/POST /recalls

GET/POST /measurement-instruments
GET/POST /calibrations
```

---

# 74. M18 — Regulatory

Base:

```text
/api/v1/regulatory
```

```text
GET/POST /families
GET/POST /certification-processes

GET/POST /certificates
POST     /certificates/{id}/activate
POST     /certificates/{id}/suspend
POST     /certificates/{id}/cancel

GET/POST /change-assessments
POST     /change-assessments/{id}/complete

GET/POST /packaging-approvals

GET/POST /regulatory-blocks
POST     /regulatory-blocks/{id}/release

GET /lots/{lot_id}/compliance

POST /gates/production/check
POST /gates/sales/check
POST /gates/billing/check
POST /gates/shipping/check
```

---

# 75. M19 — Assets / Maintenance

Bases:

```text
/api/v1/assets
/api/v1/maintenance
```

Ativos:

```text
GET/POST /assets
GET/PATCH /assets/{id}

POST /assets/{id}/transfer
POST /assets/{id}/capitalize
POST /assets/{id}/dispose

GET /assets/{id}/depreciation
```

Manutenção:

```text
GET/POST /maintenance/assets
GET/POST /maintenance/plans
GET/POST /maintenance/requests
GET/POST /maintenance/work-orders

POST /maintenance/work-orders/{id}/start
POST /maintenance/work-orders/{id}/complete
POST /maintenance/work-orders/{id}/validate
POST /maintenance/work-orders/{id}/close
```

---

# 76. M20 — RH

Base:

```text
/api/v1/hr
```

```text
GET/POST /people

GET/POST /employment-contracts
POST     /employment-contracts/{id}/terminate

GET/POST /third-party-engagements

GET/POST /departments
GET/POST /job-positions
GET/POST /assignments
GET/POST /work-schedules

GET /time-punches
GET/POST /time-adjustment-requests
GET/POST /overtime-authorizations
GET /time-bank

GET /time-periods
POST /time-periods/{id}/close
POST /time-periods/{id}/reopen

GET/POST /vacations
GET/POST /absences

POST /payroll-exports
POST /payroll-imports
```

---

# 77. M21 — Analytics

Base:

```text
/api/v1/analytics
```

```text
GET /dashboards
GET /dashboards/{id}

GET /metrics
GET /metrics/{code}

GET/POST /metric-definitions
POST     /metric-definitions/{id}/versions
POST     /metric-versions/{id}/activate

GET/POST /targets
GET/POST /budgets
GET/POST /alerts

POST /explorer/query

GET/POST /saved-analyses
GET/POST /scheduled-reports
```

Consultas pesadas podem virar job.

---

# 78. M22 — Workflow

Base:

```text
/api/v1/workflows
```

```text
GET /workflows
GET /workflows/{id}

GET /my-approvals

POST /workflows/{id}/approve
POST /workflows/{id}/reject
POST /workflows/{id}/return-for-correction
POST /workflows/{id}/request-information

GET/POST /workflow-definitions
POST     /workflow-definitions/{id}/versions
POST     /workflow-versions/{id}/activate

GET/POST /approval-policies
GET/POST /delegations

POST /workflow-simulations
```

---

# 79. M23 — Data Governance

Base:

```text
/api/v1/data
```

Imports:

```text
GET /import-templates
GET /import-templates/{id}/download-model

POST /imports
GET  /imports/{id}

POST /imports/{id}/validate
POST /imports/{id}/preview
POST /imports/{id}/confirm
POST /imports/{id}/commit
POST /imports/{id}/cancel

GET /imports/{id}/rejected-file
```

Exports:

```text
POST /exports
GET  /exports/{id}
GET  /exports/{id}/download
```

Governance:

```text
GET /domains
GET /quality/issues
GET /quality/scores
GET /duplicates

POST /merge-requests
POST /change-requests

GET /lineage
GET /entities/{domain}/{id}/lineage
```

---

# 80. Internal Contract Registry

Catálogo:

```text
contract_name
owner_module
consumer_modules
version
mode
```

Exemplo:

```text
InventoryReservationService
Owner: M5
Consumers: M4, M10
```

---

# 81. Synchronous Contract Naming

Exemplos:

```text
InventoryReservationService
InventoryAvailabilityQueryService

PricingResolutionService

CreditDecisionService

RegulatoryShippingGate

WorkforceAvailabilityService
```

---

# 82. API não Expõe Internals

Não expor diretamente:

```text
SQLAlchemy model
database column name
internal event table
```

Pydantic schemas são contratos próprios.

---

# 83. DTOs

Separar:

```text
CreateRequest
UpdateRequest
Response
SummaryResponse
```

Exemplo:

```text
ProductCreate
ProductUpdate
ProductResponse
ProductListItem
```

---

# 84. Command DTO x Resource DTO

Exemplo:

```text
CancelOrderRequest
```

não precisa ser igual ao DTO `Order`.

---

# 85. Imutabilidade no Response

Snapshots históricos são somente leitura.

---

# 86. List Response

```json
{
  "items": [],
  "page": {
    "next_cursor": null,
    "has_more": false
  }
}
```

---

# 87. Single Resource Response

Pode retornar diretamente o recurso:

```json
{
  "id": "...",
  "status": "ACTIVE",
  "version": 3
}
```

---

# 88. Data Format

Datas:

```text
ISO 8601
```

Timestamps com timezone.

---

# 89. Decimal

Valores críticos serão serializados de forma segura:

```json
{
  "amount": "1234.5600"
}
```

---

# 90. Boolean

Usar:

```json
true
false
```

Nunca `"S"` / `"N"`.

---

# 91. Enum

Valores:

```text
UPPER_SNAKE_CASE
```

Exemplo:

```text
PENDING_APPROVAL
```

---

# 92. Null

`null` é semanticamente diferente de campo ausente em PATCH.

---

# 93. PATCH

Preferência:

```text
JSON Merge Patch semantics
```

ou DTO parcial explícito.

---

# 94. API e Reason Code

Ações críticas:

```json
{
  "reason_code": "CUSTOMER_REQUEST",
  "comment": "..."
}
```

---

# 95. Workflow Reference

Comandos aprovados podem exigir:

```text
workflow_instance_id
```

ou validação resolvida pelo backend.

---

# 96. API e Step-Up

Se nível de autenticação for insuficiente:

```text
403 STEP_UP_REQUIRED
```

Exemplo:

```json
{
  "required_level": "LEVEL_3"
}
```

---

# 97. Scope Violation

```text
403 SCOPE_FORBIDDEN
```

sem revelar dados fora do escopo.

---

# 98. Sensitive Field

Campos proibidos devem ser omitidos ou mascarados no backend.

---

# 99. API Externa para Parceiros

Futuro:

```text
/api/partner/v1
```

sem expor endpoints administrativos internos.

---

# 100. Marketplace Webhook Security

Verificar:

- assinatura;
- timestamp;
- replay;
- account mapping;
- source validation.

---

# 101. Fiscal Callback

Deve ser:

- autenticado;
- idempotente;
- correlacionado ao `issuance_intent_id`.

---

# 102. Webhook Acknowledgement

Responder rapidamente após persistir trigger.

Processamento pesado fica assíncrono.

---

# 103. API de Saúde

```text
/health/live
/health/ready
```

sem detalhes sensíveis.

---

# 104. Readiness

Verifica dependências realmente necessárias.

---

# 105. API de Métricas

```text
/metrics
```

restrita à infraestrutura.

---

# 106. Security Headers

Aplicar, conforme contexto:

- HSTS;
- CSP;
- X-Content-Type-Options;
- secure cookies;
- CORS restrito.

---

# 107. CORS

Não utilizar wildcard indiscriminado em produção.

---

# 108. Request Size Limits

Limites por endpoint.

Uploads grandes usam fluxo apropriado.

---

# 109. Query Cost Protection

Consultas caras terão:

- timeout;
- limite de linhas;
- query budget quando necessário.

---

# 110. N+1 Protection

Includes e relacionamentos são explicitamente planejados.

---

# 111. API Gateway / Ingress

No MVP pode existir reverse proxy/API ingress.

Responsabilidades:

- TLS;
- routing;
- limits;
- headers;
- observabilidade.

---

# 112. API Documentation

Cada endpoint deve documentar:

```text
description
permissions
possible states
errors
idempotency requirements
examples
```

---

# 113. State Machine Documentation

Transições devem documentar:

```text
allowed_from
resulting_state
required_permission
workflow_required
```

---

# 114. Contract Ownership

Toda API tem:

```text
owner_module
```

---

# 115. API Change Review

Breaking changes passam por:

```text
API CHANGE REVIEW
```

e, quando cross-domain:

```text
Architecture Change Request
```

---

# 116. API Lifecycle

Estados:

```text
DRAFT
BETA
ACTIVE
DEPRECATED
RETIRED
```

---

# 117. Beta APIs

Não usar em processos financeiros/fiscais críticos sem aprovação técnica.

---

# 118. API Performance Classes

```text
INTERACTIVE
HEAVY_QUERY
ASYNC_JOB
STREAMING
```

---

# 119. Interactive SLA Técnico Inicial

Objetivo recomendado:

```text
p95 < 500 ms
```

para chamadas locais normais sem dependência externa.

---

# 120. External Dependency

Quando depender de SEFAZ, marketplace ou banco, usar estados explícitos:

```text
PROCESSING
PENDING_PROVIDER
```

---

# 121. Idempotent Command Examples

Obrigatório em:

```text
POST /fiscal-document-intents
POST /payment-batches/{id}/transmit
POST /imports/{id}/commit
```

quando houver risco de efeito duplo.

---

# 122. Retry pelo Cliente

Cliente só repete automaticamente quando:

- operação é idempotente;
- ou contrato declarar como seguro.

---

# 123. 5xx

Não usar 500 para regra de negócio previsível.

---

# 124. `409 Conflict`

Aplicável a:

- version conflict;
- state conflict;
- idempotency conflict;
- duplicated business key.

---

# 125. `422 Unprocessable Entity`

Aplicável a payload estruturalmente válido, porém semanticamente inválido.

---

# 126. `503 Service Unavailable`

Para dependência crítica indisponível.

Exemplo:

```text
REGULATORY_GATE_UNAVAILABLE
```

---

# 127. Retry-After

Pode ser usado com:

```text
429
503
```

---

# 128. API e Auditoria

Toda mutação deve permitir responder:

```text
quem
quando
o quê
por quê
qual versão
qual workflow
qual correlation id
```

---

# 129. API Explorer

Swagger/OpenAPI é útil para desenvolvimento.

Produção terá acesso controlado.

---

# 130. SDKs

Não são requisito do MVP.

Operation IDs estáveis preservam evolução futura.

---

# 131. Critérios de Aceite da Etapa 6

1. `/api/v1` definido.
2. callbacks externos separados.
3. contratos internos não usam HTTP obrigatoriamente.
4. REST naming padronizado.
5. methods HTTP padronizados.
6. commands de domínio não reduzidos a PATCH status.
7. status codes definidos.
8. error contract único.
9. error codes estáveis.
10. correlation ID.
11. request ID.
12. bearer authentication.
13. required permission por endpoint.
14. scopes aplicados.
15. step-up suportado.
16. idempotency key.
17. optimistic locking.
18. `If-Match`.
19. paginação.
20. filtros explícitos.
21. sorting controlado.
22. includes controlados.
23. bulk pelo M23.
24. export pelo M23.
25. uploads padronizados.
26. downloads autorizados.
27. async jobs retornam 202.
28. job status consultável.
29. OpenAPI como contrato.
30. depreciação definida.
31. rate limiting.
32. timeout.
33. observabilidade.
34. contract tests.
35. API não expõe ORM.
36. DTOs independentes.
37. snapshots históricos somente leitura.
38. ISO 8601.
39. DECIMAL seguro.
40. reason_code.
41. workflow reference validável.
42. sensitive field security.
43. webhooks autenticados.
44. webhooks idempotentes.
45. health endpoints.
46. CORS restrito.
47. request size limit.
48. heavy queries protegidas.
49. API ownership.
50. breaking change revisado.
51. lifecycle de API.
52. external dependency não bloqueia indefinidamente.
53. retry client-side documentado.
54. 5xx não representa regra de negócio.
55. auditabilidade ponta a ponta.
56. M1–M23 possuem mapa inicial de endpoints.
57. APIs respeitam Etapa 4.
58. APIs respeitam Etapa 5.
59. APIs preservam ownership.
60. futura extração de módulos continua possível.

---

# 132. Decisões Arquiteturais Consolidadas

## A. REST é fronteira externa/aplicacional

Não é mecanismo obrigatório entre módulos internos.

## B. `/api/v1` é baseline

## C. State transitions usam commands explícitos

## D. Erros possuem códigos estáveis

## E. Idempotência é obrigatória em efeitos críticos

## F. Optimistic locking é padrão em recursos concorrentes

## G. Bulk Data pertence ao M23

## H. Exportações pertencem ao M23

## I. OpenAPI é contrato

## J. DTO não é ORM

## K. API nunca ignora RBAC/Scope/SoD

## L. Jobs longos retornam `202`

## M. Webhook é trigger, não verdade operacional

## N. Breaking changes são versionados

## O. Toda API possui owner

---

# 133. Visão Consolidada da API

```text
                           CLIENT
                             │
                             ▼
                      TLS / API Ingress
                             │
                             ▼
                      Authentication M1
                             │
                             ▼
                    Authorization / Scope
                             │
                             ▼
                     FastAPI / /api/v1
                             │
         ┌───────────────────┼────────────────────┐
         │                   │                    │
         ▼                   ▼                    ▼
     QUERY API          COMMAND API          ASYNC JOB API
         │                   │                    │
         ▼                   ▼                    ▼
  Application Service   Domain Aggregate       Queue/Worker
                             │                    │
                             ▼                    ▼
                        PostgreSQL            Completion
                             │                    │
                             ▼                    ▼
                           Outbox             Notification
                             │
                             ▼
                          RabbitMQ
```

---

# 134. Status Formal da Etapa 6

A **Etapa 6 — Mapa Consolidado de APIs M1–M23** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- contratos REST;
- contracts internos;
- webhooks/callbacks;
- DTOs;
- OpenAPI;
- autenticação/autorização de endpoints;
- idempotência;
- locking;
- jobs;
- uploads/downloads;
- erros;
- observabilidade;
- lifecycle e versionamento de APIs.

Alterações incompatíveis devem seguir:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 135. Próxima Etapa

```text
ETAPA 7
MAPA COMPLETO DE TELAS E NAVEGAÇÃO DO ERP
```

A próxima etapa consolidará:

- shell global;
- menu principal;
- homes por perfil;
- telas M1–M23;
- list/detail/edit;
- dashboards;
- cockpits;
- navegação contextual;
- drill-through;
- workflows;
- alertas;
- responsive/PWA;
- padrões de grid, filtros e formulários;
- ações críticas;
- UX de estados assíncronos;
- segurança visual e field-level masking.

---

**Fim da Etapa 6 — Mapa Consolidado de APIs M1–M23**
