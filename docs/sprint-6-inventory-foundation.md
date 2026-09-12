# Sprint 6 — M5 Inventory Foundation

## Objetivo

Estabelecer a fundação de estoque antes de pedidos/reservas completas: estrutura física,
lotes, ledger imutável e projeção durável de saldo transacional por empresa.

## Commits planejados

| Commit | Tema | Entrega |
| --- | --- | --- |
| 060 | Fundação M5 | Pacote inventory, domínio puro, contratos e RBAC |
| 061 | Schema inicial | Migration `inventory` para warehouse, location, pool e lot |
| 062 | Persistência base | Repositórios e serviços company-scoped para cadastros físicos |
| 063 | APIs base | Endpoints de consulta/criação com Error Contract |
| 064 | Ledger | `inventory_transaction` e `inventory_posting` append-only |
| 065 | Balance | Atualização transacional de `inventory_balance` e concorrência |
| 066 | Ajustes | Abertura/ajuste com Audit e Outbox |
| 067 | Consultas oficiais | `GET /inventory/balances` e `GET /inventory/lots` |
| 068 | Eventos E2E | Consumers/projeções para eventos críticos M5 |
| 069 | UI/Docs | Telas iniciais, Chromium E2E e runbook operacional |

## Limites de escopo

Reserva HARD/SOFT e disponibilidade concorrente completa pertencem à Sprint 7. A Sprint 6
prepara as estruturas necessárias, mas não antecipa o motor de reserva.

## Entrega dos commits 062–063

Os cadastros físicos agora possuem repositórios tenant-bound para `Warehouse`, `Location`,
`Pool` e `Lot`. Cada repositório recebe um `company_id` imutável e aplica esse filtro em
leituras e gravações; referências a filial, depósito, localização-pai e produto também são
validadas dentro da mesma empresa antes do `flush`.

O serviço de aplicação exige as permissões específicas `inventory.<recurso>.read` e
`inventory.<recurso>.create`, além da autorização de empresa do contexto de trabalho. Falhas
de permissão, escopo, validação, recurso inexistente e conflito de unicidade são convertidas
para o Error Contract comum da API.

Rotas públicas adicionadas:

- `GET/POST /api/v1/inventory/warehouses`
- `GET /api/v1/inventory/warehouses/{warehouse_id}`
- `GET/POST /api/v1/inventory/locations`
- `GET /api/v1/inventory/locations/{location_id}`
- `GET/POST /api/v1/inventory/pools`
- `GET /api/v1/inventory/pools/{pool_id}`
- `GET/POST /api/v1/inventory/lots`
- `GET /api/v1/inventory/lots/{lot_id}`

As consultas recebem `company_id` explicitamente e retornam paginação (`data` + `meta`). As
respostas individuais incluem `ETag`; criações retornam `201` e `Location`. A camada de
composição inicializa os serviços PostgreSQL automaticamente quando a aplicação usa o
`Database` padrão.

## Entrega dos commits 068–069

O fluxo assíncrono M5 consome `InventoryAdjusted` publicado pelo Outbox através
do RabbitMQ, valida o envelope público do domínio `inventory` e persiste uma
projeção idempotente em `inventory.inventory_movement_projection`. O Inbox
registra replays por consumidor/evento e impede duplicidade de projeções,
mantendo rastreabilidade de `event_id`, `transaction_id`, quantidade de postings
e payload original.

A interface Web `/ui/` ganhou a seção **Estoque / M5**, exibida apenas para
identidades com grants de leitura ou ajuste de inventário. A tela opera somente
pelas APIs oficiais: saldos versionados, estrutura física, ajuste rápido
idempotente e rastreabilidade por lote. O runbook operacional detalhado está em
[inventory-foundation-runbook.md](inventory-foundation-runbook.md).
