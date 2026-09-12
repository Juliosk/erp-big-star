# Runbook operacional — M5 Inventory Foundation

Este runbook cobre a Sprint 6: estrutura física de estoque, lotes, ledger
imutável, saldos versionados, ajustes auditáveis, projeção assíncrona de
movimentações e tela básica em `/ui/`.

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
- Interface Web `/ui/`: saldos, estrutura física, ajuste rápido e rastreio de
  lote.

Reserva HARD/SOFT, disponibilidade comercial e motor de alocação ficam fora da
Sprint 6 e pertencem à Sprint 7.

## Permissões

Para operação completa em ambiente local/test com `DevSecurityContextResolver`,
inclua ou mantenha os grants abaixo:

```powershell
$env:DEV_AUTH_PERMISSIONS = '["admin.company.read","inventory.balance.read","inventory.warehouse.read","inventory.warehouse.create","inventory.location.read","inventory.location.create","inventory.pool.read","inventory.pool.create","inventory.lot.read","inventory.lot.create","inventory.adjustment.create"]'
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
| Rastreio por lote | `GET /api/v1/inventory/lots/{lot_id}/postings` |
| Ajuste idempotente | `POST /api/v1/inventory/adjustments` |

Toda chamada exige `company_id` explícito e identidade autorizada para a empresa
de trabalho. Falhas seguem o Error Contract padronizado.

## Eventos e projeção assíncrona

O ajuste publica `InventoryAdjusted` no Outbox com aggregate
`inventory_adjustment`. O transporte RabbitMQ usa a routing key
`inventory.inventory-adjustment.adjusted.v1` e a fila do projector
`erp.inventory.movement-projector.adjusted.v1`.

O consumer `InventoryMovementProjectionConsumer` grava uma linha única por
`event_id` em `inventory.inventory_movement_projection` através do Inbox. Replays
do mesmo evento incrementam a tentativa do Inbox e não duplicam projeções.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests
.\.venv\Scripts\python.exe -m pytest tests\integration\test_inventory_api.py tests\integration\test_inventory_adjustments_api.py tests\integration\test_inventory_events_e2e.py tests\integration\test_inventory_browser.py
```

Para validar a UI com navegador real:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest tests\integration\test_inventory_browser.py
```

O teste gera evidências em `test-results/inventory-desktop.png` e
`test-results/inventory-mobile.png`.

## Observabilidade e recuperação

- Cada ajuste grava Audit com `request_id` e `correlation_id`.
- O Outbox preserva o evento de domínio mesmo se o envio assíncrono ainda não
  tiver sido consumido.
- O Inbox garante idempotência por consumidor e evento.
- Em falha de RabbitMQ, não recrie volumes de PostgreSQL/MinIO/Redis. Verifique
  primeiro saúde do Docker Compose e soquetes de runtime, preservando dados
  locais.
