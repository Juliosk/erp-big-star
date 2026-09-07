# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 2 — Modelo de Dados Consolidado M1–M23

**Status:** APROVADO  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Modelo de dados consolidado dos módulos M1–M23  
**Objetivo:** Estabelecer a estrutura lógica e física oficial do modelo de dados do ERP, cobrindo schemas, agregados, entidades, chaves, relacionamentos, referências intermodulares, ledgers, snapshots, projeções, documentos, eventos, temporalidade, índices, particionamento, classificação de dados e regras de ownership.

---

# 1. Objetivo da Etapa 2

A Etapa 2 consolida o modelo de dados que sustentará todo o ERP Big Star / Forma Kids no PostgreSQL, respeitando as fronteiras arquiteturais definidas na Etapa 1.

O objetivo desta etapa é fechar:

- estratégia física do PostgreSQL;
- separação por schemas;
- ownership de cada conjunto de tabelas;
- política de Foreign Keys;
- referências entre domínios;
- convenções de nomenclatura;
- PKs e business keys;
- snapshots históricos;
- ledgers imutáveis;
- projeções duráveis;
- entidades por módulo;
- agregados raiz;
- relacionamentos canônicos;
- temporalidade;
- precisão numérica;
- JSONB;
- Object Storage;
- auditoria;
- idempotência;
- particionamento;
- índices;
- classificação de dados;
- retenção;
- migrações;
- regras de deleção;
- regras de versionamento;
- rastreabilidade;
- lineage transacional;
- modelo analítico separado.

Esta documentação passa a ser a **referência oficial da Etapa 2 — Modelo de Dados Consolidado M1–M23**.

---

# 2. Estratégia Física do PostgreSQL

O banco OLTP será um PostgreSQL único por ambiente, dividido por schemas de domínio:

```text
erp_oltp
│
├── platform
├── admin
├── product
├── marketplace
├── orders
├── inventory
├── procurement
├── manufacturing
├── costing
├── pricing
├── wms
├── fiscal
├── finance
├── accounting
├── crm
├── sales_b2b
├── commission
├── quality
├── regulatory
├── asset_maintenance
├── hr
├── workflow
└── governance
```

O M21 ficará fisicamente separado:

```text
erp_analytics
```

A separação por schema torna o ownership explícito também no banco:

```text
inventory.inventory_balance
finance.receivable
accounting.journal_entry
workflow.workflow_instance
```

---

# 3. Política Oficial de Foreign Keys

Existirão três classes principais de referência.

| Tipo | Uso | FK Física |
|---|---|---|
| `LOCAL_FK` | Relações dentro do mesmo Bounded Context | Sim |
| `FOUNDATION_FK` | Referências muito estáveis, como Company/Branch | Permitida |
| `LOGICAL_DOMAIN_REF` | Referências entre módulos de negócio | Não, por padrão |

Exemplo local:

```text
orders.order
    │
    └── orders.order_item.order_id
```

Pode possuir FK física.

Exemplo cross-domain:

```text
orders.order.customer_id
→ crm.customer.id
```

Será referência lógica por padrão, sem FK física obrigatória entre schemas.

Motivos:

- reduzir acoplamento de migrations;
- impedir cascades cross-domain;
- facilitar futura extração de módulos;
- obrigar integração por contratos;
- permitir consistência eventual controlada;
- evitar o banco como mecanismo principal de integração.

---

# 4. Exceções Foundation

Entidades muito estáveis poderão ser referenciadas fisicamente:

```text
admin.company
admin.branch
```

Assim tabelas transacionais podem possuir:

```text
company_id UUID NOT NULL
branch_id UUID
```

com FK controlada.

`group_id` normalmente será derivado da `company`, evitando replicação desnecessária.

---

# 5. Regra de Referência entre Domínios

Referências externas devem ser explícitas.

Exemplo:

```text
orders.order.customer_id
orders.order_item.product_id
```

Evitar:

```text
generic_fk_1
generic_fk_2
```

Referências genéricas ficam reservadas a módulos transversais:

```text
workflow
governance
audit
event infrastructure
```

Exemplo:

```text
source_module
source_entity_type
source_entity_id
```

---

# 6. Snapshots para Congelamento de Contexto

Uma transação histórica não pode depender exclusivamente do cadastro atual.

Exemplo:

```text
orders.order_item.product_id
```

é mantido para navegação atual, porém o contexto histórico será congelado em:

```text
orders.order_item_snapshot
    sku
    description
    uom
    commercial_reference
    fiscal_reference
```

Da mesma forma:

```text
orders.order_customer_snapshot
```

preserva o cliente como estava na venda.

Princípio:

```text
Reference
→ permite navegação atual

Snapshot
→ prova o contexto histórico
```

---

# 7. Padrão Universal de Chave Primária

Toda entidade principal utilizará:

```sql
id UUID PRIMARY KEY
```

Número comercial será separado:

```text
order_number
purchase_order_number
production_order_number
asset_code
maintenance_tag
```

Regra:

```text
business key
≠
technical primary key
```

---

# 8. Convenções de Nomenclatura

## 8.1 Tabelas

Nomes no singular:

```text
order
order_item
customer
inventory_transaction
journal_entry
```

## 8.2 Chaves

```text
<entity>_id
```

Exemplos:

```text
product_id
company_id
customer_id
```

## 8.3 Datas

```text
created_at
updated_at

valid_from
valid_until

occurred_at
processed_at
```

## 8.4 Autor

```text
created_by
updated_by
```

quando necessário.

---

# 9. Colunas Padrão de Entidades Mutáveis

Modelo base:

```text
id UUID

company_id UUID quando aplicável
branch_id UUID quando aplicável

status

created_at TIMESTAMPTZ
created_by UUID

updated_at TIMESTAMPTZ
updated_by UUID

version INTEGER
```

`version` será usada para optimistic locking.

---

# 10. Entidades Imutáveis

Ledgers e fatos confirmados não devem ter semântica de atualização ordinária.

Exemplos:

```text
inventory.inventory_posting
workflow.approval_decision
accounting.journal_entry_line após POSTED
hr.time_punch
commission.commission_earning
```

Preferencialmente usam:

```text
created_at
occurred_at
```

sem operações normais de UPDATE.

---

# 11. Temporalidade

Para políticas e cadastros históricos:

```text
valid_from TIMESTAMPTZ
valid_until TIMESTAMPTZ NULL
```

Opcionalmente:

```text
is_current
```

como projeção otimizada.

Regra:

```text
is_current
≠
substituto da vigência temporal
```

---

# 12. Precisões Numéricas Corporativas

Baseline recomendada:

```text
Money:
NUMERIC(19,4)

Quantity:
NUMERIC(19,6)

Weight:
NUMERIC(19,6)

Rates:
NUMERIC(19,8)

Percent:
NUMERIC(12,8)

Hours:
NUMERIC(19,6)
```

Nunca utilizar `FLOAT` para dados críticos.

---

# 13. Moeda

Valores monetários relevantes devem suportar:

```text
currency_code CHAR(3)
```

Padrão ISO 4217.

Mesmo com operação predominante em BRL, o modelo nasce preparado para múltiplas moedas.

---

# 14. Horário

Eventos e timestamps:

```text
TIMESTAMPTZ
```

Empresa/filial manterá:

```text
timezone
```

para interpretação local.

---

# 15. Uso de JSONB

Permitido para:

- payload externo;
- snapshot técnico;
- atributos dinâmicos de marketplace;
- headers de evento;
- resposta bruta de API;
- metadados;
- diff de importação.

Não permitido como substituto do modelo relacional principal.

Errado:

```text
order.data JSONB
```

contendo o pedido inteiro.

Correto:

```text
order
order_item
order_customer_snapshot
```

com JSONB apenas complementar.

---

# 16. Schema `platform`

O schema `platform` contém infraestrutura compartilhada e não representa um módulo funcional.

Principais entidades:

```text
platform.outbox_event
platform.inbox_event
platform.audit_event
platform.file_object
platform.reason_code
platform.idempotency_record
```

---

# 17. `platform.outbox_event`

Estrutura consolidada:

```text
id UUID

event_id UUID UNIQUE

event_type
event_version

aggregate_type
aggregate_id

source_module

occurred_at

payload JSONB
headers JSONB

correlation_id
causation_id
request_id

published_at
publish_attempts
last_error
```

---

# 18. `platform.inbox_event`

```text
id UUID

consumer_name
event_id

event_type
event_version

received_at
processed_at

status
attempts

last_error
```

Restrição:

```text
UNIQUE (consumer_name, event_id)
```

---

# 19. Auditoria

`platform.audit_event` será append-only.

Campos principais:

```text
id

actor_user_id

company_id
branch_id

module
entity_type
entity_id

operation

before_snapshot
after_snapshot

reason_code

occurred_at

request_id
correlation_id

source_ip
device_metadata
```

Dados sensíveis devem ser mascarados antes da gravação.

---

# 20. Arquivos

`platform.file_object`:

```text
id UUID

storage_provider
bucket
storage_key

original_filename
mime_type
size_bytes

sha256

classification

created_at
created_by

retention_until
```

O significado do arquivo é dado pela entidade de negócio que o referencia.

Exemplo:

```text
regulatory.regulatory_certificate_document
→ file_object_id
```

---

# 21. M1 — Schema `admin`

## Aggregate Roots

```text
economic_group
company
branch
user
role
permission
```

## Principais tabelas

```text
admin.economic_group
admin.company
admin.branch

admin.user
admin.user_identity

admin.role
admin.permission

admin.user_role
admin.role_permission

admin.user_scope

admin.security_policy
admin.security_event
```

Relacionamento:

```text
economic_group
  1
  │
  N
company
  1
  │
  N
branch
```

---

# 22. M2 — Schema `product`

## Aggregate Roots

```text
product
bom
```

## Principais entidades

```text
product.product
product.product_variant

product.product_barcode

product.product_packaging
product.product_packaging_level

product.product_attribute
product.product_attribute_value

product.product_fiscal_master

product.bom
product.bom_revision
product.bom_item

product.product_media

product.marketplace_product_reference
```

Tipos:

```text
PA
PI
MA
AUX
EMB
KIT
```

Lifecycle:

```text
EM_DESENVOLVIMENTO
EM_HOMOLOGACAO
ATIVO
FORA_DE_LINHA
```

---

# 23. BOM Consolidada

Ownership:

```text
M2
→ estrutura material oficial e revisão BOM

M7
→ usa a revisão dentro da Production Version
```

Estrutura:

```text
product.bom
    │
    └── product.bom_revision
            │
            └── product.bom_item
```

M7 armazena:

```text
bom_revision_id
```

como referência lógica.

---

# 24. KIT

KIT continua sem estoque físico próprio.

A composição comercial será congelada em:

```text
orders.order_item_component_snapshot
```

M5 não mantém saldo físico de KIT virtual.

---

# 25. M3 — Schema `marketplace`

## Aggregate Roots

```text
marketplace_account
marketplace_listing
marketplace_sync_job
```

## Tabelas

```text
marketplace.marketplace
marketplace.marketplace_account

marketplace.marketplace_credential

marketplace.marketplace_listing
marketplace.marketplace_listing_product

marketplace.webhook_event

marketplace.marketplace_sync_job
marketplace.marketplace_sync_attempt

marketplace.marketplace_order_snapshot

marketplace.channel_payload_snapshot

marketplace.channel_rate_limit_state
```

Referência principal:

```text
marketplace_listing.product_id
→ M2
```

---

# 26. M4 — Schema `orders`

## Aggregate Root

```text
order
```

## Principais tabelas

```text
orders.order
orders.order_item

orders.order_customer_snapshot
orders.order_item_snapshot
orders.order_item_component_snapshot

orders.fulfillment_order
orders.fulfillment_item

orders.order_hold

orders.order_status_history

orders.order_billing_request

orders.order_financial_bridge
```

---

# 27. Referências Principais do Pedido

```text
order.customer_id
→ M14

order_item.product_id
→ M2

order.source_marketplace_account_id
→ M3
```

Essas referências não concedem à M4 permissão de alterar dados externos.

---

# 28. Estados Independentes no Pedido

Manter separadamente:

```text
order_status
fulfillment_status
billing_status
financial_status
```

Princípio:

```text
Order
≠
Fulfillment
≠
Billing
≠
Finance
```

---

# 29. M5 — Schema `inventory`

M5 é um dos domínios mais rigorosos.

## Aggregate Roots

```text
warehouse
inventory_transaction
inventory_reservation
inventory_transfer
cycle_count
```

## Principais tabelas

```text
inventory.warehouse
inventory.location

inventory.inventory_pool

inventory.inventory_lot

inventory.inventory_transaction
inventory.inventory_posting

inventory.inventory_balance

inventory.inventory_reservation
inventory.inventory_reservation_allocation

inventory.inventory_transfer
inventory.inventory_transfer_item

inventory.inventory_discrepancy

inventory.cycle_count
inventory.cycle_count_item
```

---

# 30. Ledger de Estoque

Estrutura:

```text
inventory_transaction
    │
    └── inventory_posting
```

`inventory_posting` é imutável.

Granularidade:

```text
product
warehouse
location
lot
pool
inventory_state
quantity
```

---

# 31. `inventory_balance`

É projeção durável transacional atualizada na mesma transação do Ledger.

Chave lógica aproximada:

```text
product_id
warehouse_id
location_id
lot_id
pool_id
inventory_state
```

Não é cache Redis.

---

# 32. Estados de Estoque

```text
AVAILABLE
RESERVED
QUARANTINE
DAMAGED
BLOCKED
IN_TRANSIT
RECEIVING_STAGE
```

---

# 33. M6 — Schema `procurement`

## Aggregate Roots

```text
supplier
purchase_requisition
rfq
purchase_order
goods_receipt
three_way_match
```

## Principais tabelas

```text
procurement.supplier
procurement.supplier_site

procurement.product_supplier
procurement.product_supplier_uom

procurement.purchase_requisition
procurement.purchase_requisition_item

procurement.rfq
procurement.rfq_supplier
procurement.supplier_quote
procurement.supplier_quote_item

procurement.purchase_order
procurement.purchase_order_item

procurement.goods_receipt
procurement.goods_receipt_item
procurement.receipt_measurement

procurement.supplier_invoice_snapshot

procurement.three_way_match
procurement.three_way_match_item

procurement.supplier_claim

procurement.acquisition_cost_allocation
```

---

# 34. Consolidação M6 x M11

Fronteira:

```text
M11
→ autoridade do documento fiscal

M6
→ autoridade do match operacional da compra
```

Assim:

```text
procurement.supplier_invoice_snapshot
```

é apenas snapshot/referência operacional.

O documento oficial é:

```text
fiscal.fiscal_document
```

M6 mantém:

```text
fiscal_document_id
```

como referência lógica.

---

# 35. M7 — Schema `manufacturing`

## Aggregate Roots

```text
work_center
manufacturing_routing
production_version
production_order
```

## Principais tabelas

```text
manufacturing.work_center
manufacturing.work_center_resource

manufacturing.manufacturing_routing
manufacturing.routing_revision
manufacturing.routing_operation

manufacturing.production_version

manufacturing.production_order
manufacturing.production_order_batch

manufacturing.production_order_component

manufacturing.material_issue
manufacturing.material_issue_item

manufacturing.production_yield_log

manufacturing.scrap_log
manufacturing.rework_log

manufacturing.secondary_material_recovery

manufacturing.lot_genealogy_link
```

---

# 36. Production Version

Congela:

```text
product_id
bom_revision_id
routing_revision_id
validity
```

A OP congela:

```text
production_version_id
```

e nunca segue automaticamente a revisão corrente.

---

# 37. Genealogia

`lot_genealogy_link` deve permitir:

```text
PA lot
→ OP
→ PI lot
→ component/material lot
→ supplier lot
```

Essencial para M17, M18 e recall.

---

# 38. M8 — Schema `costing`

## Aggregate Roots

```text
standard_cost
production_order_cost
costing_period
```

## Tabelas

```text
costing.standard_cost_policy
costing.standard_cost_version
costing.standard_cost_component

costing.replacement_cost

costing.machine_rate
costing.labor_rate

costing.production_order_cost
costing.production_order_cost_component

costing.cost_variance

costing.inventory_moving_average

costing.post_close_cost_variance

costing.costing_period
```

---

# 39. Quantidade x Valor de Estoque

Fronteira:

```text
M5
→ quantidade física

M8
→ valoração
```

`inventory.inventory_posting` pode ser referenciado por `costing.inventory_moving_average`, mas M8 nunca altera quantidade.

---

# 40. M9 — Schema `pricing`

## Aggregate Roots

```text
price_list
pricing_policy
pricing_batch
```

## Tabelas

```text
pricing.price_list
pricing.price_list_version
pricing.price_list_item

pricing.pricing_policy
pricing.pricing_rule

pricing.minimum_margin_policy

pricing.marketplace_fee_policy
pricing.freight_provision_policy

pricing.pricing_snapshot

pricing.price_review

pricing.pricing_batch
pricing.pricing_batch_item
```

---

# 41. Snapshot de Preço

Cada preço aprovado poderá guardar:

```text
cost_reference
tax_reference
commission_reference
fee_reference
freight_reference

target_margin
minimum_margin

calculated_price
rounded_price

policy_versions
```

Isso impede recalcular passado com parâmetros atuais.

---

# 42. M10 — Schema `wms`

## Aggregate Roots

```text
picking_wave
picking_task
package
shipment
```

## Tabelas

```text
wms.picking_wave
wms.picking_wave_order

wms.picking_task
wms.picking_task_item

wms.picking_scan

wms.package
wms.package_item

wms.packing_verification

wms.shipping_label
wms.label_reprint

wms.shipment
wms.shipment_package

wms.shipping_manifest

wms.dispatch_event
```

---

# 43. M10 não Possui Saldo

Referências:

```text
picking_task
→ M4 fulfillment

inventory allocation
→ M5 reservation
```

Toda movimentação física real é comandada ao M5.

---

# 44. M11 — Schema `fiscal`

## Aggregate Roots

```text
fiscal_document
tax_rule
fiscal_series
```

## Principais tabelas

```text
fiscal.fiscal_establishment
fiscal.fiscal_profile

fiscal.tax_rule
fiscal.tax_rule_version
fiscal.tax_rule_condition

fiscal.fiscal_document_intent

fiscal.fiscal_document
fiscal.fiscal_document_item
fiscal.fiscal_tax_component

fiscal.fiscal_rule_application

fiscal.fiscal_series
fiscal.fiscal_sequence

fiscal.fiscal_invalidation

fiscal.fiscal_cancellation
fiscal.fiscal_correction

fiscal.fiscal_document_reference

fiscal.provider_exchange
```

---

# 45. Documento Fiscal Autorizado

Depois de autorizado:

```text
fiscal_document
```

é imutável em sua essência.

Correções ocorrem por:

```text
cancellation
correction
return
complementary document
```

---

# 46. M12 — Schema `finance`

## Aggregate Roots

```text
receivable
payable
financial_account
bank_reconciliation
marketplace_settlement
```

## Tabelas

```text
finance.financial_account

finance.receivable
finance.receivable_installment
finance.receivable_component

finance.receivable_genealogy

finance.payable
finance.payable_installment
finance.payable_component

finance.financial_settlement
finance.settlement_allocation
finance.settlement_reversal

finance.payment_request
finance.payment_batch
finance.payment_batch_item

finance.bank_statement_import
finance.bank_movement

finance.financial_match

finance.provisional_financial_entry

finance.marketplace_settlement
finance.marketplace_settlement_line

finance.receivable_anticipation

finance.credit_exposure

finance.cash_flow_projection
```

---

# 47. Receivable não é Invoice

Referência:

```text
receivable.source_fiscal_document_id
```

não significa identidade entre entidades.

Um documento fiscal pode gerar múltiplos títulos.

---

# 48. Settlement N:N

Modelo:

```text
financial_settlement
    │
    └── settlement_allocation
            ├── receivable
            └── payable quando aplicável
```

Suporta:

- pagamento parcial;
- agrupamento;
- diferenças;
- renegociação.

---

# 49. M13 — Schema `accounting`

## Aggregate Roots

```text
chart_of_accounts
accounting_rule
journal_entry
accounting_period
```

## Tabelas

```text
accounting.account
accounting.account_hierarchy

accounting.account_mapping

accounting.accounting_dimension
accounting.dimension_value

accounting.accounting_rule
accounting.accounting_rule_version
accounting.accounting_rule_line

accounting.accounting_event_inbox

accounting.journal_entry
accounting.journal_entry_line

accounting.accounting_period

accounting.accounting_allocation_rule
accounting.accounting_allocation

accounting.intercompany_match
accounting.consolidation_entry

accounting.accounting_reconciliation

accounting.statement_structure
accounting.statement_structure_line
```

---

# 50. Journal Entry

Regra:

```text
SUM(debit)
=
SUM(credit)
```

Depois de:

```text
POSTED
```

não editar.

Correção:

```text
reversal
+
replacement
```

---

# 51. M14 — Schema `crm`

## Aggregate Root

```text
customer
```

## Tabelas

```text
crm.customer

crm.customer_group
crm.customer_group_member

crm.customer_contact
crm.customer_address

crm.customer_interaction
crm.customer_task

crm.customer_consent

crm.customer_status_history

crm.customer_merge
crm.customer_merge_history

crm.customer_external_identity
```

---

# 52. Golden Record de Cliente

```text
crm.customer
```

é o cadastro canônico.

Marketplaces podem manter:

```text
customer_external_identity
```

mas não substituir o master.

---

# 53. M15 — Schema `sales_b2b`

## Aggregate Roots

```text
sales_quote
sales_portfolio
commercial_policy
delivery_schedule
```

## Tabelas

```text
sales_b2b.sales_quote
sales_b2b.sales_quote_item

sales_b2b.quote_revision
sales_b2b.quote_revision_item

sales_b2b.quote_loss

sales_b2b.sales_portfolio
sales_b2b.sales_portfolio_assignment
sales_b2b.sales_territory

sales_b2b.commercial_policy
sales_b2b.commercial_policy_condition
sales_b2b.commercial_policy_evaluation

sales_b2b.credit_exception_reference

sales_b2b.delivery_schedule
sales_b2b.delivery_schedule_item

sales_b2b.payment_term
sales_b2b.freight_term

sales_b2b.commercial_bonus_item

sales_b2b.sales_order_conversion

sales_b2b.sales_order_change_request
```

---

# 54. Consolidação das Aprovações do M15

Conceitos antigos como:

```text
sales_approval_request
```

não serão motor de aprovação.

Modelo consolidado:

```text
M15
→ approval_requirement / workflow_reference

M22
→ workflow_instance + approval_decision
```

---

# 55. Regra Geral para Módulos com Aprovação

Nenhum módulo terá entidade autoritativa própria:

```text
*_approval
```

com decisão humana final.

A fonte será:

```text
workflow.workflow_instance
workflow.approval_decision
```

O domínio pode manter somente:

```text
workflow_instance_id
approval_status_projection
```

para leitura otimizada.

---

# 56. M16 — Schema `commission`

## Aggregate Roots

```text
commission_rule
commission_origin
commission_period
commission_statement
```

## Tabelas

```text
commission.commission_beneficiary

commission.commission_assignment

commission.commission_rule
commission.commission_rule_version

commission.commission_snapshot

commission.commission_origin

commission.commission_base_snapshot

commission.commission_split

commission.commission_accrual

commission.commission_earning

commission.commission_receivable_link

commission.commission_reversal
commission.commission_clawback

commission.commission_adjustment

commission.commission_period

commission.commission_statement
commission.commission_statement_line

commission.commission_supporting_document
```

---

# 57. Imutabilidade Histórica da Comissão

Assignment/rule/split:

```text
congelados na conversão do pedido
```

Base:

```text
calculada sobre a NF
```

Earning:

```text
somente no settlement
```

---

# 58. M17 — Schema `quality`

## Aggregate Roots

```text
quality_inspection_plan
quality_inspection
nonconformity
capa
recall
measurement_instrument
```

## Tabelas

```text
quality.quality_inspection_plan
quality.quality_inspection_plan_version
quality.quality_inspection_characteristic

quality.quality_inspection
quality.inspection_measurement

quality.quality_disposition

quality.quality_hold
quality.quality_containment

quality.quality_temporary_deviation

quality.nonconformity

quality.capa
quality.capa_action

quality.supplier_quality_profile
quality.supplier_product_quality_status

quality.customer_quality_complaint

quality.recall
quality.recall_lot
quality.recall_customer
quality.recall_action

quality.measurement_instrument
quality.calibration_schedule
quality.calibration_record
```

---

# 59. Qualidade x Estoque

M17 decide:

```text
APPROVE
QUARANTINE
REJECT
PARTIAL_ACCEPTANCE
```

M5 executa a mudança física de estado.

M17 nunca altera `inventory_balance` diretamente.

---

# 60. M18 — Schema `regulatory`

## Aggregate Roots

```text
regulatory_family
regulatory_certification_process
regulatory_certificate
regulatory_change_assessment
regulatory_block
```

## Tabelas

```text
regulatory.regulatory_family
regulatory.regulatory_family_member

regulatory.regulatory_test_subgroup
regulatory.regulatory_scope

regulatory.certification_body
regulatory.accredited_laboratory

regulatory.regulatory_commercial_proposal

regulatory.regulatory_certification_process
regulatory.regulatory_process_milestone

regulatory.regulatory_sample
regulatory.regulatory_counter_sample

regulatory.regulatory_test
regulatory.regulatory_test_result
regulatory.regulatory_report

regulatory.regulatory_certificate
regulatory.regulatory_certificate_report_link

regulatory.regulatory_renewal_schedule
regulatory.regulatory_task

regulatory.regulatory_change_assessment

regulatory.regulatory_packaging_approval

regulatory.regulatory_compliance_snapshot

regulatory.regulatory_lot_status

regulatory.regulatory_block

regulatory.regulatory_audit
regulatory.regulatory_finding
regulatory.regulatory_nonconformity
```

---

# 61. Regulatory Snapshot por Lote

Imutável:

```text
lot
certificate
reports
bom_revision
production_version
packaging_version
change_assessment
manufactured_at
```

Serve como prova histórica.

Bloqueio de segurança corrente pode sobrepor grandfathering.

---

# 62. M19 — Schema `asset_maintenance`

Dois Aggregate Roots independentes:

```text
fixed_asset
maintenance_asset
```

## Principais tabelas

```text
asset_maintenance.fixed_asset
asset_maintenance.fixed_asset_class
asset_maintenance.fixed_asset_movement

asset_maintenance.asset_book
asset_maintenance.asset_depreciation_schedule
asset_maintenance.asset_depreciation_entry

asset_maintenance.asset_capitalization

asset_maintenance.maintenance_asset

asset_maintenance.mold_asset
asset_maintenance.mold_machine_compatibility
asset_maintenance.mold_location_history

asset_maintenance.maintenance_meter
asset_maintenance.maintenance_meter_reading

asset_maintenance.maintenance_plan

asset_maintenance.maintenance_request
asset_maintenance.maintenance_work_order

asset_maintenance.maintenance_failure
asset_maintenance.asset_downtime

asset_maintenance.maintenance_material_consumption
asset_maintenance.maintenance_labor_entry
asset_maintenance.maintenance_external_service

asset_maintenance.maintenance_actual_cost

asset_maintenance.asset_document
asset_maintenance.asset_document_version
```

---

# 63. Fixed Asset x Maintenance Asset

Relacionamento opcional:

```text
maintenance_asset.fixed_asset_id
```

Casos válidos:

```text
fixed asset sem maintenance asset
maintenance asset sem fixed asset
ambos vinculados
```

---

# 64. M20 — Schema `hr`

## Aggregate Roots

```text
person
employment_contract
third_party_engagement
time_period
vacation_entitlement
payroll_batch
```

## Tabelas

```text
hr.person

hr.employment_contract
hr.third_party_engagement

hr.workforce_member

hr.department
hr.organizational_unit

hr.job_position
hr.job_position_version

hr.employee_assignment

hr.labor_union
hr.collective_agreement

hr.work_schedule
hr.work_shift
hr.work_calendar

hr.time_device
hr.time_import_batch
hr.time_punch

hr.time_rule_policy
hr.time_rule_policy_version

hr.time_daily_calculation

hr.time_adjustment_request
hr.time_adjustment_approval_projection

hr.overtime_authorization_request

hr.time_bank_transaction
hr.time_bank_balance

hr.time_period

hr.vacation_entitlement_period
hr.vacation_request
hr.vacation_schedule

hr.employee_absence

hr.benefit_plan
hr.employee_benefit

hr.salary_advance

hr.onboarding_process
hr.onboarding_task

hr.offboarding_process
hr.offboarding_task

hr.payroll_export_batch
hr.payroll_export_event

hr.payroll_import_batch
hr.payroll_result
hr.payroll_result_component

hr.loaded_labor_rate

hr.employee_document
hr.employment_document
```

---

# 65. Pessoa x Vínculo

```text
person
  │
  ├── employment_contract
  │       CLT / ESTAGIÁRIO
  │
  └── third_party_engagement
          PJ / TERCEIRIZADO
```

`person` é única no grupo.

Novo vínculo cria novo contrato/engagement.

---

# 66. Time Punch

`hr.time_punch` é imutável.

Correção:

```text
time_adjustment_request
```

Aprovação formal:

```text
M22
```

A tabela local mantém somente projeção do workflow.

---

# 67. M21 — Banco `erp_analytics`

M21 não fica no OLTP.

Estrutura sugerida:

```text
erp_analytics
├── dim
├── fact
├── semantic
└── analytics_admin
```

---

# 68. Dimensões SCD Tipo 2

Exemplos:

```text
dim.date
dim.company
dim.branch

dim.customer
dim.product
dim.supplier

dim.seller
dim.representative

dim.channel

dim.warehouse

dim.work_center
dim.machine
dim.mold

dim.cost_center
dim.department
```

Campos:

```text
surrogate_key
source_id
valid_from
valid_until
is_current
```

---

# 69. Fatos Analíticos Principais

```text
fact.sales
fact.order
fact.inventory_movement
fact.inventory_daily_snapshot

fact.purchase

fact.production
fact.scrap

fact.receivable
fact.payable

fact.cash

fact.quality

fact.maintenance

fact.hr

fact.commission
```

Toda fact table deve possuir grain explícito.

Exemplo:

```text
fact.sales
grain = invoice item
```

---

# 70. Semantic Layer

Tabelas administrativas:

```text
semantic.metric_definition
semantic.metric_version

semantic.management_target

semantic.management_budget
semantic.budget_version

semantic.alert_rule
```

---

# 71. M22 — Schema `workflow`

## Aggregate Roots

```text
workflow_definition
approval_policy
workflow_instance
approval_delegation
```

## Tabelas

```text
workflow.workflow_definition
workflow.workflow_version

workflow.workflow_step_definition
workflow.workflow_transition_definition

workflow.approval_policy
workflow.approval_policy_rule

workflow.workflow_instance
workflow.workflow_step_instance

workflow.approver_resolution_rule
workflow.workflow_step_eligible_approver

workflow.approval_group
workflow.approval_group_member

workflow.approval_decision

workflow.approval_delegation

workflow.workflow_sla_policy
workflow.workflow_escalation_rule
workflow.workflow_escalation_event

workflow.workflow_change_policy

workflow.workflow_notification_template
workflow.workflow_notification

workflow.workflow_sod_policy

workflow.workflow_simulation
workflow.workflow_test_case
```

---

# 72. Referência Genérica do Workflow

Como o M22 atende a todos os módulos:

```text
source_module
source_entity_type
source_entity_id
source_business_key
```

ficam em `workflow_instance`.

Não criar pares de FKs por módulo.

---

# 73. Approval Decision

Append-only:

```text
workflow_instance_id
step_instance_id

approver_user_id

decision

reason_code
comment

acting_on_behalf_of

authentication_level

source_snapshot_hash

decided_at
```

---

# 74. M23 — Schema `governance`

## Aggregate Roots

```text
import_template
import_job
export_job
data_domain
data_quality_issue
merge_request
data_change_request
```

## Tabelas

```text
governance.import_template
governance.import_template_version
governance.import_field_definition
governance.import_field_permission

governance.import_job
governance.import_staging_row
governance.import_validation_result
governance.import_commit_batch

governance.match_key_policy

governance.data_change_request

governance.export_definition
governance.export_layout
governance.export_job

governance.data_domain
governance.data_owner_assignment
governance.data_steward_assignment

governance.golden_record_policy

governance.data_quality_rule
governance.data_quality_issue
governance.data_quality_score

governance.duplicate_candidate
governance.merge_request
governance.merge_survivorship_rule

governance.data_lineage
governance.data_change_audit

governance.data_classification_policy
governance.data_retention_policy
governance.data_anonymization_job

governance.migration_reconciliation
```

---

# 75. Staging não é Domínio

`import_staging_row` nunca é cadastro definitivo.

Fluxo:

```text
STAGING
→ validation
→ preview
→ commit
→ domain table
```

---

# 76. Classificação Estrutural das Tabelas

Todas as tabelas devem pertencer a uma categoria.

| Categoria | Exemplo |
|---|---|
| `MASTER` | product, customer, supplier |
| `TRANSACTION` | order, purchase_order |
| `LEDGER` | inventory_posting, time_bank_transaction |
| `SNAPSHOT` | order_customer_snapshot |
| `POLICY` | pricing_policy |
| `VERSION` | workflow_version |
| `DOCUMENT` | fiscal_document |
| `EVENT` | outbox_event |
| `PROJECTION` | inventory_balance |
| `STAGING` | import_staging_row |
| `AUDIT` | audit_event |
| `ANALYTICAL` | fact.sales |

Essa classificação será registrada na documentação do schema.

---

# 77. Relação Canônica Comercial

```text
crm.customer
       │
       ▼
sales_b2b.sales_quote
       │
       ▼
orders.order
       │
       ├─────────► inventory.inventory_reservation
       │
       ▼
orders.fulfillment_order
       │
       ▼
wms.shipment
       │
       ├─────────► fiscal.fiscal_document
       │
       ▼
finance.receivable
       │
       ▼
finance.financial_settlement
       │
       ├─────────► commission.commission_earning
       │
       └─────────► accounting.journal_entry
```

---

# 78. Relação Canônica de Compras

```text
procurement.supplier
        │
        ▼
purchase_requisition
        │
        ▼
purchase_order
        │
        ▼
goods_receipt
        │
        ├────────► inventory.inventory_posting
        ├────────► quality.quality_inspection
        └────────► fiscal.fiscal_document
                         │
                         ▼
                  finance.payable
                         │
                         ▼
                  financial_settlement
                         │
                         ▼
                  accounting.journal_entry
```

---

# 79. Relação Canônica Industrial

```text
product.product
      │
      ▼
product.bom_revision
      │
      ├──────────────┐
      │              │
      ▼              ▼
manufacturing.routing_revision
      │
      ▼
manufacturing.production_version
      │
      ▼
manufacturing.production_order
      │
      ├────► M17 Quality
      ├────► M18 Regulatory
      ├────► M19 Maintenance Availability
      │
      ▼
inventory.inventory_lot
      │
      ▼
costing.production_order_cost
      │
      ▼
pricing.price calculation
```

---

# 80. Relação Canônica RH → Produção → Custos

```text
hr.person
    │
    ▼
employment_contract
    │
    ▼
employee_assignment
    │
    ├────► work_shift
    ├────► cost_center
    └────► work_center eligibility
                 │
                 ▼
         manufacturing
                 │
                 ▼
          costing via
       loaded_labor_rate
```

---

# 81. Relação Canônica Ativo → Manutenção → Produção

```text
fixed_asset
    │ optional
    ▼
maintenance_asset
    │
    ├────► maintenance_plan
    ├────► maintenance_work_order
    ├────► meter/cycle
    │
    ▼
MaintenanceAssetUnavailable
    │
    ▼
manufacturing.work_center_resource
```

---

# 82. Política de DELETE

Regra:

```text
Business data
→ no hard delete
```

Preferir:

```text
status
valid_until
cancelled_at
superseded
```

Hard delete apenas para:

- drafts nunca publicados;
- registros técnicos temporários;
- staging expirado;
- arquivos temporários conforme retenção.

Nunca utilizar `ON DELETE CASCADE` entre domínios.

---

# 83. Índices Obrigatórios

Agregados transacionais deverão possuir índices adequados a:

```text
company_id
branch_id
status
created_at
business_number
```

Exemplo:

```sql
(company_id, status, created_at DESC)
```

---

# 84. Índices de Business Keys

Exemplos:

```text
product.sku UNIQUE

product_barcode.barcode UNIQUE conforme política

order:
UNIQUE(source_account_id, external_order_id)

supplier:
UNIQUE(company_scope, tax_id) conforme política

customer:
índices para CPF/CNPJ

fixed_asset:
UNIQUE(company_id, asset_code)

maintenance_asset:
UNIQUE(company_id, maintenance_tag)
```

---

# 85. Índices Temporais

Entidades versionadas precisarão de otimização para:

```text
valid_from
valid_until
```

Quando necessário, usar constraints que impeçam vigências conflitantes.

PostgreSQL poderá usar:

```text
EXCLUDE constraints
```

em entidades críticas.

---

# 86. Particionamento Inicial

Não particionar tudo prematuramente.

Candidatas de alto volume:

```text
platform.outbox_event
platform.inbox_event
platform.audit_event

marketplace.webhook_event

inventory.inventory_posting

manufacturing.production_yield_log

finance.bank_movement

hr.time_punch

governance.import_staging_row
```

Preferência:

```text
RANGE por mês / occurred_at
```

quando volume justificar.

---

# 87. Particionamento Analítico

Facts podem ser particionadas por data.

Exemplos:

```text
fact.sales
→ invoice_date

fact.inventory_movement
→ movement_date

fact.production
→ production_date
```

---

# 88. Retenção Operacional

Retenção não será hardcoded no banco.

M23 fornecerá:

```text
data_retention_policy
```

Ações:

```text
retain
archive
anonymize
delete when legally allowed
```

---

# 89. Classificação de Dados

Classes oficiais:

```text
PUBLIC_INTERNAL
CONFIDENTIAL
RESTRICTED
PERSONAL_DATA
SENSITIVE_BUSINESS
```

---

# 90. Exemplos de Classificação

| Domínio | Dados | Classe |
|---|---|---|
| M1 | credenciais | RESTRICTED |
| M12 | contas bancárias | RESTRICTED |
| M14 | CPF/endereço/contatos | PERSONAL_DATA |
| M20 | documentos pessoais | PERSONAL_DATA |
| M20 | salário individual | RESTRICTED |
| M9 | estratégia de margem | SENSITIVE_BUSINESS |
| M8 | custo industrial | SENSITIVE_BUSINESS |
| M18 | certificado | conforme documento |
| M21 | KPI executivo | CONFIDENTIAL |

---

# 91. Criptografia e Segredos

Tokens OAuth, credenciais e segredos:

```text
nunca em texto claro
```

Devem possuir:

- criptografia em repouso;
- acesso restrito;
- masking;
- rotação;
- ausência em logs.

Preferir:

```text
secret_reference
```

ou armazenamento criptografado isolado.

---

# 92. Multiempresa nas Tabelas

Toda entidade jurídica/transacional deve avaliar explicitamente:

```text
company_id
```

e quando necessário:

```text
branch_id
```

Não assumir contexto jurídico somente pela sessão.

---

# 93. Company Snapshot

Em documentos juridicamente críticos pode ser necessário congelar:

```text
company legal data
branch fiscal data
```

Exemplo:

```text
fiscal_document
```

---

# 94. Approval Projection

Para leitura otimizada, um domínio pode manter:

```text
approval_status
workflow_instance_id
```

Mas:

```text
approval_status projection
≠
fonte da decisão
```

Fonte:

```text
workflow.approval_decision
```

---

# 95. Analytics Projection

Read models de analytics nunca se tornam System of Record.

```text
dashboard/read model
≠
operational truth
```

---

# 96. Estado Derivado x Estado Autoritativo

Exemplos de estados derivados:

```text
inventory_balance
→ projeção do ledger

time_bank_balance
→ projeção do ledger de banco de horas

customer_operational_status
→ projeção de múltiplos domínios

available_kit_quantity
→ derivação dos componentes
```

---

# 97. Rebuildability

Read models importantes devem ser reconstruíveis.

```text
inventory_balance
← inventory_posting
```

```text
time_bank_balance
← time_bank_transaction
```

```text
analytics facts
← source events / extracts
```

---

# 98. Idempotency Keys de Negócio

Além de `event_id`, operações externas devem possuir chaves próprias.

Exemplos:

```text
Marketplace:
account + external_order_id

Workflow:
workflow_request_key

M23:
external_batch_id / checksum

Fiscal:
issuance_intent_id

Payment:
payment_request_key
```

---

# 99. Dados de Integração Externa

Payload bruto não substitui o modelo normalizado.

Pode ser preservado em:

```text
raw_request
raw_response
external_payload_snapshot
```

usando JSONB ou Object Storage conforme tamanho.

---

# 100. Migrações Alembic

Cada módulo será responsável pelas próprias tabelas.

Estrutura recomendada:

```text
modules/inventory/migrations/
modules/finance/migrations/
...
```

Migration de um módulo não deve executar:

```text
DROP/ALTER
```

em tabelas de outro módulo sem Architecture Change Request.

---

# 101. Convenção de Aggregate Root

Somente Aggregate Roots devem ser manipulados diretamente por serviços externos ao domínio.

Exemplo:

```text
PurchaseOrderService
```

opera o agregado `purchase_order`.

Não expor alteração arbitrária de `purchase_order_item` fora do agregado.

---

# 102. Agregados Especialmente Críticos

Precisam de regras transacionais fortes:

```text
inventory_transaction
order
purchase_order
production_order
fiscal_document
receivable
payable
journal_entry
workflow_instance
import_job
```

---

# 103. Transações Curtas

Não manter transação PostgreSQL aberta enquanto aguarda:

- marketplace;
- banco;
- SEFAZ;
- usuário;
- workflow;
- arquivo remoto.

Padrão:

```text
local transaction
→ commit
→ event/job
→ external call
→ persisted result
```

---

# 104. Documento x Snapshot x Arquivo

Separação:

```text
Business Document
→ fiscal_document

Snapshot
→ order_customer_snapshot

Binary File
→ platform.file_object
```

---

# 105. Versionamento de Políticas

Padrão:

```text
definition
↓
version
↓
ACTIVE
↓
SUPERSEDED
```

Aplicável a:

```text
tax
accounting
pricing
commission
quality
regulatory
time
workflow
metric
template
```

---

# 106. Referência à Versão da Regra

Transação dependente de política deve armazenar:

```text
rule_version_id
```

ou snapshot equivalente.

Não apontar apenas para a regra corrente.

---

# 107. Catálogo Preliminar de Aggregate Roots

| Módulo | Aggregate Roots Principais |
|---|---|
| M1 | Company, Branch, User, Role |
| M2 | Product, BOM |
| M3 | MarketplaceAccount, MarketplaceListing |
| M4 | Order |
| M5 | InventoryTransaction, Reservation, Transfer |
| M6 | Supplier, PurchaseOrder, GoodsReceipt |
| M7 | ProductionVersion, ProductionOrder |
| M8 | StandardCost, ProductionOrderCost, CostingPeriod |
| M9 | PriceList, PricingPolicy |
| M10 | PickingWave, Package, Shipment |
| M11 | FiscalDocument, TaxRule |
| M12 | Receivable, Payable, FinancialAccount |
| M13 | AccountingRule, JournalEntry, AccountingPeriod |
| M14 | Customer |
| M15 | SalesQuote, SalesPortfolio |
| M16 | CommissionOrigin, CommissionStatement |
| M17 | Inspection, NC, CAPA, Recall |
| M18 | CertificationProcess, Certificate, RegulatoryBlock |
| M19 | FixedAsset, MaintenanceAsset, MaintenanceWO |
| M20 | Person, EmploymentContract, TimePeriod |
| M21 | MetricDefinition, Target, Budget |
| M22 | WorkflowDefinition, WorkflowInstance |
| M23 | ImportJob, ExportJob, DataQualityIssue |

---

# 108. Espinha Dorsal de IDs

Cadeia comercial:

```text
customer_id
quote_id
order_id
fulfillment_id
shipment_id
fiscal_document_id
receivable_id
settlement_id
journal_entry_id
```

Cadeia industrial:

```text
product_id
bom_revision_id
production_version_id
production_order_id
lot_id
inventory_transaction_id
production_cost_id
```

---

# 109. Lineage Transacional

Além de `correlation_id`, entidades críticas podem guardar referências de origem.

Exemplos:

```text
receivable.source_type
receivable.source_id
```

```text
journal_entry.source_event_id
```

```text
fiscal_document.source_entity_type
fiscal_document.source_entity_id
```

---

# 110. Generic Source Reference

Padrão permitido:

```text
source_module
source_entity_type
source_entity_id
```

Usar apenas quando o domínio realmente aceitar múltiplas origens.

---

# 111. Não Usar Polymorphic FK Indiscriminadamente

Para relações estáveis:

```text
product_id
customer_id
```

preferir colunas dedicadas.

`source_entity_type/id` fica restrito a cenários polimórficos reais.

---

# 112. Regra sobre Status

Evitar enum global de status.

Cada agregado possui sua própria máquina de estados.

Exemplos:

```text
order_status
billing_status
workflow_status
fiscal_status
```

---

# 113. Enums no PostgreSQL

Recomendação:

**não depender extensivamente de PostgreSQL ENUM nativo.**

Preferir:

```text
VARCHAR
+
CHECK constraint
```

ou tabela de referência quando configurável.

Motivos:

- migrations mais simples;
- menor lock-in;
- versionamento mais controlável.

---

# 114. Catálogos Configuráveis

Não codificar em CHECK aquilo que o negócio precisa cadastrar.

Exemplos:

```text
reason codes
quality disposition reasons
loss reasons
payment terms
freight terms
failure codes
```

devem ser tabelas configuráveis.

---

# 115. Soft Delete

Não adotar genericamente:

```text
deleted_at
```

em todas as tabelas.

Preferir semântica do domínio:

```text
INACTIVE
CANCELLED
SUPERSEDED
DISPOSED
TERMINATED
```

---

# 116. Checks de Integridade Locais

Mesmo com validação em aplicação, o banco deve reforçar invariantes locais.

Exemplos:

```text
quantity >= 0 quando aplicável

valid_until > valid_from

debit >= 0
credit >= 0

one of debit/credit > 0

remaining_qty <= ordered_qty
```

---

# 117. Unique Constraints

Unicidades reais devem existir no banco.

Não depender somente de:

```python
if not exists...
```

antes do INSERT.

Isso é essencial para concorrência.

---

# 118. Locks Pessimistas

Usar apenas quando a serialização for realmente necessária.

Exemplos:

```text
inventory allocation
number sequence
certain financial reconciliation operations
```

Não aplicar `SELECT FOR UPDATE` indiscriminadamente.

---

# 119. Contadores e Sequências Comerciais

Documentos comerciais podem utilizar:

```text
business_sequence
```

segregado por:

```text
company
branch
document_type
series
```

UUID continua sendo PK.

---

# 120. Sequência Fiscal

M11 possui mecanismo próprio transacional devido à criticidade jurídica da numeração.

Não reutilizar sequência genérica de pedido para NF.

---

# 121. Reconciliabilidade

Domínios quantitativos e financeiros devem permitir reconciliação formal.

Exemplos:

```text
Inventory Ledger
vs
Inventory Balance
```

```text
Finance Subledger
vs
Accounting GL
```

```text
Marketplace Expected
vs
Settlement Actual
```

```text
Legacy Migration
vs
Opening Balance
```

---

# 122. Tabelas de Reconciliation

Não criar tabela global única.

Cada domínio mantém sua semântica:

```text
finance.financial_match
accounting.accounting_reconciliation
governance.migration_reconciliation
```

---

# 123. Data Ownership Documentado

Para cada entidade, a documentação definitiva deve registrar:

```text
schema
module
aggregate_root
table_type
owner
classification
mutability
retention
volume_class
```

Esse catálogo será aproveitado pelo M23.

---

# 124. Volume Classes

Sugestão:

```text
LOW
MEDIUM
HIGH
VERY_HIGH
```

Exemplos:

```text
company
→ LOW

order
→ HIGH

inventory_posting
→ VERY_HIGH

audit_event
→ VERY_HIGH
```

Servirá de base para particionamento e arquivamento.

---

# 125. Relações que Jamais Terão Cascade Delete

Especialmente:

```text
Customer → Order
Product → OrderItem
Supplier → PurchaseOrder
Product → InventoryPosting
Employee → TimePunch
```

Histórico transacional nunca desaparece por desativação do master.

---

# 126. Desativação de Master Data

Master usado em transação deverá ser:

```text
INACTIVE
BLOCKED
TERMINATED
SUPERSEDED
```

e não deletado.

---

# 127. Resultado Consolidado da Etapa 2

O modelo passa a ter quatro camadas conceituais:

```text
┌───────────────────────────────┐
│        MASTER DATA            │
│ Product / Customer / Supplier │
│ Person / Asset / Organization │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│       TRANSACTIONAL           │
│ Order / PO / OP / NF / AR/AP  │
│ Maintenance / Quality / WMS   │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│      LEDGERS / SNAPSHOTS      │
│ Inventory / Accounting /      │
│ Time Bank / Commission / Cost │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│        ANALYTICS              │
│ Facts / Dimensions / Metrics  │
└───────────────────────────────┘
```

Camadas transversais:

```text
M22
→ Workflow / Approval

M23
→ Data Governance / Bulk Data
```

---

# 128. Decisões Consolidadas da Etapa 2

Ficam estabelecidas como baseline:

```text
1. Um schema PostgreSQL por Bounded Context.
2. M21 em banco analítico fisicamente separado.
3. Hard FK dentro do domínio.
4. Cross-domain por referência lógica por padrão.
5. Company/Branch podem usar Foundation FK.
6. UUID como PK técnica.
7. Business Number separado.
8. Snapshots para contexto histórico.
9. Ledgers imutáveis.
10. Projeções duráveis reconstruíveis quando aplicável.
11. Nenhuma aprovação formal fora do M22.
12. Nenhuma carga massiva fora do M23.
13. M5 controla quantidade física.
14. M8 controla valoração industrial.
15. M13 controla débito/crédito.
16. M11 controla documento fiscal.
17. Temporalidade explícita em regras e masters históricos.
18. Object Storage separado do significado de negócio.
19. Eventos via Outbox.
20. Consumidores idempotentes via Inbox/idempotency.
21. Sem cascades destrutivos entre domínios.
22. Sem hard delete de histórico empresarial.
23. DECIMAL/NUMERIC para todos os valores críticos.
24. JSONB somente onde realmente dinâmico.
25. Rastreabilidade por source refs + correlation IDs.
```

---

# 129. Status Formal da Etapa 2

A **Etapa 2 — Modelo de Dados Consolidado M1–M23** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- criação dos schemas PostgreSQL;
- modelagem SQLAlchemy;
- migrations Alembic;
- definição de agregados;
- definição de repositories;
- criação de constraints;
- criação de índices;
- particionamento;
- implementação de snapshots;
- implementação de ledgers;
- desenho de eventos;
- APIs;
- Data Governance;
- arquitetura analítica.

Qualquer alteração incompatível com esta baseline deverá ser tratada como:

```text
ARCHITECTURE CHANGE REQUEST
```

com justificativa, impacto, versionamento e análise cross-domain.

---

# 130. Próxima Etapa

Após a aprovação desta documentação, o projeto poderá avançar para:

```text
ETAPA 3
CATÁLOGO OFICIAL DE EVENTOS M1–M23
```

A próxima etapa consolidará, para cada evento:

```text
event_name
producer
consumers
aggregate
trigger
payload mínimo
version
idempotency
sync/async
criticality
retry/DLQ
correlation
```

---

**Fim da Etapa 2 — Modelo de Dados Consolidado M1–M23**
