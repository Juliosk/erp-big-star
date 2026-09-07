# Sprint 1 — Platform Foundation (histórico)

Os Commits 014–020 entregaram Audit, Error Contract, Transactional Outbox, RabbitMQ,
Inbox, Celery, idempotência e optimistic locking. O endpoint técnico
`POST /api/v1/platform/test-entities` e sua tabela descartável foram removidos no Commit 029,
depois que o E2E corporativo oficial passou a validar a mesma infraestrutura.

As migrations `0006` e `0009` preservam a evolução e o rollback do esquema. Não reative a rota
temporária; valide a plataforma pelos testes corporativos descritos em
`docs/sprint-2-corporate-foundation.md`.
