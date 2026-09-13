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

## Entrega do Commit 073

`InventoryReservationService` executa comandos transacionais de reserva e
liberação com autorização por `company_id` e permissão
`inventory.reservation.manage`. O adapter PostgreSQL aplica idempotência por
ator/empresa/operação, bloqueia o bucket de saldo com `SELECT FOR UPDATE` para
reservas HARD e compara o disponível (`on_hand - HARD ativo`) antes de persistir.
Reservas SOFT são registradas para visibilidade operacional, mas não reduzem ATP.

Release exige versão positiva no comando e utiliza o versionamento otimista do
aggregate, preservando erro estável `VERSION_CONFLICT` para versões obsoletas.
Eventos de reserva e auditoria permanecem no corte planejado dos commits 076/077,
sem antecipar dependências de pedidos.

## Entrega do Commit 074

Foram expostos os endpoints oficiais:

- `GET /api/v1/inventory/availability`
- `GET /api/v1/inventory/reservations`
- `POST /api/v1/inventory/reservations`
- `GET /api/v1/inventory/reservations/{reservation_id}`
- `POST /api/v1/inventory/reservations/{reservation_id}/release`

Os writes exigem `Idempotency-Key`; o release exige `If-Match` com versão entre
aspas e retorna ETag atualizado. As APIs aplicam RBAC, Error Contract padronizado,
`Cache-Control: no-store` e escopo estrito por empresa. Leituras cruzadas por
`company_id` ocultam recursos fora do tenant pelo contrato `RESOURCE_NOT_FOUND`
quando a identidade possui acesso corporativo, mantendo o padrão já usado em
saldos e rastreabilidade de lotes.

## Entrega do Commit 075

`InventoryReservationService.expire_due` e
`PostgresInventoryReservations.expire_due` implementam a política automática de
expiração de reservas vencidas. O comando recebe `company_id`, instante de corte
timezone-aware, tamanho de lote e `Idempotency-Key`; a execução exige
`inventory.reservation.manage`, mantém escopo por empresa e bloqueia reservas
ativas vencidas com `SELECT FOR UPDATE SKIP LOCKED`.

A reserva passa de `ACTIVE` para `EXPIRED` por transição terminal do domínio e
tem versão incrementada pelo controle otimista do aggregate. Como a
disponibilidade é derivada de reservas ativas, a expiração remove a quantidade
HARD do cálculo reservado e restaura automaticamente o ATP sem lançar movimento
físico no ledger imutável.

## Entrega do Commit 076

`InventoryReservationEffects` centraliza os efeitos transacionais de reservas.
Criação, liberação e expiração registram Audit e Outbox antes da conclusão da
idempotência, dentro da mesma transação do aggregate. Os eventos emitidos são:

- `InventoryReservationCreated`
- `InventoryReservationReleased`
- `InventoryReservationExpired`

Cada envelope usa `aggregate_type=inventory_reservation`, `aggregate_id` da
reserva, `aggregate_version` da versão persistida, `company_id`, request/correlation
IDs e snapshot completo da reserva/allocations. Audit preserva snapshots before/after
nas transições de status, garantindo rastreabilidade operacional e rollback total
quando Audit ou Outbox falham.
