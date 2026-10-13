# M12 — Contas a Pagar, provisões e governança

## Objetivo e limites do módulo

O M12 é o bounded context responsável por provisões financeiras, títulos a
pagar, parcelas, vencimentos, ajustes e estado de aprovação. Ele preserva as
referências de origem sem assumir a autoridade de Compras, Fiscal ou Workflow.

- M6 é owner de fornecedor, pedido, recebimento físico e inspeção.
- M11 é owner do documento fiscal, autorização e conciliação físico-fiscal.
- M22 é owner da definição de alçadas e da decisão de aprovação.
- M12 é owner da obrigação financeira, seus bloqueios, parcelas e auditoria.
- Toda leitura, mutação e mensagem é delimitada por `company_id`.
- M12 não grava nos schemas `procurement`, `fiscal` ou `workflow`.

Liquidação bancária, remessas, retorno, conciliação bancária e o motor ampliado
de three-way match não pertencem à Sprint 17.

## Jornada operacional

1. O M6 aprova um pedido de compra e publica `PurchaseOrderApproved`.
2. O consumer `finance.payable-provisioning.v1` registra a provisão e cria o
   título em `DRAFT`. Redelivery é absorvida pela Inbox.
3. A autorização fiscal pode vincular o documento do M11 à mesma obrigação,
   evitando título duplicado quando fornecedor e valor identificam uma única
   provisão de compra.
4. O M11 publica `FiscalReceivingReconciled` após comparar XML e recebimento.
   Divergência fiscal ou física ativa o gate correspondente no M12.
5. Com os gates liberados, o operador submete o título. Valores sujeitos a
   alçada abrem uma instância no M22 e permanecem `PENDING_APPROVAL`.
6. Um aprovador distinto decide no M22. O consumer
   `finance.payable-approval.v1` atualiza título e governança exatamente uma vez.
7. Um título `APPROVED`, sem bloqueios, pode ter suas parcelas agendadas. A
   liquidação efetiva continuará fora deste slice.

## Estados do título

| Estado | Significado operacional | Próxima ação permitida |
| --- | --- | --- |
| `DRAFT` | obrigação criada e ainda ajustável | ajustar ou submeter |
| `PENDING_APPROVAL` | decisão de alçada pendente no M22 | aguardar decisão |
| `APPROVED` | governança concluída e gates liberados | agendar parcelas |
| `REJECTED` | rejeitado pelo M22 ou cancelado na origem | revisar origem |
| `SCHEDULED` | todas as parcelas possuem referência de agendamento | acompanhar |
| `PAID` | reservado para liquidação financeira futura | consultar |

Os comandos de ajuste operam somente em `DRAFT`. Agendamento exige `APPROVED`
e aprovação registrada. Transições concorrentes usam a versão persistida.

## Provisões e vínculo de origem

| Origem | Evento | Resultado no M12 |
| --- | --- | --- |
| Pedido aprovado M6 | `PurchaseOrderApproved` | provisão de compra e título `DRAFT` |
| Documento autorizado M11 | `FiscalDocumentAuthorized` | provisão fiscal vinculada ou novo título |
| Cancelamento fiscal M11 | `FiscalDocumentCancelled` | provisão `VOIDED` e título rejeitado antes da liquidação |
| Conciliação de entrada M11 | `FiscalReceivingReconciled` | atualiza gates fiscal e físico |

O vínculo usa os identificadores imutáveis da origem. Correspondência de
fornecedor e valor só reutiliza uma provisão quando existe um candidato único;
descrição, similaridade textual ou aproximação de SKU nunca são usadas.

## Governança, alçadas e segregação de funções

A definição ativa do M22 deve usar `source_module=FINANCE` e
`source_type=PAYABLE`. Cada etapa informa `required_permission` e o limite
financeiro aplicável.

- `finance.payable.approve` concede elegibilidade, não autoaprovação.
- Se o criador decidir o próprio título com valor igual ou superior ao limite
  SoD, a operação falha com `SOD_VIOLATION`.
- Título acima da autonomia do ator abre workflow mesmo que ele possua a
  permissão de aprovação.
- Sem definição ativa ou sem etapas válidas, a submissão falha de forma fechada
  com `PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED`.
- A decisão registra aprovador, instância do M22, snapshots e correlação.

## Bloqueios por divergência

| Gate | Fato recebido | Efeito |
| --- | --- | --- |
| Fiscal | `financial_blocked=true` | impede submissão/aprovação/agendamento |
| Físico/Compras | `physical_pending=true` | impede submissão/aprovação/agendamento |
| Fiscal liberado | `financial_blocked=false` | remove somente o gate fiscal |
| Físico liberado | `physical_pending=false` | remove somente o gate físico |

O M12 não recalcula quantidade, preço ou tributos. Ele projeta o resultado
publicado pelo M11 e conserva o relatório no owner fiscal. O cockpit apresenta
os dois gates separadamente para não ocultar a causa do bloqueio.

## RBAC

| Permissão | Uso |
| --- | --- |
| `finance.payable.read` | listar títulos, provisões, parcelas e auditoria |
| `finance.payable.create` | criar título manual e submeter para aprovação |
| `finance.payable.approve` | compor alçada no M22; não contorna SoD |
| `finance.payable.adjust` | ajustar descontos/acréscimos e agendar parcelas |

RBAC sempre é combinado com escopo explícito da empresa. Tentativas de leitura
de outro tenant retornam recurso inexistente para evitar enumeração.

## APIs e concorrência

| Operação | Contrato |
| --- | --- |
| Criar título | `POST /api/v1/finance/payables` |
| Listar títulos | `GET /api/v1/finance/payables` |
| Consultar dossiê | `GET /api/v1/finance/payables/{id}` |
| Submeter à alçada | `POST /api/v1/finance/payables/{id}/submit-for-approval` |
| Ajustar valores | `PATCH /api/v1/finance/payables/{id}/adjustments` |
| Agendar parcelas | `POST /api/v1/finance/payables/{id}/schedule` |

Criação e agendamento exigem `Idempotency-Key`. Mutações exigem
`If-Match: "N"`; leituras devolvem o ETag atual. Em `VERSION_CONFLICT`, releia o
dossiê, revalide a decisão operacional e repita com a nova versão.

## Audit, Outbox e Inbox

As mutações críticas registram Audit e Outbox dentro da mesma transação do
título. Falha em qualquer efeito reverte título, governança e mensagem.

| Consumer | Mensagens |
| --- | --- |
| `finance.payable-provisioning.v1` | fatos de pedido e documento fiscal |
| `finance.payable-divergence.v1` | resultado da conciliação M11 |
| `finance.payable-approval.v1` | decisão de workflow M22 |

Cada consumer deduplica por `consumer_name + message_id`. Um receipt
`PROCESSED` com múltiplas tentativas confirma redelivery idempotente. Não edite
Audit, Outbox ou Inbox manualmente; use `request_id`, `correlation_id`,
`message_id`, `source_id` e `workflow_instance_id` para diagnóstico.

## Catálogo de erros operacionais

| Código | Causa | Ação |
| --- | --- | --- |
| `SOD_VIOLATION` | criador tentou aprovar obrigação acima do limite SoD | encaminhar a outro aprovador |
| `PAYABLE_DIVERGENCE_BLOCKED` | gate fiscal ou físico ainda aberto | resolver divergência no M11/M6 |
| `PAYABLE_APPROVAL_REQUIRED` | ação exige decisão M22 concluída | aguardar/aprovar no Workflow |
| `PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED` | definição M22 ausente ou sem etapas | configurar política ativa |
| `VERSION_CONFLICT` | ETag desatualizado | recarregar e repetir conscientemente |
| `PRECONDITION_REQUIRED` | `If-Match` ausente | enviar ETag da última leitura |
| `INVALID_IF_MATCH` | header inválido | usar exatamente `"N"` |
| `PAYABLE_CONFLICT` | documento/fornecedor duplicado no tenant | abrir o título existente |
| `RESOURCE_NOT_FOUND` | recurso ausente ou fora do tenant | confirmar empresa e identidade |
| `PERMISSION_FORBIDDEN` | RBAC insuficiente | revisar papel sem ampliar o tenant |
| `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD` | chave reutilizada com outro comando | gerar nova chave após revisar payload |

## Operação do Cockpit

1. Acesse `/ui/`, conecte a identidade e selecione a empresa de trabalho.
2. Abra **Contas a pagar** e filtre a carteira por situação.
3. Use **Analisar** para abrir o dossiê, origem, parcelas e auditoria.
4. Confira o circuito M11 → M6 → M22 → Pagamento antes de agir.
5. Em `DRAFT`, ajuste desconto/acréscimo ou submeta à alçada.
6. Em `APPROVED`, sem gate aberto, agende as parcelas.

A UI usa apenas APIs oficiais, nunca persiste o token e envia o `company_id` da
empresa ativa. O backend continua sendo autoritativo para RBAC, tenant, SoD,
estado, idempotência e versão.

## Validação e recuperação

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --cov=erp --cov-branch --cov-report=term-missing
```

O cenário consolidado `test_finance_end_to_end.py` cobre os contratos
versionados de pedido aprovado e conciliação, provisão M12, bloqueio e
liberação, abertura de alçada M22, SoD e decisão idempotente. O E2E Chromium do
cockpit cobre desktop e mobile.

Em indisponibilidade local, preserve os volumes do PostgreSQL, Redis, RabbitMQ
e MinIO. Não execute factory reset nem prune de volumes como procedimento de
recuperação.

## Direção da Sprint 18 — Three-Way Match

A Sprint 18 deve introduzir um owner explícito para o match entre Pedido M6,
Recebimento M6/M17 e Documento Fiscal M11, mantendo o M12 como consumidor do
gate financeiro. O DoR precisa definir tolerâncias por empresa, moeda,
arredondamento, múltiplas entregas/notas, exceções e alçadas de override.

Plano proposto:

1. ADR e contratos puros do Three-Way Match, sem dependência entre schemas.
2. Agregado de match e snapshots imutáveis de pedido, recebimento e documento.
3. Migration e repositório tenant-bound com versionamento otimista.
4. Motor determinístico de quantidade, preço, tributos, moeda e tolerâncias.
5. Fila de exceções, APIs idempotentes e relatório explicável de divergências.
6. Alçadas avançadas M22 e SoD para overrides, sem aprovação pelo solicitante.
7. Consumers Outbox/Inbox para recomposição segura e proteção contra fatos
   obsoletos ou fora de ordem.
8. Cockpit, E2E concorrente, runbook e fechamento da Sprint 18.

