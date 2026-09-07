# M1 Admin / Corporate Foundation

## Responsibility and owner

The M1 team owns authentication, RBAC, tenant scope resolution and the corporate hierarchy.
This module is the source of truth for `EconomicGroup`, `Company` and `Branch`; other modules
may reference company and branch UUIDs as approved foundation foreign keys, but may not import
M1 infrastructure or write these tables directly.

## Dependency boundary

The package follows `domain -> application -> api/infrastructure`. Domain code is technology
neutral. Transactions are owned by application use cases; repositories only stage and flush
changes. Cross-module coordination must use public contracts or versioned events.

## Corporate hierarchy and tenancy

The hierarchy is `EconomicGroup -> Company -> Branch`. A group is a consolidation and
authorization boundary, not permission to mix transactional data. Every scoped read requires a
`TenantContext` created from the authenticated user and concrete `GROUP`, `COMPANY` or `BRANCH`
grants. Empty scopes return no records. Narrow scopes expose only the minimum parent nodes needed
to render the authorized hierarchy; they never expose sibling companies or branches.

Tables are `admin.economic_group`, `admin.company` and `admin.branch`. All mutable aggregates use
UUID identities, lifecycle status, actor/timestamps and optimistic `version` fields. Parent
deletion is restricted.

## Delivery status

- Sprint 2 commit 021: domain aggregates and invariants.
- Sprint 2 commit 022: PostgreSQL mappings, repositories and migration `0007`.
- Sprint 2 commit 023: explicit tenant context and scope-filtered directory reads.
- Planned next: `/api/v1/admin` use cases, permissions, audit, idempotency and domain events.

Operational checks: apply migrations with `alembic upgrade head`; prove schema parity with
`alembic check`; run unit and PostgreSQL integration tests before delivery.
