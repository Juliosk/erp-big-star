# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 10 — Backlog Técnico Mestre, Ordem Executiva de Desenvolvimento e Plano de Início da Codificação

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Backlog técnico mestre, ordem executiva de desenvolvimento, vertical slices, sprints iniciais, critérios de pronto, estrutura de repositório, arquitetura de testes, governança técnica e plano de início da codificação do ERP M1–M23.  
**Objetivo:** Converter toda a arquitetura consolidada das Etapas 1–9 em um plano executável de implementação que permita iniciar imediatamente o desenvolvimento real do ERP Big Star / Forma Kids.

---

# 1. Objetivo

A Etapa 10 converte tudo que foi definido nas Etapas 1–9 em um backlog que possa ser entregue diretamente ao time de desenvolvimento.

Ela responde:

```text
Qual é a primeira tarefa?
Qual Epic vem depois?
Quais contratos devem existir antes?
Quais tabelas e migrations devem nascer primeiro?
Qual vertical slice deve funcionar primeiro?
Quais módulos podem ser desenvolvidos em paralelo?
O que bloqueia o quê?
Quando uma história está pronta para entrar em desenvolvimento?
Quando uma entrega é considerada concluída?
Como começar efetivamente a codificar o ERP?
```

O resultado desta etapa permite passar de:

```text
ARQUITETURA
```

para:

```text
REPOSITÓRIO
↓
BACKLOG
↓
SPRINT
↓
CÓDIGO
↓
TESTES
↓
DEPLOY
```

---

# 2. Hierarquia Oficial do Backlog

Usaremos cinco níveis:

```text
PROGRAM
└── WAVE
    └── EPIC
        └── FEATURE
            └── STORY / TASK
```

Exemplo:

```text
ERP-BIGSTAR
└── W0 Engineering Foundation
    └── EPIC W0-PLATFORM-001
        └── Modular Monolith Bootstrap
            ├── STORY repository structure
            ├── STORY FastAPI bootstrap
            ├── STORY SQLAlchemy session
            └── STORY Alembic baseline
```

---

# 3. Tipos de Item

Cada item será classificado como:

```text
BUSINESS
TECHNICAL
INTEGRATION
DATA
SECURITY
INFRASTRUCTURE
TEST
MIGRATION
DOCUMENTATION
```

---

# 4. Prioridades

| Prioridade | Significado |
|---|---|
| `P0` | Bloqueador arquitetural / crítico |
| `P1` | Necessário para próxima capacidade |
| `P2` | Importante, mas não bloqueador imediato |
| `P3` | Evolução / otimização |

Regra:

```text
P0 incompleto
→ não avançar para dependência crítica
```

---

# 5. Identificação dos Backlog Items

Padrão:

```text
<WAVE>-<DOMAIN>-<NUMBER>
```

Exemplos:

```text
W0-PLATFORM-001
W0-SEC-002
W1-M01-001
W2-M05-004
W4-M07-012
```

---

# 6. Definition of Ready — DoR

Uma Story só entra em desenvolvimento quando possuir:

```text
objetivo claro
owner do domínio
critério de aceite
dependências identificadas
modelo de dados conhecido
API/contract quando aplicável
permission definida
eventos identificados
erros esperados
test cases principais
```

---

# 7. Story não Ready

Não iniciar algo descrito somente como:

```text
"Fazer tela de estoque"
```

Uma story correta seria:

```text
Permitir consultar saldo disponível por
empresa + warehouse + produto + lote,
respeitando inventory.balance.read
e warehouse scope.
```

---

# 8. Definition of Done — DoD

Toda entrega funcional deve possuir, quando aplicável:

```text
Domain logic
Database migration
Repository
Application service
API
RBAC
Audit
Outbox event
Inbox consumer
Error contract
Unit tests
Integration tests
Contract tests
Observability
Documentation
```

---

# 9. DoD não é Apenas “Funciona na Minha Máquina”

Antes de considerar concluído:

```text
CI green
migration tested
tests green
code reviewed
security checked
deployed in homologation
acceptance scenario executed
```

---

# 10. Estrutura Inicial do Repositório

Baseline:

```text
erp/
├── apps/
│   ├── api/
│   ├── worker/
│   └── scheduler/
│
├── modules/
│   ├── admin/
│   ├── product/
│   ├── marketplace/
│   ├── orders/
│   ├── inventory/
│   ├── procurement/
│   ├── manufacturing/
│   ├── costing/
│   ├── pricing/
│   ├── wms/
│   ├── fiscal/
│   ├── finance/
│   ├── accounting/
│   ├── crm/
│   ├── sales/
│   ├── commissions/
│   ├── quality/
│   ├── regulatory/
│   ├── assets/
│   ├── hr/
│   ├── workflow/
│   └── governance/
│
├── contracts/
│   ├── events/
│   ├── requests/
│   └── sync/
│
├── platform/
│   ├── database/
│   ├── messaging/
│   ├── security/
│   ├── audit/
│   ├── idempotency/
│   ├── observability/
│   ├── storage/
│   └── errors/
│
├── migrations/
├── tests/
├── docker/
├── docs/
└── pyproject.toml
```

M21 possuirá componente analítico fisicamente separado.

---

# 11. Estrutura Interna de um Módulo

Exemplo:

```text
modules/inventory/
├── domain/
│   ├── entities/
│   ├── value_objects/
│   ├── services/
│   ├── events/
│   └── exceptions.py
│
├── application/
│   ├── commands/
│   ├── queries/
│   ├── services/
│   └── dto/
│
├── infrastructure/
│   ├── models/
│   ├── repositories/
│   └── consumers/
│
└── api/
    ├── routes.py
    └── schemas.py
```

---

# 12. Regra de Import

Permitido:

```text
application
→ domain
```

Permitido:

```text
infrastructure
→ domain
```

Proibido:

```text
domain
→ FastAPI
domain
→ SQLAlchemy ORM
domain
→ RabbitMQ client
```

---

# 13. Dependência entre Módulos

Módulos não importam:

```text
modules/<other>/infrastructure
```

Usam:

```text
contracts/
```

ou Application Ports.

---

# 14. W0 — Backlog Executivo

## EPIC W0-PLATFORM-001 — Repository Bootstrap

Prioridade:

```text
P0
```

Features:

```text
Python project bootstrap
dependency management
lint
format
typing
testing
configuration
```

---

# 15. W0-PLATFORM-001.01 — Python Baseline

Definir versão Python oficialmente suportada.

Entregar:

```text
pyproject.toml
dependency groups
lock strategy
```

---

# 16. W0-PLATFORM-001.02 — Quality Toolchain

Configurar:

```text
Ruff
mypy
pytest
coverage
```

ou equivalentes aprovados.

---

# 17. W0-PLATFORM-002 — FastAPI Bootstrap

Entregar:

```text
FastAPI app
/api/v1
health endpoints
middleware chain
error handler
OpenAPI
```

---

# 18. Middleware Order

Baseline:

```text
Request ID
↓
Correlation ID
↓
Authentication
↓
Scope Context
↓
Logging
↓
Application
```

A ordem final deve ser testada.

---

# 19. W0-DATA-001 — PostgreSQL Foundation

Entregar:

```text
SQLAlchemy 2.x
Async/Sync strategy definida
session management
transaction boundary
naming conventions
```

---

# 20. Decisão Recomendada para SQLAlchemy

Para o backend FastAPI:

```text
Async SQLAlchemy
```

é adequado para chamadas HTTP I/O-bound.

Workers poderão usar a mesma camada de forma consistente.

Não misturar padrões arbitrariamente por módulo.

---

# 21. W0-DATA-002 — Alembic

Entregar:

```text
initial migration
schema creation
migration naming
migration CI validation
```

---

# 22. Primeira Migration

Criar inicialmente:

```text
platform
admin
```

e infraestrutura transversal mínima.

Não criar as centenas de tabelas dos 23 módulos no primeiro commit.

---

# 23. W0-DATA-003 — UUID

Implementar padrão central de:

```text
UUID
```

como PK técnica.

Preferencialmente UUID gerado pela aplicação ou PostgreSQL conforme convenção única.

---

# 24. W0-DATA-004 — Decimal

Criar tipos reutilizáveis para:

```text
Money
Quantity
Percentage
Rate
```

baseados em `Decimal`.

Nunca `float`.

---

# 25. W0-EVENT-001 — Event Envelope

Implementar envelope oficial da Etapa 3.

Campos:

```text
message_id
event_name
event_version

occurred_at

producer_module

aggregate_type
aggregate_id
aggregate_version

correlation_id
causation_id

company_id
branch_id

payload
```

---

# 26. W0-EVENT-002 — Transactional Outbox

Prioridade:

```text
P0
```

Tabela:

```text
platform.outbox_event
```

Campos:

```text
id
event_name
event_version
aggregate_id
payload
headers
occurred_at
published_at
publish_attempts
last_error
```

---

# 27. Outbox Publisher

Worker:

```text
Outbox
↓
RabbitMQ
↓
mark published
```

Com:

- retry;
- batch;
- locking;
- idempotência.

---

# 28. W0-EVENT-003 — Inbox

Tabela:

```text
platform.inbox_message
```

Protege consumidores contra entrega duplicada.

---

# 29. Consumer Transaction

Padrão:

```text
check Inbox
↓
execute effect
↓
insert Inbox
↓
commit
```

na mesma transação do efeito local.

---

# 30. W0-MSG-001 — RabbitMQ

Configurar:

```text
exchange conventions
routing key conventions
queue declarations
DLQ
retry topology
```

---

# 31. W0-MSG-002 — Celery

Configurar:

```text
worker
task base
retry policy
queue routing
structured logging
```

---

# 32. W0-CACHE-001 — Redis

Criar abstrações para:

```text
cache
rate limit
lock
debounce
```

sem acesso direto indiscriminado pelos domínios.

---

# 33. W0-STORAGE-001 — Object Storage

Contrato:

```text
ObjectStoragePort
```

Operações:

```text
put
get_signed_url
delete_when_allowed
metadata
checksum
```

---

# 34. W0-SEC-001 — Authentication Skeleton

Primeira versão:

```text
login
token issue
refresh
logout
session
```

---

# 35. W0-SEC-002 — Authorization Engine

Implementar:

```text
permission
scope
DEFAULT DENY
```

antes de telas de negócio.

---

# 36. W0-SEC-003 — Permission Decorator

Exemplo conceitual:

```python
@require_permission("product.product.read")
```

com resolução de scope pelo backend.

---

# 37. W0-SEC-004 — Step-Up Skeleton

A arquitetura do endpoint deve suportar:

```text
STEP_UP_REQUIRED
```

desde o início.

---

# 38. W0-AUD-001 — Audit Framework

Criar:

```text
platform.audit_event
```

Campos:

```text
actor
action
resource
resource_id
before
after
reason_code
request_id
correlation_id
timestamp
```

---

# 39. Audit não é Log Técnico

Separar:

```text
Application Log
≠
Audit Event
```

---

# 40. W0-API-001 — Error Contract

Implementar handler global:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": [],
    "correlation_id": "..."
  }
}
```

---

# 41. W0-API-002 — Idempotency Framework

Criar:

```text
platform.idempotency_record
```

ou equivalente.

---

# 42. W0-API-003 — Optimistic Locking

Criar convenção:

```text
version
```

com incremento controlado.

---

# 43. W0-OBS-001 — Structured Logs

Implementar logging JSON.

---

# 44. W0-OBS-002 — Metrics

Baseline:

```text
HTTP requests
latency
errors
DB pool
Celery
RabbitMQ
```

---

# 45. W0-OBS-003 — Tracing

OpenTelemetry de:

```text
HTTP
DB
RabbitMQ
Celery
```

---

# 46. W0-INFRA-001 — Docker Compose

Desenvolvedor deve executar:

```bash
docker compose up
```

e obter:

```text
PostgreSQL
RabbitMQ
Redis
MinIO
API
Worker
```

---

# 47. W0-INFRA-002 — CI

Em toda PR:

```text
lint
type check
unit test
integration test
migration validation
security scan
```

---

# 48. W0-INFRA-003 — CD Homologação

Merge em branch/release apropriada deve publicar automaticamente em homologação.

---

# 49. W0-TEST-001 — Test Architecture

```text
tests/
├── unit/
├── integration/
├── contracts/
├── e2e/
└── fixtures/
```

---

# 50. W0-TEST-002 — Database Integration Tests

Preferir PostgreSQL real/container nos testes relevantes.

Não usar SQLite como substituto do comportamento de produção.

---

# 51. Gate para Encerrar W0

Golden Technical Scenario:

```text
POST recurso
↓
PostgreSQL
↓
Outbox
↓
RabbitMQ
↓
Consumer
↓
Inbox
↓
Audit
↓
Trace
```

deve funcionar automaticamente em teste.

---

# 52. W1 — Backlog Executivo

Epics:

```text
W1-M01 Administração/Security
W1-M20 Organization Core
W1-M02 Product Master
W1-M14 Customer Core
W1-M23 Import/Export Core
```

---

# 53. W1-M01-001 — Grupo/Empresa/Filial

Features:

```text
Economic Group
Company
Branch
Fiscal identity basic
active/inactive
```

---

# 54. W1-M01-002 — Users

Features:

```text
User create
User enable
User disable
Session revoke
```

---

# 55. W1-M01-003 — Roles & Permissions

Features:

```text
Role
Permission
Role Permission
User Role
```

---

# 56. W1-M01-004 — Scopes

Implementar primeiro:

```text
GROUP
COMPANY
BRANCH
```

Depois os demais scopes entram com seus módulos.

---

# 57. W1-M20-001 — Organization Core

Features:

```text
Department
Cost Center
Job Position
Reporting Hierarchy
```

---

# 58. W1-M02-001 — Product

Campos essenciais:

```text
code
sku
name
type
lifecycle
uom
company/global applicability
```

---

# 59. W1-M02-002 — Barcode

Implementar:

```text
EAN
DUN
internal code
```

---

# 60. W1-M02-003 — Packaging

Hierarquia:

```text
unit
inner
case
pallet when applicable
```

---

# 61. W1-M02-004 — Product Lifecycle

Estados:

```text
EM_DESENVOLVIMENTO
EM_HOMOLOGACAO
ATIVO
FORA_DE_LINHA
```

---

# 62. W1-M14-001 — Customer

Features:

```text
INDIVIDUAL
COMPANY
CPF/CNPJ
status
```

---

# 63. W1-M14-002 — Customer Address/Contact

Papéis:

```text
billing
shipping
commercial
fiscal
```

quando aplicável.

---

# 64. W1-M14-003 — Duplicate Exact Match

CPF/CNPJ exato:

```text
automatic duplicate detection
```

---

# 65. W1-M23-001 — Import Template

Criar:

```text
import_template
import_template_version
```

---

# 66. W1-M23-002 — Upload/Staging

Fluxo:

```text
Upload
→ Staging
→ Parse
```

---

# 67. W1-M23-003 — Validation

Implementar:

```text
structural validation
business validation
```

---

# 68. W1-M23-004 — Preview

Mostrar:

```text
current
new
difference
errors
warnings
```

---

# 69. W1-M23-005 — Commit

Implementar:

```text
ALL_OR_NOTHING
VALID_ROWS_ONLY
BATCH_ATOMIC
```

conforme template.

---

# 70. Primeiro Vertical Slice Funcional

## VS-001 — Login → Produtos

Fluxo:

```text
Login
↓
Select Company
↓
Product List
↓
Product Detail
```

Este será o primeiro fluxo real utilizável do ERP.

---

# 71. Critérios VS-001

Deve possuir:

```text
authentication
permission
company scope
pagination
search
audit
API
frontend
tests
```

---

# 72. Segundo Vertical Slice

## VS-002 — Criar Produto

```text
New Product
↓
Validation
↓
Save
↓
ProductCreated
↓
Audit
```

---

# 73. Terceiro Vertical Slice

## VS-003 — Importar Produtos

```text
Download Template
↓
Upload XLSX
↓
Validate
↓
Preview
↓
Commit
↓
Product Master
```

Este slice valida o M23.

---

# 74. Quarto Vertical Slice

## VS-004 — Customer Core

```text
Customer List
↓
New Customer
↓
CPF/CNPJ validation
↓
Duplicate Check
↓
Save
```

---

# 75. W2 — Epics Executivos

```text
W2-M05 Inventory Core
W2-M09 Pricing Core
W2-M15 B2B Sales Core
W2-M04 Orders Core
W2-M22 Workflow Core
W2-M03 Marketplace Core
```

---

# 76. W2-M05-001 — Warehouses

```text
Warehouse
Location hierarchy
```

---

# 77. W2-M05-002 — Inventory Pools

```text
MARKETPLACE
B2B
STORE
```

---

# 78. W2-M05-003 — Inventory Ledger

Prioridade:

```text
P0
```

Imutável.

Movimentos nunca são editados.

---

# 79. W2-M05-004 — Inventory Balance

Saldo materializado na mesma transação do ledger.

---

# 80. W2-M05-005 — Reservation

Implementar:

```text
HARD
SOFT
```

e políticas de expiração.

---

# 81. W2-M05-006 — Opening Inventory

M23 + M5.

Pré-requisito do primeiro pedido real.

---

# 82. VS-005 — Order Reservation

```text
Create Test Order
↓
Reserve Inventory
↓
Inventory Ledger
↓
Reservation
↓
Order Status
```

Valida M4 ↔ M5.

---

# 83. W2-M09-001 — Standard Cost Seed

Enquanto M8 não estiver ativo:

```text
cost source = LEGACY_OPENING
```

---

# 84. W2-M09-002 — Price List

```text
Price List
Price List Version
```

---

# 85. W2-M09-003 — Pricing Resolver

Contrato:

```text
PricingResolutionService
```

---

# 86. W2-M09-004 — Floor Price

Inputs:

```text
cost
tax
commission
finance cost
minimum margin
```

---

# 87. W2-M15-001 — Portfolio

Implementar carteira vendedor/cliente.

---

# 88. W2-M15-002 — Quote

```text
Quote
Quote Items
```

---

# 89. W2-M15-003 — Quote Revision

Revisões imutáveis depois de enviadas.

---

# 90. W2-M15-004 — Commercial Policy

Separar:

```text
pricing
≠
commercial permission
```

---

# 91. W2-M22-001 — Workflow Definition Core

Primeiro engine:

```text
SEQUENTIAL
HIGHEST_LEVEL_ONLY
CUMULATIVE
```

---

# 92. W2-M22-002 — Workflow Instance

```text
request
steps
decisions
status
```

---

# 93. W2-M22-003 — My Approvals

Primeira tela transversal de workflow.

---

# 94. VS-006 — Quote → Approval

```text
Quote
↓
Discount Exception
↓
Workflow Requested
↓
Approval
↓
Quote Approved
```

---

# 95. W2-M04-001 — Order Aggregate

Implementar máquina de estados principal.

---

# 96. W2-M04-002 — Order Snapshots

Congelar:

```text
customer
items
commercial data
```

---

# 97. W2-M04-003 — Quote Conversion

Contrato:

```text
M15
→ M4
```

---

# 98. VS-007 — Quote → Order → Reservation

Golden Business Scenario inicial:

```text
Customer
↓
Quote
↓
Pricing
↓
Approval
↓
Convert
↓
Order
↓
Inventory Reservation
```

---

# 99. W2-M03-001 — Marketplace Account

Adapter skeleton.

---

# 100. W2-M03-002 — Channel Adapter

Interface comum:

```text
fetch_order
fetch_product
publish_stock
publish_price
fetch_label
```

---

# 101. W2-M03-003 — Marketplace Webhook

Persistir trigger de forma idempotente.

---

# 102. W2-M03-004 — External Order Normalization

```text
External Payload
→ Canonical Marketplace Order
```

---

# 103. VS-008 — Marketplace → Order

```text
Webhook
↓
Fetch
↓
Normalize
↓
MarketplaceOrderApproved
↓
M4 Order
↓
Reservation
```

---

# 104. Desenvolvimento Paralelo na W2

Após estabilizar contratos:

### Squad A

```text
M5 Inventory
```

### Squad B

```text
M9 + M15
```

### Squad C

```text
M3 + M4
```

### Squad Platform

```text
M22 + shared contracts
```

---

# 105. Contratos que Bloqueiam Trabalho Paralelo

Antes:

```text
InventoryReservationService
PricingResolutionService
CustomerOperationalStatusService
WorkflowRequest Contract
Order Creation Contract
```

devem estar documentados.

---

# 106. W3 — Backlog Executivo

Epics:

```text
M10 WMS
M6 Procurement
M17 Incoming Quality
M11 Inbound Fiscal
M12 Payable Bridge
```

---

# 107. Ordem de Codificação W3

```text
M10 Pick/Packing skeleton
M6 Supplier/PO
M17 Incoming Inspection
M6 Receipt
M5 receipt postings
M11 inbound validation
M6 3-Way Match
M12 PayableRequested
```

---

# 108. Golden Scenario W3-A

```text
PO
↓
Receipt
↓
Quality Inspection
↓
Inventory
```

---

# 109. Golden Scenario W3-B

```text
Fulfillment
↓
Picking
↓
Packing
↓
Dispatch
```

---

# 110. W4 — Backlog Executivo

Epics:

```text
M2 BOM Complete
M7 Engineering
M7 PCP
M7 Shop Floor
M17 Quality Full
M18 Regulatory
M19 Maintenance Core
M8 Cost Feed
```

---

# 111. W4 Ordem Executiva

```text
BOM
↓
Routing
↓
Production Version
↓
Resource/Mold
↓
Regulatory Gate
↓
Production Order
↓
Material Issue
↓
Yield/Scrap
↓
Quality Release
↓
Finished Goods Receipt
↓
Cost Feed
```

---

# 112. Golden Scenario W4

```text
Production Version
↓
Production Order
↓
Issue Material
↓
Produce
↓
Final Inspection
↓
Regulatory Eligibility
↓
Finished Lot
↓
Inventory
```

---

# 113. W5 — Backlog Executivo

```text
M11 Fiscal Full
M12 Finance Full
M16 Commissions
```

---

# 114. Ordem Executiva Fiscal

```text
Tax Rule
↓
Fiscal Intent
↓
Provider Adapter
↓
Authorization
↓
XML Storage
↓
Cancellation
↓
CC-e
↓
Returns
```

---

# 115. Ordem Executiva Finance

```text
Receivable
Payable
Settlement
Bank Statement
Reconciliation
Payment Request
Payment Batch
Transmission
Marketplace Settlement
Credit
Cash Flow
```

---

# 116. Golden Scenario W5

```text
Order
↓
Invoice
↓
Receivable
↓
Settlement
↓
Commission Earning
↓
Accounting Fact
```

---

# 117. W6 — Backlog Executivo

```text
M8 Costing Full
M13 Accounting
M20 HR Full
```

---

# 118. M13 Prioridade Interna

Primeiro:

```text
Chart of Accounts
Accounting Rule
Journal
Posting
Period
```

Depois:

```text
Reconciliation
Statements
Intercompany
Advanced Closing
```

---

# 119. Golden Scenario Accounting

```text
InvoiceAuthorized
↓
Accounting Rule
↓
Journal
↓
Post
↓
Trial Balance
```

e:

```text
ShipmentDispatched
↓
CMV / Inventory Accounting
```

---

# 120. M20 Ordem Executiva

```text
Person
Contract
Assignment
Schedule
Punch
Time Rule
Adjustment
Time Bank
Vacation
Absence
Payroll Bridge
```

---

# 121. W7 — Backlog Executivo

```text
M21 Analytics Full
M22 Advanced
M23 Advanced
```

---

# 122. M21 Backlog Prioritário

```text
Analytics DB
Dimensions
Facts
Semantic Metrics
Dashboards
Targets
Budgets
Alerts
Explorer
Scheduled Reports
```

---

# 123. M22 Advanced

```text
Parallel
ANY_ONE
ALL_REQUIRED
QUORUM
Delegation
SLA
Escalation
Fingerprint
Revalidation
Simulation
```

---

# 124. M23 Advanced

```text
Data Quality
Duplicate Detection
Merge Governance
Lineage
Data Ownership
Retention
LGPD
```

---

# 125. Backlog Técnico Transversal Permanente

Independentemente da onda:

```text
Testing
Observability
Security
Performance
Documentation
Migration
Operational Runbooks
```

não podem ser deixados para o final.

---

# 126. Security Backlog Contínuo

A cada módulo:

```text
permissions
scope
sensitive fields
audit
SoD
step-up
```

devem ser definidos junto com a feature.

---

# 127. Migration Backlog Contínuo

A cada novo master/subledger:

```text
template
mapping
validation
migration rehearsal
reconciliation
```

deve ser planejado.

---

# 128. Test Pyramid

Baseline:

```text
        E2E
       /   \
   Integration
   /         \
Unit / Domain Tests
```

Grande volume de regras deve ser coberto na base.

---

# 129. Domain Tests

Exemplo M5:

```text
cannot reserve > available
cannot reserve blocked lot
cannot mutate posting
```

---

# 130. Integration Tests

Exemplo:

```text
Order
→ InventoryReservationService
→ DB
→ Outbox
```

---

# 131. Contract Tests

Exemplo:

```text
M4 consumer
expects
InventoryReservationCreated v1
```

---

# 132. End-to-End Tests

Reservados principalmente aos Golden Scenarios.

---

# 133. First Golden Scenario Suite

Obrigatórios inicialmente:

```text
GS-001 Login → Product
GS-002 Product Import
GS-003 Customer → Quote
GS-004 Quote → Approval
GS-005 Quote → Order → Reservation
GS-006 Marketplace → Order
```

---

# 134. Backlog de Performance

P0 nos pontos críticos:

```text
inventory reservation
marketplace ingestion
WMS scanner
fiscal batch
bank reconciliation
```

---

# 135. Database Index Review

Cada feature deve revisar:

```text
FKs
business key
status filter
date filter
lookup key
```

---

# 136. Query Budget

Telas de lista críticas precisam de query plan validado com volume representativo.

---

# 137. Backlog de Observabilidade por Feature

Feature deve definir:

```text
metric
log
trace
business health signal
```

quando aplicável.

---

# 138. Exemplo Marketplace

Monitorar:

```text
orders_ingested_total
orders_failed_total
webhook_lag
stock_publication_lag
rate_limit_count
```

---

# 139. Exemplo Inventory

```text
reservation_success
reservation_conflict
shortage_detected
posting_latency
```

---

# 140. Feature Toggle Strategy

Features incompletas ficam:

```text
disabled by default
```

Nunca publicar menu inacabado para usuários gerais.

---

# 141. Primeira Sprint — Sprint 0

Objetivo:

```text
tornar o projeto executável
```

Backlog recomendado:

```text
W0-PLATFORM-001 Repository
W0-PLATFORM-002 FastAPI
W0-DATA-001 SQLAlchemy
W0-DATA-002 Alembic
W0-INFRA-001 Docker Compose
W0-TEST-001 Test structure
W0-OBS-001 Structured logs
```

---

# 142. Saída da Sprint 0

Desenvolvedor executa:

```bash
docker compose up
```

e obtém:

```text
GET /health/live
→ 200
```

com PostgreSQL acessível.

---

# 143. Sprint 1

Objetivo:

```text
primeiro fluxo transacional auditável
```

Backlog:

```text
Authentication skeleton
RBAC skeleton
Audit framework
Error contract
Request/Correlation IDs
Outbox table
Inbox table
RabbitMQ
Celery
```

---

# 144. Saída da Sprint 1

Endpoint de teste:

```text
POST /api/v1/platform/test-entities
```

deve:

```text
gravar
gerar event
publicar
consumir
auditar
```

automaticamente.

Esse endpoint será descartado posteriormente.

---

# 145. Sprint 2

Objetivo:

```text
M1 Corporate Foundation
```

Backlog:

```text
Economic Group
Company
Branch
User
Role
Permission
Scope
```

Frontend:

```text
Login
Company Selector
Users
Roles
```

---

# 146. Sprint 3

Objetivo:

```text
primeiro Product Master funcional
```

Backlog:

```text
Product
Product List
Product Detail
Product Create
Lifecycle
Barcode
```

---

# 147. Sprint 4

Objetivo:

```text
M23 Import Core
```

Backlog:

```text
Template
Upload
Parsing
Validation
Preview
Commit
```

Vertical Slice:

```text
Import Products
```

---

# 148. Sprint 5

Objetivo:

```text
Customer Core
```

Backlog:

```text
Customer
Address
Contact
Duplicate Exact
```

---

# 149. Sprint 6

Objetivo:

```text
Inventory Foundation
```

Backlog:

```text
Warehouse
Location
Pool
Lot
Ledger
Balance
```

---

# 150. Sprint 7

Objetivo:

```text
Inventory Reservation
```

Backlog:

```text
Reservation Service
HARD/SOFT
Availability Query
Concurrency Tests
```

---

# 151. Sprint 8

Objetivo:

```text
Pricing Core
```

Backlog:

```text
Cost Seed
Price List
Pricing Resolver
Floor Calculation
```

---

# 152. Sprint 9

Objetivo:

```text
Quote Core
```

Backlog:

```text
Portfolio
Quote
Items
Revision
Pricing Integration
```

---

# 153. Sprint 10

Objetivo:

```text
Workflow Core
```

Backlog:

```text
Workflow Definition
Policy
Instance
My Approvals
Approve/Reject
```

---

# 154. Sprint 11

Objetivo:

```text
Quote Conversion
```

Backlog:

```text
Commercial Policy
Approval
Convert Quote
Order Aggregate
```

---

# 155. Sprint 12

Objetivo:

```text
Order → Reservation
```

Backlog:

```text
M4-M5 integration
Order snapshots
Reserve
Hold
Cancel
```

Ao final:

```text
MVP-1 Technical Pilot Candidate
```

---

# 156. Sprints não São Calendário Imutável

A sequência é executiva.

A quantidade real de sprints pode variar conforme:

```text
team size
parallel squads
complexity
legacy discoveries
```

---

# 157. Se houver Apenas 1 Desenvolvedor

Ordem ainda mais vertical:

```text
W0
↓
M1
↓
M2
↓
M23 Product Import
↓
M14
↓
M5
↓
M9
↓
M15
↓
M22
↓
M4
```

---

# 158. Se houver 2–3 Desenvolvedores

Após W0:

```text
Dev A
M1 / M2

Dev B
M23 / M14

Dev C
Frontend / Platform / Tests
```

---

# 159. Se houver 2 Squads

### Squad Core Commerce

```text
M14
M9
M15
M4
```

### Squad Supply Platform

```text
M2
M5
M3
```

### Platform transversal

```text
M1
M22
M23
```

---

# 160. Product Owner Backlog

Para cada Epic:

```text
business goal
scope
out of scope
acceptance criteria
business owner
priority
dependencies
migration impact
```

---

# 161. Architecture Owner Backlog

Manter:

```text
contract
events
data ownership
cross-domain dependency
performance constraint
security constraint
```

---

# 162. Data Owner Backlog

Para cada domínio:

```text
source
golden record
migration key
duplicate rule
data quality rule
retention
```

---

# 163. UX Backlog

Cada Feature deve ter:

```text
screen ID
route
role
main action
empty state
error state
loading state
responsive requirement
```

---

# 164. API Backlog

Para cada endpoint:

```text
operation_id
permission
request DTO
response DTO
errors
idempotency
versioning
```

---

# 165. Event Backlog

Para cada evento:

```text
name
version
producer
consumers
payload
idempotency
criticality
```

---

# 166. Não Criar Story por Tabela

Evitar:

```text
Criar tabela ORDER
Criar tabela ORDER_ITEM
```

como backlog principal.

Preferir capacidade:

```text
Criar pedido com itens
```

---

# 167. Backlog Orientado a Capacidade

Exemplo:

```text
Usuário Comercial consegue criar orçamento
com múltiplos itens e resolver preço
```

---

# 168. Exceptions

Histórias técnicas independentes podem existir quando forem plataforma.

Exemplo:

```text
Implement Transactional Outbox
```

---

# 169. Technical Spike

Quando houver incerteza real:

```text
SPIKE
```

Exemplo:

```text
validar API TikTok Shop
```

Resultado deve ser conhecimento documentado/POC útil.

---

# 170. Integrações Externas — Spike First

Para:

```text
Mercado Livre
Shopee
TikTok Shop
SEFAZ provider
Banks
Payroll
```

realizar primeiro:

```text
credentials
sandbox
API limits
payload discovery
failure behavior
```

---

# 171. Marketplace Spike Deliverable

Documento:

```text
auth flow
webhooks
orders
stock
prices
labels
rate limits
known gaps
```

---

# 172. Fiscal Spike Deliverable

```text
provider contract
NF-e operations
callback
contingency
certificate handling
```

---

# 173. Bank Spike Deliverable

```text
CNAB format
PIX/API support
authentication
payment status
reconciliation fields
```

---

# 174. Tech Debt Register

Tabela mínima:

```text
ID
Description
Reason
Risk
Owner
Target Wave
```

---

# 175. Architecture Decision Records

Criar:

```text
docs/adr/
```

Exemplos:

```text
ADR-001 Modular Monolith
ADR-002 PostgreSQL
ADR-003 RabbitMQ
ADR-004 Transactional Outbox
ADR-005 Redis Constraints
ADR-006 Schema Per Domain
ADR-007 Event Envelope
```

---

# 176. ADR Obrigatório Quando

Houver decisão que:

```text
affects multiple modules
changes technology
changes ownership
introduces dependency
changes security baseline
```

---

# 177. Documentação Viva

Manter:

```text
module README
API OpenAPI
event catalog
ADR
migration notes
runbook
```

---

# 178. Module README

Cada módulo terá:

```text
Purpose
Owner
Aggregate Roots
Tables
APIs
Events Produced
Events Consumed
Permissions
Dependencies
Runbook Notes
```

---

# 179. Pull Request Template

Perguntas obrigatórias:

```text
Which module?
Migration?
API change?
Event change?
Permission?
Audit?
Backward compatible?
Tests?
```

---

# 180. Code Review Checklist

```text
domain boundary
transaction boundary
idempotency
permissions
audit
Decimal
timezone
locking
N+1
tests
```

---

# 181. Database Review Checklist

```text
PK UUID
business unique key
FK ownership
NUMERIC precision
timezone timestamp
indexes
immutability
version field
```

---

# 182. API Review Checklist

```text
REST convention
permission
scope
idempotency
If-Match
errors
OpenAPI
no ORM exposure
```

---

# 183. Event Review Checklist

```text
fact not command?
correct owner?
versioned?
minimal payload?
correlation?
consumer idempotent?
```

---

# 184. Frontend Review Checklist

```text
screen ID
permission
scope
loading
empty
error
version conflict
sensitive masking
```

---

# 185. Security Review Checklist

```text
least privilege
SoD
step-up
sensitive field
audit
secret exposure
```

---

# 186. Go-Live Backlog

Cada MVP terá Epics específicos para:

```text
Migration
Training
UAT
Infrastructure
Runbook
Cutover
Hypercare
Legacy Retirement
```

---

# 187. MVP-1 Go-Live Epic

Contém:

```text
Product migration
Customer migration
Inventory opening
Price seed
User provisioning
B2B pilot
Order reconciliation
Hypercare
```

---

# 188. Release Candidate Gate

Para cada MVP:

```text
All P0 closed
Critical regression green
Migration rehearsal green
Security green
Performance green
UAT green
```

---

# 189. Indicadores do Programa

Acompanhamento:

```text
Stories Done
Cycle Time
Escaped Defects
Automated Test Coverage
Deployment Frequency
Change Failure Rate
Migration Reconciliation %
Critical Blockers
```

---

# 190. Métrica que não Deve Virar Objetivo Isolado

Exemplo:

```text
lines of code
```

não será indicador de produtividade.

---

# 191. Backlog Readiness Dashboard

| Item | Status |
|---|---|
| Requirements | Ready / Gap |
| Data model | Ready / Gap |
| API | Ready / Gap |
| Events | Ready / Gap |
| Security | Ready / Gap |
| UX | Ready / Gap |
| Migration | Ready / Gap |
| Tests | Ready / Gap |

---

# 192. Ordem Executiva Global

Sequência oficial recomendada:

```text
01 Platform bootstrap
02 PostgreSQL / Alembic
03 Error + IDs + logging
04 Authentication
05 RBAC / Scope
06 Audit
07 Outbox
08 RabbitMQ
09 Inbox
10 Celery
11 Redis abstractions
12 Object Storage
13 CI/CD + Observability

14 M1 Company/User/Role
15 M20 Org Core
16 M2 Product
17 M23 Import Core
18 M14 Customer

19 M5 Inventory Core
20 M9 Pricing
21 M15 Quote
22 M22 Workflow Core
23 M4 Order
24 M3 Marketplace

25 M10 WMS
26 M6 Procurement
27 M17 Incoming Quality
28 M11 Inbound Fiscal subset
29 M12 Payable bridge

30 M2 BOM Full
31 M7 Engineering/PCP
32 M19 Maintenance Core
33 M18 Regulatory
34 M17 Quality Full
35 M7 Shop Floor
36 M8 Costing Foundation

37 M11 Fiscal Full
38 M12 Finance Full
39 M16 Commission

40 M8 Costing Full
41 M13 Accounting
42 M20 HR Full

43 M21 Analytics Full
44 M22 Advanced
45 M23 Advanced
46 Optimization / Legacy Retirement
```

---

# 193. Primeira Codificação Real

O projeto não deve começar por:

```text
Tela de pedidos
```

nem por:

```text
Marketplace integration
```

O primeiro commit funcional deve estabelecer:

```text
project bootstrap
configuration
FastAPI
PostgreSQL
migration
health check
test
```

---

# 194. Primeiros Commits Recomendados

```text
001 bootstrap Python project
002 add FastAPI app
003 add configuration layer
004 add PostgreSQL
005 add Alembic
006 add health endpoints
007 add structured logging
008 add correlation/request middleware
009 add CI pipeline
010 add Docker Compose
```

---

# 195. Depois dos Primeiros Commits

```text
011 auth skeleton
012 permission registry
013 role/scope
014 audit framework
015 outbox
016 RabbitMQ
017 inbox
018 Celery
019 idempotency
020 optimistic locking
```

---

# 196. Primeiro Módulo de Negócio Codificado

```text
M1
```

Começando por:

```text
Economic Group
Company
Branch
```

e depois:

```text
User
Role
Permission
Scope
```

---

# 197. Primeira Tela Codificada

Recomendação:

```text
Login
```

seguida por:

```text
Company Selector
```

e então:

```text
Product List
```

---

# 198. Primeira API de Negócio

```text
GET /api/v1/admin/companies
```

seguida por:

```text
GET /api/v1/products
```

---

# 199. Primeira Migration de Negócio

Criar:

```text
admin.economic_group
admin.company
admin.branch
```

antes de `product`.

---

# 200. Primeira Event Story de Negócio

Exemplo:

```text
CompanyCreated
```

para validar a plataforma de eventos.

---

# 201. Primeiro Event Consumer de Negócio

Pode ser uma projeção simples ou read model controlado.

Objetivo:

```text
validar infraestrutura real
```

---

# 202. Primeiro Teste E2E Oficial

```text
Login
↓
GET Companies
↓
Select Company
↓
GET Products
```

---

# 203. Segundo Teste E2E Oficial

```text
Create Product
↓
ProductCreated
↓
Audit
↓
Product appears in list
```

---

# 204. Terceiro Teste E2E Oficial

```text
Import Product Spreadsheet
↓
Preview
↓
Commit
↓
Product Master
```

---

# 205. Regra de Evolução

Somente depois desses fundamentos estáveis avançar para:

```text
Inventory
Orders
Marketplace
```

---

# 206. Critérios de Aceite da Etapa 10

A Etapa 10 estará pronta quando:

1. hierarquia do backlog estiver definida;
2. prioridades P0–P3 estiverem definidas;
3. DoR estiver definido;
4. DoD estiver definido;
5. estrutura do repositório estiver definida;
6. estrutura interna dos módulos estiver definida;
7. regras de dependência estiverem definidas;
8. W0 possuir backlog concreto;
9. repository bootstrap estiver especificado;
10. FastAPI bootstrap estiver especificado;
11. PostgreSQL foundation estiver especificada;
12. Alembic estiver especificado;
13. event envelope estiver especificado;
14. Outbox estiver no backlog;
15. Inbox estiver no backlog;
16. RabbitMQ estiver no backlog;
17. Celery estiver no backlog;
18. Redis abstraction estiver no backlog;
19. Object Storage estiver no backlog;
20. authentication estiver no backlog;
21. RBAC estiver no backlog;
22. audit estiver no backlog;
23. idempotency estiver no backlog;
24. optimistic locking estiver no backlog;
25. observability estiver no backlog;
26. CI/CD estiver no backlog;
27. test architecture estiver definida;
28. W1 possuir backlog;
29. W2 possuir backlog;
30. W3 possuir backlog;
31. W4 possuir backlog;
32. W5 possuir backlog;
33. W6 possuir backlog;
34. W7 possuir backlog;
35. vertical slices estiverem definidos;
36. first golden scenarios estiverem definidos;
37. desenvolvimento paralelo depender de contracts;
38. contract-first estiver formalizado;
39. test pyramid estiver definida;
40. performance backlog estiver previsto;
41. security backlog for contínuo;
42. migration backlog for contínuo;
43. ADR estiver previsto;
44. module README estiver previsto;
45. PR checklist estiver previsto;
46. database checklist estiver previsto;
47. API checklist estiver previsto;
48. event checklist estiver previsto;
49. frontend checklist estiver previsto;
50. security checklist estiver previsto;
51. MVP go-live backlog estiver previsto;
52. readiness dashboard estiver previsto;
53. ordem executiva global estiver definida;
54. primeiro commit estiver definido;
55. primeiras migrations estiverem definidas;
56. primeiro módulo funcional estiver definido;
57. primeira tela estiver definida;
58. primeira API estiver definida;
59. primeiro evento estiver definido;
60. primeiro teste E2E estiver definido;
61. Sprint 0 estiver definida;
62. Sprint 1 estiver definida;
63. Sprint 2–12 tiverem direção inicial;
64. plano suportar um desenvolvedor;
65. plano suportar múltiplos desenvolvedores;
66. plano suportar múltiplas squads;
67. backlog estiver orientado a capacidade;
68. tabelas não forem a unidade principal de valor;
69. spikes forem controlados;
70. integrações externas começarem por descoberta/homologação;
71. technical debt estiver governado;
72. feature flags não substituírem segurança;
73. migrations não forem deixadas para o final;
74. testes não forem deixados para o final;
75. observabilidade não for deixada para o final;
76. cada módulo possuir owner;
77. cada contrato possuir owner;
78. backlog respeitar a Etapa 4;
79. backlog respeitar RBAC/SoD da Etapa 5;
80. backlog respeitar APIs da Etapa 6;
81. backlog respeitar telas da Etapa 7;
82. backlog respeitar infraestrutura da Etapa 8;
83. backlog respeitar roadmap da Etapa 9;
84. início da codificação estiver objetivamente definido;
85. projeto estiver pronto para sair da fase de arquitetura e entrar em execução.

---

# 207. Decisões Consolidadas

## A. A unidade de entrega será capacidade, não tabela

## B. Vertical Slice é preferível a desenvolvimento horizontal

## C. W0 é obrigatória antes de desenvolvimento massivo

## D. Outbox/Inbox/Audit/RBAC não serão implementados depois

## E. Primeiro processo real será simples e transversal

## F. M1 é o primeiro domínio funcional

## G. Product Master é o primeiro master operacional amplo

## H. M23 entra cedo para impedir migrações improvisadas

## I. Inventory precede Order real

## J. Pricing precede Quote comercial confiável

## K. Workflow Core precede aprovações reais

## L. Contratos precedem trabalho paralelo

## M. Testes fazem parte da Story

## N. Observabilidade faz parte da Story

## O. Security faz parte da Story

## P. Migration faz parte do desenho do módulo

## Q. Todo módulo terá documentação viva

## R. ADR governa decisões arquiteturais novas

## S. MVP não significa cortar invariantes

## T. Ao final da Etapa 10 o projeto está apto a iniciar codificação

---

# 208. Visão do Primeiro Ciclo de Desenvolvimento

```text
SPRINT 0
Platform Bootstrap
        │
        ▼
SPRINT 1
Security + Events + Audit
        │
        ▼
SPRINT 2
M1 Corporate Foundation
        │
        ▼
SPRINT 3
M2 Product Master
        │
        ▼
SPRINT 4
M23 Product Import
        │
        ▼
SPRINT 5
M14 Customer Core
        │
        ▼
SPRINT 6–7
M5 Inventory
        │
        ▼
SPRINT 8
M9 Pricing
        │
        ▼
SPRINT 9
M15 Quote
        │
        ▼
SPRINT 10
M22 Workflow
        │
        ▼
SPRINT 11–12
M4 Order + Reservation
        │
        ▼
MVP-1 PILOT
```

---

# 209. Marco Final da Consolidação

Com a aprovação da Etapa 10, estão formalmente concluídos:

```text
23 módulos especificados
+
10 etapas de consolidação arquitetural
```

O trabalho seguinte deixa de ser arquitetura macro e passa a ser:

```text
IMPLEMENTAÇÃO
```

A primeira execução recomendada é:

```text
W0 — Engineering Foundation
Sprint 0
Repository Bootstrap
```

---

# 210. Status Formal da Etapa 10

A **Etapa 10 — Backlog Técnico Mestre, Ordem Executiva de Desenvolvimento e Plano de Início da Codificação** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- hierarquia do backlog;
- prioridades;
- DoR;
- DoD;
- repository structure;
- module structure;
- W0–W7;
- vertical slices;
- golden scenarios;
- sprints iniciais;
- ordem executiva;
- contratos;
- testes;
- segurança;
- observabilidade;
- migration backlog;
- ADRs;
- readiness;
- início da codificação.

Alterações incompatíveis devem seguir:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 211. Próximo Passo Oficial

A fase de consolidação arquitetural M1–M23 está encerrada.

O próximo passo passa a ser:

```text
EXECUÇÃO DO ERP
```

Começando por:

```text
W0 — Engineering Foundation
Sprint 0 — Repository Bootstrap
```

Primeiras atividades:

```text
1. bootstrap Python project
2. FastAPI app
3. configuration layer
4. PostgreSQL
5. Alembic
6. health endpoints
7. structured logging
8. correlation/request middleware
9. CI pipeline
10. Docker Compose
```

---

**Fim da Etapa 10 — Backlog Técnico Mestre, Ordem Executiva de Desenvolvimento e Plano de Início da Codificação**
