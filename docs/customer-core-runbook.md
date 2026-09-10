# Runbook operacional — M14 Customer Core

Este runbook cobre o slice vertical de clientes da Sprint 5: cadastro mestre,
grupos/segmentação, Customer 360, duplicidades e solicitação de mesclagem.

## Escopo implementado

- `GET /api/v1/customers`: consulta paginada por empresa, status e tipo.
- `POST /api/v1/customers`: criação idempotente por CPF/CNPJ dentro da empresa.
- `PATCH /api/v1/customers/{id}`: atualização concorrente com `If-Match`/ETag.
- `GET /api/v1/customers/{id}/360`: visão consolidada do cliente.
- `GET/POST /api/v1/customer-groups`: gestão de grupos por empresa.
- `POST /api/v1/customers/{id}/groups`: vínculo auditável cliente/grupo.
- `POST /api/v1/customers/{id}/duplicates/detect`: detecção por CPF/CNPJ e similaridade.
- `POST /api/v1/customers/{id}/merge-requests`: solicitação rastreável de mesclagem.

## Permissões

| Permissão | Uso |
| --- | --- |
| `crm.customer.read` | Listas, detalhes, Customer 360 e detecção de duplicidade |
| `crm.customer.create` | Criação de cliente |
| `crm.customer.update` | Alteração de dados mestre, status e grupos |
| `crm.customer.merge` | Abertura de solicitação de mesclagem |

Toda operação exige escopo `COMPANY` compatível com o `company_id`. Falhas de
escopo retornam o contrato de erro padronizado (`SCOPE_FORBIDDEN` ou
`RESOURCE_NOT_FOUND`, conforme o caso), sem revelar dados de outra empresa.

## Customer 360

O endpoint `GET /api/v1/customers/{id}/360?company_id=...` consolida apenas
dados do bounded context M14:

- cadastro mestre e versão atual;
- contatos e endereços do cliente;
- grupos ativos/inativos já vinculados;
- candidatos de duplicidade registrados;
- solicitações pendentes de mesclagem envolvendo o cliente.

Não há tabela nova para o 360 neste slice. O read model é montado em tempo de
consulta sobre tabelas M14 já migradas, sempre com predicado explícito de
`company_id`.

## Concorrência e ETag

Atualizações de cliente exigem `If-Match: "<versão>"`. Se outra transação
alterar o mesmo cliente antes da gravação, a API retorna `VERSION_CONFLICT`.
Após sucesso, a resposta devolve o novo ETag.

## Interface Web local/test

A UI está disponível em `/ui/` e usa o mesmo token Bearer das APIs oficiais. Em
ambiente `local` ou `test`, o `DevSecurityContextResolver` pode ser habilitado
com:

- `DEV_AUTH_ENABLED=true`
- `DEV_AUTH_TOKEN=<token ASCII de 32 a 256 caracteres>`
- `DEV_AUTH_ACTOR_ID=<UUID do ator>`
- `DEV_AUTH_COMPANY_IDS=<UUIDs autorizados>`

O shell não grava token em `localStorage` ou `sessionStorage`; recarregar/sair
remove o contexto da página.

## Validação operacional

Checklist recomendado antes de homologar o M14:

1. Aplicar migrations até a head atual.
2. Executar testes dedicados do módulo Customer.
3. Executar `ruff check` e `mypy`.
4. Rodar o E2E browser `tests/integration/test_customer_browser.py` com
   Chromium real.
5. Conferir screenshots gerados em `test-results/customer-360-desktop.png` e
   `test-results/customer-360-mobile.png`.

## Limites conhecidos

- A Sprint 5 abre solicitações de mesclagem, mas não executa a consolidação
  fiscal definitiva. O evento `MergeApprovalRequested` prepara a decisão pelo
  fluxo de governança.
- Contatos e endereços já compõem o Customer 360; criação/edição desses filhos
  por UI fica para os próximos slices funcionais.
