# Sprint 10 — M22 Workflow Core

## Objetivo

Criar o núcleo transversal de aprovações formais do ERP Big Star / Forma Kids.
O M22 é o dono de workflow, políticas de aprovação, pendências e decisões
humanas, mas não efetiva transações de negócio dos módulos de origem.

## Escopo central

- Criar o bounded context `erp.modules.workflow`.
- Modelar definições de workflow, políticas sequenciais, instâncias, etapas e
  decisões formais.
- Expor RBAC M22:
  - `workflow.request.read`
  - `workflow.request.create`
  - `workflow.approval.decide`
  - `workflow.definition.manage`
- Criar schema `workflow` com isolamento por `company_id`.
- Garantir versionamento otimista nos agregados mutáveis.
- Registrar Audit e publicar eventos via Outbox nas mutações de instância e
  decisão.
- Preparar integração futura de M15/M4/M6/M11/M12 por contratos e eventos, sem
  imports internos.

## Fora de escopo

- Não converter Quote em Order.
- Não criar Order M4.
- Não reservar estoque M5 a partir de workflow nesta sprint.
- Não efetivar compra, fiscal ou financeiro; o módulo de origem consumirá a
  decisão em sprints posteriores.
- Não implementar delegação, quorum, SLA avançado ou simulação visual.

## Planejamento de commits

| Commit | Tema | Entrega |
| --- | --- | --- |
| 100 | Domínio/RBAC/Plano | M22 bounded context, entidades puras, permissões e plano da sprint |
| 101 | Schema | Migration `0026`, modelos SQLAlchemy e teste de metadata/tenant scope |
| 102 | Repositórios | Persistência company-scoped para definitions, steps, instances e decisions |
| 103 | Workflow Definition API | `GET/POST /api/v1/workflow/definitions` com RBAC e Error Contract |
| 104 | Request Workflow | Criação idempotente de instância a partir de fonte externa |
| 105 | My Approvals | Consulta paginada de pendências do aprovador logado |
| 106 | Approve/Reject | Decisão concorrente com `If-Match`, Audit e Outbox |
| 107 | Events/Inbox E2E | Eventos `WorkflowCreated`, `WorkflowApproved`, `WorkflowRejected` |
| 108 | Workflow Cockpit | UI `/ui/` para pendências, detalhe e decisão |
| 109 | E2E/Runbook | Chromium, documentação operacional e encerramento da Sprint 10 |

## Entrega do Commit 100

O módulo `erp.modules.workflow` foi criado com domínio puro e sem dependência de
framework, banco ou adapters. O domínio separa definição, instância, etapa e
decisão, mantendo a regra fundamental: `WorkflowApproved`/`WorkflowRejected`
representam decisão formal, não alteração direta da entidade de origem.

As permissões oficiais do M22 foram registradas na camada de aplicação usando
apenas contratos públicos do M1 Admin. Decisões e manutenção de definições são
operações críticas; leitura e criação de solicitações continuam company-scoped.
