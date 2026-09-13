# Sprint 8 — M9 Pricing

## Objetivo

Construir o núcleo de precificação do ERP, responsável por decidir preços,
controlar versões de listas, preservar custo/margem como dado sensível e expor
contratos seguros para M15, M4 e M3 consumirem em sprints posteriores.

## Commits planejados

| Commit | Tema | Entrega |
| --- | --- | --- |
| 080 | Domínio e contratos | `PriceList`, `PriceListVersion`, `PriceListItem`, value objects e permissões |
| 081 | Schema | Migration `0023` com schema `pricing` e tabelas base |
| 082 | Persistência/serviços | Repositório e serviços tenant-bound para listas e versões draft |
| 083 | APIs base | `GET/POST /price-lists` e criação de versões com RBAC/Error Contract |
| 084 | Ativação | Concorrência/ETag, Audit e Outbox `PriceActivated`/`PriceSuperseded` |
| 085 | Custo/margem | Fonte provisória `LEGACY_OPENING` e política de margem mínima |
| 086 | Resolver | `PricingResolutionService` e `POST /pricing/resolve` |
| 087 | Simulação | Simulador persistente e evento `PricingSimulationCompleted` |
| 088 | UI | Pricing Cockpit em `/ui/` |
| 089 | E2E/Docs | Chromium E2E, runbook M9 e encerramento |

## Limites de escopo

- M9 decide preço; M3 publica no marketplace.
- M15 Quote e M4 Order apenas consumirão contratos públicos em sprints futuras.
- M8 Costing definitivo ainda não está ativo; custo inicial usa origem
  `LEGACY_OPENING`.
- Vendedores não acessam custo/margem por padrão; margem exige permissão
  `pricing.margin.view`, equivalente técnico normalizado ao item de governança
  `pricing.margin.view_sensitive`.

## Entrega do Commit 080

O domínio puro de M9 foi criado sem dependências de banco, API ou infraestrutura.
`Money` normaliza BRL em duas casas, `Percentage` normaliza razões com quatro
casas e `PriceListVersion` só permite ativação de versão draft com itens.

Os contratos públicos introduzem `PricingResolutionService`,
`PricingResolutionRequest` e `PricingResolution`, mantendo outros módulos
dependentes apenas da superfície pública de M9. O RBAC inicial segue a matriz:
`pricing.price.simulate`, `pricing.price.create`, `pricing.price.activate`,
`pricing.margin.view` e `pricing.exception.request`.

## Entrega do Commit 081

A migration `0023` cria o schema `pricing` e as tabelas fundacionais:
`price_list`, `price_list_version`, `price_list_item`,
`minimum_margin_policy` e `pricing_snapshot`. Todas as entidades persistentes
possuem `company_id`; listas, versões e itens usam chaves/constraints compostas
para impedir leitura ou escrita cruzada entre empresas.

Os modelos SQLAlchemy foram alinhados à migration e o teste de schema compara a
metadata ORM contra o banco aplicado, incluindo FKs tenant-bound para produto via
`(company_id, product_id)`.

## Entrega do Commit 082

`PricingCatalogService` foi criado como serviço de aplicação do M9, com
autorização por `PricingAuthorization` e dependência apenas das portas públicas
`PricingCatalogue`, `PricingCatalogStore` e `PricingDirectory`. O serviço cria
listas de preço, abre versões draft sequenciais e lista dados por empresa sem
expor tipos de infraestrutura.

O adapter `PostgresPricingCatalogue` controla sessões e delega persistência ao
`PriceListRepository`, sempre instanciado com `company_id` explícito. O teste de
integração cobre criação/listagem, versões `DRAFT` sequenciais, conflito de
código por empresa, RBAC e isolamento entre empresas.
