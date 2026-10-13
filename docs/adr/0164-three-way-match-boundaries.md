# ADR 0164 — Three-Way Match M6/M11/M12

- **Status:** Accepted
- **Data:** 2026-10-12
- **Decisão:** Sprint 18 / Commit 164

## Contexto

O ERP precisa decidir, de forma reproduzível, se a obrigação financeira de uma
compra corresponde ao que foi pedido, fisicamente recebido e fiscalmente
faturado. Esses fatos pertencem a bounded contexts diferentes e não podem ser
consultados por joins ou imports diretos entre seus schemas.

O modelo consolidado define `three_way_match` como agregado do M6 e estabelece
que Procurement é a autoridade do match operacional. M11 permanece autoridade
do documento fiscal de entrada e M12 permanece autoridade da provisão e do
título a pagar.

## Decisão de ownership

O motor e o futuro agregado persistente pertencem a `erp.modules.procurement`:

```text
M6 PurchaseOrder + GoodsReceipt ─┐
                                 ├─ snapshots puros → Three-Way Match M6
M11 InboundFiscalDocument ───────┘                    │
                                                      ├─ gate/evento → M12 Payable
M12 ProvisionalEntry/Payable reference ──────────────┘
```

- M6 compara pedido, recebimento aprovado pelo M17 e snapshot fiscal fornecido
  pelo M11.
- M11 não importa Procurement nem Finance e não recalcula o match.
- M12 não lê schemas `procurement` ou `fiscal`; consome apenas resultado
  versionado e conserva as referências da provisão/título.
- M22 será o único owner de decisões de override acima de alçada.
- Todo comando, snapshot, política e resultado contém `company_id` explícito.

O Commit 164 contém somente domínio puro. SQLAlchemy, FastAPI, Pydantic,
mensageria e persistência serão introduzidos em slices posteriores.

## Contratos puros

`ThreeWayMatchLine` é um snapshot imutável com as identidades das linhas de
pedido, recebimento e documento fiscal, além de quantidades e preços necessários
ao cálculo. `ThreeWayMatchReferences` preserva as identidades dos agregados M6,
M11 e M12 sem importar seus tipos internos.

`MatchingTolerancePolicy` é tenant-bound e versionada. O resultado conserva a
política efetivamente aplicada, deltas assinados, limites calculados e reason
codes. Reprocessar os mesmos snapshots com a mesma política produz o mesmo
resultado.

## Matriz de tolerâncias

O perfil fail-closed inicial é configurável por empresa e tem os seguintes
defaults:

| Dimensão | Default | Base de cálculo | Critério de aceite |
| --- | ---: | --- | --- |
| Preço unitário | `0,0000%` | preço unitário do pedido | delta absoluto menor ou igual ao percentual ou ao limite de arredondamento, o que for maior |
| Quantidade | `0,0000%` | quantidade faturada | diferença absoluta entre recebido e faturado menor ou igual ao limite |
| Arredondamento | `0,01` | valor monetário da linha | absorve somente divergência absoluta até o limite configurado |

Percentuais aceitos ficam entre `0` e `100`. O limite absoluto de arredondamento
fica entre `0,00` e `1,00` unidade monetária. Configurações futuras serão
persistidas por `company_id` e versão; alterar uma política não modifica matches
já calculados.

## Estados e precedência

| Situação da linha/relatório | Status |
| --- | --- |
| quantidade e preço dentro dos limites | `MATCHED` |
| somente quantidade fora do limite | `QUANTITY_MISMATCH` |
| somente preço fora do limite | `PRICE_MISMATCH` |
| quantidade e preço fora do limite na mesma linha | `TOLERANCE_EXCEEDED` |
| relatório com divergências de quantidade e preço em linhas diferentes | `TOLERANCE_EXCEEDED` |

Somente `MATCHED` libera o gate financeiro. Os demais estados bloqueiam o M12
até correção da origem ou futura decisão explícita do M22. O motor nunca ajusta
pedido, recebimento, documento fiscal ou título automaticamente.

## Invariantes

- a política e todas as linhas devem pertencer à mesma empresa;
- `match_key` é canônica e única dentro de um relatório;
- quantidades pedida e faturada são positivas; recebida pode ser zero;
- preços não podem ser negativos e moeda usa ISO 4217 alpha-3;
- referências de pedido, recebimento, documento fiscal, provisão e título são
  UUIDs imutáveis;
- conjuntos de recebimentos/documentos são não vazios e não aceitam duplicatas;
- valores inválidos, não finitos ou cross-tenant falham antes de qualquer I/O.

## Consequências

O match passa a ser determinístico, explicável e testável sem banco ou
framework. O custo é manter adapters anticorrupção que traduzam fatos de M11 e
M12 para snapshots M6. Esse custo é aceito para preservar ownership,
auditabilidade, replay e isolamento de tenant.
