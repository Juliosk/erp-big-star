# Runbook operacional — M5 Inventory Foundation & Reservation

Este runbook cobre as Sprints 6 e 7: estrutura física de estoque, lotes, ledger
imutável, saldos versionados, ajustes auditáveis, projeção assíncrona de
movimentações, reservas HARD/SOFT, disponibilidade ATP e tela básica em `/ui/`.

## Escopo entregue

- Cadastros físicos por empresa: depósitos, localizações, pools e lotes.
- Ledger append-only: `inventory_transaction` e `inventory_posting`.
- Saldo transacional: `inventory_balance`, com quantidade em seis casas
  decimais e versão de concorrência otimista.
- Ajuste de estoque: `POST /api/v1/inventory/adjustments`, idempotente por
  `Idempotency-Key`, com Audit e evento `InventoryAdjusted` no Outbox.
- Consultas oficiais: saldos e rastreabilidade por lote.
- Consumer M5: leitura idempotente de `InventoryAdjusted` via RabbitMQ/Inbox e
  projeção `inventory_movement_projection`.
- Reservas HARD/SOFT: criação idempotente, liberação com `If-Match`/ETag,
  expiração com `SKIP LOCKED`, Audit e Outbox transacionais.
- Disponibilidade ATP: cálculo por bucket como `on_hand - HARD ativo`, mantendo
  SOFT separado para visibilidade operacional.
- Interface Web `/ui/`: saldos, ATP, reservas, estrutura física, ajuste rápido e
  rastreio de lote.

Pedidos, picking, expedição, faturamento e motor de alocação ficam fora deste
slice. M5 expõe disponibilidade/reserva; os demais módulos consomem contratos
públicos em sprints posteriores.

## Permissões

Para operação completa em ambiente local/test com `DevSecurityContextResolver`,
inclua ou mantenha os grants abaixo:

```powershell
$env:DEV_AUTH_PERMISSIONS = '["admin.company.read","inventory.balance.read","inventory.availability.read","inventory.reservation.manage","inventory.warehouse.read","inventory.warehouse.create","inventory.location.read","inventory.location.create","inventory.pool.read","inventory.pool.create","inventory.lot.read","inventory.lot.create","inventory.adjustment.create"]'
```

O default local/test do projeto já inclui estes grants, mas ambientes
compartilhados devem receber permissões pelo provedor de identidade oficial.

## Endpoints principais

| Operação | Contrato |
| --- | --- |
| Depósitos | `GET/POST /api/v1/inventory/warehouses` |
| Localizações | `GET/POST /api/v1/inventory/locations` |
| Pools | `GET/POST /api/v1/inventory/pools` |
| Lotes | `GET/POST /api/v1/inventory/lots` |
| Saldos | `GET /api/v1/inventory/balances` |
| Disponibilidade ATP | `GET /api/v1/inventory/availability` |
| Reservas | `GET/POST /api/v1/inventory/reservations` |
| Detalhe de reserva | `GET /api/v1/inventory/reservations/{reservation_id}` |
| Liberação de reserva | `POST /api/v1/inventory/reservations/{reservation_id}/release` |
| Rastreio por lote | `GET /api/v1/inventory/lots/{lot_id}/postings` |
| Ajuste idempotente | `POST /api/v1/inventory/adjustments` |

Toda chamada exige `company_id` explícito e identidade autorizada para a empresa
de trabalho. Writes de ajuste e reserva exigem `Idempotency-Key`; release exige
também `If-Match` com a versão atual da reserva. Falhas seguem o Error Contract
padronizado, incluindo `VERSION_CONFLICT` e
`INVENTORY_RESERVATION_CONFLICT`.

## Operação de reservas

1. Consulte `GET /api/v1/inventory/availability` para localizar o bucket
   disponível por produto, depósito, lote, pool e estado.
2. Crie reserva em `POST /api/v1/inventory/reservations` com
   `reservation_kind=HARD` para bloquear ATP ou `SOFT` para registrar intenção
   sem reduzir ATP rígido.
3. Para liberar, leia a reserva ou use a versão retornada na criação e envie
   `POST /api/v1/inventory/reservations/{id}/release` com `If-Match`.
4. Reservas vencidas são processadas pelo serviço de expiração com lock
   `SELECT FOR UPDATE SKIP LOCKED`, permitindo execução concorrente segura.

O saldo físico não é alterado por reserva/liberação/expiração; disponibilidade é
derivada das reservas ativas e do saldo versionado.

## Eventos e projeção assíncrona

O ajuste publica `InventoryAdjusted` no Outbox com aggregate
`inventory_adjustment`. O transporte RabbitMQ usa a routing key
`inventory.inventory-adjustment.adjusted.v1` e a fila do projector
`erp.inventory.movement-projector.adjusted.v1`.

O consumer `InventoryMovementProjectionConsumer` grava uma linha única por
`event_id` em `inventory.inventory_movement_projection` através do Inbox. Replays
do mesmo evento incrementam a tentativa do Inbox e não duplicam projeções.

Reservas publicam no Outbox os eventos:

- `InventoryReservationCreated`
- `InventoryReservationReleased`
- `InventoryReservationExpired`

Os envelopes usam `aggregate_type=inventory_reservation`, `aggregate_id`,
`aggregate_version`, `company_id`, `request_id` e `correlation_id`, permitindo
rastreabilidade assíncrona sem acoplamento com pedidos.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_inventory_api.py tests\integration\test_inventory_adjustments_api.py tests\integration\test_inventory_events_e2e.py tests\integration\test_inventory_reservations_api.py tests\integration\test_inventory_reservations_repository.py tests\integration\test_inventory_browser.py
```

Para validar a UI com navegador real:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest tests\integration\test_inventory_browser.py
```

O teste gera evidências em `test-results/inventory-reservations-desktop.png` e
`test-results/inventory-reservations-mobile.png`.

## Observabilidade e recuperação

- Cada ajuste e mutação de reserva grava Audit com `request_id` e
  `correlation_id`.
- O Outbox preserva o evento de domínio mesmo se o envio assíncrono ainda não
  tiver sido consumido.
- O Inbox garante idempotência por consumidor e evento.
- Em falha de RabbitMQ, não recrie volumes de PostgreSQL/MinIO/Redis. Verifique
  primeiro saúde do Docker Compose e soquetes de runtime, preservando dados
  locais.
