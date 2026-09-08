# M2 Product Master — homologação 036–039

## Preparação local

Use PowerShell na raiz `C:\Users\Ti\Desktop\CODEX\ERP`. Não substitua o `.env` já homologado.
PostgreSQL e RabbitMQ precisam estar ativos; o usuário já homologou as fundações M1/Platform.

```powershell
.\.venv\Scripts\uv.exe sync --locked
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m playwright install chromium
```

Head esperado: `0011`. Upgrade preserva produtos existentes. Downgrade de 0011 apaga barcodes;
exige backup e autorização fora de banco descartável. Não executar downgrade para homologar.

## Identidade de desenvolvimento — somente local/test

O adapter não usa token padrão nem cria usuários/grants no banco. O ator simulado é explícito;
empresas devem existir e estar ativas em M1. O backend continua validando permissões e escopos.
Para localizar empresas, consulte a API M1 já homologada ou execute, com acesso administrativo:

```sql
SELECT id, code, legal_name FROM admin.company WHERE status = 'ACTIVE' ORDER BY code;
```

Em um PowerShell exclusivo para o servidor:

```powershell
$env:ENVIRONMENT = 'local'
$env:DEV_AUTH_ENABLED = 'true'
$env:DEV_AUTH_TOKEN = & .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))'
$env:DEV_AUTH_ACTOR_ID = [guid]::NewGuid().ToString()
$env:DEV_AUTH_COMPANY_IDS = '["SUBSTITUA-PELO-UUID-DA-EMPRESA"]'
# Opcional: limita os grants. O padrão explícito do adapter contém M1 company.read e os grants M2.
# $env:DEV_AUTH_PERMISSIONS = '["admin.company.read","product.product.read"]'
$env:DEV_AUTH_TOKEN | Set-Clipboard
.\.venv\Scripts\python.exe -m uvicorn erp.apps.api.app:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000/ui/`, cole o token em **Token de acesso** e clique **Conectar**.
Limpe a área de transferência após colar. Ela e o histórico do gerenciador de clipboard podem
conter o segredo temporário. Nunca reutilize esse segredo em outros ambientes.
O Bearer é anexado às chamadas oficiais pelo cliente e mantido apenas em memória: não aparece
no HTML, URL, logs, localStorage ou sessionStorage. Sair/recarregar elimina a conexão da página.
O botão Sair não revoga o token do servidor: para revogar/rotacionar, pare e reinicie o servidor
com outro token. Feche esse PowerShell após a homologação; não exporte essas flags para produção.

Token deve ter 32–256 caracteres ASCII sem espaços. Ator e empresas são UUIDs válidos. Flag em
staging/production impede startup, inclusive configuração adulterada via model_copy. Sem flag,
a injeção explícita de DevSecurityContextResolver também é recusada.
Sem adapter configurado: 503; token ausente/inválido: 401; grant insuficiente: 403; fora do escopo: 404.

## Roteiro funcional

1. Selecionar empresa autorizada e criar produto (code, SKU, nome, tipo e unidade). Esperar versão 1.
2. Conferir List/Detail, filtro de lifecycle, paginação e ausência de produtos de outra empresa.
3. Alterar nome/unidade. PATCH efetivo incrementa versão; no-op preserva a versão.
4. Abrir dois detalhes, alterar um e salvar o outro: VERSION_CONFLICT. Usar **Atualizar detalhe**,
   revisar e reaplicar conscientemente; não sobrescrever a versão do servidor automaticamente.
5. Adicionar EAN `4006381333931`, EAN-8 `96385074`, DUN `04006381333931` ou INTERNAL `0001-ABC`.
   Código é texto. Dígito inválido retorna 422; repetição na mesma empresa, 409 BARCODE_CONFLICT.
   O mesmo barcode pode existir em outra empresa; produto de outro tenant não pode ser vinculado.
6. Enviar para homologação, ativar e descontinuar. Nenhum salto ou reversão é aceito.
7. Repetir com grants somente read: botões de escrita não aparecem ou ficam desabilitados;
   chamadas HTTP forjadas continuam sendo recusadas pelo backend.
8. Reenviar um comando com a mesma chave/payload: mesma resposta, sem novos efeitos.
   Remover a permissão antes do replay: 403, mesmo com chave já concluída.

## Contratos dos comandos finais

Todos os caminhos abaixo começam em `/api/v1/products/{product_id}` e exigem `company_id` na query.

| Operação | Grant | Headers obrigatórios | Resultado |
| --- | --- | --- | --- |
| POST /submit-for-homologation | product.product.activate | Bearer, If-Match, Idempotency-Key | 200 + ETag; ProductUpdated |
| POST /activate | product.product.activate | Bearer, If-Match, Idempotency-Key | 200 + ETag; ProductActivated |
| POST /discontinue | product.product.discontinue | Bearer, If-Match, Idempotency-Key | 200 + ETag; ProductDiscontinued |
| GET /barcodes | product.product.read | Bearer | 200 + data |
| POST /barcodes | product.product.update | Bearer, If-Match, Idempotency-Key | 201 + ETag; ProductBarcodeChanged |

`If-Match: "3"` é forte e inteiro. Ausente: 428; malformado: 400; obsoleto: 409 VERSION_CONFLICT.
Idempotency-Key ausente: 422; reaproveitado com outro payload: 409. Novas tentativas técnicas
devem preservar chave, payload e versão original. Lifecycle e barcode disputam a mesma versão
do Product; existe exatamente um vencedor por versão, inclusive entre tipos de comando distintos.

O POST de barcode recebe `{"barcode_type":"EAN","barcode":"4006381333931"}`. A resposta contém
produto, barcode, event_id, audit_event_id e idempotency_replayed. Não há DELETE/PATCH de barcode
neste contrato. Ativar o cadastro não equivale a aprovação fiscal, regulatória ou liberação de estoque.

## Audit e mensageria

Agregado/versão, barcode, Audit, Outbox e idempotência são confirmados na mesma transação.
Audit inclui ator, empresa, request/correlation IDs, snapshots e barcode adicionado. Falha em
Audit/Outbox reverte tudo, inclusive a versão e a reserva da chave.

O HTTP enfileira; não publica diretamente no RabbitMQ. O publisher da plataforma usa confirms.
Evento pendente com `published_at` nulo é esperado até execução do publisher/worker. Não purgar
filas compartilhadas nem marcar manualmente mensagens como publicadas para eliminar backlog.
Investigue falhas com event_id/correlation_id e `publish_attempts`/`last_error` na Outbox.

| Evento v1 | Routing key padrão |
| --- | --- |
| ProductCreated | product.product.created.v1 |
| ProductUpdated | product.product.updated.v1 |
| ProductActivated | product.product.activated.v1 |
| ProductDiscontinued | product.product.discontinued.v1 |
| ProductBarcodeChanged | product.product.changed.v1 |

Envelope transporta company_id, aggregate_version e correlação. O E2E usa publisher real,
fila exclusiva temporária e consumidor de prova via Inbox; verifica duplicatas e processamento
durável. Não antecipa projeções de negócio de M3/M10, que pertencem às suas próprias Sprints.
Produção requer essas filas/consumidores cadastrados; publicação mandatory sem binding falha
e mantém o evento para nova tentativa. Não interpretar Outbox persistida como entrega confirmada.

## Gate reproduzível

Execute em PowerShell sem as flags de Dev Auth do servidor; a suíte configura identidades próprias.

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe erp tests migrations
.\.venv\Scripts\python.exe -m pytest --cov=erp --cov-report=term-missing --cov-report=xml
.\.venv\Scripts\python.exe -m coverage report --include='erp/modules/product/*' --fail-under=100 --precision=2
.\.venv\Scripts\uv.exe lock --check
.\.venv\Scripts\python.exe -m pip_audit
```

No Linux/CI, instalar antes `uv run playwright install --with-deps chromium`. Não omitir o marker
browser para declarar o slice validado. Screenshots desktop/mobile ficam em `test-results/`,
ignorado pelo Git, com dados exclusivamente de fixture. Cobertura Python não mede JavaScript:
a UI é verificada pelos cenários Chromium, erros de página e inspeção das capturas.

Fora do aceite: autenticação produtiva, aplicabilidade global, BOM, variantes, packaging, fiscal,
preços, estoque e importação. Não avançar à Sprint 4 sem homologação explícita do usuário.
