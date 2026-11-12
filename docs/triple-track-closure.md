# Relatório de encerramento — Trilha Tripla

## Escopo do encerramento

Os Commits 217–220 entregaram as fundações Fiscal, Procurement e
Finance/Tesouraria. O Commit 221 registra a auditoria documental e de banco e
alinha os modelos ORM aos tipos, índices e valores padrão definidos nas
migrations aplicadas.

Runbooks cobertos pelos testes de conformidade.

- Regras fiscais, imutabilidade tributária e SEFAZ. [Fiscal](fiscal-runbook.md)
- RFQs, propostas, adjudicação e SoD. [Compras](procurement-runbook.md)
- Solicitações, alçadas e liquidação bancária. [Tesouraria](treasury-runbook.md)

## Matriz de evidências

| Gate | Evidência reproduzível | Critério |
| --- | --- | --- |
| Documentação | [Conformidade dos runbooks](../tests/unit/test_triple_track_runbook_compliance.py) | APIs/UIs oficiais, RBAC, tenant, segurança do token, Audit/Outbox e recuperação presentes nos três runbooks |
| Fronteiras | [Limites de módulos](../tests/unit/test_architecture_boundaries.py) | Independência entre os bounded contexts |
| PostgreSQL | [Reversão e comparação do schema](../tests/integration/test_triple_track_schema.py) | Migration 0061 reversível, chaves compostas por empresa e comparação global via `compare_metadata` |
| APIs e Web | [Integração dos cockpits](../tests/integration/test_triple_track_cockpits.py) | RBAC, anti-enumeração, `no-store`, desktop/mobile e token somente em memória |
| Qualidade global | Ruff, Mypy e Pytest | Análise estática sem pendências e suíte integral verde |

## Auditoria de migration e ORM

A Migration 0061 é a única head. O teste de reversão confirma a remoção e
recriação das sete tabelas da trilha no ciclo `0061 → 0060 → 0061` e verifica
chaves compostas por empresa. Um teste independente carrega os mapeamentos da
API e executa `compare_metadata` com todos os schemas, comparação de tipos e
defaults do servidor. Esse teste complementa o `alembic check` com a
configuração padrão da CLI. As verificações de integridade específicas, como
triggers e regras de domínio, pertencem às suítes de cada módulo.

A auditoria alinhou quatro campos monetários de fluxo de caixa a
`NUMERIC(19, 2)`, registrou no ORM o índice
`ix_payable_governance_company_status` e incorporou 14 defaults do servidor
que já existiam nas migrations. O schema do banco continua na revisão `0061`.

Configure `POSTGRES_DB` com o nome de uma base PostgreSQL dedicada aos testes
antes de rodar estes comandos. A suíte executa downgrades que removem tabelas.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --cov=erp --cov-report=term
```

## Resultado da auditoria

| Verificação | Resultado |
| --- | --- |
| Suíte global | 2.412 testes aprovados, incluindo os cenários Chromium desktop/mobile e de acesso negado por RBAC |
| Cobertura global | 91,89% com ramificações |
| Conformidade dos runbooks | 4 testes aprovados, incluindo a verificação do relatório |
| PostgreSQL local | `0061 (head)`, `alembic check` sem novas operações e ciclo `0061 → 0060 → 0061` aprovado na base de auditoria |
| Comparação ORM/PostgreSQL | 131 tabelas mapeadas, sem diferenças detectadas pelo Alembic |
| Mypy | 973 arquivos analisados, zero erros |
| Ruff lint | `ruff check .` aprovado |
| Ruff formatação | `ruff format --check .` apontou 228 arquivos com pendências preexistentes |

A suíte global foi executada em `erp_audit_221`. O único aviso foi a
depreciação do alias `anyio.abc.BlockingPortal` no `TestClient` do Starlette.

Com a validação funcional, documental e de schema concluída, ficam encerradas
as entregas operacionais de Fiscal, Compras e Tesouraria previstas na Trilha
Tripla. A formatação global continua registrada como pendência do repositório.
