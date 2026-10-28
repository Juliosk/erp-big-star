# Runbook operacional — Tesouraria e execução de pagamentos M12

## 1. Objetivo e limites

Este runbook governa a seleção de parcelas elegíveis, criação e aprovação de
lotes, geração de remessas CNAB/PIX e liquidação após confirmação bancária. O
M12 é o owner de `PaymentBatch`; M22 decide alçadas e o banco confirma a
execução.

A confirmação de uma remessa não equivale à conciliação bancária. Importação de
extratos OFX, matching N:N de movimentos, tarifas e posição diária de caixa
pertencem ao próximo slice e não devem ser simulados por edição manual de lote.

## 2. Pré-requisitos e segurança

- Migration `0045` ativa e PostgreSQL, RabbitMQ e workers de Outbox/Inbox
  saudáveis.
- Título aprovado ou agendado, parcela aberta, Three-Way Match concluído ou
  override formal e nenhum bloqueio fiscal/físico pendente.
- Definição M22 ativa para `FINANCE / PAYMENT_BATCH`.
- Certificado, convênio, endpoint e leiaute bancário homologados antes de usar
  `PRODUCTION`.
- Dados bancários e arquivos de remessa/retorno são `RESTRICTED`: não anexar em
  chamados, não registrar payload integral em logs e não armazenar fora do
  repositório seguro aprovado.

Permissões oficiais:

| Operação | Permissão |
| --- | --- |
| Consultar fila, itens e auditoria | `finance.treasury.read` |
| Criar lote e executar dry-run | `finance.treasury_batch.create` |
| Aprovar lote na alçada | `finance.treasury_batch.approve` |
| Gerar/transmitir remessa e processar retorno | `finance.treasury_batch.execute` |

O escopo de `company_id` é obrigatório e cross-tenant responde como recurso não
encontrado. A UI mascara contas; exportações só devem mostrar o mínimo exigido
pelo banco.

## 3. Segregação de funções (SoD)

A política maker-checker é fail-closed:

- o criador do lote não o aprova nem o executa;
- criador ou aprovador de qualquer título do lote não aprova nem executa o lote;
- por padrão, o aprovador do lote não transmite a remessa;
- dividir lotes, trocar permissões ou repetir a chamada não contorna o SoD;
- `SOD_VIOLATION` exige outro ator autorizado, nunca alteração manual do banco.

Registre no mínimo três identidades auditáveis para o fluxo crítico: operador
que compõe, aprovador M22 e executor de tesouraria.

## 4. Estados e significado operacional

```text
DRAFT → PENDING_APPROVAL → APPROVED → RELEASED → SUBMITTED → CONFIRMED
                            ↘ REJECTED              ↘ FAILED
```

- `DRAFT`: lote editável somente pelos comandos autorizados.
- `PENDING_APPROVAL`: solicitação M22 aberta; nenhuma remessa oficial.
- `APPROVED`: decisão de alçada concluída por ator segregado.
- `RELEASED`: lote liberado e pronto para o adapter bancário.
- `SUBMITTED`: remessa transmitida; parcela ainda não está paga.
- `CONFIRMED`: retorno bancário inequívoco correlacionado; somente aqui ocorre
  a liquidação.
- `FAILED`: banco rejeitou/devolveu a instrução; título volta ao tratamento
  operacional previsto sem apagar o histórico.

Toda mutação exige `Idempotency-Key`; mutações sobre lote exigem `If-Match` com
o ETag lido no dossiê. Em `VERSION_CONFLICT`, recarregue e reavalie o estado.

## 5. Jornada no Cockpit `/ui/treasury`

1. Conecte uma identidade válida e selecione a empresa de trabalho.
2. Abra **Tesouraria**, filtre a fila e revise valor, favorecidos mascarados e
   bloqueios explicáveis.
3. Execute **Simular remessa**. O artefato `DRYRUN-*` valida o leiaute, mas não
   altera o estado nem autoriza pagamento.
4. Use **Solicitar alçada M22**. Um ator distinto deve decidir no Cockpit de
   Aprovações.
5. Após aprovação, um executor segregado informa a instância M22 e gera a
   remessa oficial.
6. Confira checksum, quantidade de registros, valor total e protocolo antes da
   transmissão externa.
7. Mantenha o lote em `SUBMITTED` até receber retorno CNAB ou callback PIX
   autenticado e correlacionado.
8. Atualize a fila: `CONFIRMED` mostra **Liquidado**; `FAILED` mostra a causa e
   bloqueia reenvio automático.

A linha de liberação bancária expõe quatro gates: elegibilidade, alçada M22,
remessa e confirmação. Não trate um gate verde como substituto dos demais.

## 6. CNAB 240, CNAB 400 e PIX

Antes de transmitir:

- valide banco, agência, conta, titular, CPF/CNPJ, moeda, datas e total;
- compare o SHA-256 e o total do arquivo com o dossiê;
- use o adapter/layout contratado para a conta de débito;
- preserve o arquivo original como evidência imutável;
- em timeout ou resposta ambígua, consulte o banco antes de qualquer reenvio.

No retorno CNAB, mantenha a linha, protocolo, ocorrência, valor e data de
liquidação correlacionados ao lote. Para PIX, valide autenticidade do webhook,
idempotency key/end-to-end ID e valor. Payload duplicado deve resultar em replay
idempotente, nunca em segunda baixa.

O rollout obrigatório é `dry-run → homologação bancária → piloto de baixo valor
→ produção controlada`. A aprovação do software não certifica um convênio ou
layout específico do banco.

## 7. Rejeições, devoluções e estornos

| Situação | Conduta segura |
| --- | --- |
| Conta/agência inválida | marcar `FAILED`, corrigir cadastro de origem e criar novo fluxo auditável |
| Saldo insuficiente | preservar a falha, reprogramar após autorização; não alterar retorno |
| Arquivo rejeitado | conferir leiaute/convênio e regenerar com nova chave após correção |
| Timeout na transmissão | consultar protocolo/status no banco; nunca reenviar às cegas |
| Confirmação duplicada | manter replay idempotente e uma única liquidação |
| Devolução após confirmação | abrir protocolo de reversão; não apagar a baixa nem o audit log |
| Valor divergente | bloquear liquidação e encaminhar à investigação; não aceitar por tolerância informal |

Reversão preserva protocolo, motivo, ator, horário, Audit e Outbox. Não edite
`payment_batch`, parcelas, audit log, Inbox ou Outbox diretamente.

## 8. Eventos, Inbox/Outbox e reavaliação

A Tesouraria publica fatos de criação, aprovação, liberação, submissão,
confirmação e falha na mesma transação do lote. O consumer
`finance.treasury-source-events.v1` recebe mudanças autorizadas de M6, M11, M12
e M22 com:

- deduplicação por mensagem;
- cursor monotônico por tenant/origem/agregado;
- proteção por versão e timestamp;
- reavaliação de lotes `DRAFT` ou `PENDING_APPROVAL`;
- bloqueio explicável quando título, matching ou decisão perde elegibilidade.

Para fila parada, correlacione `message_id`, `aggregate_id`, `request_id` e
`correlation_id`; compare cursor e versão; aplique retry/DLQ pela política. Não
republique payload editado.

## 9. Catálogo de falhas

| Código/sintoma | Causa provável | Ação |
| --- | --- | --- |
| `SOD_VIOLATION` | conflito entre criador/aprovador/executor | encaminhar a ator segregado |
| `PRECONDITION_REQUIRED` | `If-Match` ausente | reler lote e enviar ETag |
| `VERSION_CONFLICT` | lote mudou após leitura | atualizar e revisar nova versão |
| `PERMISSION_FORBIDDEN` | permissão insuficiente | corrigir papel sem ampliar tenant |
| `RESOURCE_NOT_FOUND` | ID ausente ou outro tenant | conferir empresa e identidade |
| lote bloqueado | título/matching/fiscal/workflow mudou | corrigir origem e aguardar reavaliação |
| `SUBMITTED` sem retorno | banco ainda não confirmou ou retorno parou | consultar protocolo e pipeline; não baixar manualmente |
| `FAILED` | rejeição/devolução bancária | tratar motivo e iniciar novo fluxo após correção |

## 10. Homologação técnica

Execução focada:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_treasury_browser.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_treasury_api.py tests\integration\test_payment_settlement.py -q
```

Homologação global:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --cov=erp --cov-branch --cov-report=term-missing
```

O E2E Chromium valida lote tenant-bound, dry-run, abertura de alçada, decisão
por ator segregado, remessa por terceiro ator e liquidação somente após retorno
CNAB confirmado. As telas desktop/mobile e a fila explicável continuam cobertas
no mesmo arquivo de testes.

## 11. Próxima etapa — Conciliação Bancária e Fluxo de Caixa

O próximo slice deve começar com DoR específico para:

1. ADR e contratos puros de extrato, movimento, conta e posição diária;
2. ingestão idempotente de OFX/CNAB extrato com hash e proveniência;
3. regras determinísticas de matching 1:1, 1:N e N:1, sem baixa automática
   ambígua;
4. fila explicável de não conciliados, tarifas, juros, estornos e transferências;
5. fechamento diário `Extrato bancário = posição financeira ERP`, com
   diferenças justificadas;
6. projeção de fluxo de caixa realizado/previsto sem misturar confirmação de
   pagamento com conciliação;
7. RBAC/SoD, Audit, Outbox/Inbox, APIs, Cockpit e E2E concorrente.

Antes do código, definir bancos/layouts piloto, timezone/data-valor, tolerâncias,
regras de duplicidade, contas internas, tratamento de arquivos corrigidos e
limites de auto-match.
