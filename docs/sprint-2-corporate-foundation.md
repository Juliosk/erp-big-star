# Sprint 2 — M1 Corporate Foundation

## Escopo entregue

O contexto M1 é o proprietário de `EconomicGroup`, `Company`, `Branch`, RBAC e resolução de
escopos. O domínio não importa FastAPI, SQLAlchemy ou módulos de negócio vizinhos. A hierarquia
persistida é `Grupo Econômico -> Empresa -> Filial`; grupo é limite de consolidação e autorização,
nunca autorização para misturar transações.

As migrations da Sprint são:

- `0007`: `admin.economic_group`, `admin.company` e `admin.branch`;
- `0008`: `admin.corporate_event_projection`;
- `0009`: remoção reversível de `platform.test_entity`.

## API `/api/v1/admin`

| Método | Rota | Contrato de segurança |
| --- | --- | --- |
| GET | `/companies` | `admin.company.read` + pelo menos um scope explícito |
| GET | `/companies/{id}` | mesma permissão; fora do scope retorna 404 |
| POST | `/companies` | `admin.company.create` + scope GROUP exato + Idempotency-Key |
| PATCH | `/companies/{id}` | `admin.company.update` + scope + If-Match |
| GET | `/economic-groups` | `admin.economic_group.read` + scope |
| GET | `/branches` | `admin.branch.read` + scope |
| POST | `/branches` | `admin.branch.create` + scope GROUP/COMPANY + Idempotency-Key |
| PATCH | `/branches/{id}` | `admin.branch.update` + scope + If-Match |
| GET | `/company-selector` | permissões de leitura de group/company/branch + scope |

Todas as rotas exigem `Authorization: Bearer <token>`. O aplicativo recebe um
`SecurityContextResolver` na composição; não existe fallback permissivo. O adapter de identidade
deve validar token/sessão e devolver permissões e scopes atuais. Sem adapter, a API responde
`503 AUTHENTICATION_UNAVAILABLE`.

Comandos retornam `Location`, `ETag` e `Idempotency-Replayed`. Atualizações exigem um ETag
positivo entre aspas, por exemplo `If-Match: "2"`; ausência responde 428 e versão obsoleta responde
`409 VERSION_CONFLICT`.

## Atomicidade e eventos

Criação e atualização registram agregado, Audit e Outbox na mesma transação PostgreSQL. Os eventos
M1 v1 são `CompanyCreated`, `CompanyUpdated`, `BranchCreated` e `BranchUpdated`. O publisher só
marca `published_at` depois do confirm do RabbitMQ.

O consumer `admin.corporate-projector.v1` grava Inbox e projeção na mesma transação. A chave do
evento impede duplicação da projeção; ACK ocorre somente após o commit. Falhas de schema seguem a
infraestrutura de retries e DLQ da Sprint 1.

## Operação local

```powershell
docker compose --env-file .env up -d
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\uvicorn.exe erp.apps.api.app:app --host 127.0.0.1 --port 8000
```

Antes de liberar um ambiente, componha o `SecurityContextResolver` real. Nunca injete permissões ou
scopes a partir de headers fornecidos pelo cliente.

## Gate e diagnóstico

```powershell
.\.venv\Scripts\ruff.exe check erp tests migrations
.\.venv\Scripts\ruff.exe format --check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m coverage run -m pytest
.\.venv\Scripts\python.exe -m coverage report --precision=2
```

Para inspecionar uma falha, use `correlation_id` do Error Contract nos logs JSON e depois consulte
`platform.audit_event`, `platform.outbox_event`, `platform.inbox_event` e
`admin.corporate_event_projection`. Não altere manualmente status de Inbox/Outbox; corrija a causa e
use ferramentas controladas de retry/replay.
