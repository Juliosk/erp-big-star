# M23 — Importação de produtos por SKU

## Contrato operacional

Somente `ALL_OR_NOTHING` está habilitado. Até 1.000 linhas e 10 MiB por arquivo.
Uma falha estrutural, semântica, de concorrência ou de persistência impede a gravação de
todo o lote no catálogo. Staging, validações e Audit de tentativas aceitas são registros de
governança; não são alterações parciais em produtos. `VALID_ROWS_ONLY` e `BATCH_ATOMIC`
continuam reservados no domínio e são recusados pela API operacional.

Template `PRODUCTS_V1`, versão 1, aba `Produtos`:

| Campo | Novo SKU | SKU existente na empresa |
| --- | --- | --- |
| code | Obrigatório, código novo | Vazio ou igual ao atual; não altera identidade |
| sku | Obrigatório, texto | Chave de localização na empresa autorizada |
| name | Obrigatório | Novo nome obrigatório |
| product_type | PA, PI, MA, AUX, EMB ou KIT | Vazio ou igual ao atual |
| uom | Obrigatório | Nova unidade obrigatória |

Cabeçalhos e ordem devem permanecer iguais ao modelo. Não inserir outras colunas/abas;
`Instrucoes` é permitida. Identificadores são texto: não converter SKU para número.
Código/SKU/tipo/unidade são normalizados para maiúsculas pelo owner M2. Não repetir SKU
ou código no mesmo arquivo. Linhas totalmente vazias são ignoradas. Nome/unidade vazios
não significam "manter": são erro. Uma linha sem diferença é `UNCHANGED` e não gera
ProductUpdated nem incrementa a versão. Criações começam em `EM_DESENVOLVIMENTO`.

A unicidade global de SKU já homologada em M2 é preservada: um SKU usado por outra empresa
é recusado sem expor dados do catálogo estrangeiro. Código continua único por empresa.
Não há alteração de lifecycle, barcodes, preço, estoque, fiscal ou identidade por importação.
Mudanças materiais/saldos sujeitos a M22/SoD continuam fora deste template.

## Preparação local

1. Execute `alembic upgrade head` com o ambiente virtual do projeto. Head: **0013**.
2. No MinIO, provisione um bucket privado `erp-imports`, sem política de acesso anônimo.
   Crie credenciais de serviço limitadas a esse bucket. A aplicação precisa consultar a
   política do bucket (`s3:GetBucketPolicy`) e ler/gravar/remover seus objetos.
3. Configure `.env` usando os campos novos de `.env.example`:

```dotenv
IMPORT_STORAGE_ENDPOINT=127.0.0.1:9000
IMPORT_STORAGE_BUCKET=erp-imports
IMPORT_STORAGE_ACCESS_KEY=<credencial-de-servico>
IMPORT_STORAGE_SECRET_KEY=<segredo-da-credencial>
IMPORT_STORAGE_SECURE=false
```

Não copiar credenciais root para ambientes compartilhados. Fora de local/test, TLS é
obrigatório. A aplicação não cria buckets nem muda políticas durante requisições, não
gera URLs públicas e não retorna storage_key ou segredo à Web. Credenciais ausentes
mantêm as demais funções do ERP operacionais; upload retorna `IMPORT_STORAGE_UNAVAILABLE`.
Os testes de MinIO usam exclusivamente buckets aleatórios `erp-import-test-*`, com
credenciais locais de teste, e removem apenas os objetos/bucket que criaram.

4. Mantenha a autenticação homologada. Para Dev Auth, continue usando a flag explicitamente
   habilitada apenas em local/test e acrescente `data.import.execute` e `data.import.confirm`
   a `DEV_AUTH_PERMISSIONS`, preservando os grants atuais. Exige também
   `product.product.read`, `product.product.create` para novas linhas e
   `product.product.update` para existentes. Nunca configurar escopo global de worker.
5. Reinicie a API, conecte-se em `/ui/`, selecione a empresa e abra **Importações**.
   **Habilitar template de produtos** é um comando explícito e auditado, não um efeito de GET.

## Jornada e APIs

Todas as rotas usam Bearer e `company_id` obrigatório, com Error Contract e correlação.

| Operação | Rota sob `/api/v1/data` |
| --- | --- |
| Provisionar o template fixo | POST `/import-templates/product` |
| Listar templates | GET `/import-templates` |
| Baixar modelo | GET `/import-templates/{id}/download-model?template_version=1` |
| Enviar XLSX | POST `/imports?template_id={id}&template_version=1&filename=Produtos.xlsx` |
| Histórico, 20 registros/página | GET `/imports?page=1` |
| Detalhe/ETag | GET `/imports/{id}` |
| Validar | POST `/imports/{id}/validate` |
| Preparar preview | POST `/imports/{id}/preview` |
| Confirmar revisão | POST `/imports/{id}/confirm` |
| Gravar catálogo | POST `/imports/{id}/commit` |
| Cancelar antes da gravação | POST `/imports/{id}/cancel` |
| Baixar inconsistências | GET `/imports/{id}/rejected-file` |

Upload recebe **bytes XLSX no corpo**, não multipart nem JSON/base64; Content-Type:
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. Use `Idempotency-Key`.
Todos os comandos sobre job exigem `If-Match: "N"`, usando o ETag/versão atual.
Validate/preview/cancel recebem `{}`. Confirm/commit recebem
`{"fingerprint":"<fingerprint-do-preview>"}`. Commit também exige `Idempotency-Key`.

Fluxo feliz: UPLOADED v1 → VALIDATED v2 → PREVIEWED v3 → CONFIRMED v4 → COMMITTED v5.
Linhas inválidas resultam em REJECTED: consulte os erros e baixe o relatório. O source é
imutável; para corrigir células, envie outro arquivo/job. Revalidar o mesmo arquivo permite
atualizar a leitura do catálogo, mas invalida a confirmação anterior. Jobs cancelados ou
concluídos não podem ser reabertos nem alterados.

Preview contém linha, ação, current, proposed, differences e errors, além do fingerprint.
O relatório exporta erros como texto, sem fórmulas executáveis. A Web mantém token/linhas
apenas em memória, descarta respostas de contexto antigo e limpa dados ao sair/trocar empresa.

## Atomicidade, concorrência e eventos

`erp/apps/api/import_composition.py` injeta o adapter público M2 na transação M23.
M23 não importa ORM/repositórios internos de M2. Um único AsyncSession/transaction envolve
produtos, Audit M2/M23, Outbox, recibo `import_commit_batch` e resposta de idempotência.
Não há chamadas HTTP por linha nem commits individuais. Job é bloqueado por linha no
PostgreSQL; M2 bloqueia a leitura dos produtos e mantém CAS/constraints como última defesa.

Confirm e commit releem fonte/checksum, staging, regras, permissões e versões. Mudança desde
o preview retorna `IMPORT_PREVIEW_STALE`; revalidar, rever e confirmar novamente.
`VERSION_CONFLICT` indica ETag obsoleto. Retry após timeout deve reutilizar exatamente a
mesma chave/corpo/versão. Replay reavalia os grants atuais, sem duplicar produtos/eventos.

O lote limitado é processado de forma síncrona, retornando sucesso somente após commit no
PostgreSQL; não há um HTTP 202 fictício. A publicação da Outbox segue os workers Celery e
RabbitMQ já homologados. Importações maiores e processamento de commit em worker dedicado
não são habilitados por este limite inicial.

Eventos M23: ImportJobCreated, ImportValidationCompleted, ImportPreviewReady, ImportCommitted;
confirmação/cancelamento também são auditados e rastreados. ProductCreated/ProductUpdated
continuam emitidos por M2. O evento de criação preserva product_id, sku e product_type.
Falhas de comando seguem o Error Contract e não publicam sucesso. Metadados de observabilidade
não devem conter células, tokens ou segredos; parâmetros SQL ficam ocultos nas exceções.

## Recuperação e operação

- Falha em qualquer produto/Audit/Outbox: rollback da transação inteira; job não fica COMMITTED.
- Falha conhecida de upload após gravar o objeto: compensação remove somente a chave recém-criada.
- Resultado de commit de upload incerto: preserva o objeto; alerta `import.upload_outcome_uncertain`.
  Reconcilie pelo job_id antes de remover qualquer objeto. Não apagar fonte de job existente.
- `import.orphan_cleanup_failed`: remover o objeto somente após verificar inexistência do job.
- Falha de MinIO/checksum/staging impede validação/commit, sem degradação para carga parcial.
- Downgrade é exclusivo de banco descartável. 0013 recusa downgrade com jobs processados;
  não executar downgrade no banco homologado para testar reversibilidade.
- Docker indisponível: consulte o [incidente de 09/09/2026](docker-recovery-2026-09-09.md).
  Não usar factory reset/prune de volumes para corrigir soquetes residuais.

## Gates de homologação

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --cov=erp --cov-report=xml --cov-report=json --cov-report=term-missing --junitxml=test-results/sprint4.xml
.\.venv\Scripts\python.exe -m coverage report --include='erp/modules/governance/*' --fail-under=100 --precision=2
.\.venv\Scripts\python.exe -m coverage report --include='erp/modules/product/*' --fail-under=100 --precision=2
.\.venv\Scripts\python.exe -m pip_audit
```

Validar manualmente: criação + atualização no mesmo arquivo; uma linha inválida entre válidas;
mudança concorrente depois do preview; retry do commit; usuário sem grant de confirmação;
empresa diferente; histórico e inconsistências; navegação desktop/mobile. Sprint 5 somente
após homologação explícita do usuário.
