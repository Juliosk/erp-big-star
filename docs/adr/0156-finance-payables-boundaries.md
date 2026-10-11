# ADR 0156 — Fronteiras do M12 Contas a Pagar

- **Status:** Accepted
- **Data:** 2026-10-11
- **Decisão:** Sprint 17 / Commit 156

## Contexto

O M12 inicia a fundação de Contas a Pagar depois que M6 estabilizou compras e
recebimento físico e M11 passou a publicar fatos fiscais autorizados e o
resultado da conciliação físico-fiscal. Provisões e títulos financeiros precisam
preservar a origem jurídica e operacional sem transformar Financeiro em owner de
pedido, recebimento ou documento fiscal.

Liquidação bancária, lotes de pagamento e conciliação bancária permanecem fora
deste slice. O M12 também não recalcula o three-way match: ele consome o gate de
conciliação publicado pelo owner competente.

## Decisão

O pacote canônico é `erp.modules.finance`, organizado em quatro camadas:

```text
finance/
├── domain/          # títulos, parcelas, provisões, invariantes e SoD puros
├── application/     # casos de uso, ports e autorização
├── infrastructure/  # persistência e adapters exclusivos do M12
└── api/             # contratos HTTP do M12
```

O primeiro commit contém apenas fronteiras, contratos puros, autorização e a
política de segregação. Persistência e HTTP serão introduzidos em slices
posteriores.

### Autoridade do M12

O M12 será o único System of Record de:

- provisões financeiras de contas a pagar;
- títulos, parcelas, vencimentos e respectivos estados;
- ajustes financeiros rastreáveis e aprovações de exceção;
- bloqueios financeiros derivados de divergências publicadas por outros owners;
- snapshots imutáveis das referências que justificaram a obrigação.

Neste slice M12 não é autoridade de caixa, bancos, remessas, retorno bancário,
liquidação ou conciliação bancária.

### Vínculo imutável com M11

M11 continua owner exclusivo do documento fiscal, chave de acesso, protocolo,
status de autorização e snapshot tributário. M12 registra somente uma referência
imutável ao fato autorizado, incluindo IDs, chave, protocolo, fornecedor e valor
necessários à rastreabilidade.

M12 não:

- altera, autoriza, cancela ou corrige documentos fiscais;
- grava tabelas do schema `fiscal`;
- importa domínio interno, ORM, repository, service ou API do M11;
- presume autorização a partir da mera existência de um XML.

### Vínculo imutável com M6

M6 continua owner de fornecedor, pedido de compra e recebimento físico. M12
preserva uma referência imutável ao pedido aprovado, com versão e valor que
fundamentaram a provisão.

M12 não:

- altera pedido, recebimento ou inspeção;
- grava tabelas do schema `procurement`;
- importa domínio interno, ORM, repository, service ou API do M6;
- refaz conciliação física, fiscal ou tributária.

### Contratos de integração

`erp.modules.finance.contracts` contém DTOs puros, imutáveis e tenant-bound que
formam a camada anticorrupção de entrada do M12. Eventos versionados de M11 e M6
são traduzidos para esses contratos por adapters na composition root
`erp.apps`; o domínio financeiro nunca conhece envelopes de mensageria ou tipos
internos dos produtores.

Todo comando e fato contém `company_id`. Referências com tenants divergentes
falham antes de alcançar persistência. O processamento futuro será idempotente
por Inbox e as mutações financeiras publicarão Audit e Outbox na mesma
transação.

## RBAC

| Permissão | Risco | Operação |
| --- | --- | --- |
| `finance.payable.read` | HIGH | consultar provisões, títulos e parcelas |
| `finance.payable.create` | HIGH | criar provisão ou título a partir de origem válida |
| `finance.payable.approve` | CRITICAL | aprovar provisões sujeitas a alçada |
| `finance.payable.adjust` | CRITICAL | ajustar valor, vencimento ou bloqueio com trilha |

Todas as permissões exigem escopo explícito de `company_id`. RBAC autoriza a
operação, mas não substitui alçada, autenticação reforçada nem SoD.

## Segregação de funções

- o limite que caracteriza alto valor é uma política configurável, nunca uma
  constante escondida no agregado;
- quando `amount >= high_value_threshold`, o ator que criou a provisão não pode
  aprová-la;
- a violação é fail-closed e usa o código estável `SOD_VIOLATION`;
- concessão de `finance.payable.approve` não permite autoaprovação;
- a decisão futura deverá registrar criador, aprovador, valor, limite aplicado e
  snapshots anterior/posterior na auditoria.

## Enforcement

- `tests/unit/test_architecture_boundaries.py` impede imports internos entre
  Finance, Fiscal e Procurement;
- `tests/unit/modules/finance/test_boundaries.py` protege também a superfície de
  contratos, que fica fora das pastas `domain` e `application`;
- testes puros validam imutabilidade, tenant, referências fiscais/operacionais,
  matriz RBAC e SoD sem FastAPI, SQLAlchemy, Celery ou banco de dados.

## Consequências

O fluxo permanece explícito e reprocessável:

```text
M6 pedido/recebimento ─┐
                       ├─ eventos versionados → adapter → M12 provisão/título
M11 autorização/gate ──┘
```

Há custo de tradução entre contratos, mas owner, isolamento de tenant,
idempotência e auditabilidade permanecem verificáveis sem dual write.
