# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 3 — Catálogo Oficial de Eventos M1–M23

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Contratos corporativos de mensagens, eventos, requisições assíncronas, notificações e integrações event-driven dos módulos M1–M23.  
**Objetivo:** Estabelecer o catálogo oficial de eventos e mensagens cross-domain do ERP, definindo envelope, naming, versionamento, producer/consumer, payload mínimo, criticidade, idempotência, retry, DLQ, correlation/causation, replay, observabilidade e separação explícita entre eventos e comandos síncronos.

---

# 1. Objetivo da Etapa 3

A Etapa 3 transforma as fronteiras de domínio definidas na Etapa 1 e o modelo de dados consolidado da Etapa 2 em contratos de integração event-driven implementáveis.

Cada mensagem corporativa relevante deverá ter, no mínimo:

```text
name
message_kind

producer
producer_module

aggregate_type
aggregate_id

consumers

trigger

payload_minimum

event_version

criticality

delivery_semantics

idempotency_policy

retry_policy

correlation_policy
```

A distinção abaixo é obrigatória:

```text
DOMAIN EVENT
≠
ASYNC REQUEST
≠
NOTIFICATION
≠
SYNCHRONOUS COMMAND
```

---

# 2. Escopo do Catálogo Corporativo

O catálogo oficial não incluirá cada pequeno evento interno de implementação.

Exemplo:

```text
OrderItemDescriptionNormalized
```

pode existir internamente no M4 sem fazer parte do catálogo corporativo.

Entram no catálogo mensagens que:

- atravessam módulos;
- causam efeitos relevantes;
- precisam de idempotência cross-domain;
- exigem auditoria;
- alimentam Analytics;
- disparam processos corporativos;
- representam fatos relevantes da empresa;
- representam solicitações assíncronas relevantes.

---

# 3. Tipos Oficiais de Mensagem

## 3.1 `DOMAIN_EVENT`

Representa um fato que já aconteceu.

Exemplos:

```text
InvoiceAuthorized
ShipmentDispatched
ReceivableSettled
ProductionYieldReported
EmployeeTerminated
```

Regra de nomenclatura:

```text
usar passado
```

Nunca utilizar um verbo imperativo para um fato.

Exemplo incorreto:

```text
AuthorizeInvoice
```

---

## 3.2 `ASYNC_REQUEST`

Representa solicitação para outro domínio executar algo.

Exemplos:

```text
PayableRequested
UserAccessRevocationRequested
IncomingInspectionRequested
AnalyticsWorkflowRequested
```

Uma requisição assíncrona não afirma que a operação já foi concluída.

---

## 3.3 `NOTIFICATION_EVENT`

Mensagem cujo objetivo principal é comunicação.

Exemplos:

```text
VacationDeadlineAlert
PreventiveMaintenanceOverdue
WorkflowSlaWarning
```

Notificações não devem ser utilizadas como fonte primária de verdade financeira, física, fiscal ou contábil.

---

## 3.4 `SYNCHRONOUS COMMAND / QUERY`

Não passa pelo RabbitMQ quando a resposta é necessária antes da continuidade da operação.

Exemplos:

```text
InventoryReservationService.reserve()
RegulatoryProductionGate.check()
CreditDecisionService.evaluate()
```

Esses contratos são apresentados na seção específica de integrações síncronas.

---

# 4. Convenção Oficial de Nomes

Eventos e mensagens de aplicação:

```text
PascalCase
```

Exemplos:

```text
OrderCreated
InventoryReservationCreated
InvoiceAuthorized
ReceivableSettled
```

Routing Key RabbitMQ:

```text
<domain>.<aggregate>.<action>.v<major>
```

Exemplos:

```text
orders.order.created.v1
inventory.reservation.created.v1
fiscal.invoice.authorized.v1
finance.receivable.settled.v1
```

---

# 5. Envelope Corporativo de Mensagem

Todas as mensagens corporativas usarão um envelope comum.

```json
{
  "message_id": "uuid",
  "message_kind": "DOMAIN_EVENT",
  "message_type": "InvoiceAuthorized",
  "event_version": 1,

  "producer_module": "M11",
  "producer_domain": "fiscal",

  "aggregate_type": "fiscal_document",
  "aggregate_id": "uuid",
  "aggregate_version": 7,

  "company_id": "uuid",
  "branch_id": "uuid",

  "occurred_at": "2026-09-06T18:20:00Z",

  "correlation_id": "uuid",
  "causation_id": "uuid",
  "request_id": "uuid",

  "payload": {}
}
```

---

# 6. Identidade da Mensagem

Cada mensagem terá:

```text
message_id UUID
```

globalmente único.

Para eventos, esse mesmo valor poderá ser utilizado como:

```text
event_id
```

na Inbox dos consumidores.

---

# 7. Aggregate Version

Quando a mensagem representar mudança em um agregado mutável:

```text
aggregate_version
```

será incluída.

Exemplo:

```text
OrderUpdated
aggregate_version = 15
```

Isso permite detectar:

- evento atrasado;
- evento repetido;
- atualização obsoleta;
- Latest State Wins quando aplicável.

---

# 8. Payload Mínimo

Eventos não carregarão cópia arbitrária de tabela.

Regra:

```text
mínimo
+
suficiente para a finalidade dos consumidores
```

Exemplo inadequado:

```text
SELECT *
FROM order
```

serializado integralmente.

Exemplo adequado:

```json
{
  "order_id": "...",
  "order_number": 101533,
  "customer_id": "...",
  "source_type": "MARKETPLACE",
  "currency_code": "BRL",
  "gross_amount": "279.9000"
}
```

---

# 9. Dados Sensíveis em Mensagens

Não transportar sem necessidade explícita:

- senha;
- OAuth token;
- segredo;
- documentos completos de RH;
- conta bancária completa;
- salário individual;
- dados pessoais desnecessários.

Preferir:

```text
entity_id
```

ou valores mascarados.

---

# 10. Versionamento de Mensagens

Campo oficial:

```text
event_version INTEGER
```

Exemplo:

```text
InvoiceAuthorized v1
```

Mudança apenas aditiva e opcional:

```text
continua v1
```

Mudança incompatível:

```text
v2
```

São breaking changes:

- remover campo obrigatório;
- alterar significado;
- alterar unidade;
- alterar tipo;
- alterar semântica do evento.

---

# 11. Compatibilidade

Cada consumidor deverá declarar versões aceitas.

Exemplo:

```text
consumer:
accounting.invoice-authorized

accepts:
v1
v2
```

Durante migração, o produtor poderá suportar compatibilidade conforme estratégia definida.

---

# 12. Garantia de Entrega

Modelo oficial:

```text
AT-LEAST-ONCE
+
IDEMPOTENT CONSUMERS
```

Não assumir exactly-once distribuído.

---

# 13. Transactional Outbox

Publicação:

```text
Business Transaction
+
platform.outbox_event
```

na mesma transação PostgreSQL.

Depois:

```text
Outbox Publisher
→ RabbitMQ
```

Objetivo:

```text
não permitir:
transação gravada
+
evento perdido
```

---

# 14. Inbox

Cada consumidor crítico registra:

```text
consumer_name
message_id
```

com:

```text
UNIQUE(consumer_name, message_id)
```

Se a mesma mensagem for recebida novamente:

```text
ACK
sem repetir o efeito
```

---

# 15. Idempotência de Negócio

Além do `message_id`, operações específicas devem possuir chave semântica.

Exemplos:

```text
Marketplace order
→ marketplace_account_id + external_order_id

Fiscal
→ issuance_intent_id

Workflow
→ workflow_request_key

Import
→ external_batch_id / checksum

Finance
→ settlement_reference
```

---

# 16. Ordenação

RabbitMQ não será tratado como mecanismo de ordenação global.

Regra:

```text
não depender de ordem global de eventos
```

Quando necessário:

```text
aggregate_id
+
aggregate_version
```

---

# 17. Evento Atrasado

Exemplo:

```text
ProductUpdated version 12
```

já processado.

Depois chega:

```text
ProductUpdated version 11
```

Para projeção de Latest State:

```text
ignore stale version
```

sem promover estado antigo a nova verdade.

---

# 18. Exchanges Corporativos

Estrutura inicial:

```text
erp.events
erp.requests
```

Tipo:

```text
topic
```

Dead Letter Exchange:

```text
erp.dlx
```

---

# 19. Filas por Consumidor

Não compartilhar uma única fila entre consumidores que precisam receber a mesma mensagem.

Exemplo:

```text
InvoiceAuthorized
```

deve poder ser entregue a:

```text
finance.invoice-authorized.v1
accounting.invoice-authorized.v1
analytics.invoice-authorized.v1
```

Cada consumidor possui sua fila.

---

# 20. Retry Padrão

Baseline:

```text
tentativa inicial

30 segundos
2 minutos
5 minutos
15 minutos

→ DLQ
```

Integrações específicas podem possuir política própria quando justificável.

---

# 21. Dead Letter Queue — DLQ

Ao esgotar retries, preservar:

```text
message_id
message_type

original_exchange
original_routing_key

consumer
attempt_count

first_failure_at
last_failure_at

error_code
error_summary
```

---

# 22. Reprocessamento de DLQ

Replay/retry preserva:

```text
original message_id
```

Se o efeito já tiver sido concluído anteriormente:

```text
Inbox impede duplicação
```

---

# 23. Criticidade

Categorias oficiais:

```text
CRITICAL
HIGH
NORMAL
LOW
```

## CRITICAL

Exemplos:

```text
Inventory physical effects
Fiscal authorization
Financial settlement
Access revocation
Regulatory block
Workflow final decision
```

DLQ crítica gera alerta operacional imediato.

## HIGH

Exemplos:

```text
Order
Production
Purchasing
Maintenance availability
```

## NORMAL

Exemplos:

```text
Master-data updates
Commercial analytics
```

## LOW

Exemplos:

```text
Informational analytics
Scheduled reports
```

---

# 24. Observabilidade das Mensagens

Métricas mínimas:

```text
published_count
consumed_count
processing_latency
retry_count
dlq_count
oldest_pending_age
consumer_lag
```

Logs devem sempre conter:

```text
message_id
message_type
correlation_id
consumer
```

---

# 25. Tracing

Exemplo:

```text
SalesQuoteConverted
↓
OrderCreated
↓
InventoryReservationCreated
↓
InvoiceAuthorized
↓
ReceivableCreated
```

Todos compartilham:

```text
correlation_id
```

Evento descendente:

```text
causation_id
=
message_id da mensagem causadora
```

---

# 26. Replay

Eventos elegíveis a replay podem reconstruir:

- M21;
- read models;
- projeções;
- consumidores recuperados.

Mas:

```text
replay
não pode repetir efeitos financeiros/físicos
```

sem idempotência adequada.

---

# 27. Registro Oficial dos Contratos

Como complemento à Etapa 2, o schema `platform` poderá manter:

```text
platform.event_definition
platform.event_schema_version
platform.event_subscription
platform.event_replay_request
```

O catálogo operacional não substitui contratos versionados em Git.

---

# 28. `platform.event_definition`

Campos:

```text
message_type
message_kind
producer_module
producer_domain
criticality
description
active
```

---

# 29. `platform.event_schema_version`

```text
event_definition_id
event_version
json_schema
published_at
deprecated_at
```

---

# 30. `platform.event_subscription`

Documenta:

```text
consumer_module
consumer_name
message_type
supported_versions
queue_name
criticality_override
```

---

# 31. Regra Especial do M21

M21 poderá consumir eventos corporativos relevantes de M1–M20, M22 e M23, respeitando classificação e segurança.

Para evitar repetição nas tabelas:

```text
M21 = consumidor implícito autorizado
```

quando o evento possuir relevância analítica.

---

# 32. M1 — Administração e Segurança

| Mensagem | Tipo | Trigger | Consumidores principais | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `CompanyCreated` | EVENT | criação de empresa | M20, M21, M23 | company_id, group_id, legal_name, status | NORMAL |
| `CompanyUpdated` | EVENT | alteração relevante | M20, M21, M23 | company_id, changed_fields, version | NORMAL |
| `BranchCreated` | EVENT | criação de filial | M11, M20, M21 | branch_id, company_id, code, timezone | NORMAL |
| `BranchUpdated` | EVENT | alteração filial | M11, M20, M21 | branch_id, changed_fields, version | NORMAL |
| `UserProvisioned` | EVENT | usuário criado/habilitado | M22, M21 | user_id, person_id?, status | HIGH |
| `UserDisabled` | EVENT | usuário bloqueado | M22 | user_id, effective_at, reason_code | CRITICAL |
| `UserAccessRevoked` | EVENT | acesso revogado | M22, auditoria | user_id, effective_at, source_reference | CRITICAL |
| `UserRoleChanged` | EVENT | RBAC modificado | M22, M21 | user_id, role_ids, effective_at | HIGH |
| `SecurityPolicyChanged` | EVENT | política ativada | M22 | policy_id, version, valid_from | HIGH |
| `UserAccessRevocationRequested` | REQUEST | solicitação M20 | M1 | person/workforce_id, effective_at, reason | CRITICAL |
| `UserProvisioningRequested` | REQUEST | onboarding | M1 | person_id, company_id, requested_scope | HIGH |

---

# 33. M2 — Product Master

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `ProductCreated` | EVENT | novo produto | M3, M5, M7, M9, M17, M18, M23 | product_id, sku, product_type | NORMAL |
| `ProductUpdated` | EVENT | master alterado | M3, M7, M9, M17, M18, M23 | product_id, changed_fields, version | NORMAL |
| `ProductActivated` | EVENT | status ATIVO | M3, M4, M5, M9, M15 | product_id, sku, effective_at | HIGH |
| `ProductDiscontinued` | EVENT | fora de linha | M3, M4, M6, M9, M15 | product_id, effective_at | HIGH |
| `ProductBarcodeChanged` | EVENT | EAN/DUN alterado | M10, M3 | product_id, barcode_type, barcode | HIGH |
| `ProductPackagingChanged` | EVENT | embalagem alterada | M6, M10, M9 | product_id, packaging_version | NORMAL |
| `ProductFiscalMasterChanged` | EVENT | NCM/origem/etc. | M11, M18, M23 | product_id, changed_fields, version | HIGH |
| `BomRevisionReleased` | EVENT | revisão RELEASED | M7, M8, M18 | bom_id, bom_revision_id, product_id, valid_from | HIGH |
| `BomRevisionObsoleted` | EVENT | revisão obsoleta | M7, M18 | bom_revision_id, valid_until | NORMAL |

---

# 34. M3 — Marketplace Hub

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `MarketplaceAccountConnected` | EVENT | OAuth/account ativa | M21 | marketplace_account_id, channel | NORMAL |
| `MarketplaceAccountDisconnected` | EVENT | conta indisponível | M21/alertas | account_id, reason | HIGH |
| `MarketplaceListingMapped` | EVENT | listing associado | M9, M21 | listing_id, product_id, channel | NORMAL |
| `MarketplaceOrderDetected` | EVENT | pedido recebido | M3 interno/M21 | account_id, external_order_id | HIGH |
| `MarketplaceOrderApproved` | EVENT | canal confirma pago/aprovado | M4 | account_id, external_order_id, snapshot_ref, approved_at | CRITICAL |
| `MarketplaceOrderCancelled` | EVENT | cancelamento externo | M4 | account_id, external_order_id, cancelled_at, reason | CRITICAL |
| `MarketplaceStockPublicationSucceeded` | EVENT | estoque publicado | M21 | listing_id, published_qty, version | NORMAL |
| `MarketplaceStockPublicationFailed` | EVENT | falha publicação | M21/cockpit | listing_id, desired_qty, error_code | HIGH |
| `MarketplacePricePublicationSucceeded` | EVENT | preço publicado | M9, M21 | listing_id, price, pricing_version | NORMAL |
| `MarketplacePricePublicationFailed` | EVENT | falha preço | M9/M21 | listing_id, desired_price, error_code | HIGH |
| `MarketplaceFiscalDataSent` | EVENT | XML/dados enviados | M4/M11 | external_order_id, fiscal_document_id | NORMAL |
| `MarketplaceLabelAvailable` | EVENT | etiqueta obtida | M10 | external_order_id, label_ref | HIGH |

---

# 35. M4 — Orders / Fulfillment

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `OrderCreated` | EVENT | pedido persistido | M5, M10, M11, M15 | order_id, number, source, customer_id, gross_amount | HIGH |
| `OrderApproved` | EVENT | pedido aprovado | M5, M10 | order_id, approved_at | HIGH |
| `OrderReserved` | EVENT | reserva confirmada | M10 | order_id, reservation_id | HIGH |
| `OrderOnHold` | EVENT | bloqueio operacional | M3, M10, M15 | order_id, hold_reason | HIGH |
| `OrderReleasedFromHold` | EVENT | hold removido | M10 | order_id | HIGH |
| `OrderCancelled` | EVENT | cancelamento | M5, M10, M11, M12, M3 | order_id, reason_code, cancelled_at | CRITICAL |
| `FulfillmentCreated` | EVENT | fulfillment criado | M10 | fulfillment_id, order_id, branch_id | HIGH |
| `FulfillmentReadyForBilling` | EVENT | condição de faturamento | M11 | fulfillment_id, order_id | CRITICAL |
| `BillingRequested` | REQUEST | faturamento requerido | M11 | order_id, fulfillment_id, billing_context | CRITICAL |
| `ReceivableRequested` | REQUEST | geração financeira requerida | M12 | order_id, fiscal_document_id, commercial_snapshot | CRITICAL |
| `OrderCompleted` | EVENT | ciclo operacional concluído | M15, M21 | order_id, completed_at | NORMAL |

---

# 36. M5 — Inventory

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `InventoryPostingCreated` | EVENT | ledger posting confirmado | M8, M21 | posting_id, transaction_id, product_id, qty, state | CRITICAL |
| `InventoryBalanceChanged` | EVENT | balance atualizado | M3, M7, M10, M15 | product_id, warehouse_id, pool_id, state, qty, balance_version | CRITICAL |
| `InventoryReservationCreated` | EVENT | reserva confirmada | M4, M10 | reservation_id, source_id, allocations | CRITICAL |
| `InventoryReservationReleased` | EVENT | reserva liberada | M4, M10 | reservation_id, reason | CRITICAL |
| `InventoryReservationExpired` | EVENT | TTL B2B expirou | M4, M15 | reservation_id, source_id | HIGH |
| `InventoryShortageDetected` | EVENT | saldo insuficiente | M4, M6, M7, M10 | product_id, warehouse_id, shortage_qty | CRITICAL |
| `InventoryDiscrepancyCreated` | EVENT | divergência | M10, M21 | discrepancy_id, product_id, qty | HIGH |
| `InventoryDiscrepancyResolved` | EVENT | divergência encerrada | M10 | discrepancy_id, resolution | NORMAL |
| `InventoryTransferDispatched` | EVENT | origem → IN_TRANSIT | M21 | transfer_id, source, destination | HIGH |
| `InventoryTransferReceived` | EVENT | destino recebido | M21 | transfer_id, received_at | HIGH |
| `InventoryLotStateChanged` | EVENT | quarantine/block/etc. | M4, M10, M17, M18 | lot_id, product_id, old_state, new_state | CRITICAL |

---

# 37. M6 — Procurement

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `PurchaseRequisitionCreated` | EVENT | necessidade criada | M22, M21 | requisition_id, company_id, amount_estimate | NORMAL |
| `PurchaseApprovalRequested` | REQUEST | alçada necessária | M22 | requisition/order_id, amount, context | HIGH |
| `PurchaseOrderApproved` | EVENT | workflow aprovado e M6 efetivou | M5, M21 | purchase_order_id, supplier_id, total | HIGH |
| `PurchaseOrderShortClosed` | EVENT | saldo cancelado | M7, M21 | purchase_order_id, affected_items | NORMAL |
| `InboundInvoiceReceived` | EVENT | documento vinculado | M11/M6 interno | fiscal_reference, supplier_id | HIGH |
| `GoodsReceiptPhysicallyConfirmed` | EVENT | entrada física | M5, M17 | goods_receipt_id, items, received_at | CRITICAL |
| `IncomingInspectionRequested` | REQUEST | item requer inspeção | M17 | receipt_id, item_id, product_id, lot/qty | CRITICAL |
| `SupplierClaimCreated` | EVENT | divergência confirmada | M12, M21 | claim_id, supplier_id, amount/qty | NORMAL |
| `PurchaseReceiptConfirmed` | EVENT | gates concluídos | M8, M12 | receipt_id, fiscal_document_id | HIGH |
| `AcquisitionCostCalculated` | EVENT | custo aquisição apurado | M8 | receipt_id, allocation_reference | HIGH |
| `PayableRequested` | REQUEST | obrigação requerida | M12 | source_type, source_id, supplier_id, installments | CRITICAL |

---

# 38. M7 — Manufacturing

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `ProductionOrderReleased` | EVENT | OP liberada | M5, M17, M18, M19 | production_order_id, product_id, version_id | HIGH |
| `ProductionOrderStarted` | EVENT | início real | M17, M19, M21 | production_order_id, resource_id, started_at | HIGH |
| `MaterialIssuedToProduction` | EVENT | consumo explícito | M5, M8 | production_order_id, material_issue_id | CRITICAL |
| `ProductionYieldReported` | EVENT | produção apontada | M5, M8, M19, M21 | production_order_id, product_id, qty, lot_id | CRITICAL |
| `ScrapRegistered` | EVENT | sucata/refugo | M8, M17, M21 | production_order_id, qty, reason_code | HIGH |
| `SecondaryMaterialRecovered` | EVENT | material recuperado | M5, M8 | production_order_id, product_id, qty, lot_id | HIGH |
| `ReworkRegistered` | EVENT | retrabalho | M8, M17 | production_order_id, qty, reason | HIGH |
| `FinishedGoodsReceived` | EVENT | PA/PI recebido | M5, M17, M18, M8 | production_order_id, lot_id, qty | CRITICAL |
| `ProductionOrderInterrupted` | EVENT | interrupção | M19, M21 | production_order_id, reason, resource_id | HIGH |
| `ProductionOrderClosed` | EVENT | OP encerrada | M8, M21 | production_order_id, closed_at | HIGH |

---

# 39. M8 — Industrial Costing

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `StandardCostActivated` | EVENT | versão ativa | M9, M15, M13 | product_id, branch_id, standard_cost_version_id, cost | CRITICAL |
| `ProductionOrderCostCalculated` | EVENT | custo provisório/final | M21 | production_order_id, status, total_cost | NORMAL |
| `ProductionOrderCostSealed` | EVENT | custo selado | M13, M21 | production_order_id, cost_id, total_cost | HIGH |
| `MovingAverageCostUpdated` | EVENT | média móvel mudou | M13, M21 | product_id, branch/warehouse context, new_cost | HIGH |
| `CostVarianceThresholdExceeded` | EVENT | limiar excedido | M9, M15, M21 | product_id, variance_pct, severity | HIGH |
| `PostCloseCostVarianceCreated` | EVENT | ajuste pós-fechamento | M13, M21 | variance_id, period, amount | HIGH |
| `CostingPeriodClosed` | EVENT | competência fechada | M13, M21 | period_id, closed_at | HIGH |
| `CostingPeriodReopened` | EVENT | reabertura excepcional | M13, M21 | period_id, reason_code | HIGH |

---

# 40. M9 — Pricing

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `PriceActivated` | EVENT | preço ativado | M3, M4, M15 | product_id, channel/table, price, version_id | CRITICAL |
| `PriceSuperseded` | EVENT | nova versão substitui | M3, M15 | old_version, new_version | HIGH |
| `PriceExpired` | EVENT | validade expirada | M3, M15 | price_version_id, expired_at | HIGH |
| `PriceReviewRequired` | EVENT | fee/custo/threshold | M15, M21 | product_id, reason_code, severity | HIGH |
| `PricingBatchActivated` | EVENT | lote ativado | M3, M15 | pricing_batch_id, affected_count | HIGH |
| `PriceExceptionApprovalRequested` | REQUEST | desconto/margem fora da regra | M22 | source_id, proposed_price, policy_context | HIGH |
| `PricingSimulationCompleted` | EVENT | simulação relevante persistida | M15/M21 | simulation_id, context | LOW |

Regra:

```text
M9 decide preço
M3 publica no marketplace
```

---

# 41. M10 — WMS / Expedição

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `PickingWaveReleased` | EVENT | onda liberada | M21 | wave_id, fulfillment_count | NORMAL |
| `PickingStarted` | EVENT | picking iniciado | M4, M21 | task_id, fulfillment_id | NORMAL |
| `PickingShortageDetected` | EVENT | falta física | M5, M4 | task_id, product_id, missing_qty | CRITICAL |
| `PickingCompleted` | EVENT | separação completa | M4 | fulfillment_id, completed_at | HIGH |
| `PackingCompleted` | EVENT | embalagem conferida | M4, M11 | fulfillment_id, package_ids | HIGH |
| `PackageFinalized` | EVENT | volume fechado | M3, M21 | package_id, dimensions, weight | NORMAL |
| `ShippingLabelPrinted` | EVENT | etiqueta impressa | M21 | package_id, label_id | LOW |
| `ShipmentReady` | EVENT | pronto para despacho | M4, M11 | shipment_id, fulfillment_ids | HIGH |
| `ShipmentDispatched` | EVENT | saída física oficial | M4, M5, M13, M21 | shipment_id, order_ids, dispatched_at | CRITICAL |
| `ShipmentDeliveryConfirmed` | EVENT | entrega confirmada | M4, M21 | shipment_id, delivered_at | NORMAL |

---

# 42. M11 — Fiscal

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `FiscalDocumentIntentCreated` | EVENT | intenção criada | M21 | intent_id, operation_type | NORMAL |
| `FiscalDocumentSubmitted` | EVENT | enviado provider/SEFAZ | M4, M21 | document_id, attempt_id | HIGH |
| `InvoiceAuthorized` | EVENT | NF de saída autorizada | M3, M4, M12, M13, M16 | fiscal_document_id, order/fulfillment refs, total, authorized_at | CRITICAL |
| `FiscalDocumentRejected` | EVENT | rejeição | M4, M15 | document_id, rejection_code | CRITICAL |
| `FiscalCancellationRequested` | REQUEST | pedido formal | M22 quando alçada | document_id, reason | HIGH |
| `FiscalDocumentCancelled` | EVENT | cancelamento autorizado | M4, M12, M13, M16 | document_id, cancelled_at | CRITICAL |
| `FiscalCorrectionRegistered` | EVENT | CC-e registrada | M13/M21 | document_id, correction_id | HIGH |
| `InboundFiscalDocumentReceived` | EVENT | NF entrada registrada | M6, M12 | document_id, supplier_id | HIGH |
| `InboundFiscalDocumentValidated` | EVENT | validação concluída | M6, M12 | document_id, divergence_status | HIGH |
| `TaxRuleActivated` | EVENT | regra fiscal ativa | M9, M13, M23 | rule_version_id, valid_from | HIGH |
| `FiscalNumberInvalidated` | EVENT | inutilização | M13/M21 | establishment_id, series, range | HIGH |

---

# 43. M12 — Financeiro

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `ReceivableCreated` | EVENT | título criado | M13, M14, M16 | receivable_id, customer_id, amount, due_date | CRITICAL |
| `ReceivablePartiallySettled` | EVENT | baixa parcial | M13, M16, M14 | receivable_id, principal_settled, settlement_id | CRITICAL |
| `ReceivableSettled` | EVENT | baixa total | M13, M16, M14 | receivable_id, settlement_id, principal_settled | CRITICAL |
| `ReceivableOverdue` | EVENT | vencimento | M14, M15 | receivable_id, customer_id, overdue_days | HIGH |
| `ReceivableRenegotiated` | EVENT | renegociação | M13, M16 | old_receivable_ids, new_receivable_ids | CRITICAL |
| `ReceivableWrittenOff` | EVENT | baixa por perda | M13, M16, M14 | receivable_id, amount, reason | CRITICAL |
| `PayableCreated` | EVENT | obrigação criada | M13 | payable_id, supplier/source, amount | CRITICAL |
| `PaymentApprovalRequested` | REQUEST | alçada | M22 | payment_request_id, amount, account | CRITICAL |
| `PayableSettled` | EVENT | pagamento realizado | M13 | payable_id, settlement_id, amount | CRITICAL |
| `BankMovementReconciled` | EVENT | conciliação | M13 | bank_movement_id, match_id | HIGH |
| `MarketplaceSettlementConfirmed` | EVENT | repasse reconciliado | M13, M16 | settlement_id, marketplace_account_id, actual_net | CRITICAL |
| `CreditExposureChanged` | EVENT | exposição alterada | M14, M15 | customer/group_id, exposure, available_limit | HIGH |
| `CustomerCreditBlocked` | EVENT | bloqueio financeiro | M14, M15 | customer/group_id, reason_code | CRITICAL |
| `CustomerCreditReleased` | EVENT | liberação | M14, M15 | customer/group_id | HIGH |
| `ReceivableAnticipated` | EVENT | antecipação | M13 | anticipation_id, cash_received, financial_cost | HIGH |

---

# 44. M13 — Contabilidade

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `AccountingEntryPosted` | EVENT | journal POSTED | M21 | journal_entry_id, period, source_event_id | HIGH |
| `AccountingEntryReversed` | EVENT | reversão | M21 | original_entry_id, reversal_entry_id | HIGH |
| `AccountingRuleActivated` | EVENT | regra ativa | M23/M21 | rule_version_id, event_type, valid_from | HIGH |
| `AccountingPeriodSoftClosed` | EVENT | soft close | M21 | period_id, closed_at | HIGH |
| `AccountingPeriodClosed` | EVENT | fechamento | M21 | period_id, closed_at | CRITICAL |
| `AccountingPeriodReopened` | EVENT | reabertura | M21, M22/audit | period_id, reason_code | CRITICAL |
| `AccountingReconciliationIssueDetected` | EVENT | subledger ≠ GL | M21/M22 | reconciliation_id, type, difference | CRITICAL |
| `AccountingReconciliationResolved` | EVENT | diferença resolvida | M21 | reconciliation_id | HIGH |
| `ConsolidationCompleted` | EVENT | consolidação grupo | M21 | period_id, consolidation_id | HIGH |

---

# 45. M14 — Clientes e CRM

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `CustomerCreated` | EVENT | novo cliente | M4, M9, M12, M15, M23 | customer_id, type, identity_ref | NORMAL |
| `CustomerUpdated` | EVENT | master alterado | M4, M9, M12, M15, M23 | customer_id, changed_fields, version | NORMAL |
| `CustomerGroupChanged` | EVENT | vínculo grupo | M9, M12, M15 | customer_id, customer_group_id | HIGH |
| `CustomerOperationalStatusChanged` | EVENT | released/restricted/blocked | M4, M9, M15 | customer_id, status, reason_codes | CRITICAL |
| `CustomerCommercialStatusChanged` | EVENT | status comercial | M15 | customer_id, status | HIGH |
| `CustomerMerged` | EVENT | merge concluído | M4, M12, M15, M21, M23 | surviving_customer_id, merged_customer_ids | CRITICAL |
| `CustomerConsentChanged` | EVENT | consentimento | CRM/comunicação | customer_id, channel, status | NORMAL |
| `CustomerDuplicateSuggested` | EVENT | candidato detectado | M23 | customer_ids, confidence | NORMAL |

---

# 46. M15 — Comercial B2B

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `SalesQuoteCreated` | EVENT | orçamento criado | M21 | quote_id, customer_id, seller | NORMAL |
| `SalesQuoteRevisionCreated` | EVENT | nova revisão | M21 | quote_id, revision_id | NORMAL |
| `SalesQuoteSent` | EVENT | enviado ao cliente | M21 | quote_id, revision_id, sent_at | NORMAL |
| `SalesQuoteStaleDetected` | EVENT | preço/custo/policy mudou | M21 | quote_id, reason_code | HIGH |
| `SalesQuoteApprovalRequested` | REQUEST | precisa alçada | M22 | quote_id, revision_id, approval_context | HIGH |
| `SalesQuoteAccepted` | EVENT | aceite total | M4/M21 | quote_id, revision_id | HIGH |
| `SalesQuotePartiallyAccepted` | EVENT | aceite parcial | M4/M21 | quote_id, accepted_item_ids | HIGH |
| `SalesQuoteLost` | EVENT | perdido | M9, M21 | quote_id, loss_reason | NORMAL |
| `SalesOrderConversionRequested` | REQUEST | conversão iniciada | M9, M12, M22 gates | quote_id | HIGH |
| `SalesOrderConverted` | EVENT | M4 order criado | M16, M21 | quote_id, order_id, snapshot_ref | CRITICAL |
| `SalesOrderChangeRequested` | REQUEST | alteração pós-conversão | M22 | order_id, change_fingerprint | HIGH |
| `CommercialPolicyViolationDetected` | EVENT | policy warning/block | M21 | source_id, policy_code, severity | NORMAL |
| `ProjectedAvailabilityUsed` | EVENT | venda contra projeção | M7, M21 | quote/order_id, product_id, expected_date | HIGH |

---

# 47. M16 — Representantes e Comissões

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `CommissionSnapshotCreated` | EVENT | conversão comercial | M21 | order_id, snapshot_id, beneficiaries | HIGH |
| `CommissionAccrued` | EVENT | NF autorizada | M13/M21 | origin_id, beneficiary_id, accrued_amount | HIGH |
| `CommissionEarned` | EVENT | principal liquidado | M13/M21 | earning_id, origin_id, amount, settlement_id | CRITICAL |
| `CommissionReversed` | EVENT | estorno | M13/M21 | origin_id, amount, reason | HIGH |
| `CommissionClawbackCreated` | EVENT | recuperação futura | M12, M13 | clawback_id, beneficiary_id, amount | CRITICAL |
| `CommissionAdjusted` | EVENT | ajuste aprovado | M13 | adjustment_id, amount, reason | HIGH |
| `CommissionPeriodClosed` | EVENT | competência fechada | M12, M13 | period_id, closed_at | HIGH |
| `CommissionStatementGenerated` | EVENT | extrato | M21 | statement_id, beneficiary_id, amount | NORMAL |
| `CommissionPayableRequested` | REQUEST | pagar representante | M12 | statement_id, beneficiary_id, payable_amount | CRITICAL |

---

# 48. M17 — Qualidade / SGQ

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `QualityInspectionStarted` | EVENT | inspeção iniciada | M6/M7 | inspection_id, type, source_ref | NORMAL |
| `QualityInspectionCompleted` | EVENT | decisão concluída | M5, M6, M7, M21 | inspection_id, result, approved_qty, rejected_qty | CRITICAL |
| `QualityLotApproved` | EVENT | lote liberado | M5, M4, M10 | lot_id, product_id, qty | CRITICAL |
| `QualityLotPartiallyApproved` | EVENT | aprovação parcial | M5 | lot_id, approved_qty, quarantine_qty | CRITICAL |
| `QualityLotRejected` | EVENT | rejeição | M5, M6, M7 | lot_id, reason_code | CRITICAL |
| `QualityHoldPlaced` | EVENT | hold | M5, M7, M10 | scope_type, scope_id, reason | CRITICAL |
| `QualityHoldReleased` | EVENT | liberação | M5, M7, M10 | hold_id | CRITICAL |
| `ProductionHoldRequested` | REQUEST | crítica em processo | M7 | production_order/resource scope, reason | CRITICAL |
| `ProductionHoldReleased` | EVENT/REQUEST | qualidade libera | M7 | hold_reference | CRITICAL |
| `NonconformityCreated` | EVENT | NC formal | M6/M7/M18 | nc_id, severity, source | HIGH |
| `CapaRequired` | EVENT | CAPA obrigatória | M22/task/M21 | nc_id, reason | HIGH |
| `CapaClosed` | EVENT | eficácia concluída | M21 | capa_id, closed_at | NORMAL |
| `SupplierQualityStatusChanged` | EVENT | probation/block | M6 | supplier_id, product_id?, new_status | CRITICAL |
| `RecallInitiated` | EVENT | recall iniciado | M4, M10, M14, M18 | recall_id, affected_lots | CRITICAL |
| `RegulatoryAssessmentRequested` | REQUEST | possível impacto regulatório | M18 | source_type, source_id, reason | CRITICAL |

---

# 49. M18 — Compliance Regulatório / INMETRO

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `RegulatoryCertificateActivated` | EVENT | certificado ativo | M2, M4, M7, M10, M11 | certificate_id, scope, valid_until | CRITICAL |
| `RegulatoryCertificateExpiring` | EVENT | janela de alerta | M21/M22 | certificate_id, days_remaining | HIGH |
| `RegulatoryCertificateExpired` | EVENT | expiração | M4, M7, M11, M10 | certificate_id, scope | CRITICAL |
| `RegulatoryCertificateSuspended` | EVENT | suspensão | M4, M7, M10, M11 | certificate_id, scope, reason | CRITICAL |
| `RegulatoryCertificateCancelled` | EVENT | cancelamento | M4, M7, M10, M11 | certificate_id, scope | CRITICAL |
| `RegulatoryChangeAssessmentRequested` | REQUEST | alteração relevante | M18 | product/BOM/supplier refs, change_fingerprint | HIGH |
| `RegulatoryChangeAssessmentCompleted` | EVENT | parecer final | M2, M7, M17 | assessment_id, result, restrictions | CRITICAL |
| `RegulatoryPackagingApproved` | EVENT | embalagem aprovada | M2, M4, M7 | approval_id, product/sku, version | CRITICAL |
| `RegulatoryProductBlocked` | EVENT | bloqueio produto/SKU/família | M3, M4, M7, M10, M11, M15 | scope, flags, reason | CRITICAL |
| `RegulatoryProductReleased` | EVENT | desbloqueio | mesmos | scope, flags | CRITICAL |
| `RegulatoryLotStatusChanged` | EVENT | regra lote | M5, M4, M10, M11 | lot_id, sales/billing/shipping flags | CRITICAL |
| `RegulatoryComplianceSnapshotCreated` | EVENT | lote produzido | M17/M21 | lot_id, snapshot_id | HIGH |
| `RegulatoryRecallRequested` | REQUEST | risco regulatório | M17 | scope/lots, reason | CRITICAL |

---

# 50. M19 — Ativo Imobilizado e Manutenção

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `MaintenanceAssetUnavailable` | EVENT | falha/bloqueio | M7 | maintenance_asset_id, resource_id, reason, started_at | CRITICAL |
| `MaintenanceAssetReleased` | EVENT | COMPLETED + VALIDATED | M7 | asset_id, resource_id, released_at | CRITICAL |
| `MaintenanceRequestCreated` | EVENT | solicitação | M21 | request_id, asset_id, priority | NORMAL |
| `MaintenanceWorkOrderCreated` | EVENT | OM criada | M5/M6/M21 | work_order_id, asset_id, type | HIGH |
| `MaintenanceWorkOrderStarted` | EVENT | execução inicia | M21 | work_order_id, started_at | NORMAL |
| `MaintenanceWorkOrderCompleted` | EVENT | manutenção concluiu | M7/M21 | work_order_id, completed_at | HIGH |
| `MaintenanceWorkOrderValidated` | EVENT | produção aceitou | M7 | work_order_id, validated_at | CRITICAL |
| `MaintenanceWorkOrderClosed` | EVENT | OM fechada | M8, M13, M21 | work_order_id, total_cost | HIGH |
| `PreventiveMaintenanceDue` | EVENT | gatilho atingido | M19/M21 | plan_id, asset_id, due_basis | HIGH |
| `PreventiveMaintenanceOverdue` | NOTIFICATION | vencida | M21/M22 | asset_id, plan_id, overdue | HIGH |
| `MaintenanceMaterialRequested` | REQUEST | reserva MRO | M5 | work_order_id, product_id, qty | HIGH |
| `MaintenanceMaterialConsumed` | EVENT | consumo real | M5, M8 | work_order_id, inventory_transaction_id | HIGH |
| `UnplannedDowntimeStarted` | EVENT | parada inicia | M7, M8 | asset_id, resource_id, started_at | CRITICAL |
| `UnplannedDowntimeEnded` | EVENT | parada termina | M8, M21 | asset_id, duration | HIGH |
| `MaintenanceActualCostCalculated` | EVENT | custo OM | M13, M21 | work_order_id, cost_components | HIGH |
| `AssetTransferred` | EVENT | mudança patrimonial | M13 | fixed_asset_id, from_branch, to_branch | HIGH |
| `AssetCapitalized` | EVENT | capitalização | M13 | asset_id, amount, effective_date | HIGH |
| `AssetDisposed` | EVENT | baixa | M13 | asset_id, disposal_type, amount | CRITICAL |
| `AssetDepreciationCalculated` | EVENT | competência | M13 | asset_book_id, period, amount | HIGH |

---

# 51. M20 — RH, Ponto e Folha Bridge

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `PersonRegistered` | EVENT | pessoa criada | M1/M21 | person_id | NORMAL |
| `EmployeeAdmitted` | EVENT | vínculo iniciado | M1, M7, M21 | person_id, contract_id, company, effective_at | CRITICAL |
| `EmployeeAssignmentChanged` | EVENT | cargo/CC/setor | M7, M8, M13, M22 | contract_id, assignment_id, effective_at | HIGH |
| `EmployeeTransferred` | EVENT | transferência | M7, M8, M13 | contract_id, from/to assignment | HIGH |
| `EmployeeTerminated` | EVENT | desligamento | M1, M7, M21 | person_id, contract_id, effective_at | CRITICAL |
| `ThirdPartyEngagementStarted` | EVENT | terceiro ativo | M1, M7 | engagement_id, person_id | HIGH |
| `ThirdPartyEngagementEnded` | EVENT | terceiro encerrado | M1, M7 | engagement_id, effective_at | CRITICAL |
| `WorkforceMemberAvailable` | EVENT | apto | M7 | workforce_member_id, effective_at | HIGH |
| `WorkforceMemberUnavailable` | EVENT | indisponível | M7 | workforce_member_id, reason, interval | CRITICAL |
| `TimePunchImported` | EVENT | lote REP | M21 | import_batch_id, punch_count | LOW |
| `TimeExceptionDetected` | EVENT | exceção | M22/M21 | workforce_id, type, date | NORMAL |
| `TimeAdjustmentApprovalRequested` | REQUEST | correção | M22 | adjustment_request_id, change_fingerprint | HIGH |
| `TimeAdjustmentApproved` | EVENT | M20 aplica decisão | payroll bridge/M21 | adjustment_id, period | HIGH |
| `OvertimeApprovalRequested` | REQUEST | extra fabril | M22 | employee, date, requested_minutes | HIGH |
| `OvertimeAuthorized` | EVENT | autorização efetivada | TimeRuleEngine/M21 | authorization_id, minutes | HIGH |
| `UnauthorizedOvertimeDetected` | EVENT | extra sem prévia | M21 | employee_id, date, minutes | NORMAL |
| `TimePeriodClosed` | EVENT | ponto fechado | payroll bridge, M8 | period_id, company_id | CRITICAL |
| `TimePeriodReopened` | EVENT | reabertura | payroll bridge, M21 | period_id, reason | HIGH |
| `VacationScheduled` | EVENT | férias confirmadas | M7, M21 | employee_id, start, end | HIGH |
| `VacationDeadlineAlert` | NOTIFICATION | D-60 | M21/M22 | employee_id, deadline | NORMAL |
| `EmployeeAbsenceStarted` | EVENT | afastamento | M7 | employee_id, start, type | CRITICAL |
| `EmployeeAbsenceEnded` | EVENT | fim afastamento | M7 | employee_id, ended_at | HIGH |
| `PayrollExportGenerated` | EVENT | lote externo | M21 | batch_id, period | NORMAL |
| `PayrollResultsImported` | EVENT | folha retornou | M8, M13, M21 | batch_id, period, totals | CRITICAL |
| `LoadedLaborRateCalculated` | EVENT | taxa agregada | M8 | period, cost_center/work_center, rate | HIGH |
| `PayrollPayableRequested` | REQUEST | folha a pagar | M12 | period, company, amount | CRITICAL |
| `TaxPayableRequested` | REQUEST | encargos | M12 | period, tax_type, amount | CRITICAL |
| `BenefitPayableRequested` | REQUEST | benefícios | M12 | period, benefit_type, amount | HIGH |
| `UserProvisioningRequested` | REQUEST | onboarding | M1 | person_id, company, requested_scope | HIGH |
| `UserAccessRevocationRequested` | REQUEST | desligamento | M1 | person_id, effective_at | CRITICAL |

---

# 52. M21 — BI, Analytics e Gestão

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `AnalyticsMetricCalculated` | EVENT | cálculo materializado | M21 interno | metric_code, period/context, version | LOW |
| `AnalyticsAlertTriggered` | EVENT | regra disparou | notificações/M22 | alert_id, metric_code, severity | NORMAL |
| `AnalyticsThresholdWarning` | NOTIFICATION | WARNING | gestores | alert_id, metric, value, threshold | NORMAL |
| `AnalyticsThresholdCritical` | EVENT | CRITICAL | M22 | alert_id, metric, context | HIGH |
| `AnalyticsSnapshotCreated` | EVENT | snapshot mensal | gestão/auditoria | snapshot_id, period | NORMAL |
| `AnalyticsDataQualityIssueDetected` | EVENT | pipeline divergiu | M23/M21 admin | dataset, issue_type | NORMAL |
| `AnalyticsWorkflowRequested` | REQUEST | alerta exige ação | M22 | alert_id, recommended_workflow, context | HIGH |
| `ScheduledReportGenerated` | EVENT | relatório pronto | notification subsystem | report_id, file_ref, recipients | LOW |

Regra:

```text
M21 nunca altera transação operacional
```

---

# 53. M22 — Workflow e Aprovações

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `WorkflowCreated` | EVENT | instância criada | domínio origem/M21 | workflow_instance_id, type, source_ref | HIGH |
| `WorkflowStepActivated` | EVENT | etapa ativa | notificações | workflow_id, step_id, eligible_approvers | HIGH |
| `ApprovalRequested` | NOTIFICATION/EVENT | pendência | inbox/email | workflow_id, step_id, SLA | HIGH |
| `ApprovalCompleted` | EVENT | decisão positiva individual | audit/source | workflow_id, step_id, approver | HIGH |
| `ApprovalRejected` | EVENT | decisão negativa individual | source | workflow_id, step_id, reason | HIGH |
| `WorkflowReturnedForCorrection` | EVENT | retorno | módulo origem | workflow_id, source_ref, impacted_fields | CRITICAL |
| `WorkflowEscalated` | EVENT | SLA escalado | source/M21 | workflow_id, old/new level | HIGH |
| `WorkflowReassigned` | EVENT | reassignment | inbox/source | step_id, from_user, to_user | HIGH |
| `WorkflowApproved` | EVENT | decisão final | módulo origem | workflow_id, source_ref, approved_at | CRITICAL |
| `WorkflowRejected` | EVENT | workflow final rejeitado | módulo origem | workflow_id, reason_code | CRITICAL |
| `WorkflowCancelled` | EVENT | cancelado | módulo origem | workflow_id, reason | HIGH |
| `WorkflowSlaWarning` | NOTIFICATION | próximo vencimento | approvers | workflow_id, step_id | NORMAL |
| `WorkflowSlaBreached` | EVENT | SLA rompido | M21/admin | workflow_id, step_id | HIGH |
| `WorkflowChangeRevalidationRequired` | EVENT | fingerprint alterado | source | workflow_id, impacted_steps | HIGH |
| `WorkflowApprovalInvalidated` | EVENT | decisão invalidada | source | workflow_id, decision_ids, reason | CRITICAL |
| `WorkflowSimulationCompleted` | EVENT | simulação | admin/audit | simulation_id, result | LOW |
| `WorkflowPolicyActivated` | EVENT | nova policy | módulos solicitantes/M23 | policy_id, version, valid_from | HIGH |

---

# 54. M23 — Importação, Exportação e Data Governance

| Mensagem | Tipo | Trigger | Consumidores | Payload mínimo | Crit. |
|---|---|---|---|---|---|
| `ImportJobCreated` | EVENT | upload aceito | M21 | import_job_id, template_version | NORMAL |
| `ImportValidationCompleted` | EVENT | validation finalizada | UI/M21 | job_id, valid/error counts | NORMAL |
| `ImportPreviewReady` | EVENT | preview disponível | usuário | job_id, change_summary | NORMAL |
| `ImportApprovalRequested` | REQUEST | mudança material | M22 | job_id, data_change_request_id, fingerprint | HIGH |
| `ImportCommitted` | EVENT | commit completo | domínio/M21 | job_id, affected_domain, count | HIGH |
| `ImportPartiallyCommitted` | EVENT | valid rows only | domínio/M21 | job_id, committed_count, rejected_count | HIGH |
| `ImportFailed` | EVENT | falha | admin | job_id, phase, error_code | HIGH |
| `ExportRequested` | EVENT | job criado | worker | export_job_id, layout_id | LOW |
| `ExportCompleted` | EVENT | arquivo pronto | notification | export_job_id, file_ref, expires_at | LOW |
| `ExportFailed` | EVENT | erro | notification/admin | export_job_id, error_code | NORMAL |
| `DataQualityIssueDetected` | EVENT | regra falhou | data steward/M21 | issue_id, domain, severity | NORMAL |
| `DataQualityThresholdBreached` | EVENT | score crítico | M22/M21 | domain, score, threshold | HIGH |
| `DataQualityRemediationRequested` | REQUEST | correção necessária | M22 | issue/domain, steward_ref | HIGH |
| `DuplicateCandidateDetected` | EVENT | similaridade | módulo dono/steward | candidate_id, domain, confidence | NORMAL |
| `MergeApprovalRequested` | REQUEST | merge precisa decisão | M22 | merge_request_id, domain | HIGH |
| `DataChangeApprovalRequested` | REQUEST | bulk critical | M22 | change_request_id, fingerprint | CRITICAL |
| `DataChangeCommitted` | EVENT | alteração aplicada | domínio/M21 | change_request_id, affected_count | CRITICAL |
| `DataRetentionActionDue` | EVENT | política venceu | steward | policy_id, domain, action | NORMAL |
| `DataAnonymizationCompleted` | EVENT | anonimização concluída | audit/M21 | job_id, domain, count | HIGH |

---

# 55. Fluxo Event-Driven Order-to-Cash

```text
SalesQuoteAccepted
        │
        ▼
SalesOrderConverted
        │
        ▼
OrderCreated
        │
        ▼
InventoryReservationCreated
        │
        ▼
FulfillmentCreated
        │
        ▼
PackingCompleted
        │
        ▼
BillingRequested
        │
        ▼
InvoiceAuthorized
        │
        ├────────────► ReceivableCreated
        │
        └────────────► CommissionAccrued
        │
        ▼
ShipmentDispatched
        │
        ▼
AccountingEntryPosted
        │
        ▼
ReceivableSettled
        │
        ├────────────► CommissionEarned
        │
        └────────────► AccountingEntryPosted
```

---

# 56. Fluxo Marketplace

```text
MarketplaceOrderApproved
        │
        ▼
OrderCreated
        │
        ▼
InventoryReservationCreated
        │
        ▼
InvoiceAuthorized
        │
        ▼
MarketplaceFiscalDataSent
        │
        ▼
MarketplaceLabelAvailable
        │
        ▼
ShipmentDispatched
```

---

# 57. Fluxo Procure-to-Pay

```text
PurchaseRequisitionCreated
        │
        ▼
PurchaseApprovalRequested
        │
        ▼
WorkflowApproved
        │
        ▼
PurchaseOrderApproved
        │
        ▼
GoodsReceiptPhysicallyConfirmed
        │
        ├────► InventoryPostingCreated
        │
        └────► IncomingInspectionRequested
                        │
                        ▼
              QualityInspectionCompleted
                        │
                        ▼
             PurchaseReceiptConfirmed
                        │
                        ├────► AcquisitionCostCalculated
                        └────► PayableRequested
                                      │
                                      ▼
                               PayableCreated
                                      │
                                      ▼
                               PayableSettled
```

---

# 58. Fluxo Plan-to-Produce

```text
ProductionOrderReleased
        │
        ▼
ProductionOrderStarted
        │
        ▼
MaterialIssuedToProduction
        │
        ▼
ProductionYieldReported
        │
        ├────► InventoryPostingCreated
        ├────► Mold Cycle Update M19
        └────► Costing Consumption
        │
        ▼
FinishedGoodsReceived
        │
        ├────► Quality Inspection
        ├────► Regulatory Snapshot
        └────► Inventory
        │
        ▼
ProductionOrderClosed
        │
        ▼
ProductionOrderCostSealed
```

---

# 59. Fluxo de Manutenção

```text
Critical Failure
      │
      ▼
MaintenanceAssetUnavailable
      │
      ▼
M7 Resource Blocked
      │
      ▼
MaintenanceWorkOrderStarted
      │
      ▼
MaintenanceWorkOrderCompleted
      │
      ▼
MaintenanceWorkOrderValidated
      │
      ▼
MaintenanceAssetReleased
```

---

# 60. Fluxo de Desligamento de Colaborador

```text
EmployeeTerminated
        │
        ├────► UserAccessRevocationRequested
        │                │
        │                ▼
        │        UserAccessRevoked
        │
        └────► WorkforceMemberUnavailable
                         │
                         ▼
                       M7
```

A revogação de acesso é `CRITICAL`.

---

# 61. Fluxo Regulatório

```text
Product/BOM Change
      │
      ▼
RegulatoryChangeAssessmentRequested
      │
      ▼
RegulatoryChangeAssessmentCompleted
      │
      ├── NO_IMPACT
      └── TEST_REQUIRED / BLOCK
                     │
                     ▼
          RegulatoryProductBlocked
                     │
          ┌──────────┼───────────┐
          ▼          ▼           ▼
         M7         M11         M10
      Production   Billing     Shipping
```

---

# 62. Fluxo Data Governance

```text
ImportPreviewReady
       │
       ▼
Material Change
       │
       ▼
DataChangeApprovalRequested
       │
       ▼
M22 Workflow
       │
       ▼
WorkflowApproved
       │
       ▼
M23 revalidation
       │
       ▼
DataChangeCommitted
```

---

# 63. Eventos não Devem ser Usados como Comandos

Proibido interpretar:

```text
OrderCreated
```

como:

> Crie um pedido.

Ele significa:

> Um pedido já foi criado.

Para solicitar ação:

```text
OrderCreationRequested
```

seria outra mensagem.

---

# 64. Autorização x Efeito de Negócio

Exemplo:

```text
WorkflowApproved
```

não significa:

```text
PurchaseOrderApproved
```

Fluxo correto:

```text
WorkflowApproved
→ M6 recebe
→ valida source snapshot/fingerprint
→ altera PO
→ PurchaseOrderApproved
```

---

# 65. Contratos Síncronos que NÃO são Eventos

## M5

```text
InventoryAvailabilityQueryService
InventoryReservationService
InventoryReallocationService
```

## M9

```text
PricingResolutionService
PricingSimulationService
```

## M11

```text
FiscalPricingQuoteService
FiscalEligibilityService
```

## M12

```text
CreditDecisionService
FinancialExposureQueryService
```

## M14

```text
CustomerOperationalStatusService
```

## M17

```text
QualityEligibilityGate
```

## M18

```text
RegulatoryProductionGate
RegulatorySalesGate
RegulatoryBillingGate
RegulatoryShippingGate
```

## M19

```text
MaintenanceAssetAvailabilityService
```

## M20

```text
WorkforceAvailabilityService
```

---

# 66. Timeout Síncrono

Chamadas síncronas cross-domain deverão possuir:

```text
timeout explícito
```

Quando aplicável:

```text
circuit breaker
```

---

# 67. Falha em Gate Crítico

Em compliance, qualidade ou crédito:

```text
timeout
≠
aprovação automática
```

Padrão:

```text
FAIL CLOSED
```

quando o risco exigir.

---

# 68. Eventual Consistency e UX

Quando o efeito for assíncrono:

```text
PENDING
PROCESSING
```

devem ser estados explícitos.

Não apresentar conclusão antes do processamento real.

---

# 69. Eventos Financeiros

Qualquer valor monetário deve transportar:

```text
amount
currency_code
```

com DECIMAL serializado como string.

Exemplo:

```json
{
  "amount": "10532.4800",
  "currency_code": "BRL"
}
```

Evitar JSON float para precisão contábil.

---

# 70. Quantidades

Mesmo princípio:

```json
{
  "quantity": "950.000000",
  "uom": "KG"
}
```

---

# 71. Datas Econômicas x Timestamp Técnico

Diferenciar quando necessário:

```text
occurred_at
business_date
competence_period
due_date
settlement_date
```

---

# 72. Evento e Snapshot

Transações críticas podem transportar:

```text
snapshot_hash
```

em vez do snapshot inteiro.

Exemplo:

```text
WorkflowApproved
source_snapshot_hash
```

---

# 73. Change Fingerprint

Contrato padronizado:

```json
{
  "fingerprint_version": 1,
  "changed_fields": [
    {
      "field": "total_amount",
      "classification": "MATERIAL"
    }
  ],
  "snapshot_hash": "sha256..."
}
```

---

# 74. Regras de Consumo

Consumidor deverá:

1. validar envelope;
2. validar versão;
3. verificar Inbox;
4. validar company/branch;
5. validar payload;
6. executar transação local;
7. gerar Outbox próprio quando necessário;
8. marcar Inbox como processada;
9. ACK somente após commit.

---

# 75. Falha no Consumidor

```text
consume
↓
local transaction starts
↓
error
↓
ROLLBACK
↓
no Inbox success
↓
NACK / retry
```

Nunca marcar Inbox concluída antes do commit efetivo.

---

# 76. Evento Inválido

Payload incompatível:

```text
SCHEMA_VALIDATION_FAILED
```

Após política de retry:

```text
DLQ
```

com alerta.

---

# 77. Poison Message

Mensagens determinísticamente inválidas podem ir mais rapidamente para DLQ.

Exemplos:

```text
unknown required enum
invalid payload signature
unsupported event version
```

---

# 78. Eventos Externos

Webhook externo não é automaticamente Domain Event.

Fluxo:

```text
External Webhook
↓
M3 webhook_event/raw payload
↓
validation/fetch
↓
official external API state
↓
MarketplaceOrderApproved
```

---

# 79. Eventos do Banco

Proibido usar mudança genérica de tabela como evento de negócio.

```text
row_updated
```

não substitui:

```text
PriceActivated
```

---

# 80. Eventos para M21

M21 deve consumir fatos semanticamente relevantes:

```text
ShipmentDispatched
InvoiceAuthorized
ReceivableSettled
```

e não alterações arbitrárias de tabela.

---

# 81. Backfill Analítico

Carga histórica inicial do M21 pode utilizar pipeline incremental/batch.

Após go-live, eventos passam a ser fonte importante da atualização near real-time.

---

# 82. Auditoria de Mensageria

Devem possuir trilha auditável:

- decisões críticas;
- retries;
- DLQ;
- replay;
- intervenção manual.

---

# 83. Reenvio Manual

Usuário autorizado pode executar:

```text
Retry
Replay
```

mas não alterar silenciosamente o payload original.

Se o fato estiver incorreto:

```text
novo evento/fato corretivo
```

---

# 84. Cancelamento não Apaga Evento

Exemplo:

```text
OrderCreated
OrderCancelled
```

ambos permanecem.

---

# 85. Event Store

O ERP não será Event Sourcing integral.

```text
PostgreSQL domain tables
=
current authoritative state

Outbox/event history
=
integration/audit mechanism
```

---

# 86. Estado Atual x Evento de Integração

Exemplo:

```text
inventory.inventory_posting
```

é Ledger de domínio.

Já:

```text
InventoryPostingCreated
```

é mensagem de integração.

São conceitos diferentes.

---

# 87. Retenção de Eventos

Retenção será governada pelo M23.

Eventos críticos devem respeitar necessidade:

- fiscal;
- financeira;
- contábil;
- regulatória;
- LGPD;
- auditoria.

Não aplicar TTL curto arbitrário.

---

# 88. Critérios de Aceite da Etapa 3

A Etapa 3 é considerada implementável quando:

1. existir envelope corporativo único;
2. `message_id` for UUID;
3. message kind for explícito;
4. naming estiver padronizado;
5. routing key estiver padronizada;
6. versão estiver presente;
7. producer estiver explícito;
8. consumers estiverem explícitos;
9. payload mínimo estiver documentado;
10. criticality estiver definida;
11. Outbox for obrigatória;
12. Inbox for obrigatória para consumidores críticos;
13. at-least-once for assumido;
14. consumidores forem idempotentes;
15. retry padrão estiver definido;
16. DLQ existir;
17. reprocessamento estiver auditado;
18. correlation_id estiver presente;
19. causation_id estiver presente;
20. aggregate_version estiver disponível quando necessário;
21. eventos obsoletos puderem ser detectados;
22. dados sensíveis não forem propagados sem necessidade;
23. valores DECIMAL forem serializados sem perda;
24. eventos externos forem normalizados antes de entrar no domínio;
25. M21 não depender de CDC sem semântica;
26. M22 não alterar transações de origem;
27. M23 não substituir módulos donos dos dados;
28. eventos críticos gerarem alerta em DLQ;
29. schema/version registry existir;
30. replay não gerar efeitos duplicados;
31. contratos síncronos estiverem separados dos eventos;
32. falha de gate crítico não resultar em liberação automática;
33. workflow approval e efeito de negócio forem eventos distintos;
34. cada módulo possuir catálogo oficial mínimo;
35. toda integração cross-domain relevante possuir owner.

---

# 89. Decisões Arquiteturais Consolidadas da Etapa 3

## A. Domain Event representa fato

Não pedido de ação.

## B. Async Request é categoria própria

Exemplo:

```text
PayableRequested
```

## C. Envelope corporativo único

Todos os módulos seguem o mesmo formato.

## D. At-least-once é premissa

Idempotência é obrigatória.

## E. Outbox protege o produtor

Inbox protege o consumidor.

## F. Não existe ordenação global

`aggregate_version` é usado quando necessário.

## G. Retry possui baseline corporativa

Depois:

```text
DLQ
```

## H. DLQ não significa perda

Significa intervenção ou reprocessamento controlado.

## I. M21 recebe fatos de negócio

Não mudança aleatória de tabela.

## J. Workflow não efetiva a transação

```text
WorkflowApproved
→ domínio origem
→ BusinessEntityApproved
```

## K. Webhook externo não é fato interno

Precisa ser normalizado.

## L. Event-driven não significa tudo assíncrono

Hard gates podem utilizar contratos síncronos.

## M. Event Sourcing integral não será adotado

Ledgers específicos continuam em seus domínios.

## N. Eventos financeiros usam representação decimal segura

Sem float.

## O. Replay precisa ser seguro

Idempotência continua obrigatória.

---

# 90. Visão Final da Arquitetura de Eventos

```text
                    DOMAIN TRANSACTION
                           │
                           ▼
                     PostgreSQL
                    ┌──────┴──────┐
                    │             │
                Domain State    Outbox
                                  │
                                  ▼
                          Outbox Publisher
                                  │
                                  ▼
                              RabbitMQ
                     ┌────────────┼────────────┐
                     ▼            ▼            ▼
                 Consumer A   Consumer B   Consumer C
                     │            │            │
                     ▼            ▼            ▼
                   Inbox        Inbox        Inbox
                     │            │            │
                     ▼            ▼            ▼
              Local Transaction Local Tx   Local Tx
                     │            │            │
                     └────────────┼────────────┘
                                  ▼
                          New Domain Events
```

Rastreabilidade:

```text
request_id
    │
    ▼
correlation_id
    │
    ├── message_id A
    │       │
    │       └── causation_id → A
    │                 │
    │                 ▼
    │            message_id B
    │
    └─────────────────────────────► trace completo
```

---

# 91. Status Formal da Etapa 3

A **Etapa 3 — Catálogo Oficial de Eventos M1–M23** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- definição de contratos de mensagens;
- configuração do RabbitMQ;
- definição de exchanges;
- definição de routing keys;
- criação de filas por consumidor;
- implementação de Transactional Outbox;
- implementação de Inbox;
- definição de retries;
- DLQ;
- observabilidade;
- tracing;
- versionamento;
- consumidores;
- produtores;
- replay;
- integração com M21;
- integração com M22;
- integração com M23.

Mudança incompatível deverá ser tratada como:

```text
ARCHITECTURE CHANGE REQUEST
```

com impacto cross-domain e versionamento.

---

# 92. Próxima Etapa

A próxima fase da Consolidação Geral será:

```text
ETAPA 4
MATRIZ COMPLETA DE INTEGRAÇÕES MÓDULO × MÓDULO
```

A matriz classificará cada relação entre M1 e M23 como:

```text
SYNC
ASYNC EVENT
ASYNC REQUEST
READ MODEL
NONE
```

e documentará:

```text
direction
producer
consumer
business purpose
contract
criticality
consistency
fallback
owner
```

---

**Fim da Etapa 3 — Catálogo Oficial de Eventos M1–M23**
