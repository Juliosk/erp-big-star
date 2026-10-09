# Runbook operacional — M11 Fiscal

## Escopo e fronteiras

O M11 é o único responsável pelo ciclo do documento fiscal eletrônico, pela comunicação com a SEFAZ e pela custódia dos XML/PDF. M6 fornece a origem comercial ou de compras por contrato; M5 e o futuro M12 reagem somente a eventos fiscais autorizados. Contas a Pagar, three-way match e escrituração financeira permanecem fora da Sprint 15.

Cada leitura, mutação e artefato é escopado por `company_id`. Documentos `AUTHORIZED` e `CANCELLED` preservam snapshots tributários imutáveis. O cockpit nunca acessa diretamente banco, MinIO ou transporte SEFAZ.

## Jornada operacional

1. Crie o rascunho no Cockpit Fiscal em `/ui/` e confira emitente, destinatário, itens e totais.
2. Acione **Solicitar emissão**. A API exige `If-Match`, `Idempotency-Key` e muda `DRAFT → ISSUING`.
3. Selecione o canal e processe a transmissão. O worker assina, envia e registra o retorno no mesmo limite transacional de documento, Audit e Outbox.
4. Em `AUTHORIZED`, confira chave, protocolo e histórico; visualize a DANFE/DANFCE e baixe o XML oficial.
5. Para cancelar dentro da janela legal, informe justificativa com no mínimo 15 caracteres. O evento `110111` aceito muda `AUTHORIZED → CANCELLED` e publica `FiscalDocumentCancelled`.

O botão **Processar retorno SEFAZ** usa o adapter determinístico apenas em `local/test`, com `DEV_AUTH_ENABLED=true`. Staging e produção falham fechados enquanto um gateway SEFAZ com certificado A1 não estiver explicitamente configurado.

## Status e respostas SEFAZ

| Estado ERP | cStat típico | Significado | Ação operacional |
|---|---:|---|---|
| `DRAFT` | — | Documento editável | Conferir dados e solicitar emissão |
| `ISSUING` | 103/105 | Lote recebido/em processamento | Aguardar consulta ou reprocessar de forma segura |
| `AUTHORIZED` | 100 | Uso autorizado | Liberar efeitos M5/M12 e distribuir DANFE/XML |
| `REJECTED` | 204, 539 | Duplicidade ou rejeição corrigível | Corrigir causa e gerar nova tentativa conforme regra fiscal |
| `DENIED` | 301, 302 | Uso denegado | Não reenviar como correção do mesmo documento |
| `CANCELLED` | 135/155 | Evento de cancelamento homologado | Confirmar estornos assíncronos e guardar `procEventoNFe` |

Erros locais relevantes: `VERSION_CONFLICT` exige recarga; `FISCAL_CANCELLATION_WINDOW_EXPIRED` impede cancelamento tardio; `FISCAL_CANCELLATION_REJECTED` preserva o documento autorizado; `FISCAL_DOCUMENT_NOT_EXPORTABLE` impede XML oficial antes da autorização; `FISCAL_STORAGE_UNAVAILABLE` indica indisponibilidade da custódia privada.

## Matriz de contingência

| Modalidade | Modelo | Uso | Observação |
|---|---|---|---|
| `NONE` | 55/65 | Autorizador normal | Caminho padrão |
| `SVC_AN` | 55 | SEFAZ Virtual de Contingência — AN | Ativação manual ou por política autorizada |
| `SVC_RS` | 55 | SEFAZ Virtual de Contingência — RS | Ativação manual ou por política autorizada |
| `OFFLINE_NFCE` | 65 | NFC-e offline | Transmitir posteriormente dentro do prazo legal |

Nunca use `OFFLINE_NFCE` para modelo 55 ou SVC para modelo 65. A escolha fica registrada no endpoint utilizado pelo gateway e no histórico operacional.

## RBAC

| Permissão | Capacidade |
|---|---|
| `fiscal.nfe.read` | Listar, detalhar e baixar artefatos da empresa autorizada |
| `fiscal.nfe.issue` | Criar rascunho, solicitar emissão e transmitir |
| `fiscal.nfe.cancel` | Solicitar o evento de cancelamento |
| `fiscal.nfe.correct` | Reservada para Carta de Correção em slice posterior |

Todas as permissões são combinadas com o escopo da empresa de trabalho. A API responde `404 RESOURCE_NOT_FOUND` sem enumerar documentos de outro tenant.

## Auditoria, eventos e artefatos

As transições fiscais gravam snapshot anterior/posterior no Audit e os eventos `FiscalDocumentAuthorized`, `FiscalDocumentRejected`, `FiscalDocumentDenied` e `FiscalDocumentCancelled` na Outbox. Consumidores M5/M12 devem usar Inbox e reagir exclusivamente ao evento autorizado/cancelado correspondente.

Os objetos privados seguem `{company_id}/{ano}/{mês}/{modelo}/{document_id}/v{version}/`. Downloads exigem autenticação e permissão, retornam `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` e digest SHA-256. Downloads repetidos da mesma versão reutilizam o artefato imutável.

## Diagnóstico e recuperação

- Consulte `/health/ready` antes de reprocessar.
- Em timeout, verifique circuit breaker e disponibilidade do autorizador; não crie outro documento para contornar uma resposta desconhecida.
- Em conflito de versão, recarregue o documento e confirme o histórico antes de repetir.
- Em falha do storage, preserve o estado fiscal; restaure MinIO e repita apenas o download.
- Compare Outbox e Inbox pelo `correlation_id` para rastrear efeitos em Estoque e Financeiro.

## Homologação da Sprint 15

Critérios: jornada Chromium completa, PDF iniciado por `%PDF`, XML `nfeProc`/`procEventoNFe`, isolamento cross-tenant, concorrência otimista, Audit/Outbox atômicos, Ruff e Mypy sem pendências e suíte global verde com cobertura de branches registrada no fechamento.

## Visão Wave 4

- Sprint 16: integração fiscal de entradas/saídas, manifestações e conciliação dos efeitos M5.
- Sprint 17: M12 Contas a Pagar — títulos, parcelas, vencimentos, baixas e eventos, sem acoplar ao schema M11.
- Sprint 18: three-way match M6/M11/M12 por contratos e Workflow M22 para divergências.
- Hardening: certificado por empresa, rotação segura, observabilidade SEFAZ, testes de carga e contingência controlada.
