# M11 — Entradas fiscais e conciliação físico-fiscal

## Objetivo e fronteiras

Este runbook cobre o recebimento de XML autorizado de fornecedor, a Manifestação
do Destinatário (MDE), a amarração explícita com o `GoodsReceipt` inspecionado e
o posting do saldo aprovado no ledger imutável do M5.

- M11 é owner do XML, chave de acesso, protocolo, MDE e relatório fiscal.
- M6 é owner do pedido e do recebimento físico.
- M17 é owner da decisão de inspeção e quarentena.
- M5 é owner do ledger e dos saldos físicos.
- M12 será owner das obrigações financeiras. O M11 apenas informa se existe
  bloqueio; não cria, altera ou liquida títulos.

Não existe associação automática por descrição, SKU aproximado ou posição. O
operador precisa vincular cada linha da NF-e a exatamente um item físico.

## Jornada operacional

1. Acesse **Fiscal → Entradas e conciliação** na empresa de trabalho correta.
2. Importe o XML `nfeProc` autorizado. O arquivo deve conter uma NF-e modelo 55,
   chave válida, protocolo, emitente, destinatário, itens e totais coerentes.
3. Confira fornecedor, chave, valores e itens no dossiê fiscal.
4. Transmita a manifestação adequada:
   - `210210`: Ciência da Operação;
   - `210200`: Confirmação da Operação;
   - `210220`: Desconhecimento da Operação;
   - `210240`: Operação não Realizada, com justificativa mínima de 15 caracteres.
5. No M6, conclua a conferência física e a inspeção M17. Apenas recebimentos em
   `INSPECTED` aparecem como candidatos à conciliação.
6. Selecione o recebimento e faça o de/para explícito de todas as linhas.
7. Execute **Conciliar e liberar estoque**. Um resultado `POSTED` cria os fatos
   do ledger M5 e atualiza `AVAILABLE` na mesma transação. Um resultado
   `DIVERGENT` não movimenta estoque.

Repetir upload, manifestação ou conciliação com a mesma `Idempotency-Key` é
seguro. Reutilizar a chave com payload diferente é rejeitado.

## Matriz de divergências

| Código | Significado | Estoque | Financeiro M12 futuro | Tratamento |
|---|---|---:|---:|---|
| `SUPPLIER_MISMATCH` | CNPJ/CPF do XML difere do fornecedor do PO | bloqueado | bloqueado | corrigir origem ou fornecedor |
| `LINE_MAPPING_MISMATCH` | linhas não cobertas de forma 1:1 | bloqueado | bloqueado | refazer amarração |
| `QUANTITY_MISMATCH` | aprovado fisicamente difere da NF-e | bloqueado | não bloqueia isoladamente | pendência física/devolução |
| `UNIT_PRICE_MISMATCH` | preço da NF-e difere do pedido | bloqueado | bloqueado | validar acordo comercial |
| `FISCAL_TOTAL_MISMATCH` | total de produtos diverge da valoração do PO | bloqueado | bloqueado | revisar XML/pedido |
| `SPECIFICATION_MISMATCH` | material recebido não atende ao pedido | bloqueado | não bloqueia isoladamente | devolução ou tratativa M17 |
| `INSPECTION_NOT_APPROVED` | inspeção não aprovou integralmente | bloqueado | não bloqueia isoladamente | quarentena/rejeição |

A tolerância monetária padrão é R$ 0,01 e pode ser ajustada até R$ 1,00 por
execução. A decisão e a tolerância ficam persistidas no relatório.

## Segurança, concorrência e rastreabilidade

| Operação | Permissão |
|---|---|
| Consultar XML, MDE e relatório | `fiscal.inbound.read` |
| Upload, manifestação e conciliação | `fiscal.inbound.manage` |
| Consultar recebimento candidato | `procurement.receipt.read` |

Todas as consultas são delimitadas por `company_id`; acesso cruzado responde
como recurso inexistente. Manifestações e conciliações exigem `If-Match`/ETag.
A conciliação bloqueia a NF-e de entrada e o recebimento com `SELECT FOR UPDATE`,
evitando posting duplo ou leitura de versões concorrentes.

Cada conciliação grava `AuditEvent` e publica `FiscalReceivingReconciled` na
Outbox na mesma transação. Quando aprovada, o evento `GoodsReceiptPosted` também
é publicado. Consumidores devem usar Inbox e manter idempotência por mensagem.

## Diagnóstico operacional

- `FISCAL_INBOUND_CONFLICT`: a chave de acesso já existe na empresa; abra o
  documento existente.
- `VERSION_CONFLICT`: atualize o dossiê e refaça a ação sobre a versão atual.
- `GOODS_RECEIPT_NOT_INSPECTED`: conclua o laudo M17.
- `RECONCILIATION_ALREADY_EXISTS`: consulte o relatório já persistido; ele é
  imutável como evidência da decisão.
- `RECONCILIATION_POSTING_INCOMPLETE`: existe item sem destino `AVAILABLE`;
  revise o laudo e as quantidades aprovadas.
- `FISCAL_RECONCILIATION_REQUIRED`: o posting direto do M6 foi bloqueado; use o
  fluxo fiscal oficial.
- `FISCAL_INBOUND_UNAVAILABLE`: verifique o bootstrap do serviço M11 e o adapter
  SEFAZ configurado para o ambiente.

Em incidentes, registre `request_id` e `correlation_id`, consulte Audit, Outbox e
Inbox e nunca edite manualmente o ledger, o XML fonte ou o relatório.

## Evidência de homologação da Sprint 16

O cenário Chromium cobre: upload XML → confirmação MDE `210200` → seleção do
recebimento inspecionado M6/M17 → amarração explícita → conciliação `POSTED` →
saldo `AVAILABLE` no M5. Capturas são gravadas em `test-results/` para desktop e
mobile, sem persistir token no navegador.

## Direção da Sprint 17 — M12 Contas a Pagar e provisões

O próximo slice deve preservar M12 como bounded context financeiro exclusivo:

1. ADR, matriz RBAC/SoD e contratos públicos M11/M6 → M12.
2. Agregados puros `Payable`, `PayableInstallment` e
   `ProvisionalFinancialEntry`, com moeda, vencimento e estados auditáveis.
3. Schema `finance`, migration reversível e repositórios tenant-bound com
   concorrência otimista.
4. Consumer Inbox de `FiscalReceivingReconciled`/`PayableRequested`: conciliação
   sem bloqueio converte provisão em obrigação; divergência mantém hold.
5. APIs de consulta, criação controlada, aprovação e cancelamento, com ETag,
   Idempotency-Key, Audit e Outbox.
6. Cockpit de Contas a Pagar, testes concorrentes e E2E.

Liquidação bancária, lote de pagamentos, conciliação bancária e three-way match
ampliado permanecem fora do primeiro slice e exigem DoR próprio.
