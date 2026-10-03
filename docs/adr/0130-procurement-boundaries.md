# ADR 0130 — Fronteiras do M6 Procurement

- **Status:** Accepted
- **Data:** 2026-09-21
- **Decisão:** Sprint 13 / Commit 130

## Contexto

O M6 inicia a Wave 3 como proprietário de fornecedores, requisições, pedidos de
compra e recebimento operacional. O roadmap também prevê integrações futuras
com M11 Fiscal e M12 Financeiro. Sem uma fronteira explícita, snapshots fiscais
ou obrigações financeiras poderiam transformar Procurement em autoridade de
dados que pertencem a outros módulos.

## Decisão

O pacote canônico é `erp.modules.procurement` e mantém quatro camadas:

```text
procurement/
├── domain/          # regras puras de Supplier, Requisition, PO e Receipt
├── application/     # casos de uso, ports e autorização
├── infrastructure/  # persistência e adapters próprios do M6
└── api/             # contratos HTTP do M6
```

### Autoridade do M6

O M6 é System of Record de:

- `Supplier` e `SupplierSite`;
- relação operacional produto–fornecedor;
- `PurchaseRequisition`;
- `RequestForQuotation` e resposta de fornecedor;
- `PurchaseOrder`;
- `GoodsReceipt` e three-way match operacional;
- snapshots operacionais necessários para preservar decisões de compra.

### Fronteira com M11 Fiscal

M11 será a única autoridade de documentos fiscais de entrada e saída. M6 poderá
guardar apenas `fiscal_document_id` e snapshot operacional imutável. M6 não:

- emite, autoriza, cancela ou corrige documento fiscal;
- grava tabelas do schema `fiscal`;
- importa ORM, repositories, services ou API internos do M11;
- interpreta regras tributárias como regra de Procurement.

Integração ocorrerá por eventos versionados ou contratos públicos injetados na
composition root. `InboundInvoiceReceived` não transfere autoridade fiscal ao
M6.

### Fronteira com M12 Financeiro

M12 será a única autoridade de contas a pagar/receber, caixa, bancos, liquidação
e conciliação. M6 apenas solicita a criação de obrigação por
`PayableRequested`, depois dos gates operacionais. M6 não:

- cria parcelas ou títulos financeiros diretamente;
- baixa, liquida, renegocia ou concilia obrigações;
- grava tabelas do schema `finance`;
- importa ORM, repositories, services ou API internos do M12.

### Dependências permitidas

- `erp.modules.admin.contracts` para identidade, RBAC e escopo corporativo;
- contratos públicos de Product, Inventory e Workflow quando o respectivo
  slice for implementado;
- primitivas técnicas compartilhadas somente fora do domínio puro;
- DTOs e ports definidos pelo próprio M6.

O domínio M6 não importa outro módulo ou tecnologia. Application não depende de
FastAPI, SQLAlchemy, Celery, Redis ou adapters. Integrações entre owners são
conectadas em `erp.apps`, nunca dentro do domínio.

## RBAC inicial

| Permissão | Risco | Uso |
| --- | --- | --- |
| `procurement.supplier.read` | MEDIUM | consultar fornecedor e sites |
| `procurement.supplier.manage` | HIGH | criar e alterar fornecedor |
| `procurement.requisition.read` | MEDIUM | consultar requisição |
| `procurement.requisition.manage` | HIGH | criar e transicionar requisição |
| `procurement.order.read` | MEDIUM | consultar pedido de compra |
| `procurement.order.manage` | HIGH | criar e transicionar pedido de compra |

A decisão de aprovação usa `workflow.approval.decide`, pertencente ao M22.
Criador e aprovador do pedido devem ser atores distintos quando a política de
SoD exigir aprovação.

## Transações e integração

- Todo registro operacional inclui `company_id`.
- Escritas críticas usam Audit e Outbox no mesmo transaction boundary.
- Comandos externos são idempotentes e recursos concorrentes usam versão/ETag.
- Consumers usam Inbox por `consumer_name + event_id`.
- M6 não participa de dual write com legado, M11 ou M12.

## Enforcement

`tests/unit/test_architecture_boundaries.py` verifica que o pacote Procurement:

- não importa internals de outros módulos;
- nunca depende diretamente dos futuros pacotes Fiscal ou Financeiro;
- acessa outros owners somente por módulos `contracts` explicitamente
  permitidos;
- preserva as regras gerais de domínio e aplicação do Monólito Modular.

## Consequências

O fluxo completo será deliberadamente assíncrono e desacoplado:

```text
M6 Purchase/Receipt
→ M11 Fiscal
→ M12 Payable
```

Isso adiciona contratos e estados de integração explícitos, mas preserva owner,
auditabilidade, reprocessamento idempotente e evolução independente dos três
módulos.
