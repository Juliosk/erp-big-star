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
