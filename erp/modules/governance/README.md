# M23 — Data Governance / Import Core

Owner da orquestração de cargas, não do Product Master. Lote 040–042: templates por empresa,
versões imutáveis e metadados de import_job. Plano, limites e DoR/DoD no
[plano da Sprint 4](../../../docs/sprint-4-product-import.md).

Domain é Python puro. Infrastructure recebe empresa previamente autorizada e sessão controlada
pelo chamador; não faz commit, não publica eventos e não importa persistência M2.
Tables: governance.import_template, import_template_version e import_job, migration 0012.
M1 company é Foundation FK; versão/template/job usam vínculo composto com company_id.

Fases 040–042 não contêm upload/parser/API/worker ou gravação de produto. Nenhum template é
semeado implicitamente. Métodos internos de persistência exigem ator e escopo; não substituem
RBAC/Audit. API futura: /api/v1/data. Grants oficiais: data.import.execute/confirm, mais M2.
Eventos futuros: ImportJobCreated, ImportValidationCompleted, ImportPreviewReady,
ImportCommitted/PartiallyCommitted/Failed. M23 acessará M2 apenas por contratos públicos.

Source guarda somente filename, storage_key, SHA-256 e tamanho; XLSX irá para MinIO privado.
Versão de template não pode sofrer UPDATE; alterações exigem nova versão. Job começa UPLOADED
com version=1; neste lote a única transição implementada é cancelamento antes de processamento.
Nenhum método transforma staging em domínio diretamente ou confirma uma importação.

Validar com Alembic upgrade head, Ruff, mypy e pytest com PostgreSQL real. Downgrade remove
histórico M23 e só deve ser usado em banco descartável ou com backup/autorização.
