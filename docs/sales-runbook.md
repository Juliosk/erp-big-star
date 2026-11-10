# Runbook operacional — Vendas B2B, Marketplaces e Fulfillment

Este runbook cobre cotações B2B, pedidos, ingestão idempotente de Mercado Livre,
Shopee e Nuvemshop, De/Para de SKUs, reserva física e integração de fulfillment.
O cockpit multicanal oficial está em `/ui/sales/cockpit`.

## Limites e responsabilidade

O M15 é dono da proposta comercial e de suas revisões imutáveis. O agregado
multicanal preserva a identidade externa `(marketplace, account_id,
external_order_id)` e só é persistido depois da resolução tenant-bound do SKU.
O M5 é dono da reserva e do ledger; o WMS é dono da execução física; Sales
mantém a fotografia comercial e publica pedidos de sincronização do canal.

Todos os registros, consultas, locks e restrições de unicidade incluem
`company_id`. A UI usa apenas APIs oficiais e nunca persiste token ou contexto
em `localStorage` ou `sessionStorage`.

## Permissões

| Permissão | Uso |
| --- | --- |
| `sales.quote.create` | criar cotação |
| `sales.quote.read` | listar e detalhar cotações |
| `sales.quote.update` | revisar, aceitar ou marcar perdida |
| `sales.quote.send` | enviar cotação |
| `sales.discount.request` | abrir alçada M22 para desconto |
| `sales.quote.convert` | autorizar conversão da cotação |
| `sales.order.create` | criar pedido pela conversão |
| `sales.order.read` | listar e detalhar pedidos |
| `sales.orders.read` | consultar pedidos canônicos multicanal e o cockpit |
| `sales.orders.write` | alterar pedidos canônicos multicanal |
| `sales.channels.read` | consultar contas de canal e De/Para |
| `sales.channels.manage` | manter OAuth e mapeamentos de SKU |
| `sales.channels.ingest` | receber webhooks/payloads externos |

A solicitação de desconto também exige `workflow.request.create`. Consultar ou
decidir a solicitação continua exigindo as permissões próprias do M22.

## Fluxo operacional

1. Crie uma cotação informando número e cliente da empresa selecionada.
2. Inclua uma revisão com produto, quantidade, preço e desconto.
3. Para exceção de desconto, solicite aprovação; deve existir definição M22
   ativa para `SALES / QUOTE_DISCOUNT`.
4. Envie e registre aceitação total ou parcial.
5. Informe o número do pedido e converta a cotação aceita.
6. Consulte o pedido criado na seção **Pedidos gerados**.

Revisões e mutações exigem `If-Match: "N"`. A conversão também exige
`Idempotency-Key`. Repetir a mesma chave e payload devolve o mesmo pedido sem
duplicar Audit, Outbox ou itens. Payload diferente com a mesma chave retorna
`IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`.

## Endpoints

| Operação | Contrato |
| --- | --- |
| Criar/listar cotação | `POST/GET /api/v1/sales/quotes` |
| Detalhar cotação | `GET /api/v1/sales/quotes/{id}` |
| Criar revisão | `POST /api/v1/sales/quotes/{id}/revisions` |
| Enviar/aceitar/perder | `POST /api/v1/sales/quotes/{id}/{ação}` |
| Solicitar desconto | `POST /api/v1/sales/quotes/{id}/discount-approval` |
| Converter em pedido | `POST /api/v1/sales/quotes/{id}/convert-to-order` |
| Listar pedidos | `GET /api/v1/sales/orders` |
| Detalhar pedido | `GET /api/v1/sales/orders/{id}` |
| Cockpit multicanal | `GET /api/v1/sales/cockpit?company_id={id}` |

## Ingestão multicanal e De/Para

1. O adapter do canal normaliza OAuth, taxas, itens, frete e descontos.
2. A identidade externa é protegida por unicidade tenant-bound e hash SHA-256
   do payload normalizado; replay idêntico devolve o resultado anterior.
3. Cada anúncio/variação precisa de De/Para ativo para um produto M2 da mesma
   empresa. SKU ausente retorna `SALES_CHANNEL_SKU_NOT_MAPPED` e toda a
   transação é revertida.
4. O pedido pago solicita reserva `HARD` no M5. Falta de ATP reverte pedido,
   reserva, Audit e Outbox.
5. Depois da separação, o fulfillment cria etiqueta/rastreio e publica
   `MarketplaceFulfillmentSyncRequested`; o worker atualiza o canal externo.

O cockpit mostra pedidos por canal e a situação de conciliação. A margem é
calculada sobre o custo padrão provisório vigente no M9. Se algum produto não
tiver custo, a interface mostra **Custo M9 pendente** em vez de estimar margem.

## Operação do cockpit multicanal

1. Acesse `/ui/sales/cockpit`, informe o Bearer token e selecione a empresa.
2. Compare volume, valor, estados e margem entre os três canais na esteira.
3. Use a fila para localizar sync pendente, custo ausente ou expedição sem
   rastreio.
4. Troque de empresa somente pelo seletor; a API reaplica RBAC e escopo em
   cada consulta. O token não é salvo no navegador.

## Consistência e eventos

A conversão bloqueia a cotação com `SELECT FOR UPDATE`. Pedido, itens,
cotação `CONVERTED`, Audit, evento `SalesOrderCreatedFromQuote` e conclusão da
idempotência compartilham a mesma transação PostgreSQL. Cada item preserva o
`quote_revision_item_id` e o `pricing_snapshot_id` da decisão comercial.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib
```

O E2E Chromium gera:

- `test-results/sales-cockpit-desktop.png`
- `test-results/sales-cockpit-mobile.png`
- `test-results/sales-marketplace-cockpit-desktop.png`
- `test-results/sales-marketplace-cockpit-mobile.png`

## Troubleshooting

- `VERSION_CONFLICT`: releia a cotação e repita com o ETag atual.
- `PRECONDITION_REQUIRED`: envie `If-Match` nas mutações.
- `SALES_ORDER_CONFLICT`: confira número e conversão anterior da cotação.
- `RESOURCE_NOT_FOUND`: confira empresa selecionada e escopo da identidade.
- Falha ao solicitar desconto: confirme a definição M22 `QUOTE_DISCOUNT`.
- `SALES_CHANNEL_SKU_NOT_MAPPED`: cadastre/ative o De/Para na mesma conta e
  empresa do webhook.
- **Sync pendente**: verifique Outbox, adapter OAuth e fila de retry/DLQ antes
  de reenviar manualmente.
- **Custo M9 pendente**: cadastre o custo padrão; não preencha margem por
  aproximação operacional.
- Em falha do Docker, preserve volumes e VHDX. Não use factory reset ou prune
  com volumes.

## Critérios de aceite da Sprint 11

- Cotação e pedido isolados por empresa.
- Revisões e snapshots comerciais preservados.
- Lifecycle protegido por ETag e concorrência otimista.
- Conversão atômica e idempotente.
- Audit/Outbox no mesmo transaction boundary.
- Cockpit responsivo validado no Chromium real.
- Ruff, Mypy, fronteiras arquiteturais e suíte global verdes.
