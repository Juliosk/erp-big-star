# Runbook operacional — M22 Workflow Core

Este runbook cobre a Sprint 10: definições versionadas, abertura de instâncias,
central de aprovações, decisões concorrentes, Audit/Outbox e Workflow Cockpit
em `/ui/`.

## Responsabilidade do domínio

O M22 registra a decisão formal e sua trilha. Ele não altera diretamente a
entidade de origem. Módulos consumidores devem reagir aos eventos públicos do
Workflow e aplicar suas próprias regras dentro de seus transaction boundaries.

Todo registro mutável é isolado por `company_id`. A definição aplicável é
resolvida por empresa, módulo e tipo da entidade de origem.

## Permissões

| Permissão | Uso |
| --- | --- |
| `workflow.definition.manage` | criar, consultar, versionar e desativar definições |
| `workflow.request.create` | abrir instâncias de workflow |
| `workflow.request.read` | consultar instâncias e My Approvals |
| `workflow.approval.decide` | aprovar ou rejeitar a etapa ativa |

Em `local`/`test`, o `DevSecurityContextResolver` pode fornecer essas permissões.
Ele é proibido fora desses ambientes. A identidade também precisa possuir
escopo explícito para a empresa informada na chamada.

## Endpoints principais

| Operação | Contrato |
| --- | --- |
| Criar/listar definições | `GET/POST /api/v1/workflow/definitions` |
| Detalhar definição | `GET /api/v1/workflow/definitions/{id}` |
| Desativar definição | `POST /api/v1/workflow/definitions/{id}/deactivate` |
| Abrir solicitação | `POST /api/v1/workflow/instances` |
| Consultar solicitação e passos | `GET /api/v1/workflow/instances/{id}` |
| Consultar pendências | `GET /api/v1/workflow/approvals/pending` |
| Aprovar ou rejeitar | `POST /api/v1/workflow/instances/{id}/decide` |

Desativação e decisão exigem `If-Match: "N"`. Versões desatualizadas retornam
`VERSION_CONFLICT`; ausência do header retorna `PRECONDITION_REQUIRED`.

## Modos de aprovação

- `SEQUENTIAL`: ativa uma etapa por vez, na ordem de sequência.
- `HIGHEST_LEVEL`: ativa somente a maior alçada aplicável.
- `CUMULATIVE`: ativa todas as etapas aplicáveis e conclui quando todas forem
  aprovadas.

Uma rejeição ativa encerra a instância como `REJECTED`. Não existem reversão,
delegação ou edição retroativa de decisões nesta sprint.

## Workflow Cockpit

1. Inicie a API e acesse `/ui/`.
2. Informe o Bearer token e selecione a empresa de trabalho.
3. Abra **Aprovações M22**.
4. Em **My Approvals**, selecione a solicitação.
5. Confira origem, versão e trilha de passos antes de decidir.
6. Registre aprovação ou rejeição com comentário.
7. Use **Definições de workflow** para criar o primeiro passo de uma nova
   política. Configurações de múltiplos passos continuam disponíveis pela API.

O token e o contexto selecionado permanecem somente em memória. A UI não usa
`localStorage` nem `sessionStorage`. Trocar a empresa recarrega fila e definições
com o novo `company_id`.

## Audit e eventos

A decisão e seus efeitos compartilham a mesma transação PostgreSQL:

- `WorkflowStepApproved`, quando outra etapa ainda aguarda decisão;
- `WorkflowInstanceApproved`, quando a aprovação conclui a instância;
- `WorkflowInstanceRejected`, quando uma etapa ativa é rejeitada.

O Audit guarda snapshots anterior e posterior, ator, razão, request ID e
correlation ID. O Outbox usa o ID da instância como agregado. Qualquer falha ao
gravar Audit ou Outbox causa rollback da decisão e da evolução dos passos.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\unit\modules\workflow tests\integration\test_workflow_schema.py tests\integration\test_workflow_repositories.py tests\integration\test_workflow_api.py tests\integration\test_workflow_browser.py tests\unit\test_architecture_boundaries.py
```

O E2E Chromium gera:

- `test-results/workflow-cockpit-desktop.png`
- `test-results/workflow-cockpit-mobile.png`

## Troubleshooting

- `WORKFLOW_DEFINITION_NOT_FOUND`: confirme empresa, módulo, tipo e definição
  ativa.
- `PERMISSION_FORBIDDEN`: confira a permissão da rota e também a
  `required_permission` da etapa.
- `VERSION_CONFLICT`: releia a instância e repita com o ETag atual.
- Fila vazia após trocar empresa é comportamento esperado quando não há etapas
  elegíveis naquele tenant.
- Em indisponibilidade do Docker, preserve os volumes. Não execute factory
  reset, `docker system prune -a --volumes` nem remova volumes locais.

## Critérios de aceite da Sprint 10

- Schema e repositories company-scoped.
- Definições, instâncias, pendências e decisões expostas por contratos oficiais.
- Concorrência otimista obrigatória nas decisões.
- Audit e Outbox atômicos com snapshots rastreáveis.
- Cockpit responsivo e isolamento entre empresas validados no Chromium real.
- Ruff, Mypy, fronteiras arquiteturais e suíte global verdes.
