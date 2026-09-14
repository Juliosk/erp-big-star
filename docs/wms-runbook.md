# M10 WMS / Expedição — Runbook Operacional

## Escopo

O M10 WMS cobre a fundação operacional de expedição: ondas de separação,
tarefas de picking, bipagem por código de barras, pacotes e embalagem. O módulo
é dono de `erp.modules.wms` e mantém escopo obrigatório por `company_id`.

Ficam fora deste runbook: pedido comercial M4, emissão fiscal M11, CT-e/MDF-e,
financeiro M12 e integrações externas de transportadora.

## Permissões

- `wms.pick.execute`: criar, consultar e liberar ondas; bipar tarefas.
- `wms.pack.execute`: criar pacote, adicionar itens, verificar e finalizar
  embalagem.
- `wms.dispatch.execute`: reservado para despacho em sprint posterior.
- `wms.label.reprint`: reservado para reimpressão auditada de etiquetas.
- `wms.shortage.override`: reservado para override formal de falta.

Em `local` e `test`, o Dev Auth pode expor essas permissões quando
`DEV_AUTH_ENABLED=true`.

## Contratos HTTP principais

### Ondas de separação

- `GET /api/v1/wms/picking-waves?company_id={company_id}`
- `POST /api/v1/wms/picking-waves`
- `GET /api/v1/wms/picking-waves/{wave_id}?company_id={company_id}`
- `POST /api/v1/wms/picking-waves/{wave_id}/release?company_id={company_id}`

A liberação exige `If-Match` com a versão atual. Conflitos retornam
`VERSION_CONFLICT`; transições inválidas retornam
`WMS_PICKING_WAVE_STATUS_CONFLICT`.

### Bipagem

- `POST /api/v1/wms/picking-tasks/{task_id}/scan?company_id={company_id}`

Requer `Idempotency-Key`, barcode válido no M2 Product para a mesma empresa e
onda em `RELEASED` ou `IN_PROGRESS`. O domínio impede over-picking e retorna
`WMS_PICKING_TASK_OVER_PICK` quando a quantidade excede o solicitado.

### Packing

- `POST /api/v1/wms/packages`
- `GET /api/v1/wms/packages/{package_id}?company_id={company_id}`
- `POST /api/v1/wms/packages/{package_id}/items?company_id={company_id}`
- `POST /api/v1/wms/packages/{package_id}/verify?company_id={company_id}`
- `POST /api/v1/wms/packages/{package_id}/finalize?company_id={company_id}`

Pacotes só recebem itens em `DRAFT`. A quantidade embalada por tarefa não pode
exceder a quantidade já bipada. `verify` exige ao menos um item e `finalize`
exige pacote `VERIFIED`. As transições usam `If-Match` e retornam `ETag`.

## Efeitos transacionais

O M10 já publica eventos de domínio via Outbox para:

- `PickingWaveReleased`
- `PickingTaskScanned`

Os mesmos comandos registram Audit com snapshots antes/depois na transação da
mutação. Consumers e dispatch físico ficam reservados para slices posteriores.

## Interface Web

Acesse `/ui/`, conecte com token Bearer e selecione a empresa de trabalho. O
menu **Expedição M10** aparece quando a identidade possui `wms.pick.execute` ou
`wms.pack.execute`.

Fluxo operacional mínimo:

1. Criar onda informando código, produto e quantidade.
2. Liberar a onda.
3. Bipar a tarefa com barcode e quantidade.
4. Criar pacote vinculado à onda.
5. Adicionar o item bipado ao pacote.
6. Verificar o pacote.
7. Finalizar o pacote.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\unit\modules\wms tests\integration\test_wms_schema.py tests\integration\test_wms_repositories.py tests\integration\test_wms_api.py tests\integration\test_wms_browser.py tests\unit\test_architecture_boundaries.py -q
```

Para E2E visual, os screenshots esperados são:

- `test-results/wms-cockpit-desktop.png`
- `test-results/wms-cockpit-mobile.png`

## Critérios de aceite da Sprint 9

- Schema WMS aplicado e compatível com ORM.
- Rotas oficiais de picking waves, scan e packages operacionais.
- RBAC e escopo por `company_id` aplicados em todas as entradas públicas.
- `If-Match`/`ETag` em transições versionadas.
- Idempotência de scan validada.
- Over-picking e over-packing bloqueados.
- Audit/Outbox transacionais nos comandos já definidos para eventos M10.
- UI `/ui/` sem armazenar token em `localStorage`/`sessionStorage`.
- Ruff, Mypy, testes focados e E2E Chromium aprovados.
