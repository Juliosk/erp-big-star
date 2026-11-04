# Runbook operacional — Fluxo de Caixa e Projeções de Liquidez M12

## 1. Objetivo, autoridade e limites

Este runbook governa a composição, leitura e recuperação das projeções de
liquidez do M12. O subsistema consolida posição bancária conciliada, obrigações
financeiras comprometidas e fontes autorizadas de recebimento em snapshots
versionados por `company_id`.

O fluxo de caixa é uma visão gerencial de liquidez. Ele não substitui razão
contábil, orçamento, DRE, extrato bancário nem baixa financeira. O M12 não pode
inferir caixa a partir de pedido, faturamento, documento fiscal ou expectativa
comercial. A fronteira oficial está registrada no ADR 0181.

Componentes operacionais:

```text
posição bancária conciliada ───────┐
parcelas a pagar comprometidas ────┼─► CashFlowEngine ─► snapshot imutável
recebíveis autorizados M13 ────────┘         │
CashFlowSourceGap ─► incompletude explícita  ├─► alertas Audit + Outbox
cenário manual ─► projeção stateless ─────────┘
```

## 2. Pré-requisitos e classificação de segurança

- Alembic em `0050 (head)` e PostgreSQL saudável.
- Workers de Inbox/Outbox ativos para recomposições assíncronas.
- Conciliação bancária atualizada e compromissos do M12 íntegros.
- Empresa de trabalho correta e identidade com escopo explícito.
- Timezone, data-base, moeda, calendário e reserva mínima confirmados.

Snapshots, saldos, compromissos, cenários e alertas são dados `RESTRICTED`.
Não copie valores reais para chamados públicos, logs manuais ou ferramentas não
homologadas. Para diagnóstico, use IDs, versões, `request_id`,
`correlation_id` e `message_id`; mascare conta, favorecido e documento.

Permissões oficiais:

| Operação | Permissão | Risco |
| --- | --- | --- |
| Consultar horizontes, snapshots e alertas | `finance.cash_flow.read` | alto |
| Criar ou recompor posição autoritativa | `finance.cash_flow.project` | crítico |
| Executar cenário stateless | `finance.cash_flow.scenario` | crítico |

Todas as operações combinam RBAC com `company_id`. Acesso cross-tenant não
enumera dados e deve responder como recurso ausente ou coleção vazia.

## 3. Fontes e semântica financeira

Cada linha possui categoria (`OPERATING`, `FINANCING`, `INVESTING`), direção,
origem e grau de certeza:

| Certeza | Significado | Entra na posição operacional? |
| --- | --- | --- |
| `REALIZED` | fato bancário/financeiro confirmado | sim |
| `COMMITTED` | obrigação ou recebível autorizado e exigível | sim |
| `SCENARIO` | premissa manual de sensibilidade | não |

Regras obrigatórias:

1. montantes usam `Decimal`, duas casas e moeda ISO 4217;
2. moedas não são convertidas implicitamente;
3. transferências internas não podem ser contadas como entrada e saída
   econômica no consolidado;
4. pagamento enviado ao banco não é realizado até confirmação e conciliação;
5. cenário nunca altera o snapshot operacional;
6. fonte ausente gera lacuna, não valor estimado.

## 4. Regra anti-especulação do M13

Enquanto o M13 não fornecer recebíveis autoritativos, o motor registra
`CashFlowSourceGap(source=RECEIVABLES)`. O estado resultante é `INCOMPLETE`,
mesmo quando o saldo numérico aparenta ser positivo.

É proibido preencher a lacuna com:

- valor de pedidos, cotações ou carrinhos;
- notas fiscais emitidas sem título a receber autorizado;
- médias históricas ou metas comerciais;
- cópia manual de planilhas sem contrato de origem;
- premissa de cenário promovida a fluxo comprometido.

No Cockpit, **Dados incompletos** exige leitura conservadora. O operador pode
simular uma hipótese, mas não pode apresentar o resultado como caixa disponível.

## 5. Horizontes e estados de liquidez

| Horizonte | Intervalo inclusivo | Uso operacional |
| --- | --- | --- |
| curto prazo | até 90 dias | caixa diário/semanal e rupturas imediatas |
| médio prazo | 91 a 365 dias | compromissos sazonais e capital de giro |
| longo prazo | acima de 365 dias | estrutura de dívida e investimentos |

Estados:

- `HEALTHY`: fechamento operacional igual ou superior à reserva mínima;
- `ATTENTION`: saldo não negativo, porém abaixo da reserva;
- `CRITICAL`: saldo operacional negativo;
- `INCOMPLETE`: falta fonte obrigatória; tem precedência sobre os demais.

O calendário ajusta ocorrências conforme a convenção configurada. Ao comparar
snapshots, confirme data-base, horizonte, granularidade, moeda, calendário e
versão; saldos iguais com parâmetros diferentes não são equivalentes.

## 6. Jornada no Cockpit `/ui/finance/cash-flow`

1. Conecte uma identidade autorizada e selecione a empresa de trabalho.
2. Abra **Fluxo de caixa** e escolha curto, médio ou longo prazo.
3. Confira ETag, instante de cálculo, moeda, período e estado de completude.
4. Leia os quatro marcos: abertura, fechamento operacional, fechamento do
   cenário e reserva de segurança.
5. No radar de runway, compare a linha operacional com a reserva. A região
   sombreada indica exposição abaixo do limite.
6. Revise a composição de realizado, comprometido e cenário antes de agir.
7. Abra cada alerta da fila e relacione valor, limite, data e origem.
8. Use **Recalcular posição** somente após confirmar que fontes upstream estão
   atualizadas. A ação exige ETag e cria nova versão.

O gráfico é uma ferramenta de navegação, não a evidência única. Para decisão
financeira, confronte buckets, fontes, gaps, alertas e dados upstream.

## 7. Simulações stateless e recuperação

O modal **Simular cenário** aceita atraso de recebíveis e variação de custos.
O resultado:

- usa a versão operacional informada em `If-Match`;
- exige `Idempotency-Key`;
- não persiste um novo snapshot operacional;
- não muda saldo, compromisso, conciliação ou agenda bancária;
- pode gerar alertas auditáveis associados à simulação;
- permanece somente na tela até **Voltar ao operacional** ou recarregar.

Se o cenário parecer incorreto:

1. clique **Voltar ao operacional**;
2. confira versão e parâmetros digitados;
3. recarregue a projeção base;
4. valide gaps e fontes antes de repetir;
5. use uma nova chave idempotente apenas quando o conteúdo mudar.

Não “corrija” um cenário editando snapshot, alerta, Audit ou Outbox. Um replay
com a mesma chave e mesmo payload devolve o mesmo resultado; chave igual com
payload diferente é conflito de idempotência.

## 8. Alertas e conduta operacional

A Migration `0050` mantém `finance.cash_flow_alert` append-only. Cada alerta
novo grava Audit e Outbox na mesma transação.

| Tipo | Interpretação | Conduta |
| --- | --- | --- |
| `CASH_RUPTURE` | saldo projetado negativo | congelar desembolsos não essenciais e escalar tesouraria |
| `SAFETY_THRESHOLD` | saldo abaixo da reserva | revisar vencimentos, disponibilidade e contingência |
| `DATE_CONCENTRATION` | volume excessivo numa data | redistribuir agenda somente por fluxo autorizado |
| `CATEGORY_CONCENTRATION` | dependência de uma rubrica | validar origem e exposição estrutural |
| `EXPOSURE_CONCENTRATION` | fornecedor/lote domina o fluxo | revisar concentração e plano alternativo |
| `DAILY_OUTLIER` | pico fora do comportamento do horizonte | validar duplicidade, data e montante upstream |
| `SCENARIO_SENSITIVITY` | premissa altera materialmente o fechamento | registrar risco e comparar cenários segregados |

Eventos publicados:

- `CashFlowLiquidityAlertTriggered`;
- `CashFlowConcentrationAlertTriggered`;
- `CashFlowSensitivityAlertTriggered`.

Alertas determinísticos podem reaparecer em versões diferentes. Não deduplique
por título visual: use ID, projeção, versão, fonte e chave do sujeito. Não apague
alertas resolvidos; registre a ação corretiva e gere nova projeção.

## 9. APIs, concorrência e contratos HTTP

Base: `/api/v1/finance/cash-flow`.

| Método e rota | Uso |
| --- | --- |
| `POST /projections` | criar posição inicial idempotente |
| `GET /horizons/{horizon}` | consultar snapshots mais recentes |
| `GET /projections/{id}` | detalhar buckets, itens e gaps |
| `POST /projections/{id}/recalculate` | recompor e versionar posição |
| `POST /scenarios` | simular sem persistir snapshot operacional |
| `GET /alerts` | consultar fila tenant-bound de alertas |

Criação, recomposição e cenário exigem `Idempotency-Key`. Recomposição e
cenário exigem `If-Match: "N"`; leituras detalhadas devolvem ETag. Em
`VERSION_CONFLICT`, recarregue o snapshot e reavalie a decisão. Respostas usam
Error Contract e `Cache-Control: no-store`.

## 10. Recomposição assíncrona e ordem de eventos

Eventos autorizados de pagamentos, conciliação e recebíveis alimentam Inbox e
uma fila durável de recomposição. O processamento aplica:

- deduplicação por mensagem;
- cursor monotônico por tenant, produtor e agregado;
- versão e timestamp para rejeitar entrega antiga;
- `SELECT FOR UPDATE SKIP LOCKED` para workers concorrentes;
- novo snapshot, alertas, Audit e Outbox no mesmo limite transacional.

Ao concluir, publica `CashFlowProjectionRecomposed`. Evento antigo, duplicado
ou fora de ordem não pode regredir a posição. Para fila parada, compare Inbox,
cursor, pedido de recomposição, versão do snapshot e DLQ usando os IDs de
correlação; não republique payload editado.

## 11. Catálogo de falhas

| Código/sintoma | Causa provável | Recuperação segura |
| --- | --- | --- |
| `PRECONDITION_REQUIRED` | `If-Match` ausente | reler projeção e enviar ETag |
| `VERSION_CONFLICT` | snapshot mudou | atualizar cockpit e revisar nova versão |
| `CASH_FLOW_CONFLICT` | identidade/regra de projeção conflita | consultar snapshot existente e parâmetros |
| `CASH_FLOW_PROJECTION_EXISTS` | criação repetida com nova chave | usar recomposição, não duplicar identidade |
| `PERMISSION_FORBIDDEN` | RBAC insuficiente | corrigir papel sem ampliar tenant |
| `RESOURCE_NOT_FOUND` | ID ausente ou empresa incorreta | conferir contexto; não enumerar tenants |
| `FINANCE_CASH_FLOW_UNAVAILABLE` | composição não inicializada | verificar aplicação e banco; não operar por SQL |
| `INCOMPLETE` | fonte autoritativa ausente | manter gap, corrigir integração; não estimar caixa |
| alerta duplicado aparente | versões/fontes diferentes | comparar ID, versão, source e subject key |
| worker sem avanço | lock, cursor, retry ou DLQ | investigar Inbox/fila e retomar pela política oficial |

## 12. Observabilidade e gates de fechamento

Monitore por empresa e moeda:

- idade do último snapshot e versão atual;
- posição operacional versus reserva por horizonte;
- quantidade e idade de `CashFlowSourceGap`;
- rupturas por data e severidade;
- concentração por categoria e exposição;
- diferença entre operacional e cenários;
- latência, retries e DLQ das recomposições;
- replays de idempotência e conflitos de versão.

Gate diário mínimo:

```text
posição bancária conciliada
+ compromissos financeiros autorizados
+ recebíveis autoritativos disponíveis
= snapshot versionado e explicável
```

Não declare a liquidez “saudável” com fonte obrigatória incompleta, extrato não
conciliado, snapshot vencido ou alerta crítico sem tratamento registrado.

## 13. Recuperação segura e continuidade

1. preserve volumes e colete `request_id`, `correlation_id`, versão e horário;
2. valide PostgreSQL, RabbitMQ, workers e Alembic;
3. confirme se a falha está na fonte, Inbox, fila, motor ou Outbox;
4. use retry/DLQ oficial e idempotência; nunca edite fatos diretamente;
5. após recuperar, gere nova projeção e compare com a última versão válida;
6. registre impacto, decisão e evidência no incidente.

Nunca execute factory reset, `docker system prune -a --volumes`, remoção de
volumes ou `UPDATE/DELETE` manual em snapshots, alerts, Audit, Inbox ou Outbox.
O rollback operacional é uma nova composição correta, não a destruição do
histórico.

## 14. Homologação técnica

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m ruff check erp tests migrations
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\integration\test_cash_flow_api.py tests\integration\test_cash_flow_alerts.py tests\integration\test_cash_flow_event_consumers.py tests\integration\test_cash_flow_browser.py -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib -q
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib --cov=erp --cov-branch --cov-report=term-missing -q
```

O E2E Chromium valida navegação tenant-bound, runway SVG, gaps explícitos,
alertas persistidos, simulação stateless, retorno ao operacional, layout
desktop/mobile, ausência de storage no navegador e ausência de overflow global.

## 15. Encerramento do ecossistema financeiro

Com a Sprint 21, o M12 passa a cobrir a cadeia financeira operacional completa:

| Capacidade | Evidência operacional | Situação |
| --- | --- | --- |
| Contas a Pagar | `finance-runbook.md` | concluída |
| Three-Way Match e governança | `matching-runbook.md` | concluída |
| Execução de pagamentos e Tesouraria | `treasury-runbook.md` | concluída |
| Conciliação bancária | `bank-conciliation-runbook.md` | concluída |
| Fluxo de Caixa e liquidez | este runbook | concluída |

Esse encerramento certifica o slice técnico entregue; não substitui
homologação bancária por convênio, parametrização contábil, cadastro produtivo,
treinamento de operadores, plano de continuidade ou implantação do futuro M13.
Novas capacidades financeiras devem abrir ADR/DoR próprios e preservar as
fronteiras, SoD, Audit, Outbox/Inbox e isolamento multi-tenant estabelecidos.

## 16. Evidência de fechamento — Sprint 21 / Commit 195

Homologação executada em 4 de novembro de 2026:

- `1.887` testes globais aprovados;
- cobertura global com branches: `91,87%` (`26.042` statements e `5.490`
  branches instrumentados);
- gate mínimo de cobertura `80%` atendido;
- Mypy sem inconsistências em `824` arquivos;
- Ruff aprovado em `erp`, `tests` e `migrations`;
- Chromium E2E aprovado em desktop e mobile;
- Alembic confirmado em `0050 (head)`;
- único warning: depreciação externa de `anyio.abc.BlockingPortal` no
  `starlette.testclient`, sem falha funcional.

Com essas evidências, a Sprint 21 e o ecossistema financeiro M12 estão
tecnicamente encerrados no escopo definido neste runbook.
