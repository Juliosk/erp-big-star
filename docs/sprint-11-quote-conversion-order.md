# Sprint 11 — M15 Quote Conversion + M4 Order Aggregate

## Objetivo

Entregar o caminho comercial inicial de orçamento aceito para pedido persistido,
recuperando primeiro a fundação M15 prevista no roadmap original e preservando
M4 como owner exclusivo do pedido.

## DoR e ajuste executivo

O roadmap pressupunha M15 Quote na Sprint 9. O repositório contém M10 WMS nessa
posição e não possui `erp.modules.sales`. Portanto, conversão direta não atende
ao DoR. Os commits 110–115 recompõem o M15 antes dos commits 116–119 de M4.

Dependências já homologadas: M1, M2, M14, M5, M9 e M22. M15 consumirá apenas
contratos públicos desses owners. Nenhum repository/ORM cross-domain será
importado pelas camadas de domínio ou aplicação.

## Planejamento

| Commit | Entrega |
| --- | --- |
| 110 | Domínio M15, lifecycle, revisões imutáveis, RBAC e plano |
| 111 | Schema `sales_b2b`, migration e modelos SQLAlchemy |
| 112 | Repositórios M15 company-scoped |
| 113 | APIs oficiais de criação, listagem e detalhe de quotes |
| 114 | Revisão/send/accept/lost com ETag, Audit e Outbox |
| 115 | Exceção comercial e integração M15 → M22 |
| 116 | Domínio/schema/repository M4 Order Aggregate |
| 117 | Conversão idempotente Quote → Order e snapshots congelados |
| 118 | APIs de conversão/consulta, concorrência e eventos |
| 119 | Cockpit Web, E2E Chromium, runbook e encerramento |

## Fora de escopo

- Reserva M4 → M5, planejada para a Sprint 12.
- Fulfillment, picking e packing automáticos a partir do pedido.
- Emissão fiscal M11, recebíveis M12 e contabilização M13.
- Crédito autoritativo dentro do M15.
- Edição de revisão já enviada ou reversão automática de aceite/conversão.

## Contratos e eventos

M15 publicará `SalesQuoteCreated`, `SalesQuoteRevisionCreated`,
`SalesQuoteSent`, `SalesQuoteApprovalRequested`, `SalesQuoteAccepted`,
`SalesQuotePartiallyAccepted`, `SalesQuoteLost`,
`SalesOrderConversionRequested` e `SalesOrderConverted` conforme o catálogo.
M4 publicará `OrderCreated`. Writes críticos usarão Audit e Outbox na mesma
transação; retries de conversão serão idempotentes.
