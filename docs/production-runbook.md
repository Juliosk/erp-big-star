# Runbook operacional — Produção, MRP e Chão de Fábrica

## 1. Objetivo, autoridade e limites

Este runbook governa o ecossistema industrial entregue nos Commits 196 a 206:
engenharia de produto, Fichas Técnicas (BOM), roteiros, centros de trabalho,
MRP, Ordens de Produção (OP), reservas de insumos e execução do chão de
fábrica. A decisão arquitetural está registrada no ADR 0192.

O bounded context `erp.modules.production` é o System of Record de engenharia,
planejamento e execução fabril. As fronteiras permanecem explícitas:

- M2 é proprietário do cadastro comercial do produto;
- M5 é proprietário do saldo, reservas e ledger físico de estoque;
- M6 recebe necessidades planejadas de compra por contrato público;
- M17 é proprietário das decisões de qualidade;
- M22 governa aprovações por seus contratos públicos.

Produção não escreve diretamente nas tabelas desses módulos. A composição
síncrona usa portas injetadas; a propagação reativa usa Outbox/Inbox. Todo dado
operacional é isolado por `company_id` e recursos de outra empresa não podem
ser enumerados.

## 2. Pré-requisitos e segurança

- PostgreSQL, RabbitMQ e workers de Inbox/Outbox saudáveis;
- Alembic em `0056 (head)`;
- produtos, depósitos, locais, pools e saldos do M5 previamente cadastrados;
- BOM e roteiro aprovados e vigentes para o produto acabado;
- centros de trabalho ativos, compatíveis e tenant-bound;
- identidade autenticada, empresa de trabalho selecionada e RBAC explícito.

Permissões oficiais:

| Operação | Permissão | Risco |
| --- | --- | --- |
| Consultar BOM, versões e roteiros | `production.engineering.read` | médio |
| Criar/revisar engenharia | `production.engineering.write` | alto |
| Consultar MRP e planos | `production.planning.read` | alto |
| Executar MRP e converter plano | `production.planning.run` | crítico |
| Consultar OPs e cockpit | `production.shop_floor.read` | alto |
| Apontar produção, consumo e refugo | `production.shop_floor.execute` | crítico |

Dados industriais são `CONFIDENTIAL`. Em incidentes, use IDs, versões,
`request_id`, `correlation_id` e `message_id`; não copie fórmulas, custos,
documentos ou dados pessoais para canais não homologados.

## 3. Engenharia: BOM multinível, roteiros e centros

### 3.1 Ficha Técnica

Cada BOM identifica empresa, produto, revisão e vigência. Quantidades usam
`Decimal` com seis casas, carregam unidade de medida e nunca passam por
conversão implícita. A expansão multinível:

1. valida que todas as estruturas pertencem à mesma empresa;
2. detecta ciclos diretos e indiretos antes do cálculo;
3. percorre subconjuntos até os componentes folha;
4. agrega a necessidade por produto e unidade;
5. aplica perda pela regra `necessidade = base / (1 - scrap_rate)`.

`BOM_CYCLE_DETECTED`, `BOM_NOT_FOUND` e `UOM_MISMATCH` são bloqueios de
engenharia; não devem ser contornados por edição de banco ou arredondamento
manual.

### 3.2 Roteiro e centro de trabalho

O roteiro congela operações ordenadas por sequência, tempos de preparação e
execução, capacidades exigidas e centros permitidos. Sequências são únicas e
um centro incompatível não pode ser escolhido silenciosamente. Ao criar uma
OP, BOM e roteiro são copiados para snapshots imutáveis: alterações futuras de
engenharia não reescrevem a ordem em andamento.

## 4. MRP determinístico

O MRP executa cálculo gross-to-net sem heurística oculta:

```text
demanda independente
+ demanda dependente da explosão da BOM
- estoque disponível
- recebimentos programados
+ estoque de segurança
= necessidade líquida por data
```

Políticas de lote mínimo, múltiplo, lead time e tipo `MANUFACTURE`/`PURCHASE`
são aplicadas após a necessidade líquida. Entradas e resultados da execução
ficam congelados em `mrp_run_history`; propostas ficam em `planned_order` com
datas de liberação e necessidade. O mesmo snapshot e as mesmas políticas devem
produzir o mesmo resultado.

Antes de executar:

1. confirme empresa, data-base e horizonte;
2. valide demandas, saldos e recebimentos autorizados;
3. confira vigência das BOMs e políticas de todos os itens;
4. revise alertas de lead time e falta de política;
5. preserve o histórico; uma nova premissa exige nova execução.

## 5. Conversão de ordem planejada e reserva HARD no M5

A conversão aceita apenas ordem `MANUFACTURE` em estado `PLANNED`. O serviço:

1. trava a proposta para conversão e verifica a empresa;
2. valida que a BOM congelada no MRP ainda é a engenharia vigente;
3. cria a OP com ID e número determinísticos;
4. solicita ao M5 uma reserva de produção `HARD` para todos os insumos;
5. grava OP, evidência da reserva e estado `CONVERTED` na mesma transação.

Repetir a mesma conversão devolve a OP e a reserva existentes. Uma proposta
convertida não pode gerar segunda OP. Falta de saldo, engenharia divergente ou
falha no M5 deve abortar toda a transação; é proibido marcar a proposta como
convertida sem as duas evidências persistidas.

## 6. Ordem de Produção e ciclo de vida

Estados oficiais:

```text
DRAFT -> RELEASED -> IN_PROGRESS -> COMPLETED
  |          |             |
  +----------+-------------+-> CANCELLED (quando permitido pelo domínio)
```

- `DRAFT`: engenharia e plano de materiais congelados, ainda não liberados;
- `RELEASED`: engenharia validada e ordem liberada ao chão de fábrica;
- `IN_PROGRESS`: ao menos uma operação foi iniciada;
- `COMPLETED`: operações obrigatórias concluídas e produção consistente;
- `CANCELLED`: encerramento explícito conforme as regras do agregado.

Toda mutação usa a versão esperada. Em `VERSION_CONFLICT`, releia a OP e
reavalie o comando; não repita cegamente com a nova versão.

## 7. MES: execução, consumo e refugo

O `ShopFloorExecutionService` coordena OP, log append-only e M5 no mesmo limite
transacional:

1. `start` valida sequência, centro permitido e versão da OP;
2. `progress` registra quantidade boa, consumo real e refugo parcial;
3. `complete` encerra a operação após validar quantidades e precedência;
4. o consumo converte a reserva HARD em lançamento `ISSUE` no ledger do M5;
5. ao finalizar o consumo aplicável, o M5 libera a reserva remanescente.

Os registros `STARTED`, `PROGRESS` e `COMPLETED` são evidências operacionais e
não devem ser alterados. O apontamento carrega ator, versões antes/depois,
horário, `request_id` e `correlation_id`.

### Motivos de refugo

`reason_code` deve ter 2 a 32 caracteres canônicos (`A-Z`, `0-9`, `_`) e notas,
quando informadas, entre 3 e 500 caracteres. Exemplos de catálogo operacional:

| Código | Uso |
| --- | --- |
| `MATERIAL_DEFECT` | matéria-prima fora da especificação |
| `PROCESS_SETUP` | perda de preparação regulada |
| `MACHINE_FAILURE` | falha do equipamento durante a operação |
| `QUALITY_REJECT` | reprovação confirmada pela qualidade |
| `OPERATOR_ERROR` | erro operacional apurado |

Novos códigos exigem governança do catálogo; não use texto livre como código.
Refugo não é baixa silenciosa: quantidade, produto, operação, centro, ator e
causa devem permanecer rastreáveis.

## 8. Eventos, Inbox e recomposição reativa

Fatos publicados atomicamente na Outbox:

- `ProductionOrderReleased`;
- `ProductionOrderCompleted`;
- `OperationCompleted`;
- `MaterialConsumed`;
- `ScrapRecorded`.

O consumer aceita somente envelopes v1 autorizados:

- `InventoryAdjusted`;
- `ProductUpdated`;
- `BillOfMaterialsUpdated`;
- `RoutingUpdated`.

O processamento aplica Inbox idempotente, cursor monotônico por empresa e
agregado, versão/timestamp do fato e fila durável. Workers concorrentes usam
`FOR UPDATE SKIP LOCKED`. Eventos duplicados ou antigos não podem regredir o
estado; fatos aceitos reavaliam OPs afetadas e publicam
`ProductionSynchronizationRequested` com a mesma correlação.

Para fila parada, compare Inbox, `production_source_cursor`,
`production_synchronization_request`, Outbox, retries e DLQ. Nunca edite o
payload nem avance cursor manualmente.

## 9. Cockpit industrial e Andon

- UI: `/ui/production/cockpit`;
- API read-only: `GET /api/v1/production/cockpit?company_id=<uuid>`;
- permissão: `production.shop_floor.read`;
- resposta: `Cache-Control: no-store`.

O cockpit mostra OPs ativas, progresso, quantidades boa/refugo, operação atual,
sincronizações pendentes, carga de centros e fila Andon. A capacidade de
referência é um turno padrão de 480 minutos:

| Carga | Estado | Conduta |
| --- | --- | --- |
| `< 85%` | `NORMAL` | acompanhar rotina |
| `>= 85%` e `< 100%` | `ATTENTION` | revisar sequência e capacidade |
| `>= 100%` | `BOTTLENECK` | tratar gargalo antes de liberar nova carga |

Alertas de OP vencida, refugo, sincronização pendente e carga elevada são
explicáveis. O cockpit é read model operacional, não substitui os agregados nem
autoriza alteração direta no banco.

## 10. Migrations e evidências persistidas

| Migration | Capacidade |
| --- | --- |
| `0051` | BOM, componentes, roteiros, operações e centros de trabalho |
| `0052` | OP, plano de materiais e execução prevista de operações |
| `0053` | histórico de MRP e ordens planejadas |
| `0054` | evidência idempotente de conversão e reserva M5 |
| `0055` | logs MES e registros de refugo |
| `0056` | cursores de origem e fila durável de sincronização |

Todas as relações críticas carregam `company_id`; snapshots e logs preservam o
histórico. Downgrade de migration é procedimento de desenvolvimento validado,
não estratégia de recuperação de produção.

## 11. Catálogo de falhas e recuperação

| Código/sintoma | Causa provável | Recuperação segura |
| --- | --- | --- |
| `BOM_CYCLE_DETECTED` | ciclo na engenharia | corrigir revisão e validar expansão novamente |
| `BOM_NOT_FOUND` | estrutura ausente/não vigente | publicar BOM válida para a data da ordem |
| `UOM_MISMATCH` | unidades incompatíveis | cadastrar conversão explícita ou corrigir a engenharia |
| `ENGINEERING_UNAVAILABLE` | BOM/roteiro mudou após MRP | reexecutar MRP e converter nova proposta |
| `MRP_POLICY_NOT_FOUND` | item sem política | parametrizar lead time e lote; não estimar manualmente |
| `PRODUCTION_CONFLICT` | estado/evidência incompatível | consultar agregado e histórico antes de repetir |
| `VERSION_CONFLICT` | comando concorrente | reler recurso e reenviar decisão revisada |
| `INVALID_PRODUCTION_ORDER_STATE` | transição fora do ciclo | seguir o estado e a sequência oficiais |
| `PRODUCTION_QUANTITY_EXCEEDED` | bom + refugo excede limite | corrigir apontamento; não elevar a OP por SQL |
| `ROUTING_INCONSISTENT` | centro/sequência incompatível | corrigir roteiro ou selecionar centro permitido |
| `LOT_TRACEABILITY_ERROR` | consumo sem lote rastreável | corrigir alocação no M5 antes de apontar |
| reserva insuficiente | ATP menor que necessidade | replanejar ou repor estoque; não forçar saldo |
| fila Andon não esvazia | Inbox/cursor/lock/retry/DLQ | diagnosticar correlação e retomar worker oficial |
| cockpit 403 | RBAC/empresa incorretos | ajustar papel ou empresa sem ampliar o tenant |
| cockpit 503 | read model não composto | verificar aplicação, banco e configuração |

## 12. Continuidade e recuperação segura

1. preserve volumes e reúna horário, empresa, OP, versão e IDs de correlação;
2. verifique PostgreSQL, RabbitMQ, workers e `alembic current`;
3. identifique se a falha está em engenharia, MRP, reserva, MES, Inbox ou Outbox;
4. deixe a transação falhar por inteiro; não complete parcialmente por SQL;
5. use idempotência, retry e DLQ oficiais;
6. após recuperar, compare OP, reserva, ledger, logs MES e eventos;
7. registre impacto e evidências no incidente.

Nunca execute factory reset, `docker system prune -a --volumes`, remoção de
volumes ou `UPDATE/DELETE` manual em saldo, ledger, OP, MRP, logs, Audit,
Inbox ou Outbox. Corrija a causa e gere uma nova decisão auditável; não destrua
o histórico.

## 13. Observabilidade e gates diários

Monitore por empresa:

- idade da última execução de MRP e propostas não convertidas;
- OPs por estado, vencimento e progresso;
- consumo planejado versus real e taxa de refugo por motivo;
- reserva HARD versus consumo efetivo;
- carga por centro e quantidade de gargalos;
- idade das sincronizações pendentes;
- retries, DLQ, replays e conflitos de versão;
- latência de Outbox/Inbox e correlação ponta a ponta.

Gate diário mínimo:

```text
engenharia vigente + demanda autorizada + saldo M5 confiável
-> MRP reproduzível -> reserva HARD -> OP executável
-> consumo/refugo rastreável -> ledger e eventos consistentes
```

## 14. Homologação e E2E de conformidade

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\unit\modules\production tests\integration\test_bom_repository.py tests\integration\test_mrp_application_service.py tests\integration\test_planned_order_conversion.py tests\integration\test_shop_floor_execution.py tests\integration\test_production_event_consumers.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_production_cockpit_browser.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --ignore-glob="tests/integration/*_browser.py" --cov=erp --cov-branch --cov-report=term-missing:skip-covered -q
```

O Chromium real certifica desktop e mobile, navegação protegida por RBAC,
isolamento por empresa, cards de carga, fila Andon, ausência de storage de
credenciais no navegador e ausência de overflow global.

## 15. Encerramento do ecossistema industrial

| Capacidade | Evidência | Situação |
| --- | --- | --- |
| Engenharia BOM/roteiros | ADR 0192 + Migration 0051 | concluída |
| Ordens de Produção | Migration 0052 | concluída |
| MRP determinístico | Migrations 0053/0054 | concluída |
| Reserva e consumo M5 | contratos públicos + ledger | concluída |
| MES e refugo | Migration 0055 | concluída |
| Sincronização reativa | Migration 0056 | concluída |
| Cockpit e Andon | API/UI + E2E Chromium | concluída |

O encerramento certifica o slice técnico, não a parametrização fabril de cada
planta, homologação de máquinas, treinamento dos operadores ou implantação em
produção. Mudanças futuras exigem DoR/ADR próprios e devem preservar domínio
puro, multi-tenancy, versionamento, Audit, Outbox/Inbox e ledger imutável.

## 16. Próxima Sprint dupla: Vendas/Marketplaces + WMS/Estoque

O próximo slice deve evoluir dois fluxos coordenados sem fundir bounded
contexts:

- **Vendas/Marketplaces:** ingestão idempotente de pedidos e mudanças de status,
  contrato canônico de canal, preços/snapshots e publicação transacional;
- **WMS/Estoque:** ATP, alocação, ondas, separação, expedição e atualização do
  ledger em resposta somente a fatos autorizados.

O DoR deve definir ownership por dado, chaves externas, política de replay,
ordenação de eventos, cancelamentos, devoluções e reconciliação. Integrações
devem usar contratos públicos e Outbox/Inbox; adaptadores de marketplace não
podem importar repositórios internos de Vendas, WMS ou M5.

## 17. Evidência final — Commit 206

Homologação técnica executada em 8 de novembro de 2026:

- `2.037` testes globais não-browser aprovados;
- `3` testes do cockpit/E2E Chromium aprovados em desktop e mobile;
- cobertura global com branches: `91,35%` (`28.990` statements e `6.346`
  branches instrumentados);
- gate mínimo de cobertura `80%` atendido;
- Mypy sem inconsistências em `883` arquivos;
- Ruff aprovado em `erp`, `tests` e `migrations`;
- Alembic confirmado em `0056 (head)`;
- único warning: depreciação externa de `anyio.abc.BlockingPortal` no
  `starlette.testclient`, sem falha funcional.

Com essas evidências, a fase de Produção, MRP e MES está tecnicamente encerrada
no escopo definido pelo ADR 0192 e por este runbook. A abertura da Sprint dupla
Vendas/Marketplaces + WMS/Estoque deve ocorrer com DoR e contratos próprios.
