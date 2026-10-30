# ADR 0181 — Fluxo de Caixa e Projeções de Liquidez M12

- **Status:** Accepted
- **Data:** 2026-10-30
- **Decisão:** Sprint 21 / Commit 187

## Contexto

O M12 já possui títulos a pagar, execução de pagamentos, confirmação bancária,
extratos e conciliação. O backlog consolidado posiciona `Cash Flow` depois de
`Bank Statement` e `Reconciliation` e prevê `finance.cash_flow_projection` como
projeção financeira, não como razão contábil nem substituto de recebíveis.

O M13 ainda não fornece a autoridade completa de Contas a Receber. Inferir
entradas a partir de pedidos, faturamento ou documentos fiscais criaria caixa
hipotético e poderia esconder rupturas de liquidez. Ao mesmo tempo, cenários de
sensibilidade são necessários, desde que nunca sejam confundidos com posição
operacional disponível.

## Decisão

O Cash Flow permanece no bounded context M12, em
`erp.modules.finance.domain.cash_flow`, com domínio puro e tenant-bound. O
Commit 187 entrega Value Objects e a política determinística; persistência,
consumers, API e UI serão slices posteriores.

```text
posição bancária conciliada ───────────────┐
parcelas a pagar aprovadas ────────────────┼─► projeção operacional
parcelas a receber M13 autorizadas ────────┘          │
lacuna M13 ─► source gap explícito                     ├─► estado de liquidez
cenário manual ────────────────────────────► sensibilidade isolada
```

### Autoridade e fronteiras

O M12 é owner de:

- posição inicial por empresa, conta, moeda e data-base;
- horizontes, categorias, cenários e snapshots de projeção;
- agregação de fatos bancários e compromissos financeiros recebidos por
  contratos públicos;
- avaliação explicável do estado de liquidez.

O M12 não lê tabelas privadas de M6, M11, M13 ou M22, não escreve no razão
contábil e não transforma faturamento em disponibilidade. Integrações chegam
por contratos puros e eventos Inbox/Outbox. Ausência de fonte autoritativa é
`CashFlowSourceGap`, nunca valor estimado silencioso.

## Modelo temporal e monetário

Todo montante usa `Decimal`, duas casas decimais e moeda ISO 4217 explícita.
Conversão cambial não ocorre implicitamente; moedas diferentes exigirão uma
política futura com taxa, fonte e instante auditáveis.

Horizontes civis inclusivos são classificados pela distância entre datas:

- curto prazo: até 90 dias;
- médio prazo: de 91 a 365 dias;
- longo prazo: acima de 365 dias.

Categorias oficiais são `OPERATING`, `FINANCING` e `INVESTING`. Ocorrências são
`REALIZED`, `COMMITTED` ou `SCENARIO`. A projeção operacional soma apenas fatos
realizados e compromissos autorizados. Cenários manuais produzem um saldo de
sensibilidade separado e não alteram o caixa disponível nem o gate de liquidez.

## Proibição de faturamento hipotético

`FISCAL_BILLING` é reconhecido apenas para rejeição explícita. Documento fiscal,
pedido ou previsão comercial não é título a receber. Uma entrada comprometida
somente pode usar `RECEIVABLE_INSTALLMENT` quando o futuro M13 fornecer snapshot
autoritativo. Enquanto isso, a projeção registra `RECEIVABLES` como fonte
incompleta e retorna estado `INCOMPLETE`.

## Estados de liquidez

- `HEALTHY`: saldo operacional igual ou superior à reserva mínima;
- `ATTENTION`: saldo não negativo, porém abaixo da reserva;
- `CRITICAL`: saldo operacional negativo;
- `INCOMPLETE`: uma fonte obrigatória não cobre o horizonte solicitado.

`INCOMPLETE` tem precedência, pois um saldo numericamente positivo não é
confiável quando uma autoridade está ausente.

## RBAC e isolamento

| Permissão | Uso | Risco |
| --- | --- | --- |
| `finance.cash_flow.read` | consultar posição e projeções | HIGH |
| `finance.cash_flow.project` | gerar ou recompor projeção autoritativa | CRITICAL |
| `finance.cash_flow.scenario` | criar/comparar cenários não autoritativos | CRITICAL |

Todas as operações exigem `company_id` autorizado. Itens e lacunas de outra
empresa falham fechados; consultas futuras usarão proteção anti-enumeração.
Snapshots e cenários serão classificados como `RESTRICTED`.

## Concorrência, auditoria e evolução

O futuro agregado `CashFlowProjection` terá versão otimista, cenário versionado,
snapshot imutável e chave idempotente. Recomputação, publicação Outbox e Audit
serão atômicos. Eventos fora de ordem usarão cursores monotônicos por tenant e
fonte. Transferências entre contas da mesma empresa deverão ser eliminadas na
visão consolidada para impedir dupla contagem.

## Consequências

A separação entre dinheiro, horizonte, evidência e política mantém as regras
testáveis sem ORM, FastAPI ou broker. Lacunas ficam visíveis e cenários continuam
úteis sem elevar expectativa comercial a caixa. O custo é exigir contratos
autoritativos e snapshots adicionais antes de oferecer uma projeção completa.
