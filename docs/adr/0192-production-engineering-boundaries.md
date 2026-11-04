# ADR 0192 — Produção, Engenharia, MRP e Chão de Fábrica

- **Status:** Accepted
- **Data:** 2026-11-04
- **Decisão:** Sprint 22 / Commit 196

## Contexto

O roadmap industrial exige fichas técnicas multinível, revisões controladas de
engenharia, roteiros, centros de trabalho, planejamento de necessidades e
apontamentos de produção. Esses conceitos não podem ser incorporados a Product
(M2) ou Inventory (M5): M2 continua proprietário do cadastro comercial do item
e M5 continua proprietário do saldo e do ledger físico.

## Decisão

O novo bounded context canônico é `erp.modules.production`, organizado em:

```text
production/
├── domain/          # BOM, revisões, roteiros, centros e regras industriais puras
├── application/     # casos de uso, portas e autorização tenant-bound
├── infrastructure/  # persistência e adaptadores exclusivos do módulo
└── api/             # contratos HTTP, sem regra industrial
```

### Autoridade do módulo

Produção é System of Record de:

- ficha técnica (`BillOfMaterials`) e suas revisões de engenharia;
- roteiros operacionais e restrições de centros de trabalho;
- ordens planejadas e firmes de produção;
- consumo previsto, realizado, rendimento e perdas (`scrap`);
- progresso e apontamentos do chão de fábrica.

Cada agregado operacional carrega `company_id`. Uma expansão de BOM, roteiro ou
ordem jamais combina objetos de empresas diferentes.

### BOM multinível e versionamento

- Quantidades usam `Decimal` com seis casas; `float` é proibido.
- A unidade de medida acompanha cada quantidade e não sofre conversão implícita.
- A revisão de engenharia possui código, número e vigência explícitos.
- Apenas uma revisão pode estar ativa por produto e empresa no instante do uso.
- A expansão percorre submontagens, agrega apenas insumos folha e aplica perda
  pela fórmula `necessidade bruta = necessidade líquida / (1 - scrap)`.
- Ciclos diretos ou indiretos são rejeitados com `BOM_CYCLE_DETECTED` antes do
  cálculo de MRP.

### Roteiros e centros de trabalho

Operações possuem sequência única e ordenada, tempos exatos de preparação e
execução, lista de centros permitidos e capacidades obrigatórias. A validação é
tenant-bound e não seleciona silenciosamente um centro incompatível.

### Fronteiras

- **M2 Product:** fornece somente identidade e dados públicos do produto.
- **M5 Inventory:** recebe comandos/eventos versionados de consumo, produção e
  scrap; Produção nunca atualiza tabelas ou saldos do M5 diretamente.
- **M6 Procurement:** pode receber necessidades planejadas por contrato público;
  Produção não cria pedidos de compra diretamente.
- **M17 Quality:** troca pedidos e resultados de inspeção por contratos/eventos.
- **M22 Workflow:** governa aprovações de revisão/liberação por contrato público.

O domínio puro não importa módulos externos, ORM, FastAPI, Pydantic ou
infraestrutura. A composição entre owners ocorre em `erp.apps` por portas
injetadas. Escritas críticas futuras usarão Audit + Outbox na mesma transação;
consumers usarão Inbox idempotente.

## RBAC

| Permissão | Risco | Finalidade |
| --- | --- | --- |
| `production.engineering.read` | MEDIUM | consultar BOM, versões e roteiros |
| `production.engineering.write` | HIGH | criar/revisar BOM, centros e roteiros |
| `production.planning.read` | HIGH | consultar MRP e planos de produção |
| `production.planning.run` | CRITICAL | executar MRP e liberar ordens planejadas |
| `production.shop_floor.read` | HIGH | consultar ordens e andamento fabril |
| `production.shop_floor.execute` | CRITICAL | apontar consumo, produção e scrap |

Toda autorização combina permissão e acesso explícito à empresa de trabalho.

## Consequências

As estruturas de engenharia tornam-se determinísticas, auditáveis e evoluem sem
vazar regras para Estoque ou Produto. O custo é manter contratos explícitos e
conversões de unidade deliberadas, evitando atalhos ambíguos durante o MRP.

