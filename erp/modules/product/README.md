# M2 — Product Master

Owner do produto/SKU, barcode e master data de produto. Lote 030–032: Product por empresa,
tipos/lifecycle oficiais, persistência e consultas limitadas ao tenant. Ver
[plano e gates da Sprint 3](../../../docs/sprint-3-product-master.md).

`domain` é Python puro. `infrastructure` é interno ao owner e só devolve agregados, nunca ORM.
O futuro `application` define contratos públicos; consumidores externos não usam repositórios M2.
Dependências: infraestrutura de banco e referência Foundation FK `admin.company`, sem cascade.
Não há acesso direto ao domínio/persistência M1; composição registra metadados de ambos os owners.

Tabela: `product.product`, migration 0010. Cada instância de repositório exige `company_id`
previamente autorizado; UUID recebido do cliente não é autorização. Nenhuma consulta global.
SKU único no catálogo, code único por empresa. Aplicabilidade global não habilitada neste lote.

Não há APIs/eventos públicos neste lote: 033–037 comporão permissões oficiais M2, Audit,
Idempotency, Outbox e If-Match antes de habilitar comandos. API product ausente é esperado.

Operação: `python -m alembic upgrade head`, depois
`python -m pytest --cov=erp --cov-report=term-missing`. Runbook detalhado e pendências no plano.
