# ADR 0196 — RFQ e comparação de propostas no M6

- **Status:** Accepted
- **Data:** 2026-11-11
- **Decisão:** Triple Track / Commit 217

## Contexto

O M6 possui fornecedor, requisição, pedido e recebimento, porém o intervalo
entre demanda aprovada e escolha do fornecedor ainda não é representado. O
modelo consolidado prevê `procurement.rfq` e `procurement.rfq_supplier`, com
comparação rastreável antes da geração do pedido.

## Decisão

`RequestForQuotation` é o agregado puro de concorrência de compra. Ele congela
itens solicitados, quantidades, especificações, data necessária e fornecedores
convidados. `SupplierQuote` representa uma proposta imutável com moeda, preços,
quantidades, lead time, frete e validade.

O ciclo inicial é `DRAFT → OPEN → CLOSED → AWARDED`, com cancelamento permitido
antes da adjudicação. A proposta precisa cobrir todos os itens sem reduzir a
quantidade pedida. O criador da RFQ não pode adjudicar a própria competição.

### Limites

- M6 é owner da RFQ, proposta recebida e adjudicação.
- Supplier continua owner do cadastro; Product continua owner do SKU.
- M11 não participa da escolha e M12 não recebe obrigação antes de PO/nota.
- Integrações futuras usam IDs e contratos públicos na composition root.
- Persistência, API, ranking multicritério e conversão em PO ficam fora do commit.

## RBAC e SoD

| Permissão | Risco | Uso |
| --- | --- | --- |
| `procurement.rfq.read` | MEDIUM | consultar RFQs e propostas |
| `procurement.rfq.manage` | HIGH | abrir RFQ e registrar proposta |
| `procurement.rfq.award` | CRITICAL | adjudicar fornecedor vencedor |

O award exige escopo `company_id`, permissão crítica e maker-checker. Aprovação
M22 pode ser adicionada por política sem transferir ownership ao Workflow.

## Consequências

A decisão de compra passa a ter evidência determinística e auditável. Isso
adiciona snapshots de proposta, mas elimina a seleção informal de fornecedor e
prepara comparação, negociação e conversão controlada em Purchase Order.
