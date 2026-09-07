# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 9 — Roadmap de Implementação, Fases, Dependências e Critérios de Go-Live

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Roadmap de implementação do ERP M1–M23, ondas de construção, dependências, MVPs progressivos, coexistência com legado, migração, piloto, cutover, hypercare, readiness e critérios de go-live.  
**Objetivo:** Transformar a arquitetura consolidada em um plano executável de construção e entrada em produção, preservando integridade física, fiscal, financeira, contábil, regulatória e operacional.

---

# 1. Objetivo da Etapa 9

A Etapa 9 transforma toda a arquitetura consolidada M1–M23 em um plano executável de construção e entrada em produção.

Ela responde:

```text
O que deve ser desenvolvido primeiro?
O que depende do quê?
Quais módulos podem entrar em produção juntos?
Quais módulos não podem entrar isoladamente?
O que pertence ao MVP?
Como coexistir com o ERP legado?
Como migrar os dados?
Como fazer piloto?
Como fazer cutover?
Quando uma fase está realmente pronta?
Quando devemos abortar ou reverter um go-live?
```

Princípio central:

```text
BUILD ORDER
≠
MODULE NUMBER ORDER
```

A construção será guiada por:

```text
DEPENDENCY
+
BUSINESS VALUE
+
RISK
+
FOUNDATION READINESS
+
MIGRATION FEASIBILITY
```

---

# 2. Princípio de Foundation First

Antes de qualquer processo crítico, devem existir fundações compartilhadas.

```text
FOUNDATION
↓
MASTER DATA
↓
TRANSACTIONAL CORE
↓
INDUSTRIAL CORE
↓
BACKOFFICE
↓
GOVERNANCE / ANALYTICS
↓
OPTIMIZATION
```

---

# 3. Visão Macro das Ondas

| Onda | Nome | Objetivo |
|---|---|---|
| W0 | Engineering Foundation | Plataforma técnica e contratos |
| W1 | Corporate & Master Data Foundation | Empresa, segurança, produtos, clientes e governança básica |
| W2 | Commercial & Order Core | Pricing, vendas, marketplaces, pedidos e estoque |
| W3 | Logistics & Procurement | WMS, compras e recebimento |
| W4 | Manufacturing Core | Engenharia, PCP, produção, qualidade e manutenção |
| W5 | Fiscal & Finance | Fiscal, financeiro, comissões |
| W6 | Costing, Accounting & HR | Custos, contabilidade e RH |
| W7 | Analytics, Workflow & Governance Completion | BI, workflow avançado, Data Governance e otimizações |

```text
W0–W7
≠
releases obrigatoriamente monolíticas
```

Cada onda poderá possuir múltiplas releases.

---

# 4. W0 — Engineering Foundation

Escopo:

```text
Repository structure
Modular Monolith skeleton

FastAPI
SQLAlchemy
Alembic
Pydantic

PostgreSQL
RabbitMQ
Redis
Celery
Object Storage

Authentication skeleton
RBAC skeleton

Transactional Outbox
Inbox

Audit framework

Correlation / Request / Causation IDs

Error contract

Idempotency framework

Optimistic locking

Observability

CI/CD

Docker environment

Testing framework
```

---

# 5. Resultado Esperado da W0

A equipe deve conseguir demonstrar:

```text
recebe API
↓
valida RBAC
↓
grava PostgreSQL
↓
gera Outbox
↓
publica RabbitMQ
↓
consumer processa idempotentemente
↓
gera Audit
↓
aparece em logs/traces
```

Se isso não estiver funcionando de ponta a ponta:

```text
não iniciar desenvolvimento massivo dos módulos
```

---

# 6. Definition of Done da Foundation

A W0 só fecha quando:

1. estrutura modular estiver definida;
2. schema-per-domain estiver funcionando;
3. migrations estiverem automatizadas;
4. API versioning existir;
5. padrão de DTO existir;
6. RBAC middleware existir;
7. correlation/request IDs existirem;
8. audit base existir;
9. Outbox estiver funcionando;
10. Inbox estiver funcionando;
11. RabbitMQ retry/DLQ estiver operacional;
12. worker Celery estiver operacional;
13. Redis estiver integrado;
14. Object Storage estiver integrado;
15. logs estruturados existirem;
16. tracing básico existir;
17. pipeline CI estiver ativo;
18. testes unitários e integração rodarem automaticamente;
19. ambiente de homologação puder ser criado;
20. deploy de uma aplicação mínima estiver automatizado.

---

# 7. W1 — Corporate & Master Data Foundation

Módulos prioritários:

```text
M1  Administração / Segurança
M2  Product Master
M14 Clientes / CRM — core cadastral
M20 Estrutura Organizacional — subset necessário
M23 Data Governance — subset de importação
```

---

# 8. Por que M20 entra Parcialmente Cedo

M22 dependerá posteriormente da hierarquia organizacional.

M1 também se beneficia de:

```text
person
employee
department
cost_center
manager hierarchy
```

Implementar primeiro:

```text
Organization Structure Core
```

---

# 9. M1 — Primeiro Domínio Funcional

Entregar:

```text
Economic Group
Companies
Branches

Users
Roles
Permissions
Scopes

Sessions
Service Accounts

Audit
```

---

# 10. M2 — Product Master

Entregar prioritariamente:

```text
Product
SKU
Variant
Barcode
Packaging
UOM
Fiscal basic data
Product type
Lifecycle
Media metadata
```

Depois:

```text
BOM
BOM Revision
```

---

# 11. M14 — Customer Core

Primeira versão:

```text
Customer
Customer Group
Address
Contact
Status
Dedup exact CPF/CNPJ
```

---

# 12. M23 — Migration Foundation

Antes de qualquer migração relevante:

```text
Template
Upload
Staging
Validation
Preview
Commit
Rejected Rows
Audit
```

Evitar:

```text
script manual
+
SQL direto
+
risco
```

---

# 13. Primeira Migração de Dados

Sequência recomendada:

```text
Companies
↓
Organization Structure
↓
Users
↓
Products
↓
Customers
↓
Suppliers
```

---

# 14. W1 — Critério de Saída

W1 estará pronta quando for possível:

```text
logar
trocar empresa/filial
consultar permissões
cadastrar/importar produto
cadastrar/importar cliente
auditar alteração
exportar cadastro
```

sem SQL manual para operação normal.

---

# 15. W2 — Commercial & Order Core

Módulos:

```text
M5 Inventory Core
M9 Pricing
M15 Comercial B2B
M3 Marketplace Hub
M4 Orders / Fulfillment Core
M22 Workflow Core
```

M18 Regulatory Gate poderá entrar em versão mínima se necessário.

---

# 16. Por que M5 vem Antes de M4

```text
Inventory foundation
→ antes
→ Order reservation
```

M5 mínimo:

```text
Warehouse
Location
Pool
Lot
Balance
Ledger
Reservation
```

---

# 17. Inventory Opening Balance

M5 só entra em produção após migração controlada de:

```text
Opening Inventory
```

usando M23 com:

```text
ALL_OR_NOTHING
```

e reconciliação formal.

---

# 18. M9 — Pricing antes do Comercial

```text
M8 Standard Cost temporariamente alimentado por legado/import
↓
M9 Pricing
↓
M15 Sales
```

Na fase inicial:

```text
standard_cost_seed
```

poderá vir do legado como snapshot controlado.

---

# 19. Transitional Cost Strategy

Durante transição:

```text
LEGACY STANDARD COST
→ imported snapshot
→ M9
```

Depois:

```text
M8
→ StandardCostActivated
→ M9
```

A origem do custo deve ser registrada.

---

# 20. M22 — Workflow Core Precisa Entrar Cedo

Primeira versão:

```text
Workflow Definition
Approval Policy
Sequential Approval
Highest Level
Cumulative
My Approvals
Approve
Reject
Audit
```

Depois:

```text
Parallel
Quorum
Delegation
SLA
Revalidation
Simulation
```

---

# 21. M15 — Comercial B2B

Primeira versão:

```text
Portfolio
Quote
Quote Revision
Pricing integration
Credit placeholder/legacy
Commercial Policy
Approval M22
Conversion
```

---

# 22. Crédito Durante Transição

Enquanto M12 não estiver completo:

```text
CreditDecisionAdapter
```

pode consultar saldo migrado, snapshot do legado ou integração temporária.

Nunca duplicar regra de crédito dentro do M15.

---

# 23. M4 — Order Core

Primeira versão:

```text
Order
Order Item Snapshot
Customer Snapshot
Reservation
Hold
Cancel
Fulfillment skeleton
```

---

# 24. M3 — Marketplace Hub

Ordem recomendada de canais:

```text
1. Mercado Livre
2. Shopee
3. TikTok Shop
```

ou outra ordem operacional validada.

---

# 25. Marketplace Go-Live Progressivo

```text
READ ONLY / SHADOW
↓
ORDER IMPORT
↓
STOCK SYNC
↓
PRICE SYNC
↓
FISCAL / LABEL
↓
FULL OPERATION
```

---

# 26. Shadow Mode

M3 inicialmente pode consumir APIs externas, comparar com legado e não efetivar automaticamente.

Validar:

- pedidos;
- status;
- preços;
- estoque.

---

# 27. W2 — Piloto Comercial

Recomendação:

```text
1 empresa
1 filial
1 carteira comercial
pequeno grupo de usuários
```

---

# 28. W2 — Critério de Saída

Deve ser possível:

```text
cotar
aprovar
converter
reservar estoque
receber pedido marketplace
criar pedido interno
controlar hold
auditar
```

com reconciliação contra legado durante piloto.

---

# 29. W3 — Logistics & Procurement

Módulos:

```text
M10 WMS
M6 Procurement
M17 Incoming Quality subset
M11 Inbound Fiscal subset
M12 Payable bridge subset
```

---

# 30. M10 — WMS

Após:

```text
M4 Fulfillment
+
M5 Inventory
```

Primeira entrega:

```text
Wave
Picking
Packing
Package
Dispatch
Scanner
Print Agent
```

---

# 31. WMS Piloto

Começar por:

```text
um fluxo B2C
+
um pequeno conjunto de operadores
```

Depois B2B.

---

# 32. WMS Parallel Run

Durante piloto:

```text
ERP novo
+
controle paralelo do legado
```

por janela curta.

Evitar parallel run longo para estoque físico.

---

# 33. Cutover de Estoque

```text
Legacy stock writes
→ STOP

Physical count / reconciliation
→ Opening snapshot confirmed

New ERP
→ sole physical stock authority
```

---

# 34. Procurement Build Order

```text
Supplier
↓
Product Supplier
↓
Purchase Requisition
↓
RFQ
↓
Purchase Order
↓
Inbound Invoice
↓
Physical Receipt
↓
3-Way Match
↓
Payable Request
```

---

# 35. Quality no Recebimento

M17 subset mínimo:

```text
Inspection Plan
Incoming Inspection
Approve / Partial / Reject
Quality Hold
```

---

# 36. W3 — Critério de Saída

```text
PO
→ Receipt
→ Quality
→ Inventory

Fulfillment
→ Pick
→ Pack
→ Dispatch
```

sem ajuste manual fora do M5.

---

# 37. W4 — Manufacturing Core

Módulos:

```text
M7 Manufacturing
M17 Quality full
M18 Regulatory
M19 Maintenance
M8 Costing foundation
```

---

# 38. Ordem dentro da W4

```text
M2 BOM complete
↓
M7 Engineering/Routing
↓
M19 Resources/Molds
↓
M18 Regulatory Gate
↓
M7 PCP/Production
↓
M17 In-Process/Final Quality
↓
M8 Actual Cost feed
```

---

# 39. Production Version antes da OP

```text
BOM Revision
+
Routing Revision
=
Production Version
```

Só depois:

```text
Production Order
```

---

# 40. M19 entra antes do Shop Floor Completo

Subset mínimo:

```text
Maintenance Asset
Availability
Mold
```

---

# 41. M18 não Pode Ser Adiado para Depois da Produção

Primeira versão:

```text
Regulatory Family
Certificate
Validity
Operational Flags
Block
Lot Snapshot
```

---

# 42. M17 Final Inspection

Antes de produzir PA regulado no novo ERP:

```text
Final Quality Release
```

deve estar operacional.

---

# 43. Piloto de Produção

Selecionar:

```text
1 família
1 linha/célula
poucos produtos
poucos moldes
```

---

# 44. Produção em Shadow Planning

```text
MRP novo
→ gera projeção

PCP atual
→ continua execução
```

Comparar necessidade, shortages, datas e capacidade.

---

# 45. Cutover do Shop Floor

OPs abertas do legado devem ser classificadas:

```text
A. terminar no legado
B. migrar como WIP opening transaction
C. cancelar/recriar no novo ERP
```

---

# 46. WIP Opening Balance

Se houver migração de WIP:

```text
OPENING_BALANCE_IMPORT
```

com:

- OP origem;
- quantidade;
- estágio;
- consumo acumulado;
- lote;
- custo carregado;
- audit trail.

---

# 47. W4 — Critério de Saída

```text
plan
release OP
consume
report production
report scrap
track lot
quality release
regulatory gate
maintenance block
receive finished goods
```

com rastreabilidade completa.

---

# 48. W5 — Fiscal & Finance

Módulos:

```text
M11 Fiscal full
M12 Finance full
M16 Commissions
M22 workflows financeiros avançados
```

---

# 49. Fiscal antes de Finance Completo

M11 precisa estabilizar:

```text
NF authorization
cancellation
CC-e
inbound validation
tax rules
```

---

# 50. Fiscal Pilot

Começar em homologação SEFAZ com cenários:

- B2B;
- marketplace;
- devolução;
- transferência;
- cancelamento;
- rejeição;
- contingência.

---

# 51. Fiscal Cutover

Séries e numeração devem ser controladas.

Nunca dois sistemas emitindo a mesma série sem desenho explícito.

---

# 52. Estratégia de Série

Durante coexistência:

```text
Legacy
→ Series A

New ERP
→ Series B
```

quando apropriado.

---

# 53. M12 Finance Build Order

```text
Financial Accounts
↓
Receivables
↓
Payables
↓
Settlements
↓
Bank Import
↓
Reconciliation
↓
Payment Requests
↓
Payment Batches
↓
Marketplace Settlement
↓
Credit
↓
Cash Flow
```

---

# 54. Saldos Financeiros de Abertura

Migrar:

```text
open receivables
open payables
bank opening balance reference
advances
```

via:

```text
OPENING_BALANCE_IMPORT
```

---

# 55. Não Migrar Histórico Financeiro Inteiro como Transação Viva

Histórico pode ser:

```text
HISTORICAL_MIGRATION
```

Somente títulos abertos entram como subledger ativo.

---

# 56. Conciliação no Go-Live Financeiro

Critério obrigatório:

```text
Bank Statement
=
ERP Financial Position
```

dentro de diferenças formalmente explicadas.

---

# 57. Pagamentos

Antes de transmissão real:

```text
dry run
→ homologation
→ low-value pilot
→ controlled production
```

---

# 58. M16 — Commissions

Entrar quando vendas, NF e settlements estiverem confiáveis.

Primeiro período:

```text
shadow commission calculation
```

---

# 59. W5 — Critério de Saída

```text
issue NF
create receivable/payable
settle
reconcile bank
transmit payment
reconcile marketplace
calculate commissions
```

sem dupla criação financeira.

---

# 60. W6 — Costing, Accounting & HR

Módulos:

```text
M8 Costing full
M13 Accounting
M20 HR full
```

---

# 61. Accounting não Precisa Ser Primeiro Go-Live

M13 depende de fatos estáveis de:

```text
Fiscal
Finance
Inventory
Costing
Assets
Payroll
```

---

# 62. M13 em Shadow Accounting

```text
ERP Events
↓
M13
↓
Journal Simulation
```

comparado com contabilidade atual.

---

# 63. Accounting Parallel Period

Recomendação:

```text
1 ou 2 competências
```

de fechamento paralelo.

Comparar:

```text
Trial Balance
DRE
Balance Sheet
AR subledger
AP subledger
Inventory
Bank
Taxes
```

---

# 64. M8 Full Costing

M8 passa a full quando existirem:

```text
real material consumption
labor rate
machine hours
maintenance information
CIF policy
actual purchase costs
```

---

# 65. Standard Cost Activation

Nova fonte:

```text
M8
```

e o seed legado é aposentado.

---

# 66. M20 RH Full

Expandir para:

```text
employment
time
overtime
time bank
vacation
absence
benefits
payroll bridge
```

---

# 67. Ponto Piloto

Iniciar em:

```text
um departamento
ou
um turno
```

comparando cálculos.

---

# 68. Payroll Bridge

```text
export variables
import payroll result
```

deve ser homologado com sistema externo.

---

# 69. W6 — Critério de Saída

```text
close costing
close accounting
reconcile subledgers
calculate time
close time period
exchange payroll data
generate finance/accounting payroll facts
```

---

# 70. W7 — Analytics, Workflow e Governance Completion

Módulos:

```text
M21 Analytics
M22 Workflow advanced
M23 Governance advanced
```

---

# 71. M21 pode Começar Antes

O pipeline analítico deve evoluir desde W1/W2, mas a versão corporativa completa entra quando as principais fontes estiverem estáveis.

---

# 72. M21 Build Order

```text
Analytics Infrastructure
↓
Dimensions
↓
Operational Facts
↓
Metric Catalog
↓
Dashboards
↓
Targets
↓
Budget
↓
Alerts
↓
Self-Service
↓
Scheduled Reports
```

---

# 73. M22 Advanced

Adicionar:

```text
Parallel approvals
Quorum
Delegation
SLA
Escalation
Change Fingerprint
Revalidation
Simulation
```

---

# 74. M23 Advanced

Adicionar:

```text
Data Quality
Duplicate Detection
Merge Orchestration
Lineage
Data Ownership
Retention
LGPD operations
```

---

# 75. Roadmap de Dependências Críticas

```text
M1
│
├─────────────► todos
│
M2
├──► M3
├──► M4
├──► M5
├──► M6
├──► M7
├──► M9
├──► M10
├──► M17
└──► M18

M5
├──► M4
├──► M7
└──► M10

M9
└──► M15

M14
└──► M15

M15
└──► M4

M4
└──► M10/M11/M12

M7
└──► M8

M11 + M12 + M8
└──► M13

M20
├──► M7
├──► M8
└──► M22
```

---

# 76. Módulos com Alto Poder Bloqueador

```text
M1 Security
M2 Product
M5 Inventory
M11 Fiscal
M12 Finance
M18 Regulatory
M22 Workflow
M23 Migration
```

---

# 77. Classificação de Releases

```text
TECHNICAL RELEASE
PILOT RELEASE
LIMITED PRODUCTION
GENERAL AVAILABILITY
```

---

# 78. Technical Release

Disponível internamente, sem usuário final produtivo.

---

# 79. Pilot Release

Uso controlado por empresa, filial, departamento, canal, família ou grupo de usuários.

---

# 80. Limited Production

Processo real com escopo limitado.

---

# 81. General Availability

Processo oficialmente liberado para o escopo definido.

---

# 82. Feature Flags para Rollout

Podem habilitar por:

```text
company
branch
user group
channel
```

Mas:

```text
feature flag
≠
authorization
```

---

# 83. Estratégia de Coexistência com Legado

Estados:

```text
LEGACY_AUTHORITY
SHADOW
DUAL_READ
NEW_ERP_AUTHORITY
RETIRED
```

---

# 84. LEGACY_AUTHORITY

Legado continua dono do fato.

---

# 85. SHADOW

Novo ERP processa sem gerar efeito oficial.

---

# 86. DUAL_READ

Consulta pode vir de mais de uma fonte temporariamente.

Não significa dual write.

---

# 87. NEW_ERP_AUTHORITY

Novo ERP é única autoridade de escrita do domínio.

---

# 88. RETIRED

Funcionalidade equivalente do legado deixa de operar.

---

# 89. Regra Contra Dual Write

```text
DUAL READ
pode existir

DUAL WRITE
deve ser evitado
```

especialmente para estoque, financeiro, fiscal e contabilidade.

---

# 90. Integração Temporária com Legado

Usar:

```text
LegacyAdapter
```

com owner, contrato, validade e sunset.

---

# 91. Anti-Corruption Layer do Legado

```text
Legacy Record
↓
Legacy Adapter
↓
Canonical DTO
↓
New Domain
```

---

# 92. Data Migration Strategy

Categorias M23:

```text
MASTER_DATA_IMPORT
OPENING_BALANCE_IMPORT
HISTORICAL_MIGRATION
TRANSACTIONAL_IMPORT
```

---

# 93. Migração em Ondas

```text
Master Data
↓
Reference Data
↓
Opening Balances
↓
Open Transactions
↓
Historical Data
```

---

# 94. Dados Mestres Primeiro

Exemplos:

```text
Products
Customers
Suppliers
Employees
Assets
BOMs
Price Tables
```

---

# 95. Saldos de Abertura

Exemplos:

```text
Inventory
Receivables
Payables
Time Bank
Assets
```

---

# 96. Transações Abertas

Exemplos:

```text
open purchase orders
open sales orders
open production orders
open workflows
```

Nem todas precisam ser migradas.

---

# 97. Histórico

Pode permanecer no legado read-only ou ser migrado para histórico/analytics.

---

# 98. Reconciliation Rules

Estoque:

```text
Legacy Qty
=
Imported Qty
=
Physical Count / approved difference
```

Financeiro:

```text
Legacy Open AR
=
ERP Open AR
```

---

# 99. Reconciliation Report

M23 deve gerar:

```text
source_count
target_count
source_total
target_total
difference
rejected_records
```

---

# 100. Data Freeze

Pode existir `freeze window` para dados críticos durante cutover.

---

# 101. Delta Migration

```text
T0 full load
↓
delta loads
↓
final delta
↓
cutover
```

---

# 102. Cutover Runbook

Cada go-live crítico possui runbook:

```text
T-7 days
T-1 day
T-4 hours
T0
T+1 hour
T+1 day
T+7 days
```

---

# 103. Exemplo T-7

```text
Go/No-Go review
backup validation
user list
training confirmation
open issue review
migration rehearsal result
```

---

# 104. Exemplo T-1

```text
freeze configuration
verify integrations
verify certificates
verify printer/scanner
verify backups
```

---

# 105. T0

```text
stop legacy writes
final delta
reconciliation
activate feature flags
smoke test
release users
```

---

# 106. Hypercare

Após go-live:

```text
T0 → T+7/T+14
```

monitorar erros, filas, divergências, reclamações, performance e reconciliações.

---

# 107. War Room

Go-lives críticos podem usar sala de acompanhamento com TI, área usuária e especialistas aplicáveis.

---

# 108. Go/No-Go Board

Participantes sugeridos:

```text
Product Owner
Tech Lead
Business Owner
Operations
Security/Infra
Data Migration Owner
```

mais Fiscal/Financeiro quando aplicável.

---

# 109. Critérios Gerais de Go-Live

Nenhum módulo entra em produção apenas porque:

```text
"o desenvolvimento terminou"
```

---

# 110. Go-Live Readiness — Funcional

```text
critical acceptance tests passed
business owner sign-off
no unresolved blocker
training completed
operating procedure documented
```

---

# 111. Go-Live Readiness — Dados

```text
migration rehearsal passed
reconciliation passed
critical data quality above threshold
backup validated
rollback dataset available
```

---

# 112. Go-Live Readiness — Técnico

```text
production infrastructure ready
monitoring ready
alerts ready
backup ready
runbooks ready
load test passed
security scan passed
```

---

# 113. Go-Live Readiness — Integrações

```text
external credentials valid
homologation completed
retry tested
DLQ tested
failure scenario tested
```

---

# 114. Go-Live Readiness — Segurança

```text
roles assigned
SoD reviewed
service accounts active
MFA tested
break glass ready
```

---

# 115. Go-Live Readiness — Suporte

```text
support owners defined
escalation list
war room channel
incident procedure
vendor contacts
```

---

# 116. Blocker Severity

```text
GO_LIVE_BLOCKER
HIGH
MEDIUM
LOW
```

---

# 117. GO_LIVE_BLOCKER

Exemplos:

```text
inventory balance divergence
financial duplicate risk
NF authorization instability
regulatory gate bypass
missing backup
unresolved security critical
```

Resultado:

```text
NO-GO
```

---

# 118. Rollback Criteria

Exemplos:

```text
critical financial duplication
inventory corruption
system unavailable beyond threshold
fiscal issuance unsafe
data migration materially incorrect
security breach
```

---

# 119. Rollback não é Sempre Técnico

Distinguir:

```text
TECHNICAL ROLLBACK
BUSINESS FALLBACK
```

---

# 120. Technical Rollback

Exemplo:

```text
deploy v1.5
→ issue
→ deploy v1.4
```

quando compatível.

---

# 121. Business Fallback

Exemplo:

```text
orders retained
processing delayed
manual operational contingency
```

sem desfazer fatos confirmados.

---

# 122. Fiscal Contingency

Deve ser documentada especificamente com M11.

---

# 123. Finance Contingency

Pagamentos não confirmados:

```text
never resend blindly
```

primeiro reconciliar status bancário.

---

# 124. Inventory Contingency

Operações físicas sem registro seguro devem ser interrompidas ou seguir contingência formal com reconciliação posterior.

---

# 125. Training Strategy

Treinar por:

```text
role
+
process
+
screen
```

---

# 126. Key Users

Cada domínio precisa de:

```text
Business Owner
Key User
Backup Key User
```

---

# 127. Train-the-Trainer

```text
Core Team
→ Key Users
→ End Users
```

---

# 128. UAT

UAT deve usar casos reais representativos e cenários end-to-end.

---

# 129. Golden Scenarios

Exemplos:

```text
B2B Quote → Cash
Marketplace Order → Settlement
Purchase → Pay
Production → Cost
Recall Traceability
Employee → Payroll
```

---

# 130. Regression Suite

Cada nova onda não pode quebrar as anteriores.

---

# 131. Release Gates

```text
Code Quality Gate
Test Gate
Security Gate
Migration Gate
Business Sign-Off
```

---

# 132. Technical Debt Policy

Débito técnico só pode ser aceito quando:

```text
documented
owned
prioritized
time-bounded
```

---

# 133. O que Pode Ser Simplificado no MVP

Pode ser simplificado:

- visual;
- automação secundária;
- relatórios não críticos;
- conveniências;
- workflows menos frequentes.

---

# 134. O que não Pode Ser Simplificado

Não simplificar:

```text
Inventory Ledger
Financial integrity
Fiscal traceability
Accounting balancing
Regulatory block
Audit
RBAC
SoD critical
Idempotency
Migration reconciliation
```

---

# 135. Release Train

Sugestão após estabilização:

```text
2-week engineering iteration
+
controlled release cadence
```

---

# 136. Desenvolvimento Paralelo

Times podem trabalhar em paralelo se contratos estiverem estabilizados.

---

# 137. Contract-First Development

Antes do paralelo:

```text
API contract
event contract
DTO
error contract
```

aprovados.

---

# 138. Vertical Slice

Preferir entregar:

```text
UI
API
Domain
Persistence
Events
Audit
Tests
```

de um fluxo pequeno inteiro.

---

# 139. Primeiros Vertical Slices Recomendados

### Slice A

```text
Login
→ Product List
→ Product Detail
```

### Slice B

```text
Customer
→ Quote
→ Price Resolve
```

### Slice C

```text
Order
→ Reservation
```

### Slice D

```text
Marketplace Order
→ Internal Order
```

---

# 140. Ambientes de Aceitação

Homologação deve possuir:

- dados mascarados;
- integrações sandbox;
- cenários automatizados;
- contas técnicas.

---

# 141. Test Data Management

M23 poderá auxiliar:

```text
seed datasets
masked datasets
reference snapshots
```

---

# 142. Release Readiness Dashboard

Sugestão:

```text
Module
Development %
Tests %
Migration %
UAT %
Training %
Infra %
Blockers
Go-Live Status
```

---

# 143. Status de Readiness

```text
NOT_STARTED
IN_PROGRESS
AT_RISK
READY
BLOCKED
LIVE
STABILIZED
```

---

# 144. Dependency Gate

Um módulo só entra em `READY` se dependências críticas estiverem em `READY` ou `LIVE`.

---

# 145. Roadmap Indicativo por Macro Fase

```text
Phase A
Foundation

Phase B
Master Data

Phase C
Commercial + Inventory + Orders

Phase D
Logistics + Procurement

Phase E
Manufacturing + Quality + Regulatory

Phase F
Fiscal + Finance

Phase G
Cost + Accounting + HR

Phase H
Analytics + Governance Optimization
```

---

# 146. Estimativa Temporal

Cronograma definitivo dependerá de:

```text
team size
developer seniority
availability of key users
legacy quality
external integrations
infrastructure
```

A Etapa 10 transforma estas ondas em backlog executável.

---

# 147. Sequência Recomendada de Autoridade Produtiva

```text
M1 Security
↓
M2 Product
↓
M14 Customer
↓
M5 Inventory
↓
M15/M4 Commercial & Orders
↓
M3 Marketplace
↓
M10 WMS
↓
M6 Procurement
↓
M7 Production
↓
M17 Quality
↓
M18 Regulatory
↓
M11 Fiscal
↓
M12 Finance
↓
M8 Costing
↓
M13 Accounting
↓
M20 HR
↓
M21 Analytics
```

M22 e M23 entram progressivamente.

---

# 148. Ordem não é Totalmente Linear

Alguns módulos precisam ser desenvolvidos antes de sua autoridade produtiva.

---

# 149. Legacy Retirement

Cada funcionalidade aposentada terá:

```text
retirement_owner
retirement_date
read_only_until
data_retention_policy
```

---

# 150. Legacy Read-Only Period

Após cutover, legado pode permanecer `READ ONLY` por período definido.

---

# 151. Desligamento do Legado

Somente quando:

```text
critical data migrated
legal retention addressed
users no longer depend
audit complete
backup preserved
```

---

# 152. Go-Live por Empresa

Big Star e Forma Kids podem migrar em momentos diferentes.

---

# 153. Go-Live por Filial

Possível, desde que não crie múltiplas autoridades para o mesmo fluxo físico.

---

# 154. Go-Live por Canal

Marketplace Hub é forte candidato a ativação gradual por conta/canal.

---

# 155. Go-Live por Família de Produto

Produção/regulatório podem usar esta estratégia.

---

# 156. Go-Live por Processo

Exemplo financeiro:

```text
AR
↓
Bank Reconciliation
↓
AP
↓
Payment Transmission
```

---

# 157. Go-Live Financeiro Conservador

Separar estreia do subledger da transmissão bancária automática.

---

# 158. Go-Live Fiscal Conservador

```text
homologation
↓
limited series / operation
↓
full production
```

---

# 159. Go-Live Industrial Conservador

```text
planning
↓
shop floor pilot
↓
full production
```

---

# 160. Go-Live Analytics

Pode ocorrer cedo para fontes já confiáveis.

---

# 161. Data Confidence Badge

Durante transição:

```text
SOURCE:
LEGACY
NEW ERP
MIXED
```

quando útil.

---

# 162. Exit from Hypercare

Uma fase sai de hypercare quando:

```text
no SEV1
no unresolved critical reconciliation
error rate stable
support volume normalized
key users approve
```

---

# 163. Stabilization

```text
LIVE
→ STABILIZED
```

---

# 164. Evitar Muitas Viradas Críticas Simultâneas

Evitar go-live simultâneo de múltiplos domínios de alto risco.

---

# 165. Change Saturation

Roadmap deve considerar capacidade humana de absorção da mudança.

---

# 166. Business Process Owners

| Processo | Owner |
|---|---|
| Order-to-Cash | Comercial + Financeiro |
| Procure-to-Pay | Compras + Financeiro |
| Plan-to-Produce | PCP + Produção |
| Quality | Qualidade |
| Record-to-Report | Contabilidade/Controladoria |
| Hire-to-Pay | RH |

---

# 167. Technical Owners

```text
Module Owner
Integration Owner
Data Migration Owner
Infrastructure Owner
```

---

# 168. Dependency Risk Register

Cada onda registra:

```text
dependency
risk
probability
impact
mitigation
owner
```

---

# 169. Riscos Principais do Programa

## R1 — Qualidade do legado

Mitigação:

```text
profiling
M23
data cleansing
rehearsals
```

## R2 — Escopo excessivo

Mitigação:

```text
waves
vertical slices
strict MVP
```

## R3 — Dependência de key users

Mitigação:

```text
formal availability
backup key user
```

## R4 — Integrações externas

Mitigação:

```text
adapter
sandbox
retry
shadow mode
```

## R5 — Fiscal/Financeiro

Mitigação:

```text
parallel validation
reconciliation
controlled rollout
```

---

# 170. Risco — Reescrever Legado sem Mudança de Processo

Novo ERP não deve simplesmente copiar telas antigas, nem reinventar processo sem validação do negócio.

---

# 171. Scope Control

Nova necessidade deve ser classificada como:

```text
Bug?
Missing agreed requirement?
Enhancement?
Architecture change?
```

---

# 172. Architecture Change

Mudanças que violem baseline M1–M23 ou Etapas 1–8 passam por:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 173. MVP Real

O MVP corporativo é o primeiro conjunto capaz de operar uma cadeia de valor real com segurança.

---

# 174. MVP-1 Recomendado

```text
M1
M2
M14 core
M5
M9
M15
M4
M22 core
M23 core
```

Resultado:

```text
B2B Quote
→ Order
→ Inventory Reservation
```

---

# 175. MVP-2

Adicionar:

```text
M3
M10
M11 outbound
```

Resultado:

```text
Marketplace / B2B
→ Order
→ Pick
→ Pack
→ Invoice
→ Dispatch
```

---

# 176. MVP-3

Adicionar:

```text
M6
M17 incoming
M12 AP bridge
```

Resultado:

```text
Procure-to-Receive
```

---

# 177. MVP-4

Adicionar:

```text
M7
M17 full
M18
M19 subset
```

Resultado:

```text
Plan-to-Produce
```

---

# 178. MVP-5

Adicionar:

```text
M12 full
M16
M8
M13
```

Resultado:

```text
complete commercial/financial/accounting cycle
```

---

# 179. MVP-6

Adicionar:

```text
M20 full
M21 full
M22 advanced
M23 advanced
M19 full
```

Resultado:

```text
corporate ERP maturity
```

---

# 180. Critérios de Aceite da Etapa 9

1. foundation-first definida.
2. W0 existente.
3. W1–W7 definidas.
4. ordem não segue número do módulo.
5. M1 entra cedo.
6. M2 entra cedo.
7. M23 migration core entra cedo.
8. M22 workflow core entra antes de processos com aprovação.
9. M5 precede reserva/picking.
10. M9 precede M15.
11. custo transitório possui estratégia.
12. crédito transitório possui adapter.
13. marketplace usa rollout progressivo.
14. shadow mode previsto.
15. WMS possui piloto.
16. estoque possui cutover de autoridade único.
17. incoming quality precede material crítico.
18. M7 depende de BOM/Routing/Production Version.
19. M18 precede produção regulada.
20. M17 precede liberação de PA.
21. produção possui piloto por família/linha.
22. WIP migration possui política.
23. fiscal possui homologação.
24. numbering/series possui estratégia.
25. financeiro possui opening balances.
26. títulos históricos não são todos transações vivas.
27. bank reconciliation é gate.
28. pagamento possui rollout conservador.
29. commission shadow run existe.
30. accounting shadow run existe.
31. accounting parallel close previsto.
32. RH time pilot previsto.
33. M21 cresce incrementalmente.
34. coexistência com legado possui estados.
35. dual write evitado.
36. LegacyAdapter possui sunset.
37. migration categories respeitadas.
38. delta migration prevista.
39. reconciliation report existe.
40. freeze window pode existir.
41. cutover runbook existe.
42. hypercare existe.
43. Go/No-Go formal existe.
44. functional readiness existe.
45. data readiness existe.
46. technical readiness existe.
47. integration readiness existe.
48. security readiness existe.
49. support readiness existe.
50. go-live blocker produz NO-GO.
51. rollback criteria definidos.
52. technical rollback e business fallback separados.
53. fiscal contingency existe.
54. finance contingency existe.
55. inventory contingency existe.
56. training role/process based.
57. key users formalizados.
58. UAT usa cenários reais.
59. golden scenarios existem.
60. regression suite existe.
61. release gates existem.
62. dívida técnica é governada.
63. invariantes críticas não são sacrificadas pelo MVP.
64. contract-first permite desenvolvimento paralelo.
65. vertical slices são preferidos.
66. readiness dashboard existe.
67. legacy retirement planejado.
68. legacy read-only period possível.
69. go-live por empresa/filial/canal/família/processo suportado.
70. finance rollout conservador.
71. fiscal rollout conservador.
72. industrial rollout conservador.
73. analytics pode entrar incrementalmente.
74. exit hypercare definido.
75. stabilization definida.
76. mudanças críticas simultâneas evitadas.
77. business owners definidos.
78. technical owners definidos.
79. dependency risk register existe.
80. Architecture Change Request preservado.
81. MVPs progressivos definidos.
82. toda onda possui critério de saída.
83. nenhuma autoridade crítica possui dual write.
84. migração usa M23.
85. roadmap respeita Etapas 1–8.

---

# 181. Decisões Consolidadas

## A. Não desenvolver módulos em ordem numérica

## B. Foundation vem antes da velocidade funcional

## C. M22 e M23 entram progressivamente desde cedo

## D. M5 é pré-requisito de operações físicas

## E. M18 não pode ser pós-produção para itens regulados

## F. Shadow Mode reduz risco

## G. Dual Write será evitado

## H. A autoridade muda por domínio, não por big bang

## I. Migração será incremental

## J. Saldos críticos exigem reconciliação

## K. Go-live exige readiness multidimensional

## L. NO-GO é uma decisão válida

## M. Rollback técnico e fallback operacional são diferentes

## N. Hypercare faz parte da entrega

## O. Legado será aposentado de forma controlada

## P. ERP crescerá por vertical slices

## Q. MVP não sacrifica integridade física, fiscal, financeira ou regulatória

---

# 182. Roadmap Visual Consolidado

```text
W0
ENGINEERING FOUNDATION
        │
        ▼
W1
CORPORATE + MASTER DATA
M1 M2 M14-core M20-org M23-core
        │
        ▼
W2
COMMERCIAL + ORDER CORE
M5 M9 M15 M4 M3 M22-core
        │
        ▼
W3
LOGISTICS + PROCUREMENT
M10 M6 M17-incoming M11-inbound-subset
        │
        ▼
W4
MANUFACTURING
M7 M17-full M18 M19 M8-foundation
        │
        ▼
W5
FISCAL + FINANCE
M11-full M12-full M16
        │
        ▼
W6
COST + ACCOUNTING + HR
M8-full M13 M20-full
        │
        ▼
W7
ANALYTICS + GOVERNANCE MATURITY
M21 M22-advanced M23-advanced
```

---

# 183. Status Formal da Etapa 9

A **Etapa 9 — Roadmap de Implementação, Fases, Dependências e Critérios de Go-Live** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- ordem de construção;
- ondas de implementação;
- MVPs progressivos;
- dependências críticas;
- coexistência com legado;
- migração;
- shadow mode;
- cutover;
- pilotagem;
- hypercare;
- readiness;
- go/no-go;
- rollback/fallback;
- retirement do legado.

Alterações incompatíveis devem seguir:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 184. Próxima Etapa

```text
ETAPA 10
BACKLOG TÉCNICO MESTRE, ORDEM EXECUTIVA DE DESENVOLVIMENTO E PLANO DE INÍCIO DA CODIFICAÇÃO
```

A Etapa 10 transformará a arquitetura consolidada em backlog executável, com:

- epics;
- capabilities;
- features;
- stories técnicas;
- stories funcionais;
- dependências;
- ordem executiva;
- critérios de pronto;
- primeiros vertical slices;
- estrutura de repositório;
- primeiros pacotes;
- migrations iniciais;
- primeira sprint técnica;
- plano de início real da codificação.

---

**Fim da Etapa 9 — Roadmap de Implementação, Fases, Dependências e Critérios de Go-Live**
