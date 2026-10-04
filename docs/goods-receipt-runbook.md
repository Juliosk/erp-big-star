# M6 Goods Receipt — Runbook operacional

## Escopo e fronteiras

Este slice cobre somente o recebimento físico iniciado por um Pedido de Compra emitido. O M6 mantém o agregado `GoodsReceipt`; o M17 fornece a decisão de inspeção por contrato público; o M5 recebe lançamentos físicos no ledger imutável. Documento fiscal, faturamento, contas a pagar e *three-way match* permanecem fora da Sprint 14.

O adaptador de composição `PostgresGoodsReceiptOperations` é o dono da transação entre M6, idempotência, ledger e saldo M5. O domínio de Procurement não importa infraestrutura de M17 ou M5.

## Jornada operacional

1. Selecione um Pedido de Compra em `ISSUED` ou `PARTIALLY_RECEIVED`.
2. Faça a conferência cega informando galpão, quantidade efetivamente contada, lote opcional e divergência de especificação.
3. Confirme a chegada física: `DRAFT → RECEIVED`.
4. Registre o laudo M17: `RECEIVED → INSPECTED`.
5. Confirme o posting: `INSPECTED → POSTED`.

Quantidades aprovadas são encaminhadas a `AVAILABLE`; quantidades retidas são encaminhadas a `QUARANTINE`. Rejeições não geram entrada disponível. A tolerância definida no recebimento impede *over-receipt* acima da margem aceita pelo pedido.

## Endpoints e concorrência

| Operação | Endpoint | Controle |
|---|---|---|
| Criar conferência | `POST /api/v1/procurement/goods-receipts` | `Idempotency-Key` |
| Listar | `GET /api/v1/procurement/goods-receipts` | filtros e tenant |
| Detalhar | `GET /api/v1/procurement/goods-receipts/{id}` | ETag |
| Confirmar chegada | `POST .../{id}/receive` | `Idempotency-Key` + `If-Match` |
| Inspecionar | `POST .../{id}/inspect` | `Idempotency-Key` + `If-Match` |
| Postar no M5 | `POST .../{id}/post-to-inventory` | `Idempotency-Key` + `If-Match` |

O `If-Match` deve conter uma versão positiva entre aspas, por exemplo `"3"`. Replay com a mesma chave e o mesmo payload retorna o resultado original. Reuso da chave com payload diferente é rejeitado. Toda consulta e mutação é vinculada ao `company_id` do contexto.

## Matriz de eventos M6 / M17 / M5

| Evento | Momento | Dados essenciais | Consumidores esperados |
|---|---|---|---|
| `GoodsReceiptCreated` | rascunho persistido | receipt, PO, fornecedor, galpão | operação de doca |
| `GoodsReceiptReceived` | chegada confirmada | status, itens, versão | qualidade M17 |
| `GoodsReceiptInspected` | laudo aplicado | status, contagem de laudos | operação e estoque M5 |
| `GoodsReceiptPosted` | ledger e saldo confirmados | transações M5, galpão, versão | projeções e rastreabilidade |

Os eventos são gravados na Outbox na mesma transação da mudança do agregado. O consumidor de referência `procurement.goods-receipt-lifecycle.v1` valida o envelope e reserva o `message_id` na Inbox; reentregas são ACKs sem reaplicar efeito.

## Permissões

| Permissão | Uso |
|---|---|
| `procurement.receipt.read` | listar e detalhar recebimentos |
| `procurement.receipt.manage` | criar, receber, inspecionar e postar |
| `procurement.order.read` | selecionar o pedido de origem |

## Divergências e resposta operacional

- `VERSION_CONFLICT`: recarregue o recebimento e repita a ação com o novo ETag.
- `IDEMPOTENCY_CONFLICT`: não altere o payload de uma chave já usada; gere uma nova chave para uma nova intenção.
- `BUSINESS_VALIDATION_ERROR`: confira quantidade, tolerância do pedido, estado atual e soma das disposições M17.
- `RESOURCE_NOT_FOUND`: confirme empresa de trabalho, pedido, recebimento, galpão e lote.
- Quantidade ou especificação divergente: registre a observação antes de confirmar a chegada; encaminhe a parcela não liberada a `QUARANTINE` ou `REJECT` no laudo.

Nunca corrija saldo diretamente no banco. Se o posting falhar, a transação reverte agregado, ledger, saldo, idempotência e Outbox em conjunto; investigue pelo `correlation_id` e repita com a mesma chave quando o erro transitório estiver resolvido.

## Verificação técnica

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_procurement_goods_receipt_api.py tests\integration\test_procurement_goods_receipt_browser.py -q
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
```

Evidências visuais do cenário automatizado são geradas em `test-results/goods-receipt-cockpit.png`.
