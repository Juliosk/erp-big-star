# Runbook operacional — M9 Pricing

Este runbook cobre a Sprint 8: domínio de listas de preço, versionamento,
ativação concorrente, custo padrão provisório, política de margem mínima,
resolução de preço com snapshot, simulação stateless e Pricing Cockpit em
`/ui/`.

## Escopo entregue

- Listas de preço por empresa (`price_list`) com código único dentro de
  `company_id`.
- Versões de lista (`price_list_version`) com itens por produto e ativação
  controlada por ETag/`If-Match`.
- Custo padrão provisório em `pricing.standard_cost_seed`, limitado à origem
  `LEGACY_OPENING` até a entrada oficial do M8 Costing.
- Política de margem mínima em `pricing.minimum_margin_policy`.
- Resolução oficial em `POST /api/v1/pricing/resolve`, persistindo
  `pricing_snapshot` para auditoria da decisão comercial.
- Simulação em `POST /api/v1/pricing/simulate`, usando as mesmas regras de
  preço/custo/margem sem persistir snapshot.
- Consulta de histórico em `GET /api/v1/pricing/snapshots`, filtrável por
  produto e sempre isolada por empresa.
- Pricing Cockpit em `/ui/` para listas, versões, ativação, snapshots e
  simulação interativa.

M9 decide preço. Publicação em marketplace, pedidos, faturamento, exceções
aprováveis de margem, campanhas avançadas, regras por canal/grupo de cliente
completo e costing definitivo pertencem a sprints/módulos posteriores. M15, M4,
M3 e demais contextos devem consumir apenas os contratos públicos de M9.

## Permissões

Para operação completa em ambiente local/test com `DevSecurityContextResolver`,
mantenha os grants:

```powershell
$env:DEV_AUTH_PERMISSIONS = '["admin.company.read","product.product.read","pricing.price.simulate","pricing.price.create","pricing.price.activate","pricing.margin.view","pricing.exception.request"]'
```

O default local/test do projeto já inclui esses grants. Em ambientes
compartilhados, a identidade oficial deve fornecer:

| Permissão | Uso |
| --- | --- |
| `pricing.price.simulate` | leitura operacional de listas, snapshots, resolve e simulate |
| `pricing.price.create` | criação de lista e versão draft |
| `pricing.price.activate` | ativação concorrente de versão |
| `pricing.margin.view` | exibição de margem efetiva/sensível |
| `pricing.exception.request` | reservado para workflow futuro de exceções |

Toda chamada exige `company_id` explícito e escopo da identidade para essa
empresa. Usuário sem `pricing.margin.view` recebe preço e snapshot, mas a
margem efetiva permanece mascarada.

## Endpoints principais

| Operação | Contrato |
| --- | --- |
| Criar/listar listas | `GET/POST /api/v1/pricing/price-lists` |
| Detalhar lista | `GET /api/v1/pricing/price-lists/{price_list_id}` |
| Criar/listar versões | `GET/POST /api/v1/pricing/price-lists/{price_list_id}/versions` |
| Detalhar versão | `GET /api/v1/pricing/price-list-versions/{version_id}` |
| Ativar versão | `POST /api/v1/pricing/price-list-versions/{version_id}/activate` |
| Resolver preço | `POST /api/v1/pricing/resolve` |
| Simular preço | `POST /api/v1/pricing/simulate` |
| Consultar snapshots | `GET /api/v1/pricing/snapshots` |

Writes idempotentes de lista, versão e ativação exigem `Idempotency-Key`.
Ativação exige também `If-Match: "N"` com a versão atual da
`price_list_version`. Falhas seguem o Error Contract padronizado:
`PERMISSION_FORBIDDEN`, `RESOURCE_NOT_FOUND`, `VERSION_CONFLICT`,
`PRICING_PRICE_LIST_CONFLICT`, `INVALID_PRICE_LIST_VERSION_STATUS`,
`STANDARD_COST_NOT_FOUND` e `MINIMUM_MARGIN_VIOLATION`.

## Jornada operacional

1. Confirme que existe produto ativo/cadastrado no M2 para a empresa de
   trabalho.
2. Cadastre ou importe o custo padrão provisório `LEGACY_OPENING` para o produto.
   A Sprint 8 fornece a estrutura e serviço de política; telas administrativas
   de custo ficam para evolução posterior.
3. Crie uma lista de preço em `POST /api/v1/pricing/price-lists`.
4. Crie uma versão draft com ao menos um item em
   `POST /api/v1/pricing/price-lists/{id}/versions`.
5. Ative a versão com `If-Match` e `Idempotency-Key`. A ativação publica
   `PriceListVersionActivated` via Outbox e grava Audit na mesma transação.
6. Use `/pricing/simulate` para negociar preço proposto sem congelar decisão.
7. Use `/pricing/resolve` quando a decisão deve ser persistida como
   `pricing_snapshot`.
8. Consulte `/pricing/snapshots` ou o Cockpit para rastrear decisões
   persistidas.

Simulação não grava snapshot. Ela retorna `persisted=false` e
`pricing_snapshot_id=00000000-0000-0000-0000-000000000000`. Resolução grava
snapshot e retorna `persisted=true`.

## Pricing Cockpit em `/ui/`

1. Inicie a API com Dev Auth habilitado apenas em `local`/`test`.
2. Acesse `/ui/`, informe o token e selecione a empresa de trabalho.
3. Abra **Pricing M9**.
4. Crie lista, selecione-a, crie versão e ative.
5. No simulador, informe produto, quantidade e opcionalmente preço proposto.
6. Use **Simular sem gravar** para projeção stateless.
7. Use **Resolver e congelar** para persistir snapshot.
8. Trocar a empresa deve limpar listas/snapshots que não pertençam ao novo
   `company_id`.

A Web não usa `localStorage`/`sessionStorage` para token, lista ou snapshots.
O token fica apenas em memória durante a sessão da página.

## Eventos, Audit e idempotência

Ativação de versão grava Audit com snapshots antes/depois e publica
`PriceListVersionActivated` no Outbox com `source_module=pricing`. Replays da
mesma `Idempotency-Key` retornam a resposta original e não duplicam Audit/Outbox.

`pricing_snapshot` é criado apenas por `/pricing/resolve`. Falhas de margem,
custo ausente, permissão, empresa não autorizada ou lista inexistente não devem
persistir snapshot.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\unit\modules\pricing tests\integration\test_pricing_schema.py tests\integration\test_pricing_catalogue.py tests\integration\test_pricing_api.py tests\integration\test_pricing_browser.py
```

Para gerar evidências visuais:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_pricing_browser.py
```

O teste gera `test-results/pricing-cockpit-desktop.png` e
`test-results/pricing-cockpit-mobile.png`.

## Troubleshooting

- `STANDARD_COST_NOT_FOUND`: cadastre seed `LEGACY_OPENING` para
  `(company_id, product_id)` antes de simular/resolver.
- `MINIMUM_MARGIN_VIOLATION`: revise preço unitário, custo ou política ativa de
  margem mínima.
- `VERSION_CONFLICT`: releia a versão/lista, obtenha o ETag atual e repita a
  ativação com nova chave idempotente.
- Lista vazia na UI após troca de empresa é comportamento esperado quando o
  outro `company_id` não possui cadastros de pricing.
- Em falha de Docker/PostgreSQL/RabbitMQ, preserve volumes. Não executar
  `docker system prune -a --volumes`, factory reset ou remoção de volumes locais.

## Critérios de aceite da Sprint 8

- Migrations aplicadas até o head da Sprint.
- Domínio de M9 isolado de infraestrutura e de outros contextos.
- Repositórios e APIs sempre filtrando por `company_id`.
- Ativação concorrente exigindo `If-Match` e idempotência.
- Audit/Outbox transacionais para ativação.
- Resolução persistindo snapshot auditável.
- Simulação stateless sem criação de snapshot.
- UI responsiva validada por Chromium real.
- Ruff, Mypy, testes de unidade, integração e E2E verdes antes da homologação.
