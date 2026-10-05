# ADR 0144 — Fundação e fronteiras do M11 Fiscal

- **Status:** Accepted
- **Data:** 2026-10-04
- **Decisão:** Sprint 15 / Commit 144

## Contexto

O M11 inicia a fundação de emissão fiscal depois da estabilização do fluxo físico
M6/M17/M5. Documentos eletrônicos possuem identidade jurídica, numeração,
conteúdo tributário e intercâmbios externos que não podem ser tratados como
extensão do pedido de compra nem como título financeiro.

## Decisão

O pacote canônico é `erp.modules.fiscal`, dividido em `domain`, `application`,
`infrastructure` e `api`. Neste commit somente domínio puro, contratos públicos
e autorização são criados. Persistência, SEFAZ e HTTP virão em commits próprios.

### Autoridade do M11

M11 é o único System of Record de:

- intenções e documentos NF-e (modelo 55) e NFC-e (modelo 65);
- chave de acesso, protocolo, XML autorizado, cancelamento e CC-e;
- séries, sequências, inutilizações e intercâmbios com SEFAZ;
- regras aplicadas e snapshots tributários de ICMS, PIS, COFINS e IPI.

Após autorização, identidade, itens, valores e snapshot tributário são
imutáveis. Ajustes legais acontecem somente por cancelamento, correção, retorno
ou documento complementar rastreável.

### Isolamento multi-tenant

Todo agregado, comando, contrato e evento fiscal carrega `company_id`. Futuras
tabelas do schema `fiscal` usarão chaves e filtros tenant-bound. Uma chave de
acesso jamais autoriza acesso cross-company.

### Fronteira M6 → M11

M6 continua owner de fornecedor, pedido e recebimento físico. Ele poderá enviar
ao M11 apenas contratos públicos imutáveis com IDs e snapshots necessários à
emissão/entrada. M11 não importa ORM, repository, service ou API de Procurement
e não altera estado físico do recebimento.

### Fronteira M11 → M12

M12 continuará owner exclusivo de contas a pagar/receber, parcelas,
liquidação e conciliação. M11 publicará fatos fiscais versionados; não criará
títulos financeiros nem gravará o schema `finance`. Contas a Pagar,
`PayableRequested` e three-way match estão explicitamente fora deste slice.

### Integração e resiliência SEFAZ

- provider é uma porta do M11 implementada por adapter externo;
- submissões são idempotentes por intenção/documento/tentativa;
- timeout é estado desconhecido, nunca autorização presumida;
- consulta de protocolo precede qualquer retransmissão ambígua;
- retry usa backoff, limite de tentativas e circuit breaker;
- cada request/response é correlacionado e auditável, sem expor certificado;
- mudanças e eventos são gravados com Audit e Outbox na mesma transação;
- consumers assíncronos deduplicam por Inbox (`consumer_name + event_id`).

## Contratos públicos

`erp.modules.fiscal.contracts` contém DTOs puros e imutáveis. M6 e M12 poderão
consumi-los sem importar domínio interno, API ou infraestrutura fiscal. A
composition root em `erp.apps` fará a conexão entre owners.

## RBAC

| Permissão | Risco | Operação |
| --- | --- | --- |
| `fiscal.nfe.read` | HIGH | consultar documento, protocolo e snapshot |
| `fiscal.nfe.issue` | CRITICAL | emitir/transmitir NF-e ou NFC-e |
| `fiscal.nfe.cancel` | CRITICAL | solicitar/registrar cancelamento |
| `fiscal.nfe.correct` | CRITICAL | registrar carta de correção |

Todas as permissões exigem escopo de empresa. RBAC não substitui futuras
alçadas, step-up authentication ou regras de segregação de funções.

## Enforcement

`tests/unit/test_architecture_boundaries.py` impede o M11 de importar internals
de M6, M12 ou qualquer outro bounded context. Testes em
`tests/unit/modules/fiscal` asseguram domínio sem framework, contratos
imutáveis, chave de 44 dígitos, snapshots tributários e matriz RBAC.

## Consequências

O primeiro slice não emite documento e não cria obrigação financeira. Ele cria
uma linguagem fiscal estável e uma fronteira que permite evoluir provider,
persistência e APIs sem dual write nem acoplamento aos módulos adjacentes.
