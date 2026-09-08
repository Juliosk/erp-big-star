# M2 — Product Master

Owner do produto/SKU, barcode e master data de produto. Slice 030–039: Product por empresa,
tipos/lifecycle oficiais, barcodes e comandos atômicos limitados ao tenant. Ver
[plano e gates da Sprint 3](../../../docs/sprint-3-product-master.md).

`domain` é Python puro. `infrastructure` é interno ao owner e só devolve agregados, nunca ORM.
`application` define portas e serviços; consumidores externos não usam repositórios M2.
Dependências: infraestrutura de banco e referência Foundation FK `admin.company`, sem cascade.
Não há acesso direto ao domínio/persistência M1; composição registra metadados de ambos os owners.

Tabelas: `product.product` (0010) e `product.product_barcode` (0011). Cada repositório exige `company_id`
previamente autorizado; UUID recebido do cliente não é autorização. Nenhuma consulta global.
SKU único no catálogo, code único por empresa. Aplicabilidade global não habilitada neste lote.

APIs oficiais `/api/v1/products`, Audit/Outbox, idempotência e If-Match compõem todos os comandos.
Barcode único por empresa; manutenção com update. Homologação/ativação exigem activate e
descontinuação exige discontinue. Fluxo estritamente progressivo, sem reversões.
UI em `/ui/`, sem acesso a tabelas; identidade de desenvolvimento é adaptador de M1 opt-in.

Operação: `python -m alembic upgrade head`, depois
`python -m pytest --cov=erp --cov-report=term-missing`. Runbook detalhado e pendências no plano.
