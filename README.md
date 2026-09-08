# ERP Big Star / Forma Kids

Monólito modular do ERP Big Star / Forma Kids, construído conforme as Etapas 1–10 da
arquitetura consolidada e o README de governança técnica em `Arquivos .MD/`.

## Estado atual

- Wave: `W1 — Corporate & Master Data Foundation`
- Sprint concluída e homologada: `3 — M2 Product Master`, commits `030–039`
- Sprint em execução: `4 — M23 Product Import`, lote `040–042` implementado para homologação técnica
- Schema atual: Alembic `0012`
- APIs atuais: health checks, contexto corporativo `/api/v1/admin` e M2 `/api/v1/products`
- M2: consultas, criação idempotente, PATCH concorrente, lifecycle estrito, barcodes e telas `/ui/`.
- DevSecurityContextResolver opt-in somente local/test; sem flag ou adapter real, autenticação segue 503.
- Produção exige provedor de identidade real. Veja o [runbook M2](docs/product-master-runbook.md).

## Baseline Python

O projeto suporta oficialmente CPython `3.14.x`. O gerenciamento de dependências usa
`uv 0.12.10`, grupos PEP 735 no `pyproject.toml` e o lock universal versionado em
`uv.lock`.

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run playwright install chromium
uv run pytest
```

As dependências permanecem travadas em `uv.lock`; mudanças de runtime entram apenas no commit que
introduz e testa a capacidade correspondente.

## Infraestrutura local

Crie o arquivo local de variáveis e suba os quatro serviços de infraestrutura:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env up -d
docker compose ps
```

O arquivo `.env` é ignorado pelo Git. Os valores de `.env.example` destinam-se somente
ao desenvolvimento local e devem ser alterados antes de qualquer ambiente compartilhado.

## Estrutura arquitetural

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

Consulte [a operação da Sprint 2](docs/sprint-2-corporate-foundation.md) para rotas, segurança,
eventos, migrations e gate de validação.

Consulte [o plano da Sprint 3](docs/sprint-3-product-master.md) para escopo, commits,
DoR/DoD, limites de aplicabilidade global e evidências dos lotes.

Consulte [o plano da Sprint 4](docs/sprint-4-product-import.md) para o fluxo de importação
de produtos, divisão 040–049, limites de M23 e decisões necessárias antes do commit funcional.
