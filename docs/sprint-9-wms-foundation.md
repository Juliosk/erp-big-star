# Sprint 9 — M10 WMS / Expedition Foundation

## Objetivo

Iniciar a Wave 3 com a fundação do M10 WMS, preparando o ERP para picking,
packing, pacotes, expedição e despacho sem antecipar pedidos, fiscal ou
financeiro. O slice segue o Backlog Técnico Mestre W3: primeiro
`M10 Pick/Packing skeleton`, antes de M6, M17, M11 e M12.

## Escopo central

- Criar o bounded context `erp.modules.wms`.
- Definir domínio puro de ondas de picking, tarefas, pacotes e shipments.
- Registrar RBAC M10:
  - `wms.pick.execute`
  - `wms.pack.execute`
  - `wms.dispatch.execute`
  - `wms.label.reprint`
  - `wms.shortage.override`
- Criar schema `wms` com tabelas company-scoped.
- Manter FKs compostas para M2 Product e M5 Inventory quando o owner já existe.
- Preparar optimistic locking para agregados mutáveis.
- Preservar futuras integrações com M4/M11/M12 via contratos públicos, não por
  imports internos.

## Fora de escopo da Sprint 9 inicial

- Não criar pedido interno ou fulfillment M4.
- Não emitir nota fiscal, CT-e, MDF-e ou fiscal intent M11.
- Não gerar financeiro/contas a pagar M12.
- Não consumir transportadoras externas.
- Não movimentar saldo físico diretamente; WMS orquestra execução e deve
  consumir contratos M5 em lotes posteriores.

## Planejamento de commits

| Commit | Tema | Entrega |
| --- | --- | --- |
| 090 | Domínio/RBAC | Bounded context M10, domínio puro, contratos públicos e permissões |
| 091 | Schema | Migration `0025`, modelos SQLAlchemy e teste de metadata/tenant FKs |
| 092 | Planejamento/config | Runbook inicial da Sprint 9 e Dev Auth com permissões M10 |
| 093 | Repositórios | Portas e repositórios company-scoped para ondas/tarefas/pacotes |
| 094 | Serviços de aplicação | Criação de wave e tarefas, validações e RBAC |
| 095 | APIs base | `GET/POST /api/v1/wms/picking-waves` e consultas iniciais |
| 096 | Release concorrente | `POST /picking-waves/{id}/release` com ETag/If-Match, Audit e Outbox |
| 097 | Picking scan | `POST /picking-tasks/{id}/scan`, idempotência e prevenção de over-pick |
| 098 | Packing skeleton | Pacotes, itens e verificação/finalização básica |
| 099 | UI/E2E/Docs | WMS Cockpit inicial, Chromium E2E e runbook operacional |

## Entrega do Commit 090

O contexto `erp.modules.wms` foi criado com domínio puro e sem dependência de
frameworks, banco ou adapters. `PickingWave`, `PickingTask`, `Package` e
`Shipment` validam transições básicas e quantidades em seis casas, alinhadas ao
padrão M5.

A matriz de permissões M10 foi criada na camada de aplicação usando apenas os
contratos públicos de M1 Admin. Reprint de etiqueta e override de falta entram
como permissões críticas e deverão gerar auditoria quando os comandos oficiais
forem implementados.

## Entrega do Commit 091

A migration `0025` cria o schema `wms` e as tabelas:
`picking_wave`, `picking_task`, `shipment`, `package` e `package_item`.
Todas possuem `company_id`; tabelas que referenciam produto, depósito, lote ou
pool usam FKs compostas para impedir vazamento entre empresas.

Os modelos SQLAlchemy foram alinhados à migration e o teste de schema compara a
metadata ORM contra o PostgreSQL aplicado, incluindo constraints de unicidade,
índices e FKs tenant-bound.

## Entrega do Commit 092

O planejamento da Sprint 9 foi documentado neste arquivo e o Dev Auth local/test
passou a incluir as permissões oficiais de M10. Isso permite que as próximas
rotas e telas sejam validadas sem bloqueio por identidade simulada, mantendo o
adapter restrito a ambientes `local` e `test`.

## Entrega do Commit 093

Os repositórios PostgreSQL do M10 foram implementados em
`erp.modules.wms.infrastructure`, com escopo obrigatório por `company_id` para
`PickingWave`, `PickingTask`, `Package` e `Shipment`.

O adapter valida referências a M2 Product e M5 Inventory usando FKs compostas e
retorna contratos estáveis (`RESOURCE_NOT_FOUND`, `SCOPE_FORBIDDEN` e conflitos
WMS) antes de expor os casos de uso oficiais. A suíte cobre round-trip,
isolamento entre empresas, duplicidade transacional e referências ausentes.

## Entrega do Commit 094

O `PickingWaveService` foi criado na camada de aplicação para autorizar
`wms.pick.execute`, validar o payload e construir atomicamente uma onda com
tarefas numeradas. O loteamento inicial agrupa as tarefas por `zone_code` antes
de gerar a sequência de execução, preservando a ordem recebida dentro de cada
zona.

O adapter `PostgresPickingWaveStore` encapsula a unidade de trabalho no banco e
usa apenas os repositórios tenant-bound do M10. A suíte unitária cobre RBAC,
paginação, validação de negócio e tradução para o Error Contract.

## Entrega do Commit 095

As rotas oficiais `GET/POST /api/v1/wms/picking-waves` foram expostas no
boundary HTTP do M10, com detalhe por ID para validação operacional. As rotas
usam o `PickingWaveService`, exigem `wms.pick.execute`, propagam `company_id`
para o escopo M1 e retornam `Cache-Control: no-store`, `ETag` e `Location` nos
contratos de escrita.

Os schemas Pydantic do WMS são próprios do módulo e a composição FastAPI passa a
montar o `PostgresPickingWaveStore` somente no application factory. A suíte de
integração cobre criação, consulta paginada, detalhe, isolamento entre empresas,
RBAC, scope e Error Contract para validação e referência ausente.
