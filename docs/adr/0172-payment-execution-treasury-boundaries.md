# ADR 0172 — Execução de Pagamentos e Tesouraria M12

- **Status:** Accepted
- **Data:** 2026-10-16
- **Decisão:** Sprint 19 / Commit 172

## Contexto

O M12 já é o System of Record de provisões, títulos e parcelas a pagar. O
próximo slice precisa selecionar obrigações elegíveis, agrupá-las em lotes,
produzir remessas bancárias e acompanhar sua execução sem confundir envio ao
banco com liquidação financeira.

Os documentos consolidados atribuem Banco, PIX e CNAB ao M12, prescrevem
rollout conservador (`dry-run → homologação → piloto de baixo valor → produção
controlada`) e exigem segregação entre criação, aprovação e transmissão. Dados
bancários são classificados como `RESTRICTED`.

## Decisão

Tesouraria é um subdomínio do bounded context M12 e permanece no pacote
canônico `erp.modules.finance` e no schema `finance`. Não será criado um segundo
owner para caixa ou pagamentos.

```text
M12 Payables (título/parcelas/matching)
        │ snapshot imutável tenant-bound
        ▼
M12 Treasury (PaymentBatch)
        │ port de remessa/execução
        ▼
Adapter bancário (CNAB 240/400 ou PIX/API)
        │ confirmação bancária explícita
        ▼
liquidação financeira
```

### Autoridade e fronteiras

Tesouraria M12 será owner de:

- `PaymentBatch` e seus itens imutáveis;
- seleção de parcelas elegíveis e prevenção de pagamento duplicado;
- ciclo de aprovação/liberação do lote;
- artefato de remessa, protocolo de transmissão e confirmação bancária;
- rastreabilidade de atores, modo de execução e snapshots bancários.

Tesouraria não altera o agregado `Payable` diretamente. Recebe snapshots puros
com `company_id`, identidade da parcela, estado aprovado, resultado do
Three-Way Match, bloqueios e atores de origem. Adapters futuros traduzirão esses
contratos nas composition roots; domínio e aplicação não importarão SDKs
bancários, layouts CNAB nem detalhes de transporte.

Conciliação bancária completa, importação de extrato, baixa por movimento,
matching bancário N:N e tratamento automático de tarifas permanecem fora deste
slice e serão implementados em sprint posterior. A confirmação de execução
usada para liquidar um lote não substitui a conciliação bancária.

## Elegibilidade de parcelas

Uma parcela só pode ingressar em um lote quando, simultaneamente:

- pertence ao mesmo `company_id` do lote;
- o título está `APPROVED` ou `SCHEDULED`;
- a parcela está `OPEN` ou `SCHEDULED`, nunca paga;
- o gate de Three-Way Match está `MATCHED` ou possui override aprovado;
- existe referência imutável à sessão de matching;
- não há bloqueio fiscal, físico ou de governança pendente;
- a parcela não pertence a outro lote ativo;
- valor, moeda e dados bancários do favorecido são válidos.

O lote aceita uma única moeda, não duplica parcelas e congela o favorecido, o
valor e os atores que criaram/aprovaram o título.

## Dry-run, remessa e liquidação

- `DRY_RUN` valida elegibilidade, SoD e geração do artefato sem transmitir nem
  liquidar;
- `HOMOLOGATION` usa o endpoint/convênio de homologação do adapter;
- `PRODUCTION` somente será liberado após os gates operacionais do rollout;
- layouts `CNAB_240`, `CNAB_400` e `PIX_API` são capacidades de adapters, não
  regras codificadas no agregado;
- sucesso de geração ou transmissão não significa pagamento;
- o lote só poderá chegar a `CONFIRMED` e gerar liquidação após confirmação
  inequívoca do banco, correlacionada por idempotency key/protocolo;
- timeout ou resposta ambígua jamais autoriza reenvio cego: primeiro consulta-se
  o status no banco.

## RBAC

| Permissão | Risco | Operação |
| --- | --- | --- |
| `finance.treasury.read` | HIGH | consultar lotes, itens e status bancário |
| `finance.treasury_batch.create` | CRITICAL | selecionar parcelas e criar lote |
| `finance.treasury_batch.approve` | CRITICAL | aprovar lote após validação SoD |
| `finance.treasury_batch.execute` | CRITICAL | liberar lote aprovado ao adapter bancário |

Os três códigos de lote normalizam o vocabulário solicitado
`finance.treasury.batch.*` para o contrato corporativo obrigatório de três
segmentos `<domain>.<resource>.<action>`. Todas as permissões exigem escopo
explícito de `company_id`. RBAC nunca elimina
os gates de elegibilidade, alçada, autenticação reforçada ou SoD.

## Segregação de funções

A política é fail-closed e usa `SOD_VIOLATION`:

- o criador do lote não pode aprovar nem executar o mesmo lote;
- quem criou qualquer título contido no lote não pode aprovar nem executar;
- quem aprovou qualquer título contido no lote não pode aprovar nem executar;
- por padrão, quem aprova o lote não pode executá-lo;
- dividir lotes ou permissões não contorna essas regras: o conflito é avaliado
  sobre todos os itens congelados.

## Contratos e segurança

Os value objects são dataclasses imutáveis, sem ORM, FastAPI, Pydantic,
mensageria ou SDK bancário. Identificadores são UUIDs tenant-bound, valores usam
`Decimal` com duas casas e os dados bancários do favorecido são snapshots
`RESTRICTED`; logs e eventos deverão mascará-los.

Persistência, APIs, portas CNAB/PIX, Audit/Outbox e confirmação bancária serão
introduzidos em commits posteriores. Este commit estabelece apenas a decisão,
RBAC, contratos e regras puras que esses adapters deverão respeitar.

## Consequências

A seleção de pagamento torna-se determinística e testável antes de qualquer
efeito bancário. Há custo de snapshots e checagens repetidas, mas isso impede
drift, autoaprovação, dupla inclusão de parcelas e liquidação baseada apenas em
um envio sem confirmação.
