# ADR 0195 — Catálogo versionado de regras tributárias do M11

- **Status:** Accepted
- **Data:** 2026-11-11
- **Decisão:** Triple Track / Commit 217

## Contexto

O M11 já controla documentos fiscais, transmissão SEFAZ e snapshots de impostos,
mas ainda não possui a autoridade que explica como um snapshot foi determinado.
O backlog W5 ordena `Tax Rule → Fiscal Intent → Provider Adapter`. Codificar a
regra dentro da emissão ou consultar cadastros mutáveis destruiria a
reprodutibilidade histórica.

## Decisão

`TaxRule` é um agregado puro e tenant-bound do pacote `erp.modules.fiscal`.
Cada versão congela critérios de operação (entrada/saída, NCM, CFOP e
jurisdições), alíquotas exatas em `Decimal`, vigência e atores de governança.

O ciclo inicial é `DRAFT → ACTIVE → RETIRED`. Uma versão ativa não é editada:
uma mudança cria nova versão. O editor não pode ativar a própria regra. O
documento fiscal futuro armazenará a identidade da versão aplicada e continuará
preservando seu `TaxSnapshot` imutável.

### Limites

- M11 é owner de regra, vigência, ativação e snapshot tributário.
- M6 fornece fatos operacionais por contratos; não interpreta tributos.
- M12 recebe fatos fiscais autorizados; não recalcula regra tributária.
- O domínio não importa ORM, FastAPI, Pydantic, SEFAZ ou módulos vizinhos.
- Persistência, resolução de precedência, API e eventos ficam fora deste commit.

## RBAC e SoD

| Permissão | Risco | Uso |
| --- | --- | --- |
| `fiscal.tax_rule.read` | HIGH | consultar versões e vigências |
| `fiscal.tax_rule.manage` | CRITICAL | criar/editar somente rascunhos |
| `fiscal.tax_rule.activate` | CRITICAL | ativar versão por maker-checker |

Todas exigem `company_id`. A ativação combina RBAC, ator distinto do editor e,
quando configurado, decisão M22; nenhuma dessas condições substitui as demais.

## Consequências

O cálculo fiscal passa a ser explicável e versionável antes da persistência. O
custo é manter versões e resolver sobreposição explicitamente, evitando regra
oculta no adapter ou alteração retroativa de documento autorizado.
