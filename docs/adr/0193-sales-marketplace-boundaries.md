# ADR 0193 — Vendas e integração com canais de e-commerce

- Status: Accepted
- Data: 2026-11-08
- Entrega: Sprint Dupla, Trilha A, Commit 207

## Contexto e DoR

As Etapas 1, 4, 5 e 10 estabelecem M3 como owner dos adaptadores externos,
M4 como owner do pedido interno e M9 como autoridade de preço. O pacote
`sales` já implementa cotações/pedidos B2B. A evolução multicanal adiciona
contratos canônicos sem alterar as rotas, permissões e estados B2B vigentes.
O aceite deste slice exige VOs imutáveis, cálculos exatos, escopo explícito,
RBAC e testes puros. APIs externas, persistência e ingestão efetiva pertencem
a entregas posteriores; portanto não há migration neste commit.

## Ownership e contratos

- `sales.domain.channels`: referência do canal, De/Para, itens e snapshot de
  pedido, estados externos e análise comercial de margem.
- `sales.contracts`: superfície pública imutável para integração.
- `marketplace.application.channel_connectors.ChannelConnector`: porta pura
  de busca/normalização de pedidos. Os futuros adaptadores de Mercado Livre,
  Shopee e Nuvemshop pertencem ao M3; autenticação e HTTP ficam na infraestrutura.
- M2 fornece identidade do produto; M5 continua proprietário de ATP/reserva e
  estoque; M10 governa separação/expedição; M11 governa emissão fiscal; M12
  governa fatos financeiros. Um status `PAID` do canal não baixa título interno.
- M9 resolve preços e congela `pricing_snapshot_id`/versão. A análise pura de
  margem neste slice é informativa e não autoriza preço nem exceção comercial.

Módulos consumidores importam `sales.contracts`, nunca repositórios ou ORM de
Vendas. A composição ocorre em `erp.apps`. Domínios usam somente biblioteca
padrão, sem FastAPI, Pydantic, SQLAlchemy ou I/O.

## Identidades, De/Para e imutabilidade

A chave de ingestão é `(company_id, marketplace, account_id, external_order_id)`.
IDs externos são opacos, sensíveis a maiúsculas e preservados sem normalização
destrutiva. O De/Para usa empresa, conta, canal, anúncio e variação para apontar
ao UUID do produto. Para anúncio sem variação, o adaptador deve produzir um
identificador explícito e estável, documentado em seu spike.

M3 é proprietário do cadastro e da futura persistência dos anúncios e seus
mapeamentos. O VO consumido por Vendas representa a referência congelada no
pedido; não transfere a autoridade do cadastro de canais para Vendas.

SKU desconhecido ou ambíguo bloqueia ingestão; não cria produto nem usa fuzzy
matching. Itens devem ter IDs externos distintos, mas anúncios diferentes podem
apontar ao mesmo produto. Todos os itens pertencem à empresa/conta/canal da
referência. Os snapshots usam dataclasses frozen e tuplas, com validação também
na construção direta.

## Valores, frete, desconto e margem

O slice inicial aceita BRL, `Decimal` finito e quantidades positivas com até
seis casas. Valores unitários, frete e desconto têm centavos exatos; `float`,
NaN, infinito e precisão excessiva são rejeitados.

- bruto da linha = quantidade × preço unitário, arredondado HALF_UP em centavos;
- líquido da linha = bruto − desconto da linha;
- total = soma dos líquidos − desconto do pedido + frete cobrado;
- desconto do pedido não pode consumir o frete nem ultrapassar mercadorias;
- contribuição = receita − custo dos produtos − taxas − frete efetivamente pago;
- margem = contribuição / receita, permitindo margem negativa para diagnóstico.

Frete cobrado do cliente e despesa de frete são valores distintos. Margem é
razão, não markup; receita zero não define margem. Não há conversão cambial
implícita. M9 considera custos, tributos, comissões e margem mínima antes da
publicação de preço. Exceções seguem M22, RBAC e Audit.

## Estados e ingestão idempotente futura

Estados canônicos do canal: `PENDING -> PAID -> SHIPPED`; `PENDING` e `PAID`
podem transitar para `CANCELLED`. Estados terminais não retrocedem. Cancelamento
após envio exige fluxo de devolução próprio. Status externo desconhecido falha
explicitamente no adaptador, sem associação silenciosa.

O próximo slice de ingestão deve implementar, atomicamente:

1. trigger persistido e Inbox por mensagem/empresa;
2. consulta ao canal, normalização e validação do De/Para;
3. unicidade da chave de ingestão no PostgreSQL;
4. comparação de payload/versionamento: replay devolve resultado existente;
   conteúdo diferente exige atualização versionada e não segunda criação;
5. estado persistido + Audit + Outbox na mesma transação;
6. `MarketplaceOrderApproved` v1 para criação idempotente do pedido interno.

Eventos atrasados exigem cursor monotônico, versão/timestamp e deduplicação.
Publicação em RabbitMQ ocorre após commit via Outbox. HTTP deve aplicar
Idempotency-Key, ETag/If-Match, Error Contract e proteção anti-enumeração.
Nenhum worker, evento ou endpoint de ingestão é ativado neste commit.

## RBAC e segurança

Permissões adicionadas ao registro existente, sempre combinadas com empresa:

| Código | Risco | Escopo |
| --- | --- | --- |
| `sales.orders.read` | MEDIUM | leitura multicanal |
| `sales.orders.write` | HIGH | mutações multicanal |
| `sales.channels.read` | MEDIUM | contas e De/Para |
| `sales.channels.manage` | CRITICAL | gestão de canais/mapeamentos |
| `sales.channels.ingest` | CRITICAL | execução de ingestão |

Permissões singulares `sales.order.*` existentes permanecem válidas em suas
rotas; não há concessão automática nem alias entre singular/plural. O backend
usa DEFAULT DENY e `SalesAuthorization` combina permissão e empresa. O wildcard
`sales.channels.*` é apenas agrupamento documental, nunca permissão executável.
Credenciais pertencem ao secret store do adaptador, não ao snapshot nem aos logs.

## Testes, DoD e próximos passos

Os testes cobrem construção direta, imutabilidade, fronteiras de conta/empresa,
identidades externas, estados, margens negativas, arredondamento, descontos,
frete e contrato do conector. As fronteiras arquiteturais são verificadas por
AST; Ruff e Mypy devem permanecer verdes.

Próximas entregas: spike por provedor (OAuth, sandbox, payloads, rate limits,
retries e webhooks), schema/De-Para, ingestão idempotente com Audit/Outbox/Inbox,
API e validação cruzada com ATP e WMS. O DoD deste commit certifica fundação de
domínio e contratos, sem afirmar homologação com provedores reais.

## Evidência local — Commit 207

- 2.092 testes globais não-browser aprovados, incluindo PostgreSQL real;
- 262 testes focados de regras, permissões e fronteiras aprovados;
- novo domínio multicanal: 100% de linhas e branches (129 statements/40 branches);
- Mypy limpo em 889 arquivos; Ruff aprovado no repositório;
- único warning da regressão: depreciação externa Starlette/AnyIO;
- schema preservado: nenhuma migration necessária para este slice puro.
