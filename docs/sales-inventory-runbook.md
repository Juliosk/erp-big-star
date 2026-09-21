# Runbook operacional — M4 Pedidos → M5 Reservas

Este runbook consolida a Sprint 12 e o fechamento do MVP-1 Técnico: pedido
aprovado, reserva física, hold, disponibilidade ATP, cancelamento/liberação e
expiração sincronizada entre Vendas e Estoque.

## Limites de domínio

- M4 é dono do pedido e da projeção `SalesOrderReservation`.
- M5 é dono da reserva física, alocações e disponibilidade.
- M4 consome somente o contrato público do M5; os domínios não importam ORM ou
  repositórios um do outro.
- Todo comando e consulta é escopado por `company_id`.
- Reserva, saldo, Audit, Outbox e idempotência compartilham a transação crítica.
- Eventos recebidos são protegidos por Inbox e `consumer_name + event_id`.

## Permissões

| Permissão | Uso |
| --- | --- |
| `sales.order.read` | listar e detalhar pedidos |
| `sales.order.reserve` | consultar, criar e estender a reserva do pedido |
| `sales.order.cancel` | cancelar pedido e liberar a reserva física |
| `inventory.availability.read` | consultar ATP no Cockpit de Vendas |
| `inventory.warehouse.read` | selecionar o depósito da reserva |

## Fluxo operacional no Cockpit

1. Abra `/ui/`, conecte a identidade e selecione a empresa de trabalho.
2. Em **Vendas**, converta a cotação aceita em pedido.
3. Após aprovação do pedido, use **Gerir** na linha do pedido.
4. Confira ATP, quantidade requerida e depósito; escolha `HARD` ou `SOFT`.
5. Solicite a reserva. O relógio mostra o prazo restante do hold.
6. Use **Estender hold +2h** quando houver justificativa operacional.
7. Use **Cancelar pedido e liberar** para cancelar o pedido e devolver o ATP na
   mesma transação.
8. Holds vencidos são processados em lote pelo M5 e sincronizados para M4 como
   `EXPIRED`.

A UI não armazena token ou contexto em `localStorage`/`sessionStorage`. O timer
é apenas uma representação do prazo persistido; o relógio e a transição
autoritativos permanecem no backend.

## APIs

| Operação | Contrato |
| --- | --- |
| Solicitar reserva | `POST /api/v1/sales/orders/{id}/reserve` |
| Consultar reserva | `GET /api/v1/sales/orders/{id}/reservation` |
| Estender hold | `POST /api/v1/sales/orders/{id}/reservation/extend-hold` |
| Cancelar e liberar | `POST /api/v1/sales/orders/{id}/cancel` |
| Consultar ATP | `GET /api/v1/inventory/availability` |
| Consultar depósitos | `GET /api/v1/inventory/warehouses` |

Os comandos exigem `Idempotency-Key`; mutações concorrentes também exigem
`If-Match: "N"`. Em conflito, releia o recurso e use o ETag mais recente.

## Eventos e recuperação

| Evento | Origem | Efeito |
| --- | --- | --- |
| `SalesOrderInventoryReserved` | M4 | confirma o vínculo comercial no M5 |
| `SalesOrderReservationReleased` | M4 | rastreia a liberação coordenada |
| `InventoryReservationExpired` | M5 | expira a projeção do hold no M4 |
| `SalesOrderReservationExpired` | M4 | publica a projeção comercial expirada |

Outbox não publicado deve permanecer pendente para retry. Inbox `PROCESSED`
com `attempts > 1` indica redelivery absorvida de forma idempotente. Não altere
linhas de Outbox/Inbox manualmente sem diagnóstico e correlação por
`request_id`/`correlation_id`.

## Operação do worker de expiração

O job chama `PostgresInventoryReservations.expire_due` em lotes limitados. A
seleção usa `FOR UPDATE SKIP LOCKED`, permitindo múltiplos workers sem processar
a mesma reserva. A publicação `InventoryReservationExpired` ocorre na mesma
transação que libera a disponibilidade.

## Validação e evidências

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib
```

O E2E Chromium cobre cotação, pedido, reserva, ATP, hold, extensão,
cancelamento/liberação e expiração. Evidências:

- `test-results/sales-inventory-cockpit-desktop.png`
- `test-results/sales-inventory-cockpit-mobile.png`

## Troubleshooting

- `VERSION_CONFLICT`: recarregue pedido/reserva e repita com o ETag atual.
- `INVENTORY_RESERVATION_CONFLICT`: confira ATP, dimensões e reserva anterior.
- `RESOURCE_NOT_FOUND`: confirme empresa, pedido e escopo da identidade.
- ATP não exibido: valide `inventory.availability.read` e o depósito selecionado.
- Hold expirado ainda ativo no M4: confira o evento M5 no Outbox e o receipt do
  consumer `sales.order-reservation-projector.v1` no Inbox.
- Em falha Docker, preserve volumes e VHDX; não use factory reset ou prune com
  volumes.

## Critérios de encerramento do MVP-1 Técnico

- Fundação corporativa, catálogo, clientes, estoque, pricing, workflow, vendas e
  WMS permanecem isolados no Monólito Modular.
- Pedido comercial reserva estoque sem over-reservation.
- Cancelamento libera fisicamente o estoque de forma atômica.
- Expiração restaura ATP e sincroniza a projeção comercial.
- Audit, Outbox, Inbox, idempotência e concorrência otimista estão ativos.
- Cockpits responsivos usam apenas APIs oficiais e respeitam RBAC/tenant.
- Migrações, Ruff, Mypy, fronteiras arquiteturais, testes e Chromium estão
  verdes antes da homologação.
