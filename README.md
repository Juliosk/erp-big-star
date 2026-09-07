# ERP Big Star / Forma Kids

Monólito modular do ERP Big Star / Forma Kids, construído conforme as Etapas 1–10 da
arquitetura consolidada e o README de governança técnica em `Arquivos .MD/`.

## Estado atual

- Wave: `W0 — Engineering Foundation`
- Sprint: `0 — Repository Bootstrap`
- Implementado nesta baseline: Commit 001 e infraestrutura local do Commit 010
- Fora do escopo até validação: FastAPI, rotas, middleware, workers e domínios M1–M23

## Baseline Python

O projeto suporta oficialmente CPython `3.14.x`. O gerenciamento de dependências usa
`uv 0.12.10`, grupos PEP 735 no `pyproject.toml` e o lock universal versionado em
`uv.lock`.

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Dependências de runtime serão adicionadas pelo commit que introduzir a respectiva
capacidade. Por isso, o Commit 001 contém apenas a toolchain de desenvolvimento.

## Infraestrutura local

Crie o arquivo local de variáveis e suba os quatro serviços de infraestrutura:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env up -d
docker compose ps
```

O arquivo `.env` é ignorado pelo Git. Os valores de `.env.example` destinam-se somente
ao desenvolvimento local e devem ser alterados antes de qualquer ambiente compartilhado.

## Estrutura arquitetural reservada

A estrutura produtiva seguirá a baseline aprovada:

```text
apps/        # API, worker e scheduler
modules/     # bounded contexts M1–M23
contracts/   # events, requests e contratos síncronos
platform/    # database, messaging, security, audit e demais capacidades transversais
migrations/  # Alembic
tests/       # unit, integration, contracts, e2e e fixtures
docker/      # artefatos auxiliares de containers
docs/        # ADRs e documentação técnica
```

Esses diretórios serão materializados nos commits que introduzirem cada capacidade,
evitando scaffolding vazio e dependências prematuras.

