# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 4 — Matriz Completa de Integrações Módulo × Módulo

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Matriz de integrações entre os módulos M1–M23  
**Objetivo:** Consolidar as dependências e contratos entre os 23 Bounded Contexts, classificando cada relação por tipo de integração, direção, ownership, consistência, criticidade e estratégia de falha.

---

# 1. Objetivo da Etapa 4

A Etapa 4 responde, para cada par de módulos:

```text
Quem chama quem?
Quem publica?
Quem consome?
A integração é síncrona ou assíncrona?
Existe read model?
Quem é o dono do fato?
Qual consistência é exigida?
O que acontece se o outro módulo estiver indisponível?
```

A matriz impede dependências informais como:

```text
Módulo A
→ consulta diretamente a tabela do módulo B
```

Toda dependência direta entre domínios deve estar formalmente documentada.

---

# 2. Tipos Oficiais de Integração

| Código | Tipo | Significado |
|---|---|---|
| `S` | `SYNC` | Contrato síncrono de aplicação/query/gate/command |
| `E` | `ASYNC EVENT` | Fato publicado pelo módulo origem |
| `R` | `ASYNC REQUEST` | Solicitação assíncrona para outro domínio |
| `RM` | `READ MODEL` | Destino mantém projeção local derivada da origem |
| `·` | `NONE` | Nenhuma integração direta aprovada |
| `—` | Self | Mesmo módulo |

Combinações são permitidas.

Exemplo:

```text
S+E
```

significa que existem contratos síncronos e eventos na relação.

---

# 3. Direção da Matriz

A leitura é sempre:

```text
LINHA
→
COLUNA
```

Exemplo:

```text
M15 → M9 = S
```

significa:

```text
M15 chama M9
```

para resolução de preço.

Já:

```text
M9 → M15 = S+E
```

significa que M9 fornece contrato síncrono e também publica eventos consumidos pelo M15.

---

# 4. Módulos

| Código | Módulo |
|---|---|
| M1 | Administração / Segurança |
| M2 | Product Master |
| M3 | Marketplace Hub |
| M4 | Orders / Fulfillment |
| M5 | Inventory |
| M6 | Procurement |
| M7 | Manufacturing |
| M8 | Industrial Costing |
| M9 | Pricing |
| M10 | WMS / Expedition |
| M11 | Fiscal |
| M12 | Finance |
| M13 | Accounting |
| M14 | Customer / CRM |
| M15 | Comercial B2B |
| M16 | Commissions |
| M17 | Quality |
| M18 | Regulatory / INMETRO |
| M19 | Assets / Maintenance |
| M20 | HR |
| M21 | Analytics |
| M22 | Workflow |
| M23 | Data Governance |

---

# 5. Matriz 23 × 23 — Bloco 1
## Destinos M1–M8

| Origem → Destino | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|---|---|---|---|---|---|---|---|---|
| M1 | — | · | · | · | · | · | · | · |
| M2 | · | — | E+RM | E | E | E | E | E |
| M3 | · | · | — | E | · | · | · | · |
| M4 | · | · | · | — | S+E | · | · | · |
| M5 | · | · | E+RM | E | — | E | E | E |
| M6 | · | S | · | · | S+E | — | E | E |
| M7 | · | S | · | · | S+E | S | — | E |
| M8 | · | · | · | · | · | · | · | — |
| M9 | · | · | E+RM | S+E | · | · | · | · |
| M10 | · | · | E | E | S+E | · | · | · |
| M11 | · | · | E | E | · | E | · | · |
| M12 | · | · | · | E | · | E | · | · |
| M13 | · | · | · | · | · | · | · | · |
| M14 | · | · | · | E | · | · | · | · |
| M15 | · | · | · | S+E | S | · | S | · |
| M16 | · | · | · | · | · | · | · | · |
| M17 | · | · | · | E | S+E | E | E+R | · |
| M18 | · | E | E | E+RM | E | · | E+RM | · |
| M19 | · | · | · | · | S+E+R | R | E | E |
| M20 | E+R | · | · | · | · | · | E+RM | E |
| M21 | · | · | · | · | · | · | · | · |
| M22 | S | · | · | · | · | E | · | · |
| M23 | S | S | S | S | S | S | S | S |

---

# 6. Matriz 23 × 23 — Bloco 2
## Destinos M9–M16

| Origem → Destino | M9 | M10 | M11 | M12 | M13 | M14 | M15 | M16 |
|---|---|---|---|---|---|---|---|---|
| M1 | · | · | E | · | · | · | · | · |
| M2 | E | E+RM | E | · | · | · | E | · |
| M3 | E | E | E | · | · | · | · | · |
| M4 | · | E | E+R | E+R | · | S | E | · |
| M5 | · | E | · | · | · | · | E | · |
| M6 | · | · | S+E | E+R | · | · | · | · |
| M7 | · | · | · | · | · | · | E | · |
| M8 | E | · | · | · | E | · | · | · |
| M9 | — | · | S | · | · | S | S+E | S |
| M10 | · | — | E | · | · | · | · | · |
| M11 | E | · | — | E | E | · | · | E |
| M12 | · | · | · | — | E | E+RM | E | E |
| M13 | · | · | · | · | — | · | · | · |
| M14 | E | · | · | E | · | — | E+RM | · |
| M15 | S | · | · | S+E | · | S | — | S+E |
| M16 | E | · | · | E+R | E | · | · | — |
| M17 | · | E | · | · | · | · | · | · |
| M18 | · | E+RM | E+RM | · | · | · | E | · |
| M19 | · | · | · | · | E | · | · | · |
| M20 | · | · | · | E+R | E | · | · | · |
| M21 | · | · | · | · | · | · | · | · |
| M22 | E | · | E | E | E | · | E | E |
| M23 | S | S | S | S | S | S | S | S |

---

# 7. Matriz 23 × 23 — Bloco 3
## Destinos M17–M23

| Origem → Destino | M17 | M18 | M19 | M20 | M21 | M22 | M23 |
|---|---|---|---|---|---|---|---|
| M1 | · | · | · | E | E+RM | E+RM | E+RM |
| M2 | E | E | · | · | E+RM | · | E |
| M3 | · | · | · | · | E+RM | · | · |
| M4 | E | S+E | · | · | E+RM | · | · |
| M5 | E | E | E | · | E+RM | · | E |
| M6 | E+R | · | · | · | E+RM | R | E |
| M7 | E | S+E | S+E | S+E | E+RM | · | · |
| M8 | · | · | · | · | E+RM | · | E |
| M9 | · | · | · | · | E+RM | R | E |
| M10 | S+E | S+E | · | · | E+RM | · | · |
| M11 | · | S | · | · | E+RM | R | E |
| M12 | · | · | · | · | E+RM | R | E |
| M13 | · | · | · | · | E+RM | R | E |
| M14 | · | · | · | · | E+RM | · | E |
| M15 | · | S | · | · | E+RM | R | · |
| M16 | · | · | · | · | E+RM | R | · |
| M17 | — | E+R | · | · | E+RM | R | E |
| M18 | E+R | — | · | · | E+RM | R | E |
| M19 | · | · | — | S | E+RM | R | E |
| M20 | · | · | · | — | E+RM | E+R | E |
| M21 | · | · | · | · | — | E+R | E |
| M22 | E | E | E | S+E | E+RM | — | E |
| M23 | S | S | S | S | S+E+RM | S+R | — |

---

# 8. Regra Especial do M1

Autenticação e autorização são transversais a toda chamada API.

Não marcamos:

```text
M2 → M1
M3 → M1
M4 → M1
...
```

como `SYNC` em cada célula, pois isso criaria a falsa impressão de dependência funcional de negócio.

Fluxo:

```text
HTTP Request
↓
Authentication
↓
Authorization / RBAC
↓
Application Service
```

M1 continua sendo autoridade de segurança.

A relação explícita:

```text
M22 → M1
```

é relevante para:

- step-up authentication;
- MFA;
- verificação de identidade;
- validade de usuário/aprovador.

---

# 9. Regra Especial do M21

M21 funciona como consumidor analítico.

Relações:

```text
Mx → M21 = E+RM
```

significam:

```text
Domain Event
↓
Analytics Pipeline
↓
Analytical Read Model
```

Nunca:

```text
M21
→ UPDATE
→ módulo operacional
```

---

# 10. Regra Especial do M22

M22 é transversal, mas não efetiva o fato de negócio.

Fluxo:

```text
M6
→ PurchaseApprovalRequested
→ M22

M22
→ WorkflowApproved
→ M6

M6
→ PurchaseOrderApproved
```

Portanto:

```text
WorkflowApproved
≠
BusinessTransactionApproved
```

até o módulo de origem efetivar a decisão.

---

# 11. Regra Especial do M23

As relações:

```text
M23 → domínio = S
```

não significam acesso direto ao banco.

Significam contratos formais como:

```text
BulkDataAdapter
ImportValidationProvider
ImportCommitProvider
ExportProjectionProvider
DataGovernanceProvider
```

Exemplo:

```text
M23
→ ProductBulkDataAdapter
→ M2
```

Nunca:

```text
M23
→ UPDATE product.product
```

---

# 12. Pacote Corporativo de Contratos

Estrutura sugerida:

```text
contracts/
├── events/
│   ├── v1/
│   └── v2/
├── requests/
│   ├── v1/
│   └── v2/
└── sync/
    ├── inventory/
    ├── pricing/
    ├── fiscal/
    ├── finance/
    ├── regulatory/
    └── workforce/
```

Regra:

```text
M4
pode importar:
contracts.inventory

M4
não pode importar:
modules.inventory.infrastructure.models
```

---

# 13. Proibição de Compartilhamento de ORM

É proibido:

```python
from modules.inventory.models import InventoryBalance
```

dentro do M10.

Correto:

```python
from contracts.inventory import InventoryReservationPort
```

ou evento versionado.

---

# 14. Cadeia Crítica Comercial B2B

## M15 → M14

```text
S
```

Contrato:

```text
CustomerOperationalStatusService
```

Finalidade:

- cliente ativo;
- status comercial;
- customer group;
- condições operacionais.

## M15 → M9

```text
S
```

Contrato:

```text
PricingResolutionService
```

Resposta congelável:

```text
pricing_snapshot_id
price
minimum_margin
pricing_version
```

## M15 → M12

```text
S
```

Contrato:

```text
CreditDecisionService
```

Retorno:

```text
APPROVED
WARNING
BLOCKED
APPROVAL_REQUIRED
```

## M15 → M5

```text
S
```

Contrato:

```text
InventoryAvailabilityQueryService
```

Retorna ATP.

## M15 → M7

```text
S
```

Retorna Projected Availability.

Regra:

```text
ATP
≠
Projected Availability
```

## M15 → M18

```text
S
```

Contrato:

```text
RegulatorySalesGate
```

## M15 → M22

```text
R
```

Usado quando houver:

- desconto fora de alçada;
- prazo excepcional;
- política comercial;
- crédito excepcional.

## M15 → M4

```text
S
```

Na conversão aprovada do orçamento.

M4 cria o Order.

---

# 15. Cadeia Marketplace

## M3 → M4

```text
E
```

Evento:

```text
MarketplaceOrderApproved
```

M4 cria pedido interno de forma idempotente.

Chave:

```text
marketplace_account_id
+
external_order_id
```

## M5 → M3

```text
E+RM
```

M3 mantém estado desejado de estoque para publicação.

Fonte:

```text
InventoryBalanceChanged
```

## M9 → M3

```text
E+RM
```

Preço aprovado:

```text
PriceActivated
```

M3 é responsável somente pela publicação.

## M11 → M3

```text
E
```

Após:

```text
InvoiceAuthorized
```

M3 envia dados fiscais ao canal.

## M3 → M10

```text
E
```

Exemplo:

```text
MarketplaceLabelAvailable
```

---

# 16. Cadeia Order / Inventory

## M4 → M5

Principal integração:

```text
S
```

via:

```text
InventoryReservationService
```

M4 nunca grava saldo.

## M5 → M4

```text
E
```

Eventos:

```text
InventoryReservationCreated
InventoryReservationReleased
InventoryReservationExpired
InventoryShortageDetected
```

---

# 17. Cadeia Fulfillment / WMS

## M4 → M10

```text
E
```

Principal evento:

```text
FulfillmentCreated
```

## M10 → M4

```text
E
```

Exemplos:

```text
PickingCompleted
PackingCompleted
ShipmentDispatched
```

## M10 → M5

```text
S
```

Para:

- reallocation;
- picking confirmation;
- packaging consumption;
- dispatch.

M10 jamais altera o Ledger diretamente.

---

# 18. Billing e Financeiro
## Regra contra Dupla Criação

O fato:

```text
InvoiceAuthorized
```

pode ser consumido pelo M12 para referência e conciliação.

Mas não será sozinho o comando que cria o título financeiro.

Criação oficial:

```text
M4
→ ReceivableRequested
→ M12
```

após M4 reconhecer a autorização fiscal correspondente.

Portanto:

```text
InvoiceAuthorized
→ fiscal/accounting/reference fact

ReceivableRequested
→ financial creation request
```

Isso evita criação duplicada de contas a receber.

---

# 19. Compras e Contas a Pagar
## Mesma Proteção contra Dupla Criação

M11 publica:

```text
InboundFiscalDocumentValidated
```

M12 pode consumir esse fato para referência.

O título a pagar nasce oficialmente de:

```text
M6
→ PayableRequested
→ M12
```

após:

```text
PO
+
NF
+
Physical Receipt
+
3-Way Match
+
Financial Gate
```

Regra:

```text
InboundFiscalDocumentValidated
≠
automatic payable creation
```

---

# 20. Cadeia Fiscal / Accounting

## M11 → M13

```text
E
```

Exemplos:

```text
InvoiceAuthorized
FiscalDocumentCancelled
TaxRuleActivated
```

M13 aplica:

```text
Accounting Rules Engine
```

## M10 → M13

```text
E
```

Evento:

```text
ShipmentDispatched
```

pode ser gatilho oficial de:

```text
CMV
+
inventory accounting
```

conforme regra contábil.

---

# 21. Cadeia Finance / Accounting

## M12 → M13

```text
E
```

Exemplos:

```text
ReceivableCreated
ReceivableSettled
PayableCreated
PayableSettled
MarketplaceSettlementConfirmed
ReceivableAnticipated
```

M12 jamais lança débito/crédito diretamente.

---

# 22. Regra contra Dupla Contabilização

M13 classifica eventos como:

```text
RECOGNITION
SETTLEMENT
REVERSAL
ADJUSTMENT
INFORMATIONAL
```

Exemplo:

```text
InvoiceAuthorized
→ RECOGNITION

ReceivableCreated
→ INFORMATIONAL ou SUBLEDGER_LINK

ReceivableSettled
→ SETTLEMENT
```

---

# 23. Cadeia M6 / M17 / M5

## M6 → M17

```text
R
```

```text
IncomingInspectionRequested
```

## M17 → M5

```text
S+E
```

M17 decide:

```text
APPROVE
PARTIAL_ACCEPTANCE
REJECT
QUARANTINE
```

M5 executa o estado físico.

## M17 → M6

```text
E
```

Resultado retorna ao recebimento.

---

# 24. Cadeia Produção / Estoque

## M7 → M5

```text
S
```

Para:

- issue;
- backflush;
- receipt;
- recovery;
- return.

M5 registra o fato físico.

## M5 → M7

```text
E
```

Para:

- disponibilidade;
- shortage;
- lot state;
- reservation changes.

---

# 25. Cadeia Produção / Custos

## M7 → M8

```text
E
```

Fatos:

```text
MaterialIssuedToProduction
ProductionYieldReported
ScrapRegistered
ReworkRegistered
ProductionOrderClosed
```

M7 informa:

```text
kg
units
hours
cycles
```

M8 adiciona:

```text
R$
```

---

# 26. Cadeia Produção / Regulatório

## M7 → M18

```text
S+E
```

Síncrono:

```text
RegulatoryProductionGate
```

Eventos:

```text
ProductionOrderReleased
FinishedGoodsReceived
```

## M18 → M7

```text
E+RM
```

Eventos críticos:

```text
RegulatoryProductBlocked
RegulatoryProductReleased
RegulatoryCertificateExpired
```

---

# 27. Cadeia Produção / Manutenção

## M7 → M19

```text
S+E
```

Consulta:

```text
MaintenanceAssetAvailabilityService
```

Eventos produtivos também atualizam contadores de ciclos/horas.

## M19 → M7

```text
E
```

```text
MaintenanceAssetUnavailable
MaintenanceAssetReleased
```

---

# 28. Cadeia Produção / RH

## M7 → M20

```text
S
```

via:

```text
WorkforceAvailabilityService
```

## M20 → M7

```text
E+RM
```

Eventos:

```text
WorkforceMemberAvailable
WorkforceMemberUnavailable
VacationScheduled
EmployeeAbsenceStarted
EmployeeTerminated
```

---

# 29. Cadeia RH / Segurança

## M20 → M1

```text
R+E
```

Admissão:

```text
UserProvisioningRequested
```

Desligamento:

```text
UserAccessRevocationRequested
```

## M1 → M20

```text
E
```

Confirmações e mudanças corporativas.

---

# 30. Cadeia RH / Financeiro

## M20 → M12

```text
R
```

```text
PayrollPayableRequested
TaxPayableRequested
BenefitPayableRequested
```

M12 cria as obrigações.

---

# 31. Cadeia RH / Costing

## M20 → M8

```text
E
```

Principal evento:

```text
LoadedLaborRateCalculated
```

M8 não lê salário individual.

---

# 32. Cadeia Comissões

## M15 → M16

```text
E
```

Na conversão:

```text
SalesOrderConverted
```

M16 congela:

- beneficiários;
- regra;
- split;
- portfolio assignment.

## M11 → M16

```text
E
```

`InvoiceAuthorized` gera accrual.

## M12 → M16

```text
E
```

```text
ReceivablePartiallySettled
ReceivableSettled
```

gera earning proporcional.

## M16 → M12

```text
R
```

```text
CommissionPayableRequested
```

---

# 33. Cadeia Regulatory / Quality

## M17 → M18

```text
R+E
```

Exemplo:

```text
RegulatoryAssessmentRequested
```

## M18 → M17

```text
R+E
```

Exemplo:

```text
RegulatoryRecallRequested
```

M17 executa o engine operacional de recall.

---

# 34. Cadeia Regulatory / Fiscal

## M11 → M18

```text
S
```

Antes do faturamento crítico:

```text
RegulatoryBillingGate
```

## M18 → M11

```text
E+RM
```

Status:

```text
billing_allowed
```

e bloqueios emergenciais.

---

# 35. Cadeia Regulatory / WMS

## M10 → M18

```text
S
```

Antes do despacho:

```text
RegulatoryShippingGate
```

## M18 → M10

```text
E+RM
```

para bloqueios assíncronos defensivos.

---

# 36. Cadeia Quality / WMS

## M10 → M17

```text
S
```

Quando necessário:

```text
QualityEligibilityGate
```

## M17 → M10

```text
E
```

Eventos de:

- hold;
- release;
- recall;
- lot rejection.

---

# 37. Cadeia Assets / Accounting

## M19 → M13

```text
E
```

Exemplos:

```text
AssetCapitalized
AssetTransferred
AssetDisposed
AssetDepreciationCalculated
MaintenanceActualCostCalculated
```

---

# 38. Cadeia Maintenance / MRO

## M19 → M5

```text
S/R
```

Para:

- reserva;
- consumo;
- devolução MRO.

## M19 → M6

```text
R
```

Quando houver necessidade de reposição:

```text
PurchaseSupplyRequested
```

ou contrato equivalente.

---

# 39. M22 → M20
## Resolução Organizacional

M22 consulta M20 de forma síncrona para:

```text
DIRECT_MANAGER
DEPARTMENT_MANAGER
COST_CENTER_MANAGER
```

A hierarquia é resolvida no momento de ativação da etapa e congelada.

---

# 40. Read Models Permitidos

Read Model não cria nova autoridade.

Padrão:

```text
source_id
source_version
refreshed_at
payload necessário
```

| Fonte | Destino | Read Model |
|---|---|---|
| M2 | M3 | Produto para listing |
| M2 | M10 | Barcode/packaging operacional |
| M5 | M3 | Estoque publicável |
| M9 | M3 | Preço desejado |
| M12 | M14 | Situação financeira resumida |
| M14 | M15 | Customer 360 comercial |
| M18 | M4 | Regulatory status |
| M18 | M7 | Production regulatory status |
| M18 | M10 | Shipping eligibility |
| M18 | M11 | Billing eligibility |
| M20 | M7 | Workforce availability |
| M1–M23 | M21 | Facts/dimensions analíticos |

---

# 41. Freshness de Read Model

Todo read model possui:

```text
source_version
refreshed_at
```

Quando stale data puder causar risco grave:

```text
read model stale
→ não assumir liberação
```

Exemplo:

```text
Regulatory status stale
→ FAIL CLOSED
```

---

# 42. Subtipos de Dependência Síncrona

Embora a matriz use `S`, internamente haverá:

```text
SYNC_QUERY
SYNC_GATE
SYNC_COMMAND
```

## `SYNC_QUERY`

Não altera estado.

Exemplo:

```text
M15 → M5
ATP query
```

## `SYNC_GATE`

Retorna:

```text
allowed / blocked / conditional
```

Exemplo:

```text
RegulatoryShippingGate
```

## `SYNC_COMMAND`

Solicita alteração ao domínio dono.

Exemplo:

```text
M10 → M5
confirm dispatch inventory movement
```

---

# 43. Atomicidade Cross-Domain no Monólito Modular

Como os módulos inicialmente compartilham o mesmo PostgreSQL, algumas invariantes críticas poderão participar de transação local coordenada.

Candidatos:

```text
Order reservation
Inventory movement at dispatch
Production material issue
Physical goods receipt
```

Mesmo nesses casos:

```text
caller
≠
owner das tabelas do callee
```

O acesso continua via Application Service.

---

# 44. Preparação para Futura Extração em Microserviço

Toda integração síncrona deverá possuir abstração que permita no futuro:

```text
local call
→ HTTP/gRPC
```

sem conhecimento de SQL ou ORM interno.

Proibido:

```text
cross-domain repository injection
```

---

# 45. Ciclos de Negócio x Ciclos de Código

Ciclos de negócio podem existir.

Exemplo:

```text
M4 → M5
M5 → M4
```

Mas imports circulares de implementação não são permitidos.

Solução:

```text
shared contracts
+
ports/interfaces
+
event contracts
```

---

# 46. Regra de Indisponibilidade

## `SYNC_QUERY`

Se indisponível:

- pode usar read model se política permitir;
- caso contrário, indisponibilidade explícita.

## `SYNC_GATE`

Para riscos críticos:

```text
FAIL CLOSED
```

## `SYNC_COMMAND`

Não assumir sucesso.

Estados típicos:

```text
PENDING
ON_HOLD
ERROR_RETRYABLE
```

---

# 47. Regra de `ASYNC EVENT`

Falha do consumidor:

```text
retry
→ DLQ
```

Não desfaz o fato já confirmado no produtor.

---

# 48. Regra de `ASYNC REQUEST`

O solicitante deve ter estado explícito.

Exemplos:

```text
PENDING_APPROVAL_REQUEST
WAITING_INSPECTION
PAYABLE_REQUEST_PENDING
```

Request enviado não significa sucesso.

---

# 49. Regra de Consistência

| Integração | Consistência |
|---|---|
| `SYNC_QUERY` | imediata |
| `SYNC_GATE` | imediata |
| `SYNC_COMMAND` | imediata ou atomic local quando explicitamente aprovado |
| `ASYNC EVENT` | eventual |
| `ASYNC REQUEST` | eventual com estado pendente |
| `READ MODEL` | eventual / versionada |

---

# 50. Integrações Explicitamente Proibidas

```text
M10 → tabela M5
M12 → tabela M13
M21 → qualquer tabela operacional para correção
M22 → tabela do módulo origem
M23 → tabela de domínio para bypass
Marketplace → master M2
M17 → inventory_balance
M8 → quantidade física M5
M7 → valor contábil M13
```

---

# 51. Single Effect Owner

Cada efeito possui um único gatilho autoritativo.

| Efeito | Gatilho autoritativo |
|---|---|
| Criar Receivable de venda | `ReceivableRequested` |
| Criar Payable de compra | `PayableRequested` |
| Mudar saldo físico | comando processado pelo M5 |
| Criar lançamento contábil | M13 Accounting Rules Engine |
| Criar commission accrual | `InvoiceAuthorized` |
| Criar commission earning | settlement M12 |
| Revogar usuário | M1 após revocation request |
| Aprovar transação | módulo origem após `WorkflowApproved` |
| Publicar preço marketplace | M3 após `PriceActivated` |
| Alterar Golden Record | módulo dono / M23 apenas orquestra |

---

# 52. Regra de Fan-Out

Um evento pode ter vários consumidores.

Exemplo:

```text
InvoiceAuthorized
├── M4
├── M3
├── M13
├── M16
├── M21
└── M12 informacional/reference
```

Cada consumidor possui:

```text
fila própria
Inbox própria
efeito próprio
```

---

# 53. Evitar Cadeia Síncrona Longa

Proibido:

```text
M15
→ M9
→ M11
→ M18
→ M17
→ M5
```

como cadeia síncrona indiscriminada.

Melhor:

```text
M15 orchestration
├── M9 Pricing
├── M12 Credit
├── M5 ATP
└── M18 Sales Gate
```

---

# 54. Orquestração x Coreografia

Modelo híbrido.

## Orquestração

Para fluxo iniciado por usuário e resposta imediata.

Exemplo:

```text
Convert Quote
```

M15 coordena:

```text
Pricing
Credit
Commercial Policy
Regulatory Gate
Order Creation
```

## Coreografia

Para fatos posteriores independentes.

Exemplo:

```text
InvoiceAuthorized
→ Accounting
→ Commission
→ Analytics
→ Marketplace
```

---

# 55. Nenhuma Saga Genérica no MVP

Não haverá um Saga Engine universal no MVP.

Processos longos usarão:

- state machines;
- eventos;
- requests;
- M22 para decisões humanas.

---

# 56. Integrações Externas

Integrações externas ficam atrás do módulo proprietário.

```text
Marketplace
→ M3
```

```text
SEFAZ / Fiscal Provider
→ M11
```

```text
Banco / PIX / CNAB
→ M12
```

```text
Folha externa
→ M20
```

Outros módulos não chamam esses provedores diretamente.

---

# 57. Anti-Corruption Layer

Cada integração externa possui adapter.

Exemplos:

```text
ShopeeAdapter
MercadoLivreAdapter
TikTokShopAdapter

FiscalProviderAdapter

BankAdapter
CnabAdapter
PixAdapter

PayrollAdapter
```

Payload externo não escapa diretamente para outros domínios.

---

# 58. Integração M23 com Domínios

Padrão:

```text
M23
   │
   ├── validate()
   ├── preview()
   ├── commit()
   └── export()
        │
        ▼
Domain Bulk Data Contract
```

O módulo de domínio continua aplicando:

```text
business invariants
authorization
version checking
```

---

# 59. Integração M23 → M22

Mudança material:

```text
DataChangeApprovalRequested
```

Depois de:

```text
WorkflowApproved
```

M23 revalida:

```text
change_fingerprint
```

antes do commit.

---

# 60. Integração M21 → M22

M21 detecta exceção.

```text
AnalyticsWorkflowRequested
```

M22 cria tarefa/workflow.

M21 nunca corrige diretamente a transação.

---

# 61. RLS e Integrações

Read models e sync queries devem receber contexto autorizado:

```text
user_id
company_scope
branch_scope
department_scope quando aplicável
```

Integração interna não pode burlar RLS.

Serviços de sistema podem usar:

```text
SYSTEM_ACTOR
```

explicitamente auditado.

---

# 62. Correlation ID

Toda cadeia cross-domain deve carregar:

```text
correlation_id
```

Exemplo:

```text
Quote
↓
Order
↓
Reservation
↓
Shipment
↓
Invoice
↓
Receivable
↓
Accounting
```

---

# 63. Causation ID

Eventos encadeados mantêm:

```text
causation_id
```

permitindo reconstruir causalidade.

---

# 64. Idempotência Cross-Domain

Cada consumidor considera:

```text
message_id
```

e, quando necessário:

```text
business idempotency key
```

Exemplo M4:

```text
account_id
+
external_order_id
```

---

# 65. Contract Tests

Toda integração terá teste de contrato.

Categorias:

```text
schema compatibility
required fields
version compatibility
idempotency
error mapping
timeout behavior
```

---

# 66. Testes de Integração Crítica

Fluxos obrigatórios:

```text
Quote → Order
Marketplace → Order
Order → Reservation
Picking → Dispatch
Billing → NF
NF → Receivable
Receipt → Inventory
Production → Inventory
Settlement → Commission
Employee Termination → Access Revocation
Regulatory Block → Production/Billing/Shipping
```

---

# 67. Chaos / Failure Tests

Cenários:

```text
RabbitMQ unavailable
M22 unavailable
Fiscal provider timeout
Marketplace API rate limit
Bank import failure
Analytics unavailable
M18 gate unavailable
```

Esperado:

```text
no silent success
no data corruption
no duplicate financial effect
```

---

# 68. Observabilidade da Matriz

Cada contrato deverá possuir:

```text
integration_name
source_module
target_module
mode

request_count
success_count
failure_count
latency

retry_count
dlq_count
```

---

# 69. Cockpit Técnico de Integrações

Deverá permitir visualizar:

```text
Integration Health

M3 → Marketplace
M11 → Fiscal Provider
M12 → Banks
M20 → Payroll

Cross-domain queues

DLQ
consumer lag
read model freshness
```

---

# 70. Dependency Ownership

Toda integração possui:

```text
Contract Owner
Consumer Owner
```

Exemplo:

```text
InventoryReservationService
Contract Owner = M5
Consumer = M4
```

---

# 71. Mudança de Contrato Síncrono

Breaking change:

```text
V1
→ V2
```

Contrato antigo permanece até consumidores migrarem.

---

# 72. Read Model Rebuild

Todo read model documenta:

```text
rebuild source
```

Exemplo:

```text
M3 stock projection
← M5 authoritative state/events
```

---

# 73. Read Model não Pode Virar Master

Exemplo:

```text
marketplace.product_name_cache
```

não pode se tornar origem de:

```text
M2 product.name
```

Golden Record continua M2.

---

# 74. Regras de Transação

Síncrono não significa automaticamente transação distribuída.

No Modular Monolith:

```text
same process
same PostgreSQL
```

permite atomicidade local quando necessário, preservando fronteiras de aplicação.

---

# 75. Integrações Críticas por Disponibilidade

## Classe A — Fail Closed

- Regulatory Gates;
- Quality Gates críticos;
- Credit hard validation;
- Security/step-up;
- Inventory physical commands.

## Classe B — Pending/Retry

- Workflow;
- Payable requests;
- Receivable requests;
- external publication;
- reporting.

## Classe C — Non-blocking

- Analytics;
- informational notifications;
- algumas projeções.

---

# 76. M21 Nunca Bloqueia Negócio

```text
M21 unavailable
→ sale/production/finance continue
```

Exceto funcionalidades puramente analíticas.

---

# 77. M22 Indisponível

Transação que exige aprovação fica:

```text
PENDING_APPROVAL_REQUEST
```

Nunca:

```text
auto-approved
```

---

# 78. M18 Indisponível em Gate Crítico

```text
FAIL CLOSED
```

Não produzir, faturar ou despachar sem confirmação regulatória obrigatória.

---

# 79. M5 Indisponível

Operações físicas críticas não continuam.

Exemplos:

```text
reserve
pick confirmation
production issue
dispatch
```

não podem assumir sucesso.

---

# 80. Consistência Externa

M3, M11 e M12 tratam sistemas externos como:

```text
eventually consistent
```

com:

- idempotency;
- reconciliation;
- retry;
- circuit breaker;
- cockpit.

---

# 81. Matriz de Autoridade

Integração bidirecional não significa autoridade compartilhada.

```text
M4 ↔ M5
```

mas:

```text
Order
→ M4

Physical Inventory
→ M5
```

Da mesma forma:

```text
M6 ↔ M17
Purchase Receipt → M6
Quality Decision → M17
```

---

# 82. Proibições Arquiteturais Consolidadas

```text
Cross-domain SQL
Cross-domain ORM import
Shared mutable domain entity
Direct table polling as primary integration
Generic CDC replacing domain event
Bypass do M22
Bypass do M23
BI writing operational data
External adapter called outside owner module
```

---

# 83. Critérios de Aceite da Etapa 4

1. Todos os M1–M23 presentes.
2. Toda relação direta classificada.
3. `NONE` explícito onde não há contrato.
4. Direção inequívoca.
5. SYNC separado de EVENT/REQUEST.
6. Read Models identificados.
7. Cross-domain SQL proibido.
8. Cross-domain ORM proibido.
9. Contratos compartilhados versionados.
10. M1 security overlay definido.
11. M21 analytics overlay definido.
12. M22 approval overlay definido.
13. M23 governance overlay definido.
14. Order/Inventory ownership preservado.
15. Fiscal/Finance ownership separado.
16. Finance/Accounting separado.
17. Quality/Inventory separado.
18. Regulatory/Operational gates definidos.
19. HR/Security separado.
20. Maintenance/Production separado.
21. Single Effect Owner definido.
22. Receivable não pode ser criado duas vezes.
23. Payable não pode ser criado duas vezes.
24. Accounting não pode reconhecer o mesmo fato duas vezes.
25. Commission accrual/earning distintos.
26. Read Model possui freshness/version.
27. Gate crítico fail-closed.
28. Async Request possui estado pendente.
29. Event failure não reverte fato do producer.
30. Contract tests obrigatórios.
31. Idempotência prevista.
32. Correlation/Causation obrigatórios.
33. Adapters externos com owner único.
34. Future extraction preservada.
35. M21 não bloqueia operação.
36. M22 indisponível não gera autoaprovação.
37. M23 não escreve diretamente em outro schema.
38. Consumers não assumem tabela interna do producer.
39. Integration ownership documentado.
40. Toda integração crítica possui estratégia de falha.

---

# 84. Decisões Arquiteturais Consolidadas

## A. A matriz é direcional

```text
A → B
≠
B → A
```

## B. Um par pode usar mais de um mecanismo

```text
S+E
```

é válido.

## C. Síncrono é reservado à necessidade imediata

Não conveniência.

## D. Assíncrono é preferido para propagação de fatos

Especialmente fan-out.

## E. Read Model é projeção

Nunca nova fonte de verdade.

## F. M1 continua transversal

Sem virar dependência funcional artificial.

## G. M21 é consumidor analítico

Nunca authority operacional.

## H. M22 governa decisão

Módulo origem governa o efeito.

## I. M23 governa bulk data

Módulo origem governa semântica.

## J. Sistemas externos só são acessados pelo módulo proprietário

## K. Ciclos de negócio são permitidos

Ciclos de código não.

## L. Nenhum módulo importa ORM de outro módulo

## M. Atomicidade cross-domain é excepcional e explícita

## N. Gates críticos falham fechados

## O. Efeitos financeiros e físicos têm gatilho único

---

# 85. Visão Consolidada

```text
                    ┌───────────────────┐
                    │      M1           │
                    │ Security Context  │
                    └─────────┬─────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────┐
 │                  BUSINESS DOMAINS                   │
 │                                                     │
 │ M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13          │
 │ M14 M15 M16 M17 M18 M19 M20                       │
 │                                                     │
 │   SYNC ──────────► immediate decision               │
 │   EVENT ─────────► facts                            │
 │   REQUEST ───────► async action                     │
 │   READ MODEL ────► local projection                 │
 └───────────────┬───────────────────┬─────────────────┘
                 │                   │
                 ▼                   ▼
         ┌──────────────┐     ┌──────────────┐
         │     M22      │     │     M23      │
         │  Workflow    │     │ Governance   │
         └──────┬───────┘     └──────┬───────┘
                │                    │
                └─────────┬──────────┘
                          ▼
                    ┌───────────┐
                    │    M21    │
                    │ Analytics │
                    └───────────┘
```

---

# 86. Status Formal da Etapa 4

A **Etapa 4 — Matriz Completa de Integrações Módulo × Módulo** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- contratos síncronos;
- eventos assíncronos;
- requests assíncronos;
- read models;
- ownership de integração;
- boundaries;
- contract tests;
- idempotência;
- estratégia de falha;
- preparação para futura extração de módulos.

Mudanças incompatíveis devem ser tratadas como:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 87. Próxima Etapa

```text
ETAPA 5
RBAC + SEGREGAÇÃO DE FUNÇÕES (SoD) GLOBAL
```

A próxima etapa deverá consolidar:

- roles corporativas;
- permissões;
- scopes;
- acesso por empresa/filial;
- segregação de funções;
- incompatibilidades;
- step-up authentication;
- MFA;
- privilégios temporários;
- delegação;
- SYSTEM_ACTOR;
- matriz de permissões M1–M23;
- segurança de dados sensíveis;
- ações críticas;
- auditoria de acesso.

---

**Fim da Etapa 4 — Matriz Completa de Integrações Módulo × Módulo**
