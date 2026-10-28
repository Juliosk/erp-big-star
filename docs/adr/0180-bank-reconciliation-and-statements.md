# ADR 0180 — Conciliação bancária automática e extratos M12

- **Status:** Accepted
- **Data:** 2026-10-28
- **Decisão:** Sprint 20 / Commit 180

## Contexto

O M12 já controla títulos, parcelas, lotes de pagamento, confirmação bancária e
liquidação. A confirmação de um lote prova que o banco aceitou ou efetivou uma
instrução, mas não substitui o extrato oficial nem certifica que a posição
financeira do ERP fecha com a posição bancária.

Os documentos consolidados definem `Bank Statement → Reconciliation → Cash
Flow`, atribuem ao M12 as tabelas `bank_statement_import`, `bank_movement`,
`financial_match` e `cash_flow_projection`, e tornam o fechamento
`Bank Statement = ERP Financial Position` um gate de go-live financeiro.

## Decisão

Extratos e conciliação permanecem no bounded context M12, pacote
`erp.modules.finance` e futuro schema `finance`. O Commit 180 estabelece o
domínio puro e os adaptadores de ingestão; persistência, API, Audit/Outbox e UI
serão slices posteriores.

```text
OFX / CSV bancário
        │ adapters de parsing fail-closed
        ▼
BankStatement + BankMovement (M12)
        │ regras determinísticas tenant-bound
        ▼
BankReconciliationPolicy
        │ sugestões explicáveis
        ▼
Financial Match / fila de exceções
        │ evento após persistência transacional
        ▼
BankMovementReconciled v1 → M13
```

### Autoridade e fronteiras

O M12 será owner de:

- importação, identidade e hash do arquivo de extrato;
- movimentos bancários normalizados e seu estado de conciliação;
- tolerâncias de valor/data/documento configuráveis por empresa;
- sugestões, decisões, divergências, tarifas e matches financeiros;
- posição bancária operacional e projeções de fluxo de caixa.

O M12 não escreve no razão contábil do M13. Após uma conciliação persistida,
publicará `BankMovementReconciled` via Outbox; o M13 decide os lançamentos
contábeis. O parser não acessa banco, ORM, FastAPI, broker ou outros módulos.
Confirmações CNAB/PIX da Sprint 19 continuam sendo evidência da execução de
pagamento, enquanto o extrato é a evidência independente da movimentação da
conta.

## Modelo de domínio

`BankStatement` é um agregado imutável e tenant-bound, identificado por UUID,
conta financeira, banco, período, formato e SHA-256 do arquivo fonte. Seus
`BankMovement` são únicos por identificador externo, usam `Decimal`, data civil
e direção explícita (`CREDIT`/`DEBIT`). Alterações retornam nova instância; uma
movimentação conciliada não pode ser conciliada novamente.

O motor automático compara um movimento com snapshots de títulos/liquidações
por:

1. mesmo `company_id` e mesma direção;
2. diferença absoluta de valor dentro da tolerância;
3. diferença de dias dentro da janela permitida;
4. similaridade normalizada do documento quando ambos os lados o possuem;
5. score ponderado e limiar mínimo para auto-match.

Empates permanecem `AMBIGUOUS`; ausência de candidato ou score insuficiente
permanece `PENDING`. O motor nunca escolhe silenciosamente entre candidatos
equivalentes. Split N:N, baixa manual, ignore com motivo e criação de provisão
serão comandos auditados em slices posteriores.

## Ingestão OFX e CSV

- OFX 1.x SGML e OFX 2.x XML são aceitos sem DTD ou entidades externas;
- arquivos possuem limite de 10 MiB e hash SHA-256 para idempotência futura;
- datas, valores, identificadores e conta são validados de forma fail-closed;
- CSV aceita aliases PT-BR/EN, delimitadores comuns, layouts configuráveis e
  valores brasileiros ou ISO;
- CP1252 é suportado como fallback para bancos legados;
- linhas sem identificador recebem fingerprint determinístico, nunca UUID
  aleatório;
- adapters apenas normalizam; decisões de matching permanecem no domínio.

## Tarifas e divergências

Tarifas, juros e tributos são classificados, porém não auto-lançados. Um
movimento sem correspondência permanece pendente para a futura fila explicável,
que poderá associar, dividir, ignorar com justificativa ou criar provisão sob
RBAC/Audit. Diferenças acima das tolerâncias jamais são conciliadas
automaticamente.

## Segurança, RBAC e SoD

O contrato corporativo existente `finance.bank.reconcile` controlará decisões
de conciliação. Leitura/importação e manutenção de conta serão detalhadas nos
commits de API, preservando `finance.treasury.read` e
`finance.bank_account.manage`. Todo acesso é escopado por `company_id`.

Dados completos de conta são `RESTRICTED`: UI, logs, eventos e traces devem
mascará-los. Importar o extrato não concede autoridade para aprovar ajustes,
criar provisões ou postar contabilidade. Essas operações exigirão permissões e
SoD próprias.

## Idempotência, concorrência e observabilidade futura

O hash do arquivo, a conta e o tenant formarão a identidade de ingestão. A
persistência futura terá unique constraints, optimistic locking e
`Idempotency-Key`. A decisão de conciliação, seu Audit e o evento Outbox serão
gravados na mesma transação. Métricas mínimas incluirão arquivos aceitos/
rejeitados, movimentos pendentes, taxa de auto-match, ambiguidades, tarifas e
diferença diária entre extrato e posição ERP.

## Consequências

A separação entre parser, agregado e política torna o matching determinístico,
explicável e testável sem infraestrutura. Há custo de snapshots e revisão de
ambiguidades, mas o desenho evita reconciliações falsas, vazamento cross-tenant
e dependência de layouts bancários dentro das regras financeiras.
