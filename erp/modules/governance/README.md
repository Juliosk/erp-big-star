# M23 — Data Governance / Import Core

Owner da orquestração de cargas, não do Product Master. Templates por empresa, versões
imutáveis, upload privado, staging, validação, preview, confirmação e commit. DoR/DoD no
[plano da Sprint 4](../../../../docs/sprint-4-product-import.md).

Domain é Python puro. Repositórios não fazem commit; o store orquestra a transação composta,
sem importar persistência M2. A raiz `erp/apps/api/import_composition.py` injeta o contrato
público `ProductBulkDataAdapter` na mesma sessão. Audit, Outbox, recibo e produtos são atômicos.
Tables: governance.import_template, import_template_version, import_job, import_staging_row,
import_validation_result e import_commit_batch, migrations 0012–0013.
M1 company é Foundation FK; versão/template/job usam vínculo composto com company_id.

API: /api/v1/data. Nenhum template é semeado por GET: o provisionamento é um comando explícito,
autorizado e auditado. Grants: data.import.execute/confirm, product.product.read e create/update
conforme cada linha. Confirm/commit revalidam fonte, escopo, fingerprint e versões. Workers
existentes publicam a Outbox; o commit inicial limitado a 1.000 linhas é síncrono.

Source guarda somente filename, storage_key, SHA-256 e tamanho; XLSX fica no MinIO privado.
Job: UPLOADED → VALIDATED → PREVIEWED → CONFIRMED → COMMITTED. REJECTED e CANCELLED
não alteram catálogo. Somente ALL_OR_NOTHING está habilitado. Outros modos permanecem futuros.
Criação/atualização por SKU é executada pelo owner M2, nunca por SQL M23 em product.product.
Veja [operação e limitações](../../../../docs/product-import-runbook.md).

Validar com Alembic upgrade head, Ruff, mypy e pytest com PostgreSQL real. Downgrade remove
histórico M23 e só deve ser usado em banco descartável ou com backup/autorização.
