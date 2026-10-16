# Runbook operacional — Three-Way Match M6/M11/M12

## 1. Objetivo e limites

O Three-Way Match compara, por empresa, três fatos que permanecem proprietários
de seus bounded contexts:

1. pedido de compra do M6;
2. recebimento físico e documento fiscal de entrada do M6/M11;
3. provisão ou título financeiro do M12.

O módulo de matching não altera esses fatos. Ele congela referências versionadas,
executa regras determinísticas e mantém sua própria trilha append-only. O M22 é o
único responsável pela decisão formal de override. Persistência, FastAPI,
mensageria e modelos de outros módulos não entram no domínio puro.

## 2. Pré-requisitos operacionais

- Migration `0042` ativa.
- PostgreSQL, RabbitMQ e workers de Outbox/Inbox saudáveis.
- Pedido, recebimento, NF-e de entrada e provisão pertencentes ao mesmo
  `company_id`, fornecedor e moeda.
- Documento fiscal e recebimento em estados válidos para comparação.
- Definição M22 ativa para `PROCUREMENT / MATCHING_OVERRIDE`.
- Permissões mínimas:

| Operação | Permissão |
| --- | --- |
| Consultar sessões e fila | `procurement.matching.read` |
| Criar e executar sessão | `procurement.matching.execute` |
| Abrir solicitação de override | `workflow.request.create` |
| Aprovar ou rejeitar override | `workflow.approval.decide` |

Todo acesso também exige escopo da empresa de trabalho. Uma tentativa cross-tenant
é respondida como recurso não encontrado, evitando enumeração.

## 3. Ciclo da sessão

```text
PENDING → RUNNING → MATCHED
                  ↘ DISCREPANCY_DETECTED → OVERRIDDEN
                                          ↘ REJECTED
```

- `PENDING`: snapshot criado e ainda não avaliado.
- `RUNNING`: estado transitório registrado na mesma execução transacional.
- `MATCHED`: todas as linhas ficaram dentro das tolerâncias.
- `DISCREPANCY_DETECTED`: ao menos uma linha requer explicação ou ação.
- `OVERRIDDEN`: exceção aprovada pelo M22, com justificativa e SoD válidas.
- `REJECTED`: override recusado; a divergência não pode liberar o fluxo financeiro.

Cada mutação exige `If-Match`/ETag e `Idempotency-Key`. Um replay com a mesma
chave e o mesmo payload retorna o resultado original; a mesma chave com payload
diferente é rejeitada.

## 4. Catálogo de resultados e divergências

| Resultado | Interpretação | Conduta |
| --- | --- | --- |
| `MATCHED` | preço e quantidade dentro da política | seguir com o fluxo financeiro |
| `PRICE_MISMATCH` | preço unitário excede tolerância percentual/absoluta | validar contrato, imposto e desconto |
| `QUANTITY_MISMATCH` | pedido, recebimento e faturamento divergem | conferir doca, devolução ou saldo pendente |
| `TOLERANCE_EXCEEDED` | diferença combinada ultrapassa a política | corrigir fonte ou solicitar override |

Razões explicáveis são persistidas por linha. As mais comuns são
`UNIT_PRICE_TOLERANCE_EXCEEDED`, `QUANTITY_TOLERANCE_EXCEEDED` e
`ROUNDING_TOLERANCE_EXCEEDED`. O operador deve atuar no fato de origem; nunca
editar o snapshot histórico para “fazer bater”.

## 5. Regras de tolerância

A política é versionada e congelada com a sessão:

- variação percentual do preço unitário;
- variação percentual da quantidade;
- limite absoluto de arredondamento, normalmente `0,01`;
- versão da política da empresa.

O motor calcula o delta em precisão decimal. Uma diferença é aceita somente se
estiver dentro dos limites percentuais e absolutos aplicáveis. Alterar a política
corporativa não muda sessões concluídas; uma nova avaliação cria novo contexto
auditável.

## 6. Operação pelo cockpit Web

1. Abra `/ui/`, selecione a empresa e entre em **Compras**.
2. No painel **Three-Way Match**, abra **Nova sessão de conferência**.
3. Informe IDs de pedido, recebimento, NF-e, provisão e as referências dos itens.
4. Revise as tolerâncias e crie a sessão.
5. Confira o dossiê congelado nas colunas M6, M11 e M12.
6. Execute a conferência.
7. Em caso de divergência, leia o delta e a razão item a item.
8. Corrija o artefato de origem ou registre justificativa e solicite alçada M22.
9. Um aprovador distinto decide o override. O criador da compra ou lançador da
   nota não pode aprovar sua própria exceção.

A fila **Só divergências** é a caixa de trabalho operacional. A trilha lateral
registra criação, execução e decisão com versão e horário.

## 7. APIs oficiais

| Método | Rota | Uso |
| --- | --- | --- |
| `POST` | `/api/v1/procurement/matching-sessions` | criar snapshot e sessão |
| `POST` | `/api/v1/procurement/matching-sessions/{id}/execute` | executar motor determinístico |
| `GET` | `/api/v1/procurement/matching-sessions` | listar e filtrar sessões |
| `GET` | `/api/v1/procurement/matching-sessions/exceptions` | fila explicável |
| `GET` | `/api/v1/procurement/matching-sessions/{id}` | dossiê e audit log |
| `POST` | `/api/v1/procurement/matching-sessions/{id}/override` | solicitar alçada |
| `POST` | `/api/v1/procurement/matching-sessions/{id}/override/decide` | decidir override |

Mutations usam `company_id`, `Idempotency-Key` e, após a criação, `If-Match`.
Respostas de erro seguem o Error Contract e carregam `request_id`/
`correlation_id` para investigação.

## 8. Alçadas M22 e segregação de funções

- A definição deve possuir ao menos um nível que cubra o valor total da
  divergência; o último nível pode ser sem teto.
- O solicitante, comprador ou lançador fiscal não pode decidir a própria
  exceção (`SOD_VIOLATION`).
- Aprovações parciais avançam apenas o passo do workflow; a sessão permanece
  `DISCREPANCY_DETECTED` até a decisão final.
- Aprovação final gera `MatchingOverrideApproved` e transita para `OVERRIDDEN`.
- Rejeição gera `MatchingOverrideRejected` e transita para `REJECTED`.
- Justificativas devem descrever a evidência e a decisão, nunca apenas “de acordo”.

Audit e Outbox são gravados no mesmo transaction boundary da decisão.

## 9. Eventos assíncronos e reavaliação

O `MatchingEventConsumer` recebe alterações autorizadas de M6, M11 e M12 pelo
Inbox. As garantias são:

- deduplicação por mensagem;
- cursor monotônico por origem/agregado;
- versão e timestamp impedem regressão de estado;
- replay retorna resultado idempotente;
- evento atrasado ou fora de ordem não sobrescreve fato mais novo;
- snapshots concluídos continuam imutáveis.

Quando uma alteração válida torna a evidência atual obsoleta, o consumer marca a
necessidade de reavaliação e publica o evento correspondente via Outbox. O
operador cria/executa uma nova avaliação; não se reescreve a sessão histórica.

Procedimento para fila parada:

1. confirme saúde de RabbitMQ, worker e banco;
2. localize `message_id`, `aggregate_id`, versão e cursor no Inbox;
3. compare com a versão vigente do artefato de origem;
4. se for replay ou evento antigo, mantenha-o como processado/ignorado;
5. se for falha transitória, reenvie pela política de retry, sem editar payload;
6. encaminhe para DLQ após esgotar tentativas e preserve `correlation_id`.

## 10. Diagnóstico rápido

| Código/sintoma | Causa provável | Ação |
| --- | --- | --- |
| `PRECONDITION_REQUIRED` | `If-Match` ausente | releia o dossiê e reenvie com ETag |
| `VERSION_CONFLICT` | sessão mudou após a leitura | atualizar tela e revisar nova versão |
| `SOD_VIOLATION` | solicitante tentou aprovar | encaminhar a outro ator autorizado |
| alçada não cobre valor | workflow sem nível aplicável | ajustar definição M22; não forçar estado |
| fila vazia inesperada | empresa/filtro incorreto | conferir empresa de trabalho e status |
| sessão aguardando reavaliação | fonte mudou por evento assíncrono | verificar Inbox e executar nova sessão |

## 11. Homologação e evidências

Execução focada:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_matching_browser.py -q
```

O cenário Chromium cobre criação, execução com `PRICE_MISMATCH`, abertura de
override, decisão por outro ator e responsividade. Evidências visuais:

- `test-results/matching-cockpit-desktop.png`;
- `test-results/matching-cockpit-mobile.png`.

Antes de produção, executar também a suíte global, Ruff, Mypy e confirmar que o
Alembic está em `0042`.

## 12. Próxima etapa estratégica da Wave financeira

Após a Sprint 18, o próximo slice recomendado é **Execução de Pagamentos e
Tesouraria M12**:

1. ADR de fronteiras bancárias, RBAC e SoD de pagamento;
2. agregados de lote/ordem de pagamento e estados imutáveis;
3. schema tenant-bound, repositórios e concorrência otimista;
4. geração em dry-run e homologação antes de transmissão;
5. adaptadores bancários/CNAB com idempotência e confirmação explícita;
6. liquidação de títulos somente após retorno confirmado;
7. Outbox/Inbox, auditoria e contingência “nunca reenviar às cegas”;
8. cockpit, E2E e piloto de baixo valor antes de produção controlada.

Conciliação bancária completa deve entrar depois da confirmação segura do fluxo
de pagamento, mantendo o critério `Bank Statement = ERP Financial Position`
dentro de diferenças formalmente explicadas.
