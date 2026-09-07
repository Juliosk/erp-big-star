# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 5 — RBAC + Segregação de Funções (SoD) Global

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Segurança funcional, autorização, escopos, segregação de funções e controles privilegiados dos módulos M1–M23  
**Objetivo:** Consolidar o modelo corporativo de RBAC, scopes, Row-Level Security, Segregação de Funções (SoD), step-up authentication, MFA, privilégios temporários, service accounts, auditoria de acesso e regras de segurança cross-domain do ERP Big Star / Forma Kids.

---

# 1. Objetivo da Etapa 5

A Etapa 5 consolida a segurança funcional de todo o ERP M1–M23.

Ela responde:

```text
Quem pode acessar?
O que pode visualizar?
O que pode criar?
O que pode alterar?
O que pode aprovar?
Em qual empresa?
Em qual filial?
Em qual departamento?
Em qual carteira?
Até qual valor?
Quais funções são incompatíveis?
Quando MFA/step-up é obrigatório?
Como delegações temporárias funcionam?
```

Regra central:

```text
AUTHENTICATION
≠
AUTHORIZATION
≠
APPROVAL
```

Onde:

```text
Authentication
→ M1

Authorization / RBAC
→ M1

Formal Approval
→ M22
```

---

# 2. Modelo de Segurança Consolidado

A autorização é composta por quatro camadas:

```text
USER
  │
  ▼
ROLE
  │
  ▼
PERMISSION
  │
  ▼
SCOPE
```

com controles adicionais:

```text
SoD
+
Data Classification
+
Step-Up Authentication
+
Approval Authority
```

Visão consolidada:

```text
Can User Act?
=
Authenticated
AND
Permission Granted
AND
Scope Allowed
AND
SoD Valid
AND
Data Classification Allowed
AND
Step-Up Satisfied when required
AND
Workflow Approval when required
```

---

# 3. Princípio de Menor Privilégio

Regra corporativa:

```text
DEFAULT DENY
```

O usuário só executa uma operação quando houver permissão explícita.

Não utilizar:

```text
acesso liberado por padrão
+
bloqueios pontuais
```

Preferir:

```text
bloqueado por padrão
+
concessão explícita
```

---

# 4. Estrutura de M1

Entidades centrais:

```text
admin.user
admin.role
admin.permission

admin.user_role
admin.role_permission

admin.user_scope

admin.security_policy
admin.security_event
```

Complementos consolidados:

```text
admin.role_hierarchy

admin.sod_policy
admin.sod_rule
admin.sod_conflict

admin.privileged_access_grant

admin.step_up_policy

admin.data_access_policy

admin.access_review
admin.access_review_item
```

---

# 5. Permission Naming Convention

Padrão:

```text
<domain>.<resource>.<action>
```

Exemplos:

```text
product.product.read
product.product.create
product.product.update
product.product.activate

inventory.balance.read
inventory.adjustment.create

finance.receivable.read
finance.payment.execute

accounting.journal.post

workflow.approval.decide

governance.import.commit
```

---

# 6. Ações Oficiais

Baseline:

```text
read
create
update
delete_draft

activate
deactivate

submit
approve
reject

execute
cancel
reverse

import
export

manage
configure

view_sensitive
override
```

Não reutilizar `manage` indiscriminadamente quando ações críticas precisarem ser separadas.

---

# 7. Role não é Cargo

Regra:

```text
ROLE
≠
JOB POSITION
```

Exemplo:

```text
Cargo RH:
Analista Financeiro

Roles:
FINANCE_RECEIVABLE_OPERATOR
BANK_RECONCILIATION_ANALYST
```

M20 é fonte da estrutura organizacional.

M1 é fonte dos privilégios digitais.

---

# 8. Role Assignment Temporal

`user_role` deve suportar:

```text
valid_from
valid_until
```

e:

```text
assignment_source
```

Exemplos:

```text
MANUAL
JOB_BASED
TEMPORARY
EMERGENCY
DELEGATED
```

---

# 9. Role Hierarchy

Herança controlada é permitida.

Exemplo:

```text
FINANCE_MANAGER
    inherits
FINANCE_ANALYST
```

Mas:

```text
herança
≠
bypass de SoD
```

---

# 10. Perfis Corporativos Macro

Famílias:

```text
PLATFORM_ADMIN

EXECUTIVE
DIRECTOR
MANAGER
SUPERVISOR
ANALYST
OPERATOR
VIEWER
```

Essas famílias não substituem roles específicas de domínio.

---

# 11. Scopes

Autorização deve suportar:

```text
GROUP
COMPANY
BRANCH

DEPARTMENT
COST_CENTER

WAREHOUSE

SALES_PORTFOLIO

CHANNEL
MARKETPLACE_ACCOUNT

PRODUCT_CATEGORY
PRODUCT_FAMILY
```

quando aplicável.

---

# 12. User Scope

Exemplo:

```text
user_id
scope_type = COMPANY
scope_id = Big Star
```

Outro:

```text
scope_type = SALES_PORTFOLIO
scope_id = PORTFOLIO_SUDESTE
```

---

# 13. Precedência de Scope

Princípio:

```text
permission
+
scope
```

Permissão sem scope não deve automaticamente liberar todas as empresas.

---

# 14. Group Scope

Diretoria pode receber:

```text
GROUP
```

para visão consolidada.

Operações jurídicas continuam vinculadas a:

```text
company_id
branch_id
```

---

# 15. Row-Level Security

RLS deve proteger leituras por:

```text
company_id
branch_id
department_id
cost_center_id
portfolio_id
warehouse_id
```

quando aplicável.

A implementação poderá combinar:

```text
application-level authorization
+
PostgreSQL RLS
```

em áreas sensíveis.

---

# 16. RLS não Substitui Permissão Funcional

Exemplo:

```text
finance.receivable.read
```

com scope correto permite leitura.

Não autoriza automaticamente:

```text
finance.receivable.writeoff
```

---

# 17. SYSTEM_ACTOR

Jobs e integrações automáticas usam identidade explícita:

```text
SYSTEM_ACTOR
```

Exemplos:

```text
SYSTEM_MARKETPLACE_SYNC
SYSTEM_FISCAL_PROCESSOR
SYSTEM_ANALYTICS_PIPELINE
SYSTEM_IMPORT_WORKER
```

---

# 18. Service Account

Criar:

```text
admin.service_account
```

Campos:

```text
purpose
owner
allowed_permissions
allowed_scopes
credential_reference
validity
```

---

# 19. Credenciais de Service Account

Requisitos:

- rotação;
- secret manager;
- auditoria;
- expiração;
- owner responsável.

---

# 20. Segregação de Funções — SoD

Objetivo:

```text
evitar que uma única pessoa
crie
aprove
execute
e reconcilie
a mesma transação crítica
```

---

# 21. Tipos de SoD

```text
STATIC_SOD
DYNAMIC_SOD
TRANSACTIONAL_SOD
```

---

# 22. STATIC_SOD

Impede combinação permanente de roles incompatíveis.

Exemplo:

```text
PAYMENT_CREATOR
+
PAYMENT_APPROVER
```

---

# 23. DYNAMIC_SOD

Roles podem coexistir, mas não podem ser exercidas na mesma transação.

Exemplo:

```text
usuário pode criar PO
e possuir função de aprovação

mas
não pode aprovar PO criada por ele
```

---

# 24. TRANSACTIONAL_SOD

Avalia o contexto real.

Exemplos:

```text
created_by
≠
approved_by
```

```text
prepared_by
≠
posted_by
```

---

# 25. SoD por Cadeia

Exemplos:

```text
Create Vendor
≠
Approve Vendor Bank Data

Create Payment
≠
Approve Payment

Approve Payment
≠
Transmit Payment

Create Journal
≠
Post Journal

Create Asset Disposal
≠
Approve Disposal

Create Price Exception
≠
Approve Exception
```

---

# 26. SoD no M22

M22 valida:

```text
requester
creator
current approver
delegate
```

contra políticas SoD.

Mesmo com:

```text
workflow.approval.decide
```

SoD pode negar a decisão.

---

# 27. Autoaprovação Proibida

Padrão:

```text
requester != approver
creator != approver
```

para operações formalmente aprovadas.

---

# 28. Delegação

Delegação permanece sob M22.

Regra:

```text
delegation
≠
permanent role assignment
```

---

# 29. Acting on Behalf Of

Decisão delegada registra:

```text
performed_by
acting_on_behalf_of
```

---

# 30. Delegação não Ignora SoD

Delegado não pode aprovar transação criada por ele próprio.

---

# 31. Privileged Access Grant

Criar:

```text
admin.privileged_access_grant
```

Campos:

```text
user_id
permission
scope
valid_from
valid_until
reason_code
approved_workflow_id
```

---

# 32. Just-In-Time Access

Privilégios críticos podem usar:

```text
JIT ACCESS
```

Exemplo:

```text
accounting.period.reopen
```

ativo apenas durante janela curta.

---

# 33. Break Glass

Acesso emergencial exige:

```text
explicit emergency action
reason mandatory
step-up authentication
very short validity
immediate audit alert
post-event review
```

---

# 34. Break Glass Nunca Silencioso

Evento:

```text
EmergencyPrivilegeActivated
```

deve gerar alerta para Segurança, Auditoria e responsáveis aplicáveis.

---

# 35. Step-Up Authentication

Níveis:

```text
LEVEL_1
NORMAL_SESSION

LEVEL_2
PASSWORD_REAUTH

LEVEL_3
MFA
```

---

# 36. Exemplos de LEVEL_3

```text
Pagamento de alto valor
Descarte de ativo
Reabertura contábil
Desvio regulatório crítico
Alteração de conta bancária
Exportação de dados extremamente sensíveis
```

---

# 37. Step-Up Policy

Criar:

```text
admin.step_up_policy
```

Critérios:

```text
permission
transaction_amount
risk_level
data_classification
workflow_type
```

---

# 38. Sessão Step-Up

Elevação temporária:

```text
step_up_verified_at
step_up_level
expires_at
```

---

# 39. Classificação de Dados

Categorias:

```text
PUBLIC_INTERNAL
CONFIDENTIAL
RESTRICTED
PERSONAL_DATA
SENSITIVE_BUSINESS
```

---

# 40. Permissão por Classificação

Exemplo:

```text
hr.employee.read
```

não implica:

```text
hr.salary.view_sensitive
```

---

# 41. Field-Level Security

Campos críticos podem possuir autorização própria.

Exemplos:

```text
bank_account_number
salary
industrial_cost
target_margin
credit_limit
oauth_secret
```

---

# 42. Masking

Usuário sem permissão específica pode ver:

```text
Banco ****1234
```

em vez do valor completo.

---

# 43. Exportação Sensível

Separar:

```text
data.export.execute
```

de:

```text
data.export.sensitive
```

---

# 44. Auditoria de Acesso

Eventos:

```text
SensitiveDataViewed
SensitiveDataExported
PrivilegeGranted
PrivilegeRevoked
RoleAssigned
RoleRemoved
StepUpCompleted
BreakGlassActivated
```

---

# 45. Access Review

Criar:

```text
admin.access_review
```

Ciclos possíveis:

```text
trimestral
semestral
```

---

# 46. Recertificação

Estados:

```text
PENDING_REVIEW
APPROVED
REVOKE_REQUIRED
COMPLETED
```

---

# 47. Joiner / Mover / Leaver

## Joiner

```text
EmployeeAdmitted
→ M1
→ baseline roles
→ optional approval
→ UserProvisioned
```

## Mover

```text
EmployeeAssignmentChanged
→ reevaluate scopes/roles
```

## Leaver

```text
EmployeeTerminated
→ UserAccessRevocationRequested
→ immediate revocation
```

---

# 48. Role Mapping por Função Organizacional

Pode existir:

```text
job_position
→ suggested_role_set
```

Mas:

```text
suggested
≠
automatic unrestricted grant
```

---

# 49. Mudança de Função

Ao mudar de departamento:

```text
old scopes
→ revoke/review

new scopes
→ grant/review
```

Evitar privilege accumulation.

---

# 50. Matriz de Permissões — M1

Roles:

```text
SECURITY_ADMIN
USER_ADMIN
ACCESS_REVIEWER
AUDITOR
```

Permissões críticas:

```text
admin.user.create
admin.user.disable
admin.role.manage
admin.permission.manage
admin.scope.manage
admin.break_glass.execute
```

SoD preferencial:

```text
Role/Permission Configurator
≠
Access Reviewer
```

---

# 51. M2 — Product Master

Roles:

```text
PRODUCT_VIEWER
PRODUCT_ANALYST
PRODUCT_ENGINEER
PRODUCT_MASTER_ADMIN
```

Permissões:

```text
product.product.read
product.product.create
product.product.update
product.product.activate

product.bom.read
product.bom.edit
product.bom.release
```

SoD:

```text
BOM Editor
≠
BOM Releaser
```

quando política exigir.

---

# 52. M3 — Marketplace

Roles:

```text
MARKETPLACE_OPERATOR
MARKETPLACE_MANAGER
MARKETPLACE_ADMIN
```

Permissões críticas:

```text
marketplace.account.connect
marketplace.account.disconnect
marketplace.listing.map
marketplace.sync.reprocess
```

Tokens nunca ficam visíveis diretamente.

---

# 53. M4 — Orders

Roles:

```text
ORDER_OPERATOR
ORDER_SUPERVISOR
ORDER_MANAGER
```

Permissões:

```text
orders.order.read
orders.order.create
orders.order.cancel
orders.order.hold
orders.order.release_hold
```

---

# 54. M5 — Inventory

Roles:

```text
INVENTORY_VIEWER
INVENTORY_OPERATOR
INVENTORY_SUPERVISOR
INVENTORY_MANAGER
```

Permissões:

```text
inventory.balance.read
inventory.reservation.manage
inventory.transfer.create
inventory.adjustment.create
inventory.adjustment.confirm
inventory.cycle_count.manage
```

SoD:

```text
Inventory Adjustment Creator
≠
Inventory Adjustment Approver
```

quando política exigir.

---

# 55. M6 — Procurement

Roles:

```text
BUYER
PURCHASE_SUPERVISOR
PURCHASE_MANAGER
SUPPLIER_MASTER_ADMIN
```

Permissões:

```text
procurement.requisition.create
procurement.rfq.manage
procurement.purchase_order.create
procurement.purchase_order.change
procurement.supplier.manage
```

Aprovação:

```text
M22
```

SoD:

```text
PO Creator
≠
PO Approver
```

---

# 56. M7 — Manufacturing

Roles:

```text
PCP_ANALYST
PRODUCTION_OPERATOR
PRODUCTION_SUPERVISOR
PRODUCTION_MANAGER
ENGINEERING_ADMIN
```

Permissões:

```text
manufacturing.production_order.create
manufacturing.production_order.release
manufacturing.production.report
manufacturing.scrap.report
manufacturing.routing.manage
```

---

# 57. M8 — Costing

Roles:

```text
COST_ANALYST
COST_MANAGER
COST_CONTROLLER
```

Permissões:

```text
costing.standard_cost.read
costing.standard_cost.manage
costing.standard_cost.activate
costing.actual_cost.read
costing.period.close
costing.period.reopen
```

SoD:

```text
Standard Cost Preparer
≠
Standard Cost Approver
```

---

# 58. M9 — Pricing

Roles:

```text
PRICING_ANALYST
PRICING_MANAGER
PRICING_DIRECTOR
```

Permissões:

```text
pricing.simulate
pricing.price.create
pricing.price.activate
pricing.margin.view_sensitive
pricing.exception.request
```

Vendedor não vê custo/margem por padrão.

---

# 59. M10 — WMS

Roles:

```text
PICKER
PACKER
WMS_SUPERVISOR
WMS_MANAGER
```

Permissões:

```text
wms.pick.execute
wms.pack.execute
wms.dispatch.execute
wms.label.reprint
wms.shortage.override
```

Reprint e override exigem auditoria.

---

# 60. M11 — Fiscal

Roles:

```text
FISCAL_ANALYST
FISCAL_SUPERVISOR
FISCAL_MANAGER
TAX_RULE_ADMIN
```

Permissões:

```text
fiscal.document.issue
fiscal.document.cancel
fiscal.document.correct
fiscal.rule.manage
fiscal.rule.activate
fiscal.sequence.manage
```

SoD:

```text
Tax Rule Editor
≠
Tax Rule Activator
```

---

# 61. M12 — Financeiro

Roles:

```text
AR_ANALYST
AP_ANALYST
TREASURY_OPERATOR
TREASURY_MANAGER
FINANCE_MANAGER
FINANCE_DIRECTOR
```

Permissões:

```text
finance.receivable.manage
finance.payable.manage
finance.payment.request
finance.payment.approve
finance.payment.transmit
finance.bank.reconcile
finance.bank_account.manage
```

SoD obrigatório:

```text
Payment Creator
≠
Payment Approver
```

e, para alçadas críticas:

```text
Payment Approver
≠
Payment Transmitter
```

---

# 62. Dados Bancários

Alterações exigem:

```text
separate permission
+
M22 approval
+
step-up
```

Exemplo:

```text
finance.bank_data.change
```

---

# 63. M13 — Accounting

Roles:

```text
ACCOUNTING_ANALYST
ACCOUNTING_MANAGER
CONTROLLER
```

Permissões:

```text
accounting.journal.create
accounting.journal.post
accounting.journal.reverse

accounting.rule.manage
accounting.rule.activate

accounting.period.soft_close
accounting.period.close
accounting.period.reopen
```

SoD:

```text
Journal Creator
≠
Journal Poster
```

para lançamentos manuais críticos.

---

# 64. Reabertura Contábil

Pode exigir:

```text
M22
+
MFA
+
JIT privilege
```

---

# 65. M14 — CRM

Roles:

```text
CUSTOMER_VIEWER
CUSTOMER_ANALYST
CUSTOMER_MASTER_ADMIN
CRM_USER
```

Permissões:

```text
crm.customer.read
crm.customer.create
crm.customer.update
crm.customer.merge
crm.consent.manage
```

---

# 66. Merge de Cliente

Permissão:

```text
crm.customer.merge
```

mais:

```text
M23 governance
```

e aprovação quando política exigir.

---

# 67. M15 — Comercial B2B

Roles:

```text
SELLER
SALES_SUPERVISOR
SALES_MANAGER
SALES_DIRECTOR
```

Permissões:

```text
sales.quote.create
sales.quote.update
sales.quote.send
sales.quote.convert

sales.discount.request
sales.customer_portfolio.read
```

Seller não recebe por padrão:

```text
pricing.margin.view_sensitive
costing.standard_cost.read
```

---

# 68. Carteira Comercial

Scope:

```text
SALES_PORTFOLIO
```

Vendedor consulta clientes da própria carteira.

---

# 69. M16 — Commissions

Roles:

```text
COMMISSION_ANALYST
COMMISSION_MANAGER
COMMISSION_CONTROLLER
```

Permissões:

```text
commission.rule.manage
commission.statement.read
commission.statement.close
commission.adjustment.request
commission.simulator.view
```

---

# 70. M17 — Quality

Roles:

```text
QUALITY_INSPECTOR
QUALITY_ANALYST
QUALITY_SUPERVISOR
QUALITY_MANAGER
```

Permissões:

```text
quality.inspection.execute
quality.disposition.decide
quality.hold.place
quality.hold.release
quality.nc.manage
quality.capa.manage
quality.recall.initiate
```

SoD possível:

```text
Inspector
≠
Critical Deviation Approver
```

---

# 71. M18 — Regulatory

Roles:

```text
REGULATORY_ANALYST
REGULATORY_MANAGER
COMPLIANCE_DIRECTOR
```

Permissões críticas:

```text
regulatory.certificate.manage
regulatory.block.create
regulatory.block.release
regulatory.deviation.request
regulatory.packaging.approve
```

Liberação crítica pode exigir:

```text
M22
+
step-up
```

---

# 72. M19 — Assets / Maintenance

Roles:

```text
MAINTENANCE_TECHNICIAN
MAINTENANCE_PLANNER
MAINTENANCE_SUPERVISOR
ASSET_ANALYST
ASSET_MANAGER
```

Permissões:

```text
maintenance.work_order.execute
maintenance.work_order.complete
maintenance.asset.release

asset.create
asset.transfer
asset.dispose
asset.capitalize
```

Descarte de ativo usa aprovação CUMULATIVE no M22.

---

# 73. M20 — RH

Roles:

```text
HR_ANALYST
HR_MANAGER
TIME_ADMIN
BENEFITS_ADMIN
```

Permissões:

```text
hr.person.read
hr.contract.manage
hr.assignment.manage
hr.time.adjustment.create
hr.time.period.close
hr.payroll.import
hr.salary.view_sensitive
```

---

# 74. M21 — Analytics

Roles:

```text
ANALYTICS_VIEWER
ANALYTICS_ANALYST
ANALYTICS_MANAGER
METRIC_GOVERNOR
```

Permissões:

```text
analytics.dashboard.read
analytics.self_service.use
analytics.metric.manage
analytics.metric.activate
analytics.target.manage
analytics.budget.manage
analytics.alert.manage
```

RLS permanece obrigatório.

---

# 75. M22 — Workflow

Roles:

```text
WORKFLOW_USER
WORKFLOW_APPROVER
WORKFLOW_ADMIN
WORKFLOW_AUDITOR
```

Permissões:

```text
workflow.approval.decide
workflow.delegation.create
workflow.policy.manage
workflow.policy.activate
workflow.simulation.run
workflow.audit.read
```

---

# 76. M23 — Data Governance

Roles:

```text
DATA_IMPORT_OPERATOR
DATA_EXPORT_USER
DATA_STEWARD
DATA_OWNER
DATA_GOVERNANCE_ADMIN
```

Permissões:

```text
data.import.execute
data.import.confirm
data.import.opening_balance

data.export.execute
data.export.sensitive

data.quality.manage

data.merge.request

data.change_request.create

data.retention.manage
```

---

# 77. Opening Balance Import

SoD:

```text
Uploader
≠
Approver
```

e pode exigir:

```text
M22
+
MFA
```

---

# 78. Bulk Data Change

Mudanças materiais:

```text
M23
→ DataChangeApprovalRequested
→ M22
```

RBAC não substitui aprovação.

---

# 79. Matriz Global de SoD — Núcleo

| Processo | Função A | Incompatível com B |
|---|---|---|
| Compras | Criar PO | Aprovar própria PO |
| Financeiro | Criar pagamento | Aprovar próprio pagamento |
| Financeiro | Aprovar pagamento alto | Transmitir o mesmo lote, quando política exigir |
| Contabilidade | Criar journal manual | Postar o mesmo journal |
| Pricing | Criar exceção | Aprovar própria exceção |
| Ativos | Solicitar descarte | Aprovar próprio descarte |
| RH | Solicitar ajuste | Aprovar próprio ajuste |
| Qualidade | Criar desvio crítico | Aprovar próprio desvio |
| Regulatory | Solicitar exceção | Liberar própria exceção |
| Data Governance | Upload crítico | Aprovar próprio lote |
| Workflow | Criar policy | Ativar a mesma policy, quando política exigir |
| Security | Criar privilégio crítico | Revisar/recertificar o próprio privilégio |

---

# 80. Conflitos de Role

Exemplo:

```text
PAYMENT_CREATOR
x
PAYMENT_APPROVER_HIGH_VALUE
```

pode ser configurado como incompatível.

---

# 81. Conflict Severity

```text
BLOCK
REQUIRE_EXCEPTION_APPROVAL
WARN
```

Padrão crítico:

```text
BLOCK
```

---

# 82. SoD Exception

Criar:

```text
admin.sod_exception
```

com:

```text
reason
scope
validity
approving_workflow
compensating_control
```

---

# 83. Compensating Control

Exemplo:

```text
filial pequena
1 responsável financeiro
```

pode exigir controle compensatório formal e revisão posterior por superior.

---

# 84. Aprovação não Concede Permissão

```text
WorkflowApproved
+
user lacks finance.payment.transmit
→ cannot transmit
```

---

# 85. Permissão não Substitui Aprovação

```text
user has finance.payment.execute
```

não autoriza pagar transação pendente de M22.

---

# 86. Autorização em Duas Fases

Para operação crítica:

```text
CAN_DO_FUNCTION
+
IS_THIS_TRANSACTION_APPROVED
```

ambos precisam ser verdadeiros.

---

# 87. Escopo de Valor

Permissões podem possuir limite:

```text
max_amount
```

Exemplo:

```text
finance.payment.approve
up_to = 25000
```

---

# 88. Escopo por Risco

Exemplo:

```text
regulatory.block.release
risk_level <= MAJOR
```

CRITICAL exige função superior e workflow.

---

# 89. Acesso Temporário

Toda permissão temporária possui:

```text
valid_from
valid_until
```

e expira automaticamente.

---

# 90. Session Revocation

Mudanças críticas devem poder invalidar sessões ativas.

Exemplos:

```text
UserDisabled
EmployeeTerminated
RoleCriticalRevoked
```

---

# 91. Token Claims

Tokens podem carregar:

```text
user_id
session_id
auth_level
```

Evitar autorização excessivamente longa e não revogável.

---

# 92. Authorization Cache

Redis pode cachear permissões.

Mas:

```text
cache
≠
authority
```

Mudança de role/scope invalida cache.

---

# 93. Sensitive Action Logging

Registrar:

```text
actor
effective_user
acting_on_behalf_of

permission
scope

resource
resource_id

decision

step_up_level

workflow_reference

timestamp
```

---

# 94. Auditor

Auditor deve ser predominantemente:

```text
READ ONLY
```

sem capacidade operacional equivalente.

---

# 95. Super Admin

Evitar superusuário de negócio.

`PLATFORM_ADMIN` cuida de infraestrutura funcional e segurança, mas não recebe automaticamente:

```text
accounting.post
payment.execute
regulatory.release
```

---

# 96. Database Superuser

Credencial de banco não representa usuário da aplicação.

Acesso DB administrativo é separado e auditado.

---

# 97. Frontend Security

Esconder botão:

```text
não é segurança
```

Backend sempre revalida permissão, scope e SoD.

---

# 98. API Authorization

Cada endpoint deve declarar:

```text
required_permission
scope_resolver
step_up_policy
```

quando aplicável.

---

# 99. Exemplo de Endpoint Crítico

```text
POST /api/v1/finance/payment-batches/{id}/transmit
```

pode exigir:

```text
finance.payment.transmit
company_scope
MFA
workflow approved
```

---

# 100. Export Security

Ao iniciar export:

```text
authorize
```

Ao concluir:

```text
authorize again
```

quando necessário.

---

# 101. Background Job Authorization

Jobs devem guardar:

```text
requested_by
authorization_snapshot
```

e revalidar quando necessário.

---

# 102. Data Governance de Permissões

M23 pode auditar qualidade do modelo de acesso, mas M1 continua sendo autoridade RBAC.

---

# 103. M21 e Segurança

M21 pode consumir:

```text
RoleAssigned
SensitiveDataExported
BreakGlassActivated
```

para dashboards de risco.

Não pode revogar acesso diretamente.

---

# 104. Eventos de Segurança Importantes

Complementos futuros ao catálogo de eventos:

```text
RoleAssigned
RoleRevoked

UserScopeChanged

PrivilegedAccessGranted
PrivilegedAccessExpired

SodConflictDetected

StepUpAuthenticationSucceeded
StepUpAuthenticationFailed

BreakGlassActivated

AccessReviewCompleted
```

---

# 105. Permission Registry

M1 deve manter:

```text
permission_code
domain
description
risk_level
data_classification
step_up_default
```

---

# 106. Permission Risk Level

```text
LOW
MEDIUM
HIGH
CRITICAL
```

---

# 107. Role Design

Evitar roles gigantes.

Preferir composição:

```text
AP_ANALYST
TREASURY_OPERATOR
BANK_RECONCILIATION_ANALYST
```

---

# 108. Role Explosion

Não criar uma role por usuário.

Equilíbrio:

```text
stable job functions
+
scopes
+
temporary grants
```

---

# 109. Named User Exception

Exceções individuais usam:

```text
privileged_access_grant
```

em vez de role permanente artificial.

---

# 110. SoD Engine

Fluxo de concessão:

```text
Role Assignment Requested
        │
        ▼
Static SoD Check
        │
        ├── conflict?
        │      ├── BLOCK
        │      └── exception workflow
        ▼
Role Granted
```

Fluxo transacional:

```text
Action Requested
        │
        ▼
RBAC
        │
        ▼
Dynamic / Transactional SoD
        │
        ▼
Step-Up
        │
        ▼
Workflow State
        │
        ▼
EXECUTE
```

---

# 111. Performance

Sugestão:

```text
permission resolution
→ cacheable

transactional SoD
→ evaluated live

critical workflow state
→ evaluated live
```

---

# 112. Não Cachear Decisão Crítica por Longo Período

Exemplo:

```text
payment approved?
```

deve refletir estado atual.

---

# 113. Multiempresa

Usuário pode ter:

```text
FINANCE_MANAGER
```

na Big Star e:

```text
FINANCE_VIEWER
```

na Forma Kids.

---

# 114. Branch Specific Access

Exemplo:

```text
WAREHOUSE_OPERATOR
```

apenas:

```text
Branch A
Warehouse 01
```

---

# 115. Portfolio Access

Seller:

```text
SALES_PORTFOLIO = X
```

Gestor:

```text
SALES_TEAM = Y
```

Diretoria:

```text
GROUP
```

---

# 116. Cost Center Access

Aplicável a:

- gestores;
- Analytics;
- Budget;
- RH;
- Accounting.

---

# 117. Warehouse Access

M5/M10 podem restringir usuário a depósitos específicos.

---

# 118. Marketplace Account Access

M3 pode restringir operações por:

```text
MARKETPLACE_ACCOUNT
```

---

# 119. Data Access Policy

Criar:

```text
admin.data_access_policy
```

para combinar:

```text
role
permission
scope
classification
```

---

# 120. Privacy by Design

Dados pessoais ficam disponíveis somente onde existe necessidade funcional.

---

# 121. Right to Know

Cada acesso sensível deve possuir motivo funcional justificável.

---

# 122. Access Request

Acesso adicional pode seguir:

```text
AccessGrantRequested
→ M22
→ approved
→ M1 grant
```

---

# 123. Access Revocation

Revogação por:

- término de vínculo;
- mudança de função;
- decisão manual;
- access review;
- fim de validade.

---

# 124. Recertificação de Privilégios Críticos

Exemplos:

```text
finance.payment.transmit
accounting.period.reopen
regulatory.block.release
security.role.manage
```

---

# 125. Critérios de Aceite da Etapa 5

1. `DEFAULT DENY` definido.
2. user, role, permission e scope separados.
3. naming de permission padronizado.
4. role não confundida com cargo.
5. assignment temporal.
6. scope por group/company/branch.
7. scope por department/cost center.
8. portfolio scope.
9. warehouse scope.
10. marketplace account scope.
11. RLS previsto.
12. SYSTEM_ACTOR definido.
13. service account definido.
14. static SoD.
15. dynamic SoD.
16. transactional SoD.
17. requester ≠ approver.
18. creator ≠ approver.
19. delegação não burla SoD.
20. privileged access temporário.
21. JIT access.
22. break glass controlado.
23. step-up levels.
24. MFA.
25. field-level security.
26. masking.
27. export sensitive separado.
28. audit de acesso.
29. access review.
30. joiner/mover/leaver.
31. leaver com revogação rápida.
32. role mapping por job controlado.
33. privilege accumulation evitado.
34. roles M1–M23 mapeadas.
35. Finance SoD.
36. Accounting SoD.
37. Procurement SoD.
38. Pricing SoD.
39. Asset disposal SoD.
40. Data Governance SoD.
41. Payroll/HR sensitive data protegido.
42. regulatory critical release com step-up.
43. opening balance import com SoD.
44. approval não concede permission.
45. permission não substitui approval.
46. amount limit suportado.
47. risk scope suportado.
48. temporary grant expira automaticamente.
49. session revocation.
50. authorization cache não é authority.
51. backend revalida segurança.
52. API declara required permission.
53. export job revalida acesso.
54. auditor read-only.
55. platform admin não é superuser de negócio.
56. DB superuser separado.
57. permission registry.
58. permission risk classification.
59. SoD exception formal.
60. compensating control documentado.
61. access grant pode passar pelo M22.
62. recertificação de privilégios críticos.
63. audit completo.
64. multiempresa por role/scope.
65. segurança compatível com M1–M23.

---

# 126. Decisões Arquiteturais Consolidadas

## A. M1 é autoridade de identidade e autorização

## B. M22 é autoridade de aprovação

## C. RBAC não substitui workflow

## D. Workflow não substitui RBAC

## E. Permission e scope são independentes

## F. Cargo não é role

## G. SoD é política nativa

## H. Autoaprovação é proibida por padrão

## I. Delegação não altera privilégio permanente

## J. Ações críticas exigem step-up

## K. Dados sensíveis possuem field-level control

## L. RLS complementa backend authorization

## M. SYSTEM_ACTOR é explícito

## N. Super admin técnico não recebe poder de negócio automaticamente

## O. Joiner/Mover/Leaver é automatizado e auditável

## P. Privilege accumulation deve ser evitado

## Q. Break Glass é excepcional e visível

## R. Access Reviews são recorrentes

---

# 127. Visão Consolidada

```text
                       USER
                         │
                         ▼
                  AUTHENTICATION
                       M1
                         │
                         ▼
                   ROLE / PERMISSION
                         │
                         ▼
                       SCOPE
                         │
                         ▼
                    DATA POLICY
                         │
                         ▼
                  STATIC SoD CHECK
                         │
                         ▼
                TRANSACTION REQUEST
                         │
                         ▼
                DYNAMIC / TX SoD
                         │
                         ▼
                STEP-UP REQUIRED?
                    /          \
                  NO            YES
                  │              │
                  │             MFA
                  │              │
                  └──────┬───────┘
                         ▼
                 WORKFLOW REQUIRED?
                    /          \
                  NO            YES
                  │              │
                  │             M22
                  │              │
                  └──────┬───────┘
                         ▼
                     EXECUTION
                         │
                         ▼
                       AUDIT
```

---

# 128. Status Formal da Etapa 5

A **Etapa 5 — RBAC + Segregação de Funções (SoD) Global** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- autenticação;
- autorização;
- RBAC;
- scopes;
- RLS;
- SoD;
- step-up;
- MFA;
- acesso privilegiado;
- service accounts;
- auditoria de acesso;
- access reviews;
- joiner/mover/leaver;
- proteção de dados sensíveis;
- controles M1–M23.

Alterações incompatíveis deverão ser tratadas como:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 129. Próxima Etapa

```text
ETAPA 6
MAPA CONSOLIDADO DE APIs
```

A próxima etapa consolidará:

- convenções REST;
- versionamento;
- endpoints M1–M23;
- contratos internos e externos;
- autenticação/autorização por endpoint;
- idempotency keys;
- optimistic locking;
- paginação;
- filtros;
- erros;
- async jobs;
- uploads/downloads;
- OpenAPI;
- contract testing;
- observabilidade;
- depreciação de APIs.

---

**Fim da Etapa 5 — RBAC + Segregação de Funções (SoD) Global**
