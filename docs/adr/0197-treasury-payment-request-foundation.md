# ADR 0197 — Solicitação de pagamento antes do lote bancário M12

- **Status:** Accepted
- **Data:** 2026-11-11
- **Decisão:** Triple Track / Commit 217

## Contexto

Tesouraria já controla `PaymentBatch`, remessa e confirmação bancária. O backlog
financeiro, entretanto, exige `Payment Request → Payment Batch`. Selecionar
parcelas diretamente no lote mistura intenção/aprovação financeira com o
artefato operacional de transmissão.

## Decisão

`PaymentRequest` é o agregado puro que antecede o lote. Ele congela parcelas,
beneficiário bancário, matching, valor, moeda, vencimento, conta de tesouraria,
finalidade e data planejada. O subdomínio permanece em `erp.modules.finance`;
não será criado outro bounded context ou schema para Treasury.

O ciclo inicial é `DRAFT → PENDING_APPROVAL → APPROVED → BATCHED`, com rejeição
e cancelamento explícitos. Aprovação exige ator diferente do solicitante,
moeda coincidente e alçada suficiente. Somente solicitação aprovada pode ser
associada a um `PaymentBatch`.

### Limites

- Payables continua owner do título e parcela.
- PaymentRequest é owner da intenção e aprovação de pagamento.
- PaymentBatch é owner da remessa, transmissão e retorno bancário.
- O agregado usa snapshot bancário do próprio M12 e não importa M6 ou M11.
- Persistência, M22, API e conversão em lote ficam fora deste commit.

## RBAC e SoD

| Permissão | Risco | Uso |
| --- | --- | --- |
| `finance.treasury.read` | HIGH | consultar solicitação e execução |
| `finance.payment.request` | CRITICAL | criar/submeter solicitação |
| `finance.payment.approve` | CRITICAL | aprovar/rejeitar sob alçada |

Solicitante, aprovador e executor obedecem maker-checker. Aprovação M22 não
concede permissão e permissão não substitui aprovação transacional.

## Consequências

Intenção financeira e transmissão bancária ficam separadas e rastreáveis. O
custo é uma etapa adicional, compensada pela prevenção de pagamento sem alçada,
drift de favorecido e inclusão direta de parcelas em remessas.
