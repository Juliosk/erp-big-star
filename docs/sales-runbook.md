# Runbook operacional — M15 Cotações B2B e M4 Pedidos

Este runbook cobre a Sprint 11: cotações revisionadas, aprovação de descontos,
conversão idempotente em pedidos e Sales Cockpit em `/ui/`.

## Limites e responsabilidade

O M15 é dono da proposta comercial e de suas revisões imutáveis. O M4 recebe
uma fotografia congelada da revisão aceita. Reservas de estoque, faturamento,
expedição e financeiro não fazem parte desta sprint.

Todos os registros, consultas, locks e restrições de unicidade incluem
`company_id`. A UI usa apenas APIs oficiais e nunca persiste token ou contexto
em `localStorage` ou `sessionStorage`.

## Permissões

| Permissão | Uso |
| --- | --- |
| `sales.quote.create` | criar cotação |
| `sales.quote.read` | listar e detalhar cotações |
| `sales.quote.update` | revisar, aceitar ou marcar perdida |
| `sales.quote.send` | enviar cotação |
| `sales.discount.request` | abrir alçada M22 para desconto |
| `sales.quote.convert` | autorizar conversão da cotação |
| `sales.order.create` | criar pedido pela conversão |
| `sales.order.read` | listar e detalhar pedidos |

A solicitação de desconto também exige `workflow.request.create`. Consultar ou
decidir a solicitação continua exigindo as permissões próprias do M22.

## Fluxo operacional

1. Crie uma cotação informando número e cliente da empresa selecionada.
2. Inclua uma revisão com produto, quantidade, preço e desconto.
3. Para exceção de desconto, solicite aprovação; deve existir definição M22
   ativa para `SALES / QUOTE_DISCOUNT`.
4. Envie e registre aceitação total ou parcial.
5. Informe o número do pedido e converta a cotação aceita.
6. Consulte o pedido criado na seção **Pedidos gerados**.

Revisões e mutações exigem `If-Match: "N"`. A conversão também exige
`Idempotency-Key`. Repetir a mesma chave e payload devolve o mesmo pedido sem
duplicar Audit, Outbox ou itens. Payload diferente com a mesma chave retorna
`IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`.

## Endpoints

| Operação | Contrato |
| --- | --- |
| Criar/listar cotação | `POST/GET /api/v1/sales/quotes` |
| Detalhar cotação | `GET /api/v1/sales/quotes/{id}` |
| Criar revisão | `POST /api/v1/sales/quotes/{id}/revisions` |
| Enviar/aceitar/perder | `POST /api/v1/sales/quotes/{id}/{ação}` |
| Solicitar desconto | `POST /api/v1/sales/quotes/{id}/discount-approval` |
| Converter em pedido | `POST /api/v1/sales/quotes/{id}/convert-to-order` |
| Listar pedidos | `GET /api/v1/sales/orders` |
| Detalhar pedido | `GET /api/v1/sales/orders/{id}` |

## Consistência e eventos

A conversão bloqueia a cotação com `SELECT FOR UPDATE`. Pedido, itens,
cotação `CONVERTED`, Audit, evento `SalesOrderCreatedFromQuote` e conclusão da
idempotência compartilham a mesma transação PostgreSQL. Cada item preserva o
`quote_revision_item_id` e o `pricing_snapshot_id` da decisão comercial.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib
```

O E2E Chromium gera:

- `test-results/sales-cockpit-desktop.png`
- `test-results/sales-cockpit-mobile.png`

## Troubleshooting

- `VERSION_CONFLICT`: releia a cotação e repita com o ETag atual.
- `PRECONDITION_REQUIRED`: envie `If-Match` nas mutações.
- `SALES_ORDER_CONFLICT`: confira número e conversão anterior da cotação.
- `RESOURCE_NOT_FOUND`: confira empresa selecionada e escopo da identidade.
- Falha ao solicitar desconto: confirme a definição M22 `QUOTE_DISCOUNT`.
- Em falha do Docker, preserve volumes e VHDX. Não use factory reset ou prune
  com volumes.

## Critérios de aceite da Sprint 11

- Cotação e pedido isolados por empresa.
- Revisões e snapshots comerciais preservados.
- Lifecycle protegido por ETag e concorrência otimista.
- Conversão atômica e idempotente.
- Audit/Outbox no mesmo transaction boundary.
- Cockpit responsivo validado no Chromium real.
- Ruff, Mypy, fronteiras arquiteturais e suíte global verdes.
