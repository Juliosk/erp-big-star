# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 7 — Mapa Completo de Telas e Navegação do ERP

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Arquitetura de navegação, telas, workspaces, cockpits, dashboards e padrões de UX dos módulos M1–M23  
**Objetivo:** Consolidar a experiência operacional do ERP, definindo shell global, menus, homes por perfil, padrões de telas, navegação cross-domain, drill-through, UX assíncrona, aprovações, scanner/PWA, segurança visual e mapa de telas dos 23 módulos.

---

# 1. Objetivo da Etapa 7

Esta etapa transforma toda a arquitetura M1–M23 em uma experiência operacional única, definindo:

```text
estrutura de menu
homes por perfil
cockpits
listas
cadastros
detalhes
formulários
workspaces operacionais
drill-through
navegação cross-domain
ações críticas
UX de workflow
UX de processos assíncronos
responsive/PWA
scanner/coletor
segurança visual
```

Regra central:

```text
UI
≠
regra de negócio
```

A interface orienta e restringe a experiência, mas validações e invariantes continuam no backend.

---

# 2. Princípios Gerais de UX

O frontend seguirá:

```text
ROLE-BASED
CONTEXT-AWARE
TASK-ORIENTED
RESPONSIVE
AUDITABLE
DOMAIN-DRIVEN
```

A navegação será personalizada por:

- função;
- role;
- empresa;
- filial;
- departamento;
- carteira;
- depósito;
- permissões;
- tarefas pendentes.

---

# 3. Shell Global

Estrutura principal:

```text
┌──────────────────────────────────────────────────────────┐
│ Logo | Empresa/Filial | Busca | Aprovações | Alertas | 👤│
├───────────────┬──────────────────────────────────────────┤
│               │                                          │
│ Menu lateral  │              Conteúdo                    │
│               │                                          │
│               │                                          │
└───────────────┴──────────────────────────────────────────┘
```

Elementos fixos:

```text
Company Context
Global Search
My Approvals
Notifications
Jobs / Downloads
Help
User Menu
```

---

# 4. Seletor de Contexto Corporativo

No topo:

```text
Grupo Econômico
Empresa
Filial
```

Exemplo:

```text
Grupo Big Star
└── Big Star
    └── Matriz
```

Ou:

```text
Grupo Consolidado
```

quando a permissão permitir.

---

# 5. Troca de Empresa

Ao trocar `company_id`:

- filtros são atualizados;
- menus sem acesso desaparecem;
- favoritos incompatíveis ficam indisponíveis;
- formulários abertos não mudam silenciosamente de contexto.

Se houver edição pendente:

```text
troca de contexto
→ confirmação obrigatória
```

---

# 6. Menu Corporativo Macro

```text
Home

Cadastros
├── Produtos
├── Clientes
├── Fornecedores
├── Estrutura Organizacional
└── Ativos

Comercial
├── B2B
├── Pricing
├── Comissões
└── Marketplaces

Supply Chain
├── Compras
├── Estoque
└── Expedição

Industrial
├── Engenharia
├── PCP
├── Produção
├── Custos
└── Manutenção

Qualidade & Compliance
├── Qualidade
└── Regulatório / INMETRO

Backoffice
├── Fiscal
├── Financeiro
└── Contabilidade

Pessoas
└── RH

Gestão
├── BI & Analytics
├── Workflow
└── Data Governance

Administração
├── Empresas
├── Usuários
├── Perfis
├── Segurança
└── Auditoria
```

O usuário verá apenas o que possui permissão para acessar.

---

# 7. Home Personalizada por Perfil

A Home não será uma dashboard única.

Exemplos:

```text
EXECUTIVE_HOME
FINANCE_HOME
SALES_HOME
PCP_HOME
QUALITY_HOME
HR_HOME
WMS_HOME
PURCHASING_HOME
```

---

# 8. Home da Diretoria

Visão padrão:

```text
Grupo Econômico
Big Star + Forma Kids
```

Cards:

- faturamento;
- margem;
- vendas por canal;
- caixa;
- inadimplência;
- estoque;
- produção;
- sucata;
- qualidade;
- certificações;
- absenteísmo.

Com:

```text
Real
Meta
Budget
Variação
```

---

# 9. Home Financeiro

Widgets:

```text
Caixa Hoje
Contas a Receber
Contas a Pagar
Inadimplência
Pagamentos Pendentes
Conciliação Bancária
Marketplace Settlements
```

---

# 10. Home Comercial

Widgets:

```text
Venda do Dia
Venda do Mês
Meta
Margem
Orçamentos Abertos
Orçamentos Stale
Pedidos em Hold
Clientes Bloqueados
```

---

# 11. Home PCP

```text
OPs do Dia
OPs Atrasadas
Produção Real x Planejada
Material Shortage
Recursos Indisponíveis
Qualidade em Hold
Certificação Bloqueando Produção
```

---

# 12. Home Qualidade

```text
Inspeções Pendentes
Lotes em Quarentena
NCs
CAPAs
Supplier Quality
Recall
Calibrações Vencendo
```

---

# 13. Home RH

```text
Headcount
Absenteísmo
Horas Extras
Banco de Horas
Férias em Risco
Ajustes de Ponto
Onboarding
Offboarding
```

---

# 14. Navegação por Rotas

Padrão:

```text
/<domain>/<resource>
```

Exemplo:

```text
/products
/products/{id}

/sales/quotes
/sales/quotes/{id}

/finance/receivables
```

---

# 15. Screen ID

Toda tela oficial terá código estável.

Padrão:

```text
Mxx-AREA-NNN
```

Exemplos:

```text
M02-PRD-001
M12-FIN-004
M22-WKF-002
```

Serve para:

- documentação;
- testes;
- suporte;
- treinamento;
- analytics de uso.

---

# 16. Tipos Oficiais de Tela

```text
HOME
COCKPIT
LIST
DETAIL
FORM
WORKSPACE
WIZARD
SIMULATOR
REPORT
CONFIGURATION
```

---

# 17. Padrão de LIST

Toda lista corporativa seguirá:

```text
Título
Ações principais
Filtros rápidos
Filtros avançados
Pesquisa
Grid
Paginação
Salvar visão
Exportar
```

---

# 18. Grid

Recursos:

- ordenar;
- fixar coluna;
- redimensionar;
- esconder coluna;
- salvar layout;
- densidade;
- filtros;
- seleção.

Layouts:

```text
Pessoal
Departamento
Corporativo
```

governados pelo M23 quando persistidos.

---

# 19. Bulk Actions

A UI pode oferecer ações em massa, mas a execução formal deverá ser enviada ao M23 quando caracterizar bulk change.

---

# 20. Padrão DETAIL

```text
Header
Summary
Status
Primary Actions

Tabs
├── Overview
├── Items
├── Documents
├── Financial
├── History
├── Audit
└── Related
```

---

# 21. Timeline

Entidades transacionais críticas terão Timeline.

Exemplo Pedido:

```text
10:02 Pedido criado
10:02 Reserva confirmada
10:07 Picking iniciado
10:25 Packing concluído
10:27 NF autorizada
10:29 Etiqueta disponível
11:45 Despachado
```

---

# 22. Audit Tab

Quando autorizado:

```text
Quem
Quando
Alteração
Motivo
Workflow
Correlation ID
```

---

# 23. Related Entities

Exemplo Pedido:

```text
Cliente
Reserva
Fulfillment
NF
Recebível
Shipment
Comissão
```

Cada clique navega ao módulo dono.

---

# 24. Drill-Through

Exemplo:

```text
M21 Margem
↓
Produto
↓
Cliente
↓
Pedido
↓
NF
```

---

# 25. Breadcrumbs

Exemplo:

```text
Comercial
>
Orçamentos
>
Q-000983
>
Revisão 4
```

---

# 26. Global Search

Busca global poderá localizar:

```text
SKU
EAN
Pedido
NF
Cliente
CNPJ
OP
Lote
PO
Recebível
Ativo
Colaborador
```

Resultados obedecem RBAC/RLS.

---

# 27. Nunca Revelar Resultado sem Acesso

Se o item existe mas usuário não possui scope, ele não aparece na busca.

---

# 28. Favoritos

Usuário poderá favoritar:

- tela;
- relatório;
- consulta;
- dashboard;
- layout.

---

# 29. Recentes

Lista opcional:

```text
Itens recentemente acessados
```

respeitando autorização atual.

---

# 30. Central de Aprovações

Disponível globalmente:

```text
Minhas Aprovações
```

Origem:

```text
M22
```

Cards:

```text
Pendentes
Vencendo
Escaladas
Delegadas
```

---

# 31. Ações de Aprovação

```text
Approve
Reject
Return for Correction
Request Information
```

Com:

- motivo;
- anexos;
- fingerprint;
- impacto;
- step-up quando exigido.

---

# 32. Deep Link de Workflow

Exemplo:

```text
Pagamento #123
```

abre o recurso financeiro original.

M22 não duplica a tela de domínio.

---

# 33. Central de Notificações

Categorias:

```text
INFO
WARNING
CRITICAL
ACTION_REQUIRED
```

---

# 34. Jobs & Downloads

Tela global:

```text
Meus Processamentos
```

Estados:

```text
QUEUED
PROCESSING
COMPLETED
FAILED
```

---

# 35. UX de Processamento Assíncrono

Jobs longos não bloqueiam a tela.

---

# 36. Conflito de Versão

`409 VERSION_CONFLICT` abre comparação:

```text
Sua versão
vs
Versão atual
```

Opções:

```text
Recarregar
Descartar alterações
Reaplicar manualmente
```

---

# 37. Step-Up Authentication

Ao executar ação crítica:

```text
Confirmar identidade
```

via senha ou MFA.

---

# 38. Ação Irreversível

Exibir:

- impacto;
- motivo obrigatório;
- workflow;
- step-up quando aplicável.

---

# 39. Status Chips

Estados terão componentes consistentes:

```text
ACTIVE
PENDING
BLOCKED
CRITICAL
CLOSED
```

A cor é complementar, não exclusiva.

---

# 40. Acessibilidade

Baseline:

- teclado;
- labels;
- foco visível;
- contraste;
- semântica para screen readers;
- erro associado ao campo.

---

# 41. Responsive Design

Categorias:

```text
DESKTOP-FIRST
RESPONSIVE
MOBILE-OPTIMIZED
```

---

# 42. Mobile-Optimized

Prioridade:

```text
M10 WMS
M17 Quality
M19 Maintenance
M20 Approvals / Time actions
M22 Approvals
```

---

# 43. PWA

Preparar arquitetura para PWA, especialmente para scanner, chão de fábrica, manutenção, inventário e aprovações.

---

# 44. Scanner

Aceita:

```text
EAN
DUN-14
SKU
Reference
```

conforme contexto.

---

# 45. Scanner Feedback

```text
OK
ERRO
QUANTIDADE COMPLETA
LOTE INCORRETO
ITEM NÃO ESPERADO
```

---

# 46. Atalhos de Teclado

Poderão existir em telas desktop operacionais, desde que documentados.

---

# 47. M1 — Administração / Segurança

## Menu

```text
Administração
├── Grupo Econômico
├── Empresas
├── Filiais
├── Usuários
├── Roles
├── Permissões
├── Service Accounts
├── Revisões de Acesso
└── Segurança
```

| ID | Tela | Tipo |
|---|---|---|
| M01-ADM-001 | Empresas | LIST |
| M01-ADM-002 | Empresa | DETAIL/FORM |
| M01-ADM-003 | Filiais | LIST |
| M01-SEC-001 | Usuários | LIST |
| M01-SEC-002 | Usuário | DETAIL |
| M01-SEC-003 | Roles | LIST |
| M01-SEC-004 | Editor de Role | FORM |
| M01-SEC-005 | Permission Registry | LIST |
| M01-SEC-006 | Scopes do Usuário | WORKSPACE |
| M01-SEC-007 | Service Accounts | LIST |
| M01-SEC-008 | Access Reviews | COCKPIT |
| M01-SEC-009 | Segurança / Eventos | COCKPIT |

---

# 48. Tela de Usuário

Tabs:

```text
Perfil
Roles
Scopes
Sessões
Step-Up
Histórico
Access Reviews
Audit
```

Ações:

```text
Enable
Disable
Revoke Sessions
Grant Temporary Access
```

---

# 49. M2 — Product Master

```text
Produtos
├── Produtos
├── Variantes
├── BOMs
├── Embalagens
├── Barcodes
├── Atributos
└── Mídias
```

| ID | Tela | Tipo |
|---|---|---|
| M02-PRD-001 | Catálogo de Produtos | LIST |
| M02-PRD-002 | Produto | DETAIL |
| M02-PRD-003 | Novo/Editar Produto | FORM |
| M02-PRD-004 | Variantes | WORKSPACE |
| M02-PRD-005 | Barcodes | WORKSPACE |
| M02-PRD-006 | Packaging Hierarchy | WORKSPACE |
| M02-BOM-001 | BOMs | LIST |
| M02-BOM-002 | BOM | DETAIL |
| M02-BOM-003 | Editor de Revisão BOM | WORKSPACE |
| M02-PRD-007 | Mídias | WORKSPACE |

---

# 50. Editor de BOM

```text
Produto
Revisão
Status

Tree BOM
│
├── Componente
├── Quantidade
├── Unidade
├── Scrap previsto
└── Regulatory classification
```

Ações:

```text
Save Draft
Submit
Release
Obsolete
```

---

# 51. M3 — Marketplace Hub

```text
Marketplaces
├── Cockpit
├── Contas
├── Listings
├── Pedidos Externos
├── Sincronizações
├── Estoque Publicado
├── Preços Publicados
└── Integrações
```

| ID | Tela |
|---|---|
| M03-MKT-001 | Marketplace Cockpit |
| M03-MKT-002 | Contas |
| M03-MKT-003 | Conta Marketplace |
| M03-MKT-004 | Listings |
| M03-MKT-005 | Listing Detail |
| M03-MKT-006 | De/Para Produto |
| M03-MKT-007 | Pedidos Externos |
| M03-MKT-008 | Snapshot Pedido Externo |
| M03-MKT-009 | Sync Jobs |
| M03-MKT-010 | Integration Health |

---

# 52. Marketplace Cockpit

Cards:

```text
Contas Online
Pedidos Pendentes
Falhas de Estoque
Falhas de Preço
Rate Limit
DLQ
```

---

# 53. M4 — Orders / Fulfillment

```text
Pedidos
├── Pedidos
├── Em Hold
├── Fulfillments
├── Billing Pending
└── Cancelados
```

| ID | Tela |
|---|---|
| M04-ORD-001 | Pedidos |
| M04-ORD-002 | Pedido |
| M04-ORD-003 | Novo Pedido |
| M04-ORD-004 | Holds |
| M04-FUL-001 | Fulfillments |
| M04-FUL-002 | Fulfillment |
| M04-BIL-001 | Billing Queue |

---

# 54. Tela Pedido

Header:

```text
Pedido
Cliente
Origem
Status Order
Status Fulfillment
Status Billing
Status Financial
```

Tabs:

```text
Itens
Cliente Snapshot
Fulfillment
Fiscal
Financeiro
Shipment
Eventos
Audit
```

---

# 55. M5 — Inventory

```text
Estoque
├── Cockpit
├── Saldos
├── Lotes
├── Reservas
├── Transferências
├── Divergências
├── Inventários
└── Ledger
```

| ID | Tela |
|---|---|
| M05-INV-001 | Inventory Cockpit |
| M05-INV-002 | Saldos |
| M05-INV-003 | Lotes |
| M05-INV-004 | Lote Detail |
| M05-INV-005 | Reservas |
| M05-INV-006 | Transferências |
| M05-INV-007 | Transferência |
| M05-INV-008 | Divergências |
| M05-INV-009 | Cycle Counts |
| M05-INV-010 | Inventory Ledger |

---

# 56. Tela de Saldo

```text
Produto
→ Warehouse
→ Location
→ Lot
→ Pool
→ State
```

Exibe:

```text
On Hand
Available
Reserved
Quarantine
Blocked
Transit
```

---

# 57. M6 — Procurement

```text
Compras
├── Cockpit
├── Requisições
├── Cotações
├── Pedidos de Compra
├── Recebimentos
├── 3-Way Match
├── Fornecedores
└── Claims
```

| ID | Tela |
|---|---|
| M06-PUR-001 | Purchasing Cockpit |
| M06-REQ-001 | Requisições |
| M06-REQ-002 | Requisição |
| M06-RFQ-001 | RFQs |
| M06-RFQ-002 | Comparativo de Cotações |
| M06-PO-001 | Pedidos de Compra |
| M06-PO-002 | Pedido de Compra |
| M06-GR-001 | Recebimentos |
| M06-GR-002 | Recebimento |
| M06-MAT-001 | 3-Way Match |
| M06-SUP-001 | Fornecedores |
| M06-CLM-001 | Supplier Claims |

---

# 58. Comparativo de Cotação

```text
Item
Supplier A
Supplier B
Supplier C

Price
Lead Time
MOQ
Payment Terms
Quality Status
```

Escolha não significa aprovação formal.

---

# 59. M7 — Manufacturing / PCP

```text
Industrial
├── PCP Cockpit
├── MRP
├── Production Versions
├── OPs
├── Apontamento
├── Work Centers
├── Resources
├── Routings
└── Genealogia
```

| ID | Tela |
|---|---|
| M07-PCP-001 | PCP Cockpit |
| M07-MRP-001 | MRP |
| M07-PV-001 | Production Versions |
| M07-PV-002 | Production Version |
| M07-OP-001 | Ordens de Produção |
| M07-OP-002 | Ordem de Produção |
| M07-SF-001 | Shop Floor Workspace |
| M07-ISS-001 | Material Issue |
| M07-YLD-001 | Yield Entry |
| M07-WC-001 | Work Centers |
| M07-ROU-001 | Routings |
| M07-GEN-001 | Genealogia de Lote |

---

# 60. Shop Floor Workspace

```text
OP
Produto
Lote
Máquina
Operação

[Iniciar]
[Consumir]
[Produzir]
[Scrap]
[Parada]
[Finalizar]
```

---

# 61. M8 — Industrial Costing

```text
Custos
├── Cockpit
├── Standard Cost
├── Actual OP Cost
├── Moving Average
├── Variâncias
└── Períodos
```

| ID | Tela |
|---|---|
| M08-CST-001 | Cost Cockpit |
| M08-STD-001 | Standard Costs |
| M08-STD-002 | Standard Cost Version |
| M08-ACT-001 | Production Order Costs |
| M08-ACT-002 | OP Cost Detail |
| M08-MAC-001 | Moving Average |
| M08-VAR-001 | Cost Variances |
| M08-PRD-001 | Costing Periods |

---

# 62. Cost Detail

```text
Material
PI
Labor
Machine
Setup
CIF
Scrap
Rework
Recovery Credit
```

Mostrar:

```text
Standard
Actual
Variance
```

---

# 63. M9 — Pricing

```text
Pricing
├── Cockpit
├── Tabelas
├── Políticas
├── Simulador
├── Batches
└── Reviews
```

| ID | Tela |
|---|---|
| M09-PRI-001 | Pricing Cockpit |
| M09-LST-001 | Price Lists |
| M09-LST-002 | Price List Version |
| M09-POL-001 | Pricing Policies |
| M09-SIM-001 | Pricing Simulator |
| M09-BAT-001 | Pricing Batches |
| M09-REV-001 | Price Reviews |

---

# 64. Pricing Simulator

Inputs:

```text
Product
Channel/Table
Quantity
Payment Term
Freight
Discount
```

Output:

```text
Standard Cost
Taxes
Fees
Commission
Freight
Contribution Margin
Suggested Price
Minimum Price
```

---

# 65. M10 — WMS / Expedition

Menu Desktop:

```text
Expedição
├── Cockpit
├── Ondas
├── Picking
├── Packing
├── Shipments
├── Manifestos
└── Labels
```

Mobile:

```text
Minhas Tarefas
Picking
Packing
Dispatch
```

| ID | Tela |
|---|---|
| M10-WMS-001 | WMS Cockpit |
| M10-WAV-001 | Waves |
| M10-PIC-001 | Picking Task |
| M10-PIC-002 | Picking Scanner |
| M10-PAC-001 | Packing Station |
| M10-PKG-001 | Package Detail |
| M10-SHP-001 | Shipments |
| M10-DSP-001 | Dispatch Workspace |
| M10-MNF-001 | Manifestos |

---

# 66. Picking Scanner

```text
Scan Address
↓
Scan Product
↓
Scan Lot
↓
Enter/scan Qty
↓
Confirm
```

Erros bloqueantes:

```text
WRONG_ADDRESS
WRONG_PRODUCT
WRONG_LOT
OVER_PICK
```

---

# 67. Packing Station

```text
Pedido
Itens Esperados
Itens Lidos
Volumes
Peso
Dimensões
Etiqueta
```

Double verification B2C obrigatória.

---

# 68. M11 — Fiscal

```text
Fiscal
├── Cockpit
├── Documentos
├── Pendências
├── Rejeições
├── Regras Tributárias
├── Séries
└── Estabelecimentos
```

| ID | Tela |
|---|---|
| M11-FIS-001 | Fiscal Cockpit |
| M11-DOC-001 | Documentos Fiscais |
| M11-DOC-002 | Fiscal Document Detail |
| M11-REJ-001 | Rejeições |
| M11-TAX-001 | Tax Rules |
| M11-TAX-002 | Rule Simulator |
| M11-SER-001 | Séries |
| M11-EST-001 | Estabelecimentos |

---

# 69. Documento Fiscal Detail

Tabs:

```text
Resumo
Itens
Impostos
XML
Referências
Provider Exchanges
Cancelamento/CC-e
Audit
```

Documento autorizado é read-only.

---

# 70. M12 — Financeiro

```text
Financeiro
├── Cockpit
├── Contas a Receber
├── Contas a Pagar
├── Pagamentos
├── Bancos
├── Conciliação
├── Marketplaces
├── Antecipações
├── Crédito
└── Fluxo de Caixa
```

| ID | Tela |
|---|---|
| M12-FIN-001 | Finance Cockpit |
| M12-AR-001 | Receivables |
| M12-AR-002 | Receivable Detail |
| M12-AP-001 | Payables |
| M12-AP-002 | Payable Detail |
| M12-PAY-001 | Payment Requests |
| M12-PAY-002 | Payment Batch |
| M12-BNK-001 | Bank Accounts |
| M12-REC-001 | Bank Reconciliation Workspace |
| M12-MKT-001 | Marketplace Settlement |
| M12-ANT-001 | Anticipations |
| M12-CRD-001 | Credit Exposure |
| M12-CF-001 | Cash Flow |

---

# 71. Bank Reconciliation Workspace

```text
Bank Movement
          ↕
Matching Engine Suggestions
          ↕
ERP Titles
```

Ações:

```text
Match
Split
Ignore with reason
Create Provisional Entry
```

---

# 72. M13 — Accounting

```text
Contabilidade
├── Cockpit
├── Plano de Contas
├── Regras
├── Lançamentos
├── Períodos
├── Reconciliações
└── Demonstrações
```

| ID | Tela |
|---|---|
| M13-ACC-001 | Accounting Cockpit |
| M13-COA-001 | Chart of Accounts |
| M13-RUL-001 | Accounting Rules |
| M13-RUL-002 | Rule Simulator |
| M13-JRN-001 | Journals |
| M13-JRN-002 | Journal Detail |
| M13-PRD-001 | Accounting Periods |
| M13-REC-001 | Reconciliations |
| M13-RPT-001 | Trial Balance |
| M13-RPT-002 | General Ledger |
| M13-RPT-003 | DRE |
| M13-RPT-004 | Balance Sheet |

---

# 73. Journal Detail

```text
Account
Debit
Credit
Dimensions
History
Source Event
```

Após `POSTED`:

```text
READ ONLY
```

Ação:

```text
Reverse
```

---

# 74. M14 — Customer / CRM

```text
Clientes
├── Clientes
├── Grupos
├── Interações
├── Tarefas
├── Duplicidades
└── Customer 360
```

| ID | Tela |
|---|---|
| M14-CRM-001 | Clientes |
| M14-CRM-002 | Cliente |
| M14-CRM-003 | Novo/Editar Cliente |
| M14-GRP-001 | Grupos |
| M14-CRM-004 | Customer 360 |
| M14-INT-001 | Interações |
| M14-TSK-001 | Tarefas |
| M14-DUP-001 | Duplicate Review |

---

# 75. Customer 360

```text
Cadastro
Endereços
Contatos
Compras
Últimos Pedidos
Returns
Credit Status
Overdue Flag
Interactions
Tasks
```

Dados financeiros detalhados apenas para roles autorizadas.

---

# 76. M15 — Comercial B2B

```text
Comercial
├── Cockpit
├── Orçamentos
├── Carteiras
├── Territórios
├── Políticas
├── Agenda de Entrega
└── Pedidos Alterados
```

| ID | Tela |
|---|---|
| M15-SAL-001 | Sales Cockpit |
| M15-QTE-001 | Quotes |
| M15-QTE-002 | Quote Workspace |
| M15-QTE-003 | Quote Revision |
| M15-POR-001 | Portfolios |
| M15-POL-001 | Commercial Policies |
| M15-DEL-001 | Delivery Schedules |
| M15-CHG-001 | Order Change Requests |

---

# 77. Quote Workspace

```text
Customer
Seller
Price Table
Payment Term
Freight

Items Grid
Quantity
Price
Discount
Availability
Promised Date

Warnings
Credit
Commercial Policy
Regulatory
```

---

# 78. M16 — Commissions

```text
Comissões
├── Cockpit
├── Beneficiários
├── Regras
├── Accruals
├── Earnings
├── Ajustes
├── Períodos
└── Extratos
```

| ID | Tela |
|---|---|
| M16-COM-001 | Commission Cockpit |
| M16-BEN-001 | Beneficiaries |
| M16-RUL-001 | Commission Rules |
| M16-ACC-001 | Accruals |
| M16-EAR-001 | Earnings |
| M16-ADJ-001 | Adjustments |
| M16-PRD-001 | Commission Periods |
| M16-STM-001 | Statements |

---

# 79. M17 — Quality

```text
Qualidade
├── Cockpit
├── Inspeções
├── Quarentena
├── NC
├── CAPA
├── Supplier Quality
├── Reclamações
├── Recall
└── Calibração
```

| ID | Tela |
|---|---|
| M17-QLT-001 | Quality Cockpit |
| M17-INS-001 | Inspections |
| M17-INS-002 | Inspection Workspace |
| M17-HLD-001 | Quality Holds |
| M17-NC-001 | Nonconformities |
| M17-CAP-001 | CAPA Workspace |
| M17-SUP-001 | Supplier Quality |
| M17-CMP-001 | Complaints |
| M17-RCL-001 | Recall Cockpit |
| M17-CAL-001 | Calibration |

---

# 80. Inspection Workspace

```text
Produto
Lote
Plano
Amostra

Characteristic
Target
Tolerance
Measured
Result

[Approve]
[Partial]
[Reject]
```

---

# 81. Recall Cockpit

```text
Affected Lot
↓
Production Order
↓
Material Lots
↓
Shipments
↓
Customers
```

---

# 82. M18 — Regulatory / INMETRO

```text
Regulatório
├── Cockpit
├── Famílias
├── Certificações
├── Certificados
├── Renovação
├── Amostras
├── Ensaios
├── Change Assessments
├── Packaging Approval
├── Blocks
└── Audits
```

| ID | Tela |
|---|---|
| M18-REG-001 | Regulatory Cockpit |
| M18-FAM-001 | Regulatory Families |
| M18-CER-001 | Certification Processes |
| M18-CER-002 | Certification Workspace |
| M18-CRT-001 | Certificates |
| M18-RNW-001 | Renewal Calendar |
| M18-SMP-001 | Samples |
| M18-TST-001 | Tests / Reports |
| M18-CHG-001 | Change Assessments |
| M18-PKG-001 | Packaging Approval |
| M18-BLK-001 | Regulatory Blocks |
| M18-AUD-001 | Regulatory Audits |

---

# 83. Regulatory Cockpit

```text
Certificates Expiring
Blocked Products
Renewals
Pending Samples
Pending Reports
Packaging Pending
Open Assessments
```

---

# 84. M19 — Assets / Maintenance

```text
Ativos & Manutenção
├── Cockpit
├── Ativos
├── Moldes
├── Maintenance Assets
├── Planos Preventivos
├── Solicitações
├── Ordens
├── Medidores
├── Downtime
└── Depreciação
```

| ID | Tela |
|---|---|
| M19-MNT-001 | Maintenance Cockpit |
| M19-AST-001 | Fixed Assets |
| M19-AST-002 | Fixed Asset Detail |
| M19-MOL-001 | Molds |
| M19-MNT-002 | Maintenance Assets |
| M19-PLN-001 | Preventive Plans |
| M19-REQ-001 | Maintenance Requests |
| M19-WO-001 | Maintenance Work Orders |
| M19-WO-002 | Work Order Workspace |
| M19-MTR-001 | Meters |
| M19-DWN-001 | Downtime |
| M19-DEP-001 | Depreciation |

---

# 85. Maintenance Work Order

```text
Asset
Failure
Priority

Tasks
Parts
Labor
External Service
Photos
Downtime

[Start]
[Pause]
[Complete]
```

---

# 86. M20 — HR

```text
RH
├── Cockpit
├── Pessoas
├── Contratos
├── Estrutura
├── Cargos
├── Escalas
├── Ponto
├── Banco de Horas
├── Horas Extras
├── Férias
├── Afastamentos
├── Benefícios
├── Onboarding
├── Offboarding
└── Folha
```

| ID | Tela |
|---|---|
| M20-HR-001 | HR Cockpit |
| M20-PER-001 | People |
| M20-CON-001 | Employment Contracts |
| M20-ORG-001 | Organization Structure |
| M20-JOB-001 | Job Positions |
| M20-SCH-001 | Work Schedules |
| M20-TIM-001 | Time Cockpit |
| M20-PUN-001 | Time Punches |
| M20-ADJ-001 | Time Adjustment Requests |
| M20-OT-001 | Overtime |
| M20-BNK-001 | Time Bank |
| M20-VAC-001 | Vacation |
| M20-ABS-001 | Absences |
| M20-BEN-001 | Benefits |
| M20-ONB-001 | Onboarding |
| M20-OFF-001 | Offboarding |
| M20-PAY-001 | Payroll Bridge |

---

# 87. Time Cockpit

```text
Hoje
Período
Exceptions
Overtime
Missing Punches
Unauthorized Overtime
Pending Corrections
```

---

# 88. M21 — BI / Analytics

```text
Analytics
├── Minha Home
├── Executivo
├── Financeiro
├── Comercial
├── Produção
├── Qualidade
├── RH
├── Explorer
├── Metas
├── Budget
├── Alertas
└── Relatórios Agendados
```

| ID | Tela |
|---|---|
| M21-BI-001 | Personalized Home |
| M21-BI-002 | Executive Dashboard |
| M21-BI-003 | Finance Dashboard |
| M21-BI-004 | Sales Dashboard |
| M21-BI-005 | Manufacturing Dashboard |
| M21-BI-006 | Quality Dashboard |
| M21-BI-007 | HR Dashboard |
| M21-EXP-001 | Analytical Explorer |
| M21-MET-001 | Metric Catalog |
| M21-TGT-001 | Targets |
| M21-BUD-001 | Budget |
| M21-ALT-001 | Analytics Alerts |
| M21-RPT-001 | Scheduled Reports |

---

# 89. Analytical Explorer

```text
Dataset
Metrics
Dimensions
Filters
Grouping
Pivot
Chart
Table
```

Salvar:

```text
Personal
Department
Corporate
```

---

# 90. M22 — Workflow

```text
Workflow
├── Minhas Aprovações
├── Solicitados por Mim
├── Delegações
├── Workflows
├── Políticas
├── SLA
├── Simulador
└── Auditoria
```

| ID | Tela |
|---|---|
| M22-WKF-001 | My Approvals |
| M22-WKF-002 | Approval Detail |
| M22-WKF-003 | My Requests |
| M22-DEL-001 | Delegations |
| M22-DEF-001 | Workflow Definitions |
| M22-DEF-002 | Workflow Designer |
| M22-POL-001 | Approval Policies |
| M22-SLA-001 | SLA Cockpit |
| M22-SIM-001 | Workflow Simulator |
| M22-AUD-001 | Workflow Audit |

---

# 91. Workflow Designer

```text
START
  │
  ▼
Step 1
  │
  ├── condition
  ▼
Step 2A ──┐
Step 2B ──┤ ALL_REQUIRED
          ▼
         END
```

Configura:

- approver resolution;
- quorum;
- SLA;
- escalation;
- change policy;
- SoD.

---

# 92. M23 — Data Governance

```text
Data Governance
├── Imports
├── Exports
├── Templates
├── Data Quality
├── Duplicidades
├── Merge
├── Change Requests
├── Lineage
├── Data Ownership
└── Retention
```

| ID | Tela |
|---|---|
| M23-IMP-001 | Imports |
| M23-IMP-002 | Import Wizard |
| M23-IMP-003 | Import Preview |
| M23-IMP-004 | Rejected Rows |
| M23-EXP-001 | Exports |
| M23-TPL-001 | Templates |
| M23-DQ-001 | Data Quality Cockpit |
| M23-DQ-002 | Data Quality Issues |
| M23-DUP-001 | Duplicate Candidates |
| M23-MRG-001 | Merge Workspace |
| M23-CHG-001 | Data Change Requests |
| M23-LIN-001 | Data Lineage |
| M23-OWN-001 | Data Owners/Stewards |
| M23-RET-001 | Retention Policies |

---

# 93. Import Wizard

```text
1 Upload
↓
2 Template Version
↓
3 Parsing
↓
4 Structural Validation
↓
5 Business Validation
↓
6 Preview
↓
7 Approval if needed
↓
8 Commit
↓
9 Result
```

---

# 94. Import Preview

```text
Row
Status
Current Value
New Value
Difference
Warnings
Errors
```

---

# 95. Data Quality Cockpit

Cards:

```text
Product Score
Customer Score
Supplier Score
HR Score
Fiscal Score
```

Drill-down:

```text
Domain
→ Rule
→ Issue
→ Record
```

---

# 96. Tela de Lineage

```text
Source
↓
Import
↓
Domain Entity
↓
Transformation
↓
Analytics
```

---

# 97. Navegação Cross-Domain — Pedido

```text
Customer
→ M14

Reservation
→ M5

Picking
→ M10

Invoice
→ M11

Receivable
→ M12

Commission
→ M16
```

---

# 98. Navegação Cross-Domain — OP

```text
Product
→ M2

BOM
→ M2

Routing
→ M7

Consumed Lots
→ M5

Quality
→ M17

Regulatory
→ M18

Machine
→ M19

Cost
→ M8
```

---

# 99. Navegação Cross-Domain — Compra

```text
Supplier
→ M6

PO
→ M6

Fiscal Document
→ M11

Receipt
→ M6

Lot
→ M5

Quality
→ M17

Payable
→ M12
```

---

# 100. Navegação Cross-Domain — Cliente

Customer 360 pode navegar para:

```text
Quotes
Orders
Invoices
Receivables
Interactions
Complaints
```

---

# 101. Context Drawer

Quick views poderão abrir em drawer read-only.

Edição complexa continua no módulo dono.

---

# 102. Quick View

Pode mostrar:

```text
Nome
SKU
Status
EAN
Available Stock
Price
```

conforme autorização.

---

# 103. Não Criar Mega-Tela Universal

Evitar telas que repliquem módulos completos.

Preferir links contextualizados.

---

# 104. Navegação Preservando Filtros

Ao voltar de um detalhe, manter:

- filtro;
- ordenação;
- página/cursor;
- scroll quando viável.

---

# 105. URL Compartilhável

Filtros importantes devem aparecer na URL quando possível.

---

# 106. Segurança em Links

Deep link sempre revalida:

```text
permission
scope
```

---

# 107. Empty State

Não revelar existência de dados sem autorização.

---

# 108. Error State

Erro deve exibir:

```text
Mensagem compreensível
Error Code
Correlation ID
Retry quando seguro
```

---

# 109. Warning x Blocking Error

```text
WARNING
→ pode prosseguir

BLOCKING
→ não pode confirmar
```

---

# 110. Business Warnings

Exemplos:

```text
Margem abaixo do alvo
Projected Availability
Cliente próximo do limite
Certificado próximo do vencimento
```

---

# 111. Ações Primárias

Cada tela deverá ter foco principal claro quando possível.

---

# 112. Ações Secundárias

Agrupar em:

```text
Mais ações
```

---

# 113. Dangerous Actions

Separar visualmente:

```text
Cancelar
Excluir Draft
Reverter
Bloquear
```

---

# 114. Form Save

Cadastros normais:

```text
Save
```

Fluxos complexos:

```text
Save Draft
Submit
```

---

# 115. Auto-Save

Não usar em transações críticas.

---

# 116. Form Validation

```text
client-side
+
backend authoritative
```

---

# 117. Unsaved Changes

Navegação com alterações não salvas exige confirmação.

---

# 118. Contexto de Workflow

Quando `PENDING_APPROVAL`, mostrar:

```text
Workflow
Etapa atual
Aprovadores
SLA
```

---

# 119. Returned for Correction

Mostrar:

- motivo;
- campos impactados;
- aprovações preservadas/invalidadas.

---

# 120. Timeline de Workflow

```text
Requested
Approved Step 1
Returned
Corrected
Revalidated
Approved
```

---

# 121. UX de Regulatory Gate

Mostrar razão do bloqueio, certificado, escopo e validade quando autorizado.

---

# 122. UX de Quality Gate

Exemplo:

```text
QUARANTINE
Inspection #...
Approved Qty: 950
Pending Qty: 50
```

---

# 123. UX de Credit Gate

Seller vê status resumido:

```text
AVAILABLE
WARNING
BLOCKED
```

---

# 124. UX de Pricing

Seller vê limite comercial.

Gestor autorizado pode ver margem e impacto de custo.

---

# 125. Sensitive Data Masking

Exemplos:

```text
CPF ***.***.***-12
Bank ****1234
```

---

# 126. Documentos / Evidências

Object Storage suporta:

```text
Upload
Preview
Download
Version
```

---

# 127. Print

Impressões operacionais incluem etiquetas, documentos e relatórios.

ZPL via Print Agent no M10.

---

# 128. Print Agent UX

Mostrar:

```text
Printer
Online/Offline
Queue
Last Print
```

Reprint pode exigir `reason_code`.

---

# 129. Local Scanner/Hardware

Driver local não contém regra de negócio.

---

# 130. Design System

Componentes oficiais:

```text
Button
Input
Select
DatePicker
DataGrid
StatusBadge
Alert
Modal
Drawer
Tabs
Timeline
Stepper
FileUpload
MetricCard
```

---

# 131. Terminologia

A UI usa linguagem do domínio, não nomes de tabelas.

---

# 132. Internacionalização

Locale oficial inicial:

```text
pt-BR
```

---

# 133. Formatação Brasileira

Interface:

```text
R$ 1.234,56
01/09/2026
```

API permanece em formatos técnicos.

---

# 134. Timezone

Frontend apresenta horários no timezone de contexto apropriado.

---

# 135. Preferências do Usuário

Persistir:

```text
tema
densidade
layouts
favorites
default company
```

---

# 136. Cockpit Técnico

Administração técnica poderá visualizar:

```text
Queues
DLQ
External Integrations
Jobs
Read Model Freshness
API Health
```

---

# 137. Navegação em Falha Externa

Exemplo:

```text
Conta Shopee
DEGRADED
```

Operações internas seguem quando permitido.

---

# 138. M21 sem Disponibilidade

Operação do ERP continua normalmente.

---

# 139. M22 sem Disponibilidade

Transação que precisa aprovação fica pendente, nunca autoaprovada.

---

# 140. M18 Gate Indisponível

Gate crítico apresenta falha e bloqueia a operação.

---

# 141. Desktop vs Mobile

Desktop prioriza:

- grids;
- comparação;
- análise;
- cadastros.

Mobile prioriza:

- tarefas;
- scanner;
- aprovações;
- execução operacional.

---

# 142. Navegação Mobile

Pode usar:

```text
Home
Tasks
Scan
Alerts
Profile
```

---

# 143. Push Notifications Futuras

Preparar para:

- approval;
- WMS;
- maintenance;
- quality.

---

# 144. Critérios de Aceite da Etapa 7

1. shell global definido.
2. company/branch context definido.
3. menu corporativo agrupado.
4. menu permission-driven.
5. homes role-based.
6. executive home prevista.
7. finance home prevista.
8. commercial home prevista.
9. PCP home prevista.
10. quality home prevista.
11. HR home prevista.
12. Screen ID padronizado.
13. tipos de tela definidos.
14. LIST pattern definido.
15. DETAIL pattern definido.
16. grids padronizados.
17. layouts pessoal/departamento/corporativo.
18. bulk changes via M23.
19. timeline em entidades críticas.
20. audit tab previsto.
21. related entities preservam ownership.
22. drill-through definido.
23. breadcrumbs.
24. global search respeita RLS.
25. favoritos.
26. central de aprovações.
27. central de notificações.
28. central de jobs.
29. async UX definida.
30. version conflict UX definida.
31. step-up UX.
32. dangerous actions reforçadas.
33. status chips consistentes.
34. acessibilidade baseline.
35. responsive design.
36. telas mobile prioritárias.
37. scanner flow.
38. M1–M23 com mapa de telas.
39. Customer 360.
40. Quote Workspace.
41. Shop Floor Workspace.
42. Picking Scanner.
43. Packing Station.
44. Bank Reconciliation Workspace.
45. Inspection Workspace.
46. Workflow Designer.
47. Import Wizard.
48. Data Quality Cockpit.
49. cross-domain navigation.
50. quick views sem violar ownership.
51. mega-tela universal evitada.
52. filtros preservados.
53. deep links autorizados.
54. warnings/blockers diferenciados.
55. workflow states visíveis.
56. regulatory/quality/credit gates explicáveis.
57. field-level masking refletido na UI.
58. Object Storage integrado.
59. Print Agent UX.
60. design system.
61. terminologia de domínio.
62. PT-BR inicial.
63. formatação local separada da API.
64. timezone tratado.
65. preferências de usuário.
66. cockpit técnico.
67. UX adequada para falhas externas.
68. M21 indisponível não bloqueia operação.
69. M22 indisponível não autoaprova.
70. M18 indisponível bloqueia gate crítico.
71. desktop/mobile com responsabilidades claras.
72. backend revalida segurança.
73. navegação consistente com Etapa 6.
74. telas respeitam Etapa 5.
75. telas respeitam Etapa 1.

---

# 145. Decisões Arquiteturais Consolidadas

## A. A Home é personalizada por função

## B. Menu deriva de permissão e scope

## C. Tela não duplica autoridade de outro módulo

## D. Drill-through é preferível à duplicação de telas

## E. Bulk operacional usa M23

## F. Aprovações são centralizadas no M22

## G. UX nunca substitui segurança de backend

## H. Operações críticas explicam impacto

## I. Estado assíncrono é explícito

## J. Scanner possui UX especializada

## K. WMS/Qualidade/Manutenção/Aprovações são mobile-first quando aplicável

## L. Desktop permanece superior para análise e grids

## M. Read-only snapshots são visualmente imutáveis

## N. Histórico e auditoria são primeira classe

## O. Falhas de gates críticos são visíveis e fail-closed

---

# 146. Visão Consolidada de Navegação

```text
                           USER
                             │
                             ▼
                     PERSONALIZED HOME
                             │
             ┌───────────────┼────────────────┐
             │               │                │
             ▼               ▼                ▼
         COCKPITS         WORKLISTS        SEARCH
             │               │                │
             └───────┬───────┴────────┬───────┘
                     ▼                ▼
                  DETAILS          WORKSPACES
                     │                │
          ┌──────────┼───────┐        │
          ▼          ▼       ▼        ▼
       Related     Audit   Timeline  Commands
          │                           │
          ▼                           ▼
   Cross-Domain Link            Backend/API
                                      │
                                      ▼
                               Domain Application
```

---

# 147. Status Formal da Etapa 7

A **Etapa 7 — Mapa Completo de Telas e Navegação do ERP** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- shell global;
- menu;
- homes;
- screen IDs;
- cockpits;
- lists;
- details;
- workspaces;
- wizards;
- dashboards;
- mobile/PWA;
- scanner;
- workflow UX;
- drill-through;
- cross-domain navigation;
- visual security;
- asynchronous UX;
- design system.

Alterações incompatíveis devem seguir:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 148. Próxima Etapa

```text
ETAPA 8
INFRAESTRUTURA, DEPLOYMENT, OBSERVABILIDADE E SEGURANÇA OPERACIONAL
```

A próxima etapa consolidará:

- ambientes;
- containers;
- PostgreSQL;
- RabbitMQ;
- Redis;
- Celery;
- Object Storage;
- CI/CD;
- secrets;
- backup;
- DR;
- HA;
- observabilidade;
- logs;
- métricas;
- traces;
- alertas;
- vulnerabilidades;
- patching;
- SLO/SLA;
- capacity planning;
- runbooks;
- segurança operacional.

---

**Fim da Etapa 7 — Mapa Completo de Telas e Navegação do ERP**
