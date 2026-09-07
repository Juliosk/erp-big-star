# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 1 — Arquitetura Corporativa Consolidada e Fronteiras de Domínio

**Status:** APROVADO  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Consolidação arquitetural dos módulos M1–M23  
**Objetivo:** Estabelecer a baseline oficial de arquitetura, fronteiras de domínio, autoridades de dados, invariantes corporativos, padrões de integração e fluxos unificados do ERP industrial/omnichannel Big Star / Forma Kids.

---

# 1. Objetivo da Etapa 1

A Etapa 1 consolida as decisões tomadas ao longo das entrevistas investigativas dos 23 módulos funcionais do ERP, transformando definições isoladas em uma arquitetura corporativa única, coerente e implementável.

Esta etapa estabelece:

- baseline tecnológica oficial;
- estilo arquitetural;
- regras do Monólito Modular;
- fronteiras dos 23 Bounded Contexts;
- autoridade de dados por domínio;
- invariantes corporativos;
- fluxos unificados de negócio;
- separação entre fatos físicos, fiscais, financeiros e contábeis;
- padrões de integração síncrona e assíncrona;
- uso de Transactional Outbox e Inbox;
- estratégia de idempotência;
- regras de consistência;
- padrão de identificadores;
- regras de precisão monetária e quantitativa;
- temporalidade;
- imutabilidade histórica;
- armazenamento de arquivos;
- rastreabilidade por correlation IDs;
- auditoria corporativa;
- reason codes estruturados;
- multiempresa e grupo econômico.

Esta documentação passa a constituir a **referência oficial da Etapa 1 da Consolidação Geral da Arquitetura M1–M23**.

---

# 2. Baseline Tecnológico Oficial

```text
Frontend Web
    │
    │ HTTPS / REST
    ▼
FastAPI
    │
    ▼
Modular Monolith
Python
    │
    ├── SQLAlchemy 2.x
    ├── Pydantic
    ├── Alembic
    │
    ├── PostgreSQL OLTP
    │
    ├── Transactional Outbox
    │
    └── Domain Modules M1–M23
    │
    ├───────────────┐
    ▼               ▼
 RabbitMQ         Redis
    │             Cache
    │             Locks
    │             Debounce
    │             Rate Limits
    ▼
Celery Workers / Beat
    │
    ├── Integrações externas
    ├── Jobs assíncronos
    ├── Exportações
    ├── Reconciliações
    └── Analytics Pipeline

Object Storage
S3 / MinIO
    │
    ├── XML
    ├── DANFE
    ├── Certificados
    ├── Laudos
    ├── Fotos
    ├── Documentos RH
    ├── CAD
    ├── Imports
    └── Exports

Analytics Store
fisicamente separado
    │
    ▼
M21 BI / Semantic Layer
```

## 2.1 Backend

- Linguagem principal: **Python**
- Framework HTTP/API: **FastAPI**
- ORM: **SQLAlchemy 2.x**
- DTOs/validação: **Pydantic**
- Migrações: **Alembic**
- Cliente HTTP externo: **HTTPX**

## 2.2 Banco Transacional

Banco oficial:

```text
PostgreSQL
```

O Firebird não faz parte da arquitetura do novo ERP.

## 2.3 Mensageria

Broker durável:

```text
RabbitMQ
```

Usos:

- eventos de domínio;
- filas de integração;
- processamento assíncrono;
- retries;
- desacoplamento entre módulos.

## 2.4 Redis

Uso exclusivo para:

- cache;
- debounce;
- rate limiting;
- locks;
- circuit breaker;
- read models temporários.

Regra:

```text
Redis != fonte durável de verdade
```

## 2.5 Jobs Assíncronos

```text
Celery + Celery Beat
```

Aplicações:

- sincronizações;
- exportações;
- importações;
- reconciliações;
- alertas;
- pipelines analíticos;
- tarefas periódicas.

## 2.6 Object Storage

```text
S3 / MinIO
```

Arquivos pesados ficam no Object Storage. O PostgreSQL mantém somente metadados, checksum e storage key.

---

# 3. Estilo Arquitetural Oficial

```text
MODULAR MONOLITH
+
EVENT-DRIVEN INTEGRATION
+
API FIRST
```

## 3.1 Monólito Modular

Objetivos:

- isolamento de domínio;
- transações locais fortes;
- deploy inicialmente simples;
- menor complexidade operacional;
- capacidade futura de extração de módulos.

Estrutura recomendada:

```text
module/
├── domain/
├── application/
├── infrastructure/
├── api/
├── events/
├── schemas/
└── tests/
```

## 3.2 Regra Máxima de Isolamento

Nenhum módulo altera diretamente tabelas internas de outro módulo.

Proibido:

```sql
UPDATE inventory_balance ...
```

executado pelo M10.

Correto:

```text
M10 WMS
→ InventoryCommand
→ M5
→ Inventory Ledger
```

M22 também não altera diretamente Pedido de Compra. Ele publica uma decisão e M6 efetiva a transação.

## 3.3 API First

Contratos HTTP versionados:

```text
/api/v1/...
```

Frontend e integrações nunca dependem de acesso direto ao banco.

---

# 4. Os 23 Bounded Contexts Oficiais

| Módulo | Bounded Context | Autoridade Principal |
|---|---|---|
| M01 | Administração / Segurança | Empresas, usuários, autenticação, RBAC |
| M02 | Product Master | Produto, SKU, EAN, embalagem, master data de produto |
| M03 | Marketplace Hub | Integração com marketplaces e canais |
| M04 | Orders / Fulfillment | Pedido e execução comercial |
| M05 | Inventory | Verdade física do estoque |
| M06 | Procurement | Compras e recebimento |
| M07 | Manufacturing | Engenharia, PCP e produção |
| M08 | Industrial Costing | Custos industriais e valoração |
| M09 | Pricing | Formação e decisão de preços |
| M10 | WMS / Expedition | Separação, embalagem e expedição |
| M11 | Fiscal | Documentos fiscais e regras tributárias |
| M12 | Finance | Direitos, obrigações, caixa e bancos |
| M13 | Accounting | General Ledger e regras contábeis |
| M14 | Customer / CRM | Golden Record de clientes |
| M15 | B2B Sales | Negociação e orçamento B2B |
| M16 | Commissions | Representantes e comissões |
| M17 | Quality | SGQ e qualidade operacional |
| M18 | Regulatory | Compliance / INMETRO |
| M19 | Assets / Maintenance | Imobilizado e manutenção |
| M20 | HR | Workforce, ponto e integração de folha |
| M21 | Analytics | BI e camada semântica |
| M22 | Workflow | Aprovações corporativas |
| M23 | Data Governance | Importação, exportação e governança de dados |

---

# 5. Agrupamento Macro de Domínios

```text
CORPORATE FOUNDATION
M1
M22
M23

MASTER DATA
M2
M14
M20

COMMERCIAL / OMNICHANNEL
M3
M4
M9
M15
M16

SUPPLY CHAIN
M5
M6
M10

MANUFACTURING
M7
M8
M19

QUALITY / REGULATORY
M17
M18

BACK OFFICE
M11
M12
M13

MANAGEMENT
M21
```

---

# 6. Autoridade Oficial dos Dados

| Informação | System of Record |
|---|---|
| Usuário / acesso | M1 |
| Produto / SKU | M2 |
| Barcode | M2 |
| BOM mestre / estrutura técnica | M2/M7 conforme contexto |
| Listing marketplace | M3 |
| Pedido | M4 |
| Saldo físico | M5 |
| Reserva de estoque | M5 |
| Pedido de compra | M6 |
| Recebimento físico | M6 + posting no M5 |
| OP | M7 |
| Apontamento produtivo | M7 |
| Custo industrial | M8 |
| Preço | M9 |
| Picking / Packing | M10 |
| NF-e | M11 |
| Contas a receber/pagar | M12 |
| Caixa / bancos | M12 |
| Lançamento contábil | M13 |
| Cliente | M14 |
| Orçamento B2B | M15 |
| Comissão | M16 |
| Inspeção / NC / CAPA | M17 |
| Certificado / INMETRO | M18 |
| Ativo patrimonial | M19 |
| Manutenção | M19 |
| Colaborador / organograma | M20 |
| KPI corporativo | M21 |
| Aprovação formal | M22 |
| Carga massiva / Data Governance | M23 |

---

# 7. Invariantes Corporativos

```text
Order
≠
Fiscal Document
```

```text
Invoice
≠
Receivable
```

```text
Shipment
≠
Accounting Entry
```

```text
Physical Inventory Truth
=
M5
```

```text
Debit / Credit
=
M13 Accounting Rules Engine
```

```text
Formal Approval
=
M22
```

```text
Bulk Change
=
M23
```

```text
M21
→ detecta

M21
≠
altera transação
```

Histórico confirmado não é sobrescrito silenciosamente.

---

# 8. Fluxo Unificado Order-to-Cash

```text
M14 CUSTOMER
     │
     ▼
M15 QUOTE / B2B SALE
     │
     ├── M9 Pricing
     ├── M12 Credit
     ├── M22 Approval
     └── M18 Regulatory Gate
     │
     ▼
M4 ORDER
     │
     ▼
M5 RESERVATION
     │
     ▼
M10 PICK / PACK
     │
     ├── M17 Quality Gate
     └── M18 Regulatory Gate
     │
     ▼
M11 NF-e
     │
     ▼
M10 DISPATCH
     │
     ▼
M12 RECEIVABLE
     │
     ▼
M12 SETTLEMENT
     │
     ├── M16 Commission Earning
     └── M13 Accounting
```

Marketplace:

```text
M3
→ M4
```

---

# 9. Fluxo Unificado Procure-to-Pay

```text
Necessidade
   │
   ▼
M6 Purchase Requisition
   │
   ▼
RFQ / Quotes
   │
   ▼
M22 Approval
   │
   ▼
Purchase Order
   │
   ▼
Physical Receipt
   │
   ├── M17 Incoming Inspection
   ├── M5 Inventory
   └── M11 Fiscal Inbound
   │
   ▼
3-Way Match
   │
   ▼
M12 Payable
   │
   ▼
Payment
   │
   ▼
M13 Accounting
```

---

# 10. Fluxo Unificado Plan-to-Produce

```text
Demand
  │
  ▼
M7 MRP / PCP
  │
  ├── M5 Inventory
  ├── M6 Purchase Supply
  └── M7 Production Supply
  │
  ▼
Production Order
  │
  ├── M18 Production Gate
  ├── M17 First Piece
  └── M19 Machine Availability
  │
  ▼
Material Consumption
  │
  ▼
Production Yield
  │
  ▼
Finished Lot
  │
  ├── M17 Final Inspection
  ├── M18 Compliance Snapshot
  └── M5 Inventory
  │
  ▼
M8 Actual Cost
```

---

# 11. Separação entre Físico, Fiscal, Financeiro e Contábil

```text
PHYSICAL
M5 / M7 / M10

FISCAL
M11

FINANCIAL
M12

ACCOUNTING
M13
```

Exemplo:

```text
NF autorizada
→ fato fiscal

Título criado
→ fato financeiro

Mercadoria despachada
→ fato físico

Receita / CMV lançados
→ fato contábil
```

Um fato nunca substitui automaticamente outro.

---

# 12. Customer-to-Cash

```text
M14
Customer Master
   │
   ▼
M15
Commercial Negotiation
   │
   ├── M9 Price
   ├── M12 Credit
   └── M22 Approval
   │
   ▼
M4
Order Execution
   │
   ▼
M11
Fiscal
   │
   ▼
M12
Receivable / Settlement
   │
   ▼
M13
Accounting
```

---

# 13. Produto → Produção → Custo → Preço

```text
M2
Product Master
   │
   ▼
M7
Production Version
   │
   ├── BOM Revision
   └── Routing Revision
   │
   ▼
M18
Regulatory Approval
   │
   ▼
M7
Production
   │
   ▼
M17
Quality
   │
   ▼
M8
Cost
   │
   ▼
M9
Price
```

---

# 14. Fronteira M17 x M18

M17 responde:

> O produto atende às especificações de qualidade?

M18 responde:

> O produto está legalmente/regulatoriamente apto a ser produzido e comercializado?

Regra:

```text
Quality Approved
≠
Regulatory Released
```

---

# 15. Fronteira M19 x M7

M19 é dono da disponibilidade técnica do equipamento.

```text
M19
→ MaintenanceAssetUnavailable
→ M7 block
```

Corretiva fabril:

```text
M19 COMPLETED
+
Production VALIDATED
→ MaintenanceAssetReleased
→ M7 release
```

---

# 16. Fronteira M20 x M1

```text
M20
→ pessoa / vínculo / estrutura / disponibilidade

M1
→ identidade digital / autenticação / acesso
```

Fluxo:

```text
EmployeeTerminated
→ M20
→ UserAccessRevocationRequested
→ M1
```

---

# 17. M22 como Serviço Corporativo Transversal

M22 é o único motor formal de:

- aprovação;
- alçada;
- exceção;
- dupla validação;
- quorum;
- SLA;
- escalonamento;
- delegação.

Módulos consumidores:

```text
M6
M9
M12
M13
M15
M16
M17
M18
M19
M20
M21
M23
   │
   ▼
  M22
```

---

# 18. M23 como Gateway de Alterações Massivas

```text
M23
→ staging
→ validation
→ preview
→ approval
→ batching
→ commit
→ audit
```

M23 governa a carga; o módulo proprietário continua validando a regra semântica.

---

# 19. M21 como Consumidor Não Crítico

```text
M21 indisponível
→ ERP continua funcionando
```

Fluxo:

```text
Operational Modules
→ Events
→ M21
```

M21 nunca será dependência síncrona obrigatória para transações operacionais.

---

# 20. Modelo de Integração Interno

## 20.1 Comandos Síncronos

Quando uma decisão é necessária antes de prosseguir:

```text
M10
→ InventoryReservationService
→ M5
```

```text
M7
→ RegulatoryProductionGate
→ M18
```

## 20.2 Eventos Assíncronos

Quando o efeito pode ocorrer após commit:

```text
InvoiceAuthorized
→ M12
→ M13
→ M21
```

---

# 21. Transactional Outbox

```text
Business Transaction
+
Outbox Event
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

# 22. Inbox e Idempotência

Padrão:

```text
event_id UUID
```

Restrição conceitual:

```text
UNIQUE (consumer, event_id)
```

Garantia:

```text
evento duplicado
→ efeito idempotente
```

---

# 23. Garantia de Entrega

Modelo oficial:

```text
AT-LEAST-ONCE
+
IDEMPOTENT CONSUMERS
```

Não assumir exactly-once distribuído.

---

# 24. Consistência

```text
Dentro do domínio
→ Strong Consistency
```

```text
Entre efeitos assíncronos
→ Eventual Consistency
```

```text
Cross-domain imediato
→ explicit synchronous application contract
```

---

# 25. Concorrência

Entidades críticas terão:

```text
version
```

Conflito:

```text
HTTP 409 Conflict
```

Aplicável a:

- pedidos;
- orçamento;
- PO;
- workflow;
- políticas;
- cadastros mestres;
- fechamentos;
- previews de importação.

---

# 26. Identificadores

Chave técnica:

```text
UUID
```

Número comercial separado:

```text
business_number
```

Exemplo:

```text
order.id
UUID

order.order_number
100238
```

---

# 27. Precisão Monetária e Quantitativa

Usar:

```text
NUMERIC / DECIMAL
```

Nunca:

```text
FLOAT
```

para:

- dinheiro;
- custo;
- preço;
- imposto;
- comissão;
- peso;
- quantidade;
- taxa;
- saldo.

---

# 28. Temporalidade

Entidades históricas devem usar:

```text
valid_from
valid_until
```

Quando aplicável a:

- preços;
- comissão;
- portfolio;
- customer status;
- employee assignment;
- certificados;
- workflows;
- KPIs;
- templates;
- regras fiscais;
- regras contábeis;
- regras de aprovação.

---

# 29. Imutabilidade Histórica

```text
Fato confirmado
→ não apagar
→ não sobrescrever silenciosamente
```

Correções por:

```text
reversal
replacement
new version
compensating event
```

---

# 30. Armazenamento de Arquivos

Arquivos pesados:

```text
S3 / MinIO
```

PostgreSQL:

```text
storage_key
checksum
mime_type
size
metadata
version
```

---

# 31. Correlation IDs

Toda operação distribuída preserva:

```text
correlation_id
request_id
causation_id
```

Exemplo:

```text
Quote Conversion
→ Order
→ Reservation
→ Invoice
→ Receivable
→ Accounting
```

---

# 32. Auditoria Corporativa

Modelo conceitual:

```text
audit_event
```

Campos:

```text
actor
timestamp

company
branch

module
entity
entity_id

operation

before
after

reason_code

request_id
correlation_id

source_ip
device
```

Dados sensíveis devem ser mascarados.

---

# 33. Reason Codes

Overrides relevantes devem registrar:

```text
reason_code
+
optional_comment
```

Aplicável a:

- estoque;
- workflow;
- qualidade;
- pricing;
- crédito;
- comissão;
- ponto;
- ativo;
- fiscal;
- regulatório;
- data governance;
- manutenção.

---

# 34. Multiempresa

Estrutura:

```text
GROUP
→ COMPANY
→ BRANCH
```

O ERP deve separar juridicamente empresas e filiais, mantendo visão consolidada autorizada.

Regra:

```text
consolidação
≠
mistura transacional
```

---

# 35. Baseline Consolidada de Dependências

```text
                          ┌──────────────┐
                          │     M1       │
                          │ Foundation   │
                          └──────┬───────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
       MASTER DATA          TRANSACTIONAL       GOVERNANCE
       M2 M14 M20          M3–M19             M22 M23
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 │
                                 ▼
                               M21
                            ANALYTICS
```

Camadas transversais:

```text
M22
→ governa decisões humanas formais

M23
→ governa movimentação e qualidade dos dados
```

Autoridades estruturais:

```text
M5
=
Physical Inventory Truth

M13
=
Accounting Truth

M21
=
Corporate Semantic / KPI Truth
```

---

# 36. Princípios Corporativos Consolidados

```text
Order != Invoice != Picking != Receivable
```

```text
Physical != Fiscal != Financial != Accounting
```

```text
Quality != Regulatory
```

```text
Employee != User
```

```text
Approval != Transaction
```

```text
Analytics != Operational Truth
```

Princípios:

1. dono único por fato;
2. integração por contratos;
3. eventos at-least-once;
4. consumidores idempotentes;
5. histórico preservado;
6. auditoria desde o início;
7. governança transversal;
8. nenhuma dependência indevida de tabela interna.

---

# 37. Fluxos Corporativos Resumidos

## 37.1 Order-to-Cash

```text
M14
→ M15
→ M9/M12/M22
→ M4
→ M5
→ M10
→ M11
→ M12
→ M16
→ M13
```

## 37.2 Procure-to-Pay

```text
M6
→ M22
→ M6
→ M17/M5/M11
→ M12
→ M13
```

## 37.3 Plan-to-Produce

```text
Demand
→ M7
→ M5/M6
→ M18/M17/M19
→ M7
→ M5
→ M8
```

## 37.4 Quote-to-Order B2B

```text
M14
→ M15
→ M9
→ M12
→ M22
→ M4
```

## 37.5 Marketplace-to-ERP

```text
Marketplace
→ M3
→ M4
→ M5
→ M10
→ M11
→ M12
```

## 37.6 Hire-to-Access

```text
M20
→ EmployeeAdmitted
→ M1
→ User Provisioning
```

## 37.7 Termination-to-Revocation

```text
M20
→ EmployeeTerminated
→ M1
→ Immediate Access Revocation
```

## 37.8 Maintenance-to-Production Availability

```text
M19
→ MaintenanceAssetUnavailable
→ M7 block

M19 COMPLETED
+
Production VALIDATED
→ MaintenanceAssetReleased
→ M7 release
```

## 37.9 Data Change Governance

```text
M23
→ Staging
→ Validation
→ Preview
→ Material Change?
→ M22
→ Commit
→ Domain Module
```

## 37.10 Analytics

```text
M1–M20
→ Events / Incremental Extract
→ M21
→ Semantic Layer
→ Dashboard / Alert
→ M22 quando ação formal for necessária
```

---

# 38. Regras Obrigatórias para Desenvolvimento

1. não acessar tabelas internas de outro módulo;
2. usar serviços de aplicação ou contratos explícitos;
3. publicar eventos relevantes via Outbox;
4. consumidores devem ser idempotentes;
5. usar UUID como PK técnica;
6. usar DECIMAL/NUMERIC para valores e quantidades;
7. aplicar optimistic locking onde houver concorrência;
8. preservar histórico;
9. usar Object Storage para arquivos;
10. preservar correlation_id/request_id/causation_id;
11. registrar reason_code em overrides;
12. respeitar o System of Record de cada domínio;
13. manter segregação entre físico, fiscal, financeiro e contábil;
14. não duplicar motores de aprovação fora do M22;
15. não criar atalhos de bulk update fora do M23;
16. não tornar M21 dependência síncrona da operação;
17. não usar Redis como verdade durável;
18. não registrar segredos em logs;
19. aplicar RBAC e auditoria;
20. manter multiempresa explícito.

---

# 39. Estrutura da Consolidação Geral Após a Etapa 1

| Etapa | Entregável |
|---|---|
| 1 | Arquitetura corporativa e fronteiras de domínio — **CONCLUÍDA E APROVADA** |
| 2 | Modelo de dados consolidado M1–M23 |
| 3 | Catálogo oficial de eventos |
| 4 | Matriz completa de integrações módulo × módulo |
| 5 | RBAC + SoD global |
| 6 | Mapa consolidado de APIs |
| 7 | Mapa completo de telas e navegação |
| 8 | Infraestrutura, deployment, observabilidade e segurança |
| 9 | Roadmap MVP / fases de implantação |
| 10 | Backlog técnico executável / ordem real de desenvolvimento |

---

# 40. Status Formal da Etapa 1

A **Etapa 1 — Arquitetura Corporativa Consolidada e Fronteiras de Domínio** está:

```text
FORMALMENTE APROVADA
```

Esta documentação passa a ser baseline arquitetural oficial para:

- modelagem;
- desenvolvimento;
- code review;
- APIs;
- eventos;
- integrações;
- segurança;
- testes;
- telas;
- governança;
- roadmap técnico.

Mudanças futuras incompatíveis com esta baseline deverão ser tratadas como:

```text
ARCHITECTURE CHANGE REQUEST
```

com justificativa, impacto e versionamento.

---

# 41. Próxima Etapa

```text
ETAPA 2
MODELO DE DADOS CONSOLIDADO M1–M23
```

A Etapa 2 deverá consolidar:

- agregados raiz;
- entidades;
- chaves;
- relacionamentos;
- referências intermodulares;
- ledgers;
- snapshots;
- documentos;
- eventos;
- projeções;
- tabelas de domínio;
- tabelas transversais;
- tabelas de integração;
- convenções de nomenclatura;
- cardinalidades;
- regras de ownership;
- estratégia de índices/particionamento;
- classificação de dados.

---

**Fim da Etapa 1 — Arquitetura Corporativa Consolidada e Fronteiras de Domínio**
