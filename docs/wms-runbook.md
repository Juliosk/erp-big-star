# M10 WMS / Expedição — Runbook Operacional

## Escopo

O M10 WMS cobre a fundação operacional de expedição e armazenagem: layout
cartesiano, guarda física (putaway), ondas de separação, tarefas de picking,
bipagem por código de barras, pacotes e embalagem. O módulo é dono de
`erp.modules.wms` e mantém escopo obrigatório por `company_id`.

O pedido comercial continua no contexto Sales e o ledger no M5. O WMS recebe
demandas por contratos e eventos, executa o movimento físico e devolve
evidências de picking, packing e despacho sem escrever diretamente nos
agregados vizinhos.

## Permissões

- `wms.pick.execute`: criar, consultar e liberar ondas; bipar tarefas.
- `wms.pack.execute`: criar pacote, adicionar itens, verificar e finalizar
  embalagem.
- `wms.dispatch.execute`: reservado para despacho em sprint posterior.
- `wms.label.reprint`: reservado para reimpressão auditada de etiquetas.
- `wms.shortage.override`: reservado para override formal de falta.
- `wms.locations.read`: consultar zonas, corredores, estantes, níveis e bins.
- `wms.locations.write`: manter a estrutura física e suas capacidades.
- `wms.inventory.movement`: executar movimentações físicas e guarda em bins.
- `wms.inventory.read`: consultar ocupação, ondas e fila do cockpit WMS.

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

### Rotas cartesianas, packing e manifesto (Migration 0060)

As tabelas `wms_picking_wave`, `wms_picking_item` e
`wms_packing_verification` suportam a jornada física integrada aos pedidos de
marketplace. A criação da onda ordena os itens por
`Zona/Corredor/Estante/Nível/Bin`, reduzindo retornos do operador. Cada scan de
packing exige EAN correto, chave idempotente e saldo previamente separado.

O manifesto só é gerado quando todos os itens estão `PACKED`. No mesmo
transaction boundary, o WMS registra a baixa física no ledger M5 e preserva a
evidência de conferência. Divergências de EAN ou quantidade bloqueiam o
manifesto com `WMS_PACKING_DIVERGENCE`; nunca faça ajuste direto nas tabelas.

### Guarda física (putaway)

O `WMSPutawayService` recebe saldo em `RECEIVING_STAGE`, originado por compras
ou produção, e o transfere para um bin de `PICKING` ou `RESERVE`. Antes do
lançamento, o domínio valida empresa, armazém, zoneamento, bloqueio, dimensões,
peso, volume e quantidade máxima. O bin é bloqueado com `SELECT FOR UPDATE` e
a versão informada pelo chamador precisa ser atual; disputas retornam
`VERSION_CONFLICT` e somente uma movimentação vence.

O comando exige `Idempotency-Key` e a permissão
`wms.inventory.movement`. Repetir a mesma chave e o mesmo payload devolve o
resultado original sem novo lançamento. Chave reutilizada com payload diferente
é rejeitada pelo contrato corporativo de idempotência.

## Efeitos transacionais

O M10 já publica eventos de domínio via Outbox para:

- `PickingWaveReleased`
- `PickingTaskScanned`
- `WmsPutawayCompleted`

Os mesmos comandos registram Audit com snapshots antes/depois na transação da
mutação. No putaway, a atualização da ocupação do bin, os dois postings do
ledger M5 (`RECEIVING_STAGE` negativo e destino positivo), os saldos, Audit,
Outbox e resultado idempotente compartilham a mesma transação PostgreSQL.
Consumers e dispatch físico ficam reservados para slices posteriores.

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

O cockpit operacional consolidado fica em `/ui/wms/cockpit` e exige
`wms.inventory.read`. Ele apresenta:

- ocupação por zona com capacidade e bins bloqueados;
- ondas ordenadas pela rota cartesiana e próximo endereço;
- progresso combinado de picking e packing;
- fila explicável da doca com itens a separar, conferir e despachar.

O painel é somente leitura. Ações continuam nas APIs/comandos oficiais com as
permissões de execução. O Bearer token permanece apenas em memória e a troca de
empresa dispara uma nova consulta tenant-bound.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\unit\modules\wms tests\integration\test_wms_schema.py tests\integration\test_wms_repositories.py tests\integration\test_wms_api.py tests\integration\test_wms_browser.py tests\unit\test_architecture_boundaries.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_wms_putaway_service.py -q
```

Para E2E visual, os screenshots esperados são:

- `test-results/wms-cockpit-desktop.png`
- `test-results/wms-cockpit-mobile.png`
- `test-results/wms-operations-cockpit-desktop.png`
- `test-results/wms-operations-cockpit-mobile.png`

## Recuperação e resiliência

- Bin lotado/incompatível: revise capacidade e zoneamento; não mova saldo por
  SQL. Reexecute o putaway com outro bin e nova chave idempotente.
- Onda parada: confira item/rota, reservation HARD e status do saldo no M5.
- Divergência de packing: reconte fisicamente, valide EAN do M2 e só então
  repita a conferência.
- Evento atrasado: acompanhe Outbox, retry e DLQ. Replays são seguros pelo
  Inbox/idempotência; preserve a ordem monotônica do agregado.
- Ambiente Docker: preserve volumes PostgreSQL/Redis/MinIO. Não use factory
  reset nem `docker system prune -a --volumes` em recuperação operacional.

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
