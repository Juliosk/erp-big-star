# Vendas — contratos B2B e multicanal

O pacote preserva os agregados B2B `SalesQuote` e `SalesOrder` e acrescenta os
VOs canônicos multicanal definidos no [ADR 0193](../../../docs/adr/0193-sales-marketplace-boundaries.md).

- `domain/channels.py`: referências por empresa/conta/canal, De/Para de SKU,
  itens, snapshots, transições externas e análise de margem com `Decimal`.
- `contracts.py`: interface pública imutável para o M3.
- `application/permissions.py`: permissões e autorização combinada com empresa.
- `application/multichannel_ingestion.py`: autorização, normalização por porta
  e comando idempotente de ingestão sem dependência de HTTP/ORM.
- M3 mantém a porta `ChannelConnector` em `marketplace/application`; os
  adaptadores OAuth e dialetos homologados de Mercado Livre, Shopee e
  Nuvemshop ficam em `marketplace/infrastructure`.

`sales.order.*` continua protegendo as APIs B2B. `sales.orders.read/write` e
`sales.channels.read/manage/ingest` são permissões explícitas para a evolução
multicanal, sem concessão implícita entre os dois grupos.

O Commit 211 usa a persistência tenant-bound do Commit 209 e não requer nova
migration. Pedidos pagos são normalizados, resolvidos pelo De/Para e gravados
com ID determinístico; a reserva HARD do M5, Audit e Outbox compartilham a
mesma transação PostgreSQL. Replays idênticos retornam o pedido e a reserva já
existentes; payload divergente ou SKU não mapeado falha fechado. M9 permanece
autoridade de preço; a margem calculada aqui é diagnóstica.

O Commit 213 mantém o WMS como autoridade da expedição física: somente uma
remessa `READY_TO_DISPATCH`, com ao menos um pacote `FINALIZED`, pode avançar.
O serviço de fulfillment gera a etiqueta de forma idempotente, despacha a
remessa e os pacotes no WMS, transiciona o pedido multicanal de `PAID` para
`SHIPPED` e persiste o vínculo comercial em `sales.sales_shipment`. Audit,
logs de fulfillment e o evento `MarketplaceFulfillmentSyncRequested` são
gravados na mesma transação PostgreSQL; a atualização externa do status e do
rastreio é executada pelos adaptadores de canal a partir da Outbox, sem chamada
de rede dentro da transação.

Validação do domínio:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/unit/modules/sales/domain/test_sales_rules.py --cov=erp.modules.sales.domain.channels --cov-branch --cov-fail-under=100 -q
```
