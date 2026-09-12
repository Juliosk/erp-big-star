# Sprint 7 — Inventory Reservation

## Objetivo

Completar o núcleo de reserva do M5 antes da criação de pedidos reais: reservas
HARD/SOFT, consulta de disponibilidade, expiração, proteção contra
over-reservation e testes concorrentes sobre o mesmo produto, pool e lote.

## Commits planejados

| Commit | Tema | Entrega |
| --- | --- | --- |
| 070 | Domínio e contratos | Reserva HARD/SOFT, lifecycle, availability e contratos públicos M5 |
| 071 | Schema | `inventory_reservation` e `inventory_reservation_allocation` |
| 072 | Persistência/query | Repositórios tenant-bound e `InventoryAvailabilityQueryService` |
| 073 | Reservation Service | Criação HARD/SOFT com lock transacional e prevenção de over-reservation |
| 074 | APIs oficiais | `GET/POST /inventory/reservations`, detail e release com RBAC/Error Contract |
| 075 | Expiração | Política de expiração e comando idempotente de expiração |
| 076 | Audit/Outbox | Eventos `InventoryReservationCreated/Released/Expired` |
| 077 | Concorrência | Testes paralelos same product/pool/lot e rollback fiscalmente seguro |
| 078 | UI | Aba de reservas no cockpit M5 com disponibilidade e liberação |
| 079 | E2E/Docs | Chromium E2E, runbook e encerramento da Sprint |

## Limites de escopo

- M5 é o owner de reserva e disponibilidade; M4 consumirá contrato público em
  sprint posterior.
- A Sprint 7 não cria pedidos, picking, expedição ou faturamento.
- Reserva HARD reduz disponibilidade reservável; reserva SOFT registra intenção
  operacional e não consome ATP rígido.
- Todo write crítico exige `Idempotency-Key`, Audit, Outbox e isolamento por
  `company_id`.

## Entrega do Commit 070

O domínio puro define `InventoryReservation`, `InventoryReservationAllocation`,
`InventoryAvailability`, `InventoryReservationKind` e
`InventoryReservationStatus`. As transições são terminais: reserva ativa pode ser
liberada ou expirada, mas não reativada. A disponibilidade oficial é calculada
como `on_hand - HARD`, mantendo SOFT separado para visibilidade operacional.

Os contratos públicos foram estendidos com referências de disponibilidade,
reserva e eventos de reserva v1, sem exportar tipos de infraestrutura.

## Entrega do Commit 071

A migration `0022` adiciona `inventory.inventory_reservation` e
`inventory.inventory_reservation_allocation`. O aggregate é versionado, possui
unicidade por `company_id + reference_type + reference_id` e mantém expiração
opcional. As allocations carregam as dimensões de contenção
produto/depósito/localização/lote/pool/estado, com FKs compostas por empresa
para preservar tenant isolation.

## Entrega do Commit 072

O adapter `PostgresInventoryReservations` implementa leitura tenant-bound de
reservas e disponibilidade. `InventoryAvailabilityQueryService` autoriza
`inventory.availability.read`, calcula `on_hand`, `hard_reserved`,
`soft_reserved` e `available`, e mantém SOFT separado da disponibilidade rígida.
`InventoryReservationQueryService` prepara a superfície de leitura que será
exposta pela API no lote seguinte.
