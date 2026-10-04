# Runbook operacional — M6 Procurement

Este runbook consolida a Sprint 13: fornecedores, requisições, pedidos de
compra, integração de aprovação com M22, segregação de funções e Procurement
Cockpit em `/ui/`.

## Ownership e fronteiras

O M6 é autoridade de `Supplier`, `SupplierSite`, `PurchaseRequisition` e
`PurchaseOrder`. A aprovação formal pertence ao M22. O M6 não grava tabelas do
Workflow e o M22 não altera pedidos diretamente: a decisão retorna por evento
e é efetivada pelo consumer idempotente do Procurement.

M11 continuará sendo autoridade fiscal e M12 será autoridade financeira. Um
recebimento futuro poderá referenciar fatos desses módulos, mas não criará
documento fiscal nem obrigação financeira dentro do schema `procurement`.

Todos os recursos são vinculados a `company_id`. Chaves, repositories, APIs,
Audit, Outbox e Inbox preservam o tenant em cada operação.

## Permissões RBAC

| Permissão | Operação |
| --- | --- |
| `procurement.supplier.read` | listar e consultar fornecedores e estabelecimentos |
| `procurement.supplier.manage` | cadastrar e alterar fornecedor |
| `procurement.requisition.read` | listar e consultar requisições |
| `procurement.requisition.manage` | criar e transicionar requisições |
| `procurement.order.read` | listar e consultar pedidos de compra |
| `procurement.order.manage` | criar e transicionar pedidos de compra |
| `workflow.request.create` | abrir solicitação formal no M22 |
| `workflow.request.read` | acompanhar a instância de aprovação |
| `workflow.approval.decide` | decidir a etapa ativa no M22 |

Permissão de gestão não equivale a aprovação. A regra dinâmica de SoD impede
que solicitante ou comprador aprove a própria operação e retorna
`SOD_VIOLATION`.

## APIs operacionais

| Recurso | Contratos principais |
| --- | --- |
| Fornecedores | `GET/POST /api/v1/procurement/suppliers` |
| Detalhe/alteração | `GET/PATCH /api/v1/procurement/suppliers/{id}` |
| Requisições | `GET/POST /api/v1/procurement/requisitions` |
| Transições | `POST /api/v1/procurement/requisitions/{id}/{action}` |
| Pedidos | `GET/POST /api/v1/procurement/purchase-orders` |
| Transições | `POST /api/v1/procurement/purchase-orders/{id}/{action}` |
| Recebimento atual | `POST /api/v1/procurement/purchase-orders/{id}/receive` |

Alterações exigem `If-Match: "N"`. Leituras de detalhe retornam ETag. Versão
desatualizada retorna `VERSION_CONFLICT`; ausência do header retorna
`PRECONDITION_REQUIRED`.

## Eventos publicados e consumidos

| Direção | Evento | Finalidade |
| --- | --- | --- |
| M6 → broker/M22 | `PurchaseApprovalRequested` | solicitar aprovação formal de requisição ou pedido |
| M6 → broker | `PurchaseOrderApproved` | registrar aprovação efetivada no owner |
| M6 → broker | `PurchaseOrderRejected` | registrar rejeição efetivada no owner |
| M6 → broker | `PurchaseOrderCancelled` | registrar cancelamento do pedido |
| M22 → M6 | `ApprovalDecisionMade` | devolver decisão formal para aplicação no pedido |

A mutação, Audit e Outbox compartilham a mesma transação PostgreSQL. O consumer
`procurement.approval-decision.v1` valida envelope, tenant e SoD, processa o
evento uma única vez e registra Inbox antes do commit.

## Operação do Cockpit

1. Inicie a API e abra `/ui/`.
2. Conecte a identidade e selecione a empresa de trabalho.
3. Abra **Compras M6**.
4. Cadastre o fornecedor e confira documento e status.
5. Abra a requisição, informe produto, quantidade, prazo e justificativa.
6. Envie a requisição para aprovação e acompanhe o estado.
7. Após aprovação, crie o pedido vinculado à requisição e ao fornecedor.
8. Use **Solicitar aprovação M22** no pedido em rascunho.
9. Um ator diferente decide no Cockpit de Aprovações M22.
10. Após o consumer processar `ApprovalDecisionMade`, atualize Compras para
    visualizar `APPROVED` ou `REJECTED`.

O token permanece somente em memória. Trocar a empresa recarrega fornecedores,
requisições e pedidos usando o novo `company_id`. A UI não usa armazenamento
local do navegador.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib `
  tests\unit\modules\procurement `
  tests\integration\test_procurement_schema.py `
  tests\integration\test_procurement_supplier_repository.py `
  tests\integration\test_procurement_supplier_api.py `
  tests\integration\test_procurement_purchasing_repository.py `
  tests\integration\test_procurement_purchasing_api.py `
  tests\integration\test_procurement_browser.py `
  tests\unit\test_architecture_boundaries.py
```

O Chromium gera:

- `test-results/procurement-cockpit-desktop.png`;
- `test-results/procurement-cockpit-mobile.png`.

## Troubleshooting

- `SOD_VIOLATION`: conecte outro ator autorizado para decidir.
- `VERSION_CONFLICT`: releia o recurso e repita com o novo ETag.
- `SUPPLIER_CONFLICT`: confirme documento e empresa antes de cadastrar.
- Pedido ausente no seletor: somente requisições `APPROVED` originam pedidos.
- Decisão concluída no M22 e pedido ainda pendente: verifique publicação do
  Outbox, fila, retries/DLQ e Inbox do consumer M6.
- Cockpit vazio após trocar a empresa é o resultado esperado quando o tenant
  não possui dados.

Nunca execute factory reset, `docker system prune -a --volumes` ou remova
volumes para corrigir indisponibilidade local.

## Encerramento da Sprint 13

- domínio M6 framework-free e fronteiras cobertas por teste;
- schema `procurement` e migrations 0031–0033 ativos;
- suppliers, requisitions e purchase orders tenant-bound;
- concorrência otimista, Audit, Outbox, Inbox e SoD operacionais;
- Cockpit responsivo consumindo exclusivamente APIs oficiais;
- jornada E2E M6 → M22 → M6 coberta em Chromium real.

## Próximo slice — Sprint 14

A Sprint 14 inicia o recebimento físico integrado:

1. agregado `GoodsReceipt` e itens recebidos no M6;
2. recebimento parcial, divergências e idempotência de documento operacional;
3. gate de inspeção de entrada pertencente ao M17;
4. posting físico executado exclusivamente pelo M5;
5. eventos `GoodsReceiptStarted`, `GoodsReceived` e decisões de qualidade;
6. concorrência, Audit/Outbox/Inbox, APIs, UI e E2E do recebimento.

Ficam fora do slice inicial a escrituração fiscal M11, o contas a pagar M12 e o
three-way match financeiro completo.
