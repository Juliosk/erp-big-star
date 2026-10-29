# Runbook operacional — Conciliação bancária M12

## 1. Objetivo, autoridade e limites

Este runbook governa a importação de extratos OFX/CSV, normalização de
movimentos bancários, sugestões explicáveis, conciliação com títulos do ERP e
tratamento de divergências no M12. O extrato é a evidência independente do
banco; confirmação CNAB/PIX prova a execução de uma instrução, mas não substitui
a conciliação.

O M12 é owner de `BankStatement`, `BankMovement`, tolerâncias, candidatos,
decisões e evidências de conciliação. Ele não grava diretamente no M13
Contábil, não altera o título que originou um candidato e não edita fatos do M6,
M11 ou M22.

`DIRECT_ENTRY` classifica tarifa, juros ou tributo para tratamento posterior.
Essa ação não cria título fictício, não marca o movimento como `RECONCILED` e
não posta contabilidade. Splits 1:N/N:1, criação de provisão pelo cockpit e baixa
contábil direta continuam fora do slice da Sprint 20.

## 2. Arquitetura operacional

```text
OFX / CSV confiável
        │ parser fail-closed + SHA-256
        ▼
BankStatement + BankMovement (finance)
        │ política determinística tenant-bound
        ▼
Sugestões explicáveis / fila de exceções
        │ aceite ou override com ETag
        ▼
conciliation_record append-only + Outbox
        │
        ├── BankMovementReconciled v1
        └── BankReconciliationReviewRequired v1
```

Persistência principal:

| Estrutura | Responsabilidade |
| --- | --- |
| `finance.bank_statement` | identidade do extrato por empresa, conta e hash |
| `finance.bank_movement` | linhas normalizadas e estado de conciliação |
| `finance.statement_import_audit` | evidência append-only da importação |
| `finance.conciliation_record` | decisão append-only, ator, score e referência |
| `finance.bank_reconciliation_candidate` | candidatos projetados de módulos vizinhos |
| `finance.bank_reconciliation_source_cursor` | cursor monotônico por tenant e agregado |
| `platform.inbox_event` | deduplicação do consumo assíncrono |
| `platform.outbox_event` | publicação transacional de fatos conciliados/revisões |

As migrations `0046` e `0047` devem estar ativas. Não atualize ou remova as
tabelas de auditoria manualmente; triggers do PostgreSQL protegem importações e
conciliações como append-only.

## 3. Pré-requisitos e segurança

- PostgreSQL, RabbitMQ e workers de Inbox/Outbox saudáveis.
- Migration `0047` no head do Alembic.
- Conta bancária cadastrada e empresa de trabalho correta.
- Arquivo obtido do canal oficial do banco, sem edição após o download.
- Identidade com escopo explícito de `company_id` e somente as permissões
  necessárias.
- Relógio, timezone e data contábil do ambiente verificados antes de fechar o
  dia.

Extratos, números de conta, documentos e candidatos financeiros são dados
`RESTRICTED`. Não anexe arquivos reais em chamados, não copie payloads para
logs, não exponha números completos em screenshots e não mova extratos para
armazenamento pessoal. Use `request_id`, `correlation_id`, `message_id`, IDs e
hashes para diagnóstico.

Permissões oficiais:

| Operação | Permissão | Risco |
| --- | --- | --- |
| Consultar extratos, movimentos e candidatos | `finance.reconciliation.read` | alto |
| Importar OFX/CSV na conta selecionada | `finance.reconciliation.import` | crítico |
| Simular, aceitar ou sobrescrever uma decisão | `finance.reconciliation.execute` | crítico |

Todas combinam RBAC e escopo da empresa. Acesso cross-tenant responde como
recurso não encontrado para evitar enumeração. Importar não concede autoridade
para forçar match; leitura não autoriza download ou tratamento fora do ERP.

## 4. Ingestão segura de OFX e CSV

O upload aceita `OFX` ou `CSV`, exige `company_id`, `bank_account_id` e arquivo,
e limita o conteúdo a 10 MiB. Banco e referência da conta podem vir do arquivo
ou dos campos operacionais, conforme o adapter.

### OFX

- OFX 1.x SGML e OFX 2.x XML são normalizados sem resolver entidades externas.
- Datas, valores, direção, conta e identificadores são validados de forma
  fail-closed.
- O identificador bancário original é preservado; linha sem ID recebe
  fingerprint determinístico.

### CSV

- Use somente o template/layout homologado para o banco piloto.
- Delimitador, aliases de colunas, datas e valores devem ser reconhecidos pelo
  adapter; CP1252 é aceito apenas como fallback legado.
- Não corrija células diretamente no arquivo para fazê-lo “passar”. Solicite
  novo extrato ou registre formalmente a transformação homologada.

O SHA-256, a empresa e a conta formam a identidade idempotente da importação.
Reenvio idêntico devolve o extrato existente, HTTP 200 e
`Idempotency-Replayed: true`; não duplica movimentos. Arquivo novo devolve HTTP
201, `Location`, ETag e a trilha append-only de importação.

Antes de importar, confirme empresa, conta, banco, período, saldo inicial/final
e tamanho. Depois, compare a quantidade de linhas e os totais de crédito/débito
com o portal bancário.

## 5. Estados e interpretação da fila

Estados persistidos do extrato:

```text
PENDING → PARTIALLY_RECONCILED → RECONCILED
```

O movimento persiste somente como `PENDING` ou `RECONCILED`. O cockpit deriva
estados explicáveis sem inventar persistência adicional:

| Estado visual | Significado | Conduta |
| --- | --- | --- |
| `PENDING` | ainda não existe decisão persistida | analisar candidatos |
| `MATCHED` | referência financeira e evidência persistidas | somente consultar |
| `AMBIGUOUS` | candidatos equivalentes ou insuficientemente distintos | resolver manualmente |
| `UNMATCHED` | nenhum candidato elegível | corrigir origem ou aguardar novo fato |
| `DIRECT_FEE` | tarifa, juros ou tributo identificados | classificar com justificativa; não criar falso match |

Um movimento conciliado é imutável. Reversão posterior do fato financeiro não
apaga a conciliação: desativa o candidato e publica uma revisão obrigatória.

## 6. Regras de matching e explicabilidade

A política padrão compara apenas candidatos do mesmo `company_id` e direção:

1. tolerância de valor: `R$ 0,01`;
2. janela de data: até `2` dias;
3. similaridade mínima de documento: `0,80` quando ambos informam documento;
4. score mínimo de auto-match: `0,85`;
5. empate no melhor score: `AMBIGUOUS`, nunca escolha silenciosa.

Razões oficiais incluem `DIRECTION_MISMATCH`, `AMOUNT_MISMATCH`,
`DATE_MISMATCH`, `DOCUMENT_MISMATCH`, `SCORE_BELOW_THRESHOLD`,
`NO_CANDIDATE` e `AMBIGUOUS_CANDIDATES`. O cockpit mostra fonte, documento,
valor, data, score e razão; score alto não substitui evidência operacional.

`SIMULATE` calcula resultados sem persistir. `APPLY` e `ACCEPT_MATCH` usam o
candidato válido. `FORCE_MATCH` exige candidato e justificativa entre 10 e 500
caracteres. A justificativa deve citar evidência verificável, nunca apenas
“ajuste”, “ok” ou texto genérico.

## 7. Jornada no Cockpit `/ui/finance/conciliation`

1. Conecte uma identidade válida e selecione a empresa de trabalho.
2. Abra **Conciliação** e confirme que a conta pertence à empresa selecionada.
3. Preencha conta, formato, banco e referência; selecione o OFX/CSV oficial.
4. Importe e valide a mensagem, o extrato recente e os totalizadores.
5. Filtre a fila por estado, conta e período.
6. Selecione a linha. A mesa Banco ↔ ERP exibe sugestão, score e causa da
   divergência.
7. Em sugestão exata, use **Aceitar sugestão** somente após conferir documento,
   data, valor e direção.
8. Em ambiguidade, escolha o candidato correto e registre justificativa no
   modal de resolução manual.
9. Para tarifa/juros/tributo, use **Classificar lançamento direto**. O movimento
   continua sem título artificial e aguarda o slice contábil apropriado.
10. Atualize a mesa e confirme ETag, estado, totais e evidência vinculada.

Não use `FORCE_MATCH` para fechar diferença de caixa. Se não houver evidência,
mantenha pendente e corrija a origem.

## 8. APIs, concorrência e contratos HTTP

Base: `/api/v1/finance/reconciliation`.

| Método e rota | Uso | Permissão |
| --- | --- | --- |
| `POST /statements/upload` | importar OFX/CSV multipart | `finance.reconciliation.import` |
| `GET /statements` | listar por conta/período | `finance.reconciliation.read` |
| `GET /statements/{id}` | consultar extrato e ETag | `finance.reconciliation.read` |
| `GET /statements/{id}/movements` | linhas do extrato | `finance.reconciliation.read` |
| `GET /movements` | fila paginada global do tenant | `finance.reconciliation.read` |
| `GET /statements/{id}/movements/{movement_id}/candidates` | opções explicáveis | `finance.reconciliation.read` |
| `POST /statements/{id}/match` | simular/aplicar motor | `finance.reconciliation.execute` |
| `POST /statements/{id}/movements/{movement_id}/resolve` | aceitar, forçar ou classificar | `finance.reconciliation.execute` |

Mutações de matching e resolução exigem `If-Match: "N"`; leituras detalhadas
devolvem ETag. Em `VERSION_CONFLICT`, recarregue o extrato, revise candidatos e
repita conscientemente. Não incremente a versão manualmente. Respostas usam o
Error Contract oficial e `Cache-Control: no-store`.

## 9. Eventos, Inbox/Outbox e ordem de entrega

O consumer `finance.bank-reconciliation-source-events.v1` recebe:

- `PayableInstallmentSettled` e `ReceivableInstallmentSettled`, que criam ou
  atualizam candidatos;
- `BankSettlementReversed` e `ReceivableSettlementReversed`, que desativam o
  candidato e sinalizam revisão;
- `PaymentBatchConfirmed`, usado como fato de origem sem criar candidato
  duplicado.

Inbox deduplica por mensagem. O cursor aceita somente versão maior ou, na mesma
versão, timestamp mais recente. Eventos antigos ou repetidos não regridem a
projeção. Reavaliação bloqueia extratos pendentes com `SELECT FOR UPDATE SKIP
LOCKED`, evitando corrida entre consumers e operadores.

Saídas transacionais:

| Evento | Quando | Uso downstream |
| --- | --- | --- |
| `BankMovementReconciled` v1 | movimento ganha evidência completa | projeções financeiras/contábeis autorizadas |
| `BankReconciliationReviewRequired` v1 | referência conciliada é revertida na origem | fila de revisão sem apagar histórico |

Para fila parada, correlacione `message_id`, `request_id`, `correlation_id`,
aggregate version e cursor. Use retry/DLQ oficial; não edite nem republique
payload manualmente.

## 10. Catálogo de falhas e recuperação

| Código/sintoma | Causa provável | Recuperação segura |
| --- | --- | --- |
| `INVALID_BANK_STATEMENT_UPLOAD` | vazio ou acima de 10 MiB | obter novo arquivo oficial dentro do limite |
| `INVALID_BANK_STATEMENT` / `VALIDATION_ERROR` | layout, data, valor ou justificativa inválidos | preservar original, corrigir adapter/origem e revalidar |
| `BANK_STATEMENT_CONFLICT` | identidade/hash conflita no tenant | consultar o extrato existente; não apagar auditoria |
| `BANK_MOVEMENT_ALREADY_RECONCILED` | tentativa repetida sobre decisão final | atualizar a mesa e consultar evidência existente |
| `MATCH_CANDIDATE_NOT_FOUND` | candidato mudou, foi revertido ou é de outro tenant | recarregar candidatos e investigar a origem |
| `MATCH_CONFLICT` | candidato não atende à política automática | revisar causa; usar override somente com evidência formal |
| `DIRECT_ENTRY_NOT_ALLOWED` | linha não é tarifa, juros ou tributo | manter pendente ou selecionar título válido |
| `PRECONDITION_REQUIRED` | `If-Match` ausente | reler o extrato e enviar o ETag atual |
| `VERSION_CONFLICT` | outro ator/consumer atualizou o extrato | recarregar, revisar e repetir a decisão |
| `PERMISSION_FORBIDDEN` | RBAC insuficiente | corrigir papel sem ampliar tenant |
| `RESOURCE_NOT_FOUND` | ID ausente ou empresa incorreta | conferir empresa ativa; não enumerar outros tenants |
| `FINANCE_RECONCILIATION_UNAVAILABLE` | composição do serviço indisponível | verificar aplicação, banco e inicialização; não operar por SQL |
| replay não altera estado | arquivo/evento já processado | confirmar hash/message ID e usar o resultado existente |
| referência revertida | liquidação upstream foi estornada | tratar `BankReconciliationReviewRequired`; não apagar match |

Arquivo importado na conta errada não deve ser apagado ou movido por SQL.
Interrompa o fechamento, preserve hash e auditoria, registre incidente e execute
o procedimento compensatório aprovado. Nunca manipule `bank_statement`,
`bank_movement`, Inbox, Outbox, cursor ou audit log diretamente.

## 11. Fechamento diário e observabilidade

Gate obrigatório de go-live financeiro:

```text
Bank Statement = ERP Financial Position
```

Toda diferença deve estar explicada por movimento pendente, ambiguidade,
tarifa/juros/tributo, trânsito bancário ou revisão aberta. Acompanhe ao menos:

- arquivos aceitos, rejeitados e replays por conta;
- movimentos pendentes e idade do pendente;
- taxa de auto-match, overrides e ambiguidades;
- lançamentos diretos por tipo e valor;
- revisões por estorno upstream;
- diferença diária por conta entre extrato e posição ERP;
- lag, retries e DLQ do consumer.

Não declare o dia fechado enquanto houver diferença sem causa ou revisão de
referência revertida.

## 12. Homologação técnica e recuperação local

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_bank_conciliation_api.py tests\integration\test_bank_conciliation_event_consumers.py tests\integration\test_bank_conciliation_browser.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --cov=erp --cov-branch --cov-report=term-missing -q
```

O E2E Chromium cobre upload, sugestão explicável, aceite, classificação direta,
desktop/mobile, ausência de storage persistente no browser e ausência de
overflow horizontal.

Em falha local, diagnostique serviço, contexto Docker e logs antes de reiniciar.
Preserve os volumes do PostgreSQL, RabbitMQ, Redis e MinIO. Não execute factory
reset, `docker system prune -a --volumes` ou remoção manual de volumes como
procedimento de recuperação.

## 13. Diretrizes da Sprint 21 — Fluxo de Caixa e Liquidez

A ordem executiva mantém `Cash Flow` após extratos e conciliação. A Sprint 21
deve construir projeção sem confundir saldo bancário, pagamento confirmado,
movimento conciliado e lançamento contábil.

DoR obrigatório:

1. definir conta/posição de abertura, timezone, moeda, horizonte e calendário;
2. classificar fontes como realizado, comprometido, previsto e cenário;
3. impedir dupla contagem de transferências entre contas da mesma empresa;
4. definir tratamento de parcelas vencidas, recorrências, probabilidades e
   datas estimadas;
5. formalizar contratos de entrada de M12 e futuro M13 sem acesso cross-schema;
6. versionar cenários e congelar snapshots para auditoria histórica;
7. definir RBAC, SoD, tolerâncias, alertas e KPIs antes da UI.

Plano indicativo de commits:

| Commit | Slice |
| --- | --- |
| 187 | ADR, fronteiras, RBAC e VOs puros de posição/projeção |
| 188 | agregado `CashFlowProjection`, cenários e motor determinístico |
| 189 | Migration 0048, snapshots e repositório tenant-bound |
| 190 | projeções de realizado/previsto via contratos M12/M13 |
| 191 | consumers Inbox/Outbox, recomposição e eventos fora de ordem |
| 192 | APIs de posição, horizonte, cenários e liquidez com ETag |
| 193 | alertas de ruptura, concentração e sensibilidade de cenário |
| 194 | Cash Flow Cockpit responsivo e trilha explicável |
| 195 | E2E Chromium, runbook e fechamento da Sprint 21 |

Até a autoridade de recebíveis M13 estar implementada, nenhuma entrada futura
de caixa deve ser inventada ou inferida de faturamento. O motor deve expor a
lacuna de fonte como dado incompleto, não como saldo disponível.
