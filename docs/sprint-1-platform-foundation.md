# Sprint 1 — validação da fundação de plataforma

Este lote implementa os Commits 014 a 020 da ordem executiva aprovada:

| Commit | Entrega |
| --- | --- |
| 014 | `platform.audit_event` append-only, mascaramento e Error Contract |
| 015 | Envelope corporativo e Transactional Outbox |
| 016 | RabbitMQ durável, publisher confirms, quatro retries e DLQ |
| 017 | Inbox idempotente por consumidor e mensagem |
| 018 | Celery, filas explícitas, late ACK e task do Outbox Publisher |
| 019 | `Idempotency-Key`, fingerprint SHA-256 e replay do resultado |
| 020 | Optimistic locking e cenário técnico ponta a ponta |

## Aplicar o banco

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

## Subir a API

```powershell
.\.venv\Scripts\uvicorn.exe erp.apps.api.app:app --host 127.0.0.1 --port 8000
```

O endpoint técnico é habilitado por padrão somente nos ambientes `local` e `test`.
Em produção, ele responde `404` salvo habilitação explícita.

## Executar o cenário de aceite

```powershell
$headers = @{
    "Idempotency-Key" = [guid]::NewGuid().ToString()
    "X-Correlation-ID" = [guid]::NewGuid().ToString()
}
$body = @{ name = "Sprint 1 golden flow" } | ConvertTo-Json
Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/platform/test-entities" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
```

Resultado esperado:

```json
{
  "id": "uuid",
  "name": "Sprint 1 golden flow",
  "status": "CONSUMED",
  "version": 2,
  "event_id": "uuid",
  "audit_event_ids": ["uuid", "uuid"],
  "idempotency_replayed": false
}
```

Repetir a requisição com a mesma chave e o mesmo corpo devolve o resultado original
e o header `Idempotency-Replayed: true`. Reusar a chave com outro corpo devolve
`409 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`.

## Executar o worker

```powershell
.\.venv\Scripts\celery.exe `
    -A erp.platform.workers.celery_app:celery_app `
    worker `
    --loglevel=INFO `
    --queues=erp.default,erp.maintenance `
    --pool=solo
```

O `--pool=solo` é destinado ao desenvolvimento no Windows. O ambiente de produção
deve usar workers em contêiner Linux, dimensionados por fila operacional.

## Gate automatizado

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe erp tests migrations
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\pytest.exe --cov=erp --cov-report=term-missing
```
