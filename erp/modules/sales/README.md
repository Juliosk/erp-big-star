# Vendas — contratos B2B e multicanal

O pacote preserva os agregados B2B `SalesQuote` e `SalesOrder` e acrescenta os
VOs canônicos multicanal definidos no [ADR 0193](../../../docs/adr/0193-sales-marketplace-boundaries.md).

- `domain/channels.py`: referências por empresa/conta/canal, De/Para de SKU,
  itens, snapshots, transições externas e análise de margem com `Decimal`.
- `contracts.py`: interface pública imutável para o M3.
- `application/permissions.py`: permissões e autorização combinada com empresa.
- M3 mantém a porta `ChannelConnector` em `marketplace/application`; futuros
  adaptadores HTTP e credenciais pertencem à infraestrutura daquele módulo.

`sales.order.*` continua protegendo as APIs B2B. `sales.orders.read/write` e
`sales.channels.read/manage/ingest` são permissões explícitas para a evolução
multicanal, sem concessão implícita entre os dois grupos.

O Commit 207 não requer migration nem ativa endpoints de canal. Persistência,
unicidade da chave de ingestão, Audit/Outbox/Inbox e conectores homologados
serão entregues nos slices seguintes. M9 permanece autoridade de preço; a
margem calculada aqui é diagnóstica.

Validação do domínio:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/unit/modules/sales/domain/test_sales_rules.py --cov=erp.modules.sales.domain.channels --cov-branch --cov-fail-under=100 -q
```
