# Sprint 4 — M23 Product Import / W1

## 1. Objetivo

Importar produtos por uma carga governada: Template XLSX → Upload/Staging → Validation →
Preview → Confirm → Commit → Product Master. M23 orquestra; M2 preserva a autoridade semântica.
Baseline: Etapa 10 §§65–69, §70/VS-003 e §147; Etapa 2 §§74–75; Etapa 4 §§11 e 58;
Etapa 5 §§76–78; Etapa 6 §79; Etapa 7 §§92–94; Etapa 9 §12; README de governança §19.
Sprint 3 homologada expressamente pelo usuário em 2026-09-08.

## 2. Escopo

Templates versionados, upload XLSX privado com checksum, staging, validação estrutural e de
negócio pelo owner M2, preview de valores/diferenças/erros, confirmação e commit idempotente.
Modos corporativos: ALL_OR_NOTHING, VALID_ROWS_ONLY, BATCH_ATOMIC, conforme versão do template.
Primeiro lote 040–042: domínio de templates/jobs, schema e repositórios por empresa. Não expõe
upload/commit pela API antes de compor autorização, armazenamento seguro, Audit e Outbox.

## 3. Fora de escopo

Exports gerais, saldos iniciais, migração histórica/transacional, fiscal, BOM, preço, estoque,
merge/deduplicação avançada, retenção/anonymization e integração produtiva de identidade.
Templates globais ou company_id nulo não habilitados. Nenhum SQL M23 em tabelas de produto.

## 4. Dependências

M1 RBAC/CompanyAccessService; M2 Product Master homologado; PostgreSQL/Alembic; plataforma
Audit, Outbox/Inbox, Error Contract, Idempotency e Celery. MinIO está operacional, mas o adapter
de armazenamento deve ser implementado/testado no lote de upload. M22 para mudanças materiais
continua posterior: não presumir aprovação nem contornar SoD para habilitar uma carga crítica.

## 5. DoR Check

- [x] Wave/Sprint e owner M23 confirmados; M2 permanece dono do cadastro final.
- [x] Entidades oficiais import_template, import_template_version e import_job identificadas.
- [x] Empresa obrigatória; Foundation FK para admin.company, sem cascade cross-domain.
- [x] Versões de template imutáveis; jobs referenciam versão exata da mesma empresa.
- [x] SHA-256, storage_key e metadados, sem BLOB no PostgreSQL (Etapa 8 §§29–32).
- [x] APIs, eventos e permissões oficiais identificados para os lotes correspondentes.
- [x] Testes de limites, isolamento, imutabilidade, migração e CAS definidos para 040–042.
- [x] Usuário definiu criação e atualização por SKU. Update preserva o contrato M2 homologado:
      nome/unidade, somente na empresa autorizada, com versão capturada no preview e CAS no commit.
- [ ] Confirmar modo inicialmente habilitado no template antes do commit funcional.
- [ ] Se houver atualização material, definir aprovação M22 e fingerprint: NOT_READY até definição.

As decisões ainda pendentes foram apresentadas ao usuário. Elas não bloqueiam a fundação, que não
instala template operacional, não escolhe modo implícito e não grava produtos.
Limites técnicos iniciais, não atribuídos à arquitetura: até 100 campos, 10 MiB por XLSX,
nomes de até 255 caracteres; parser ainda deverá impor limites de expansão ZIP/linhas/células
e rejeitar fórmulas, macros, links externos e arquivos não-XLSX antes da exposição HTTP.

## 6. Backlog ordenado

040 domínio → 041 migration → 042 persistência → 043 template/storage → 044 upload/parsing
→ 045 validação → 046 preview → 047 confirmação → 048 commit → 049 UI/E2E/runbook.

## 7. Arquivos

```text
erp/modules/governance/
  domain/import_template.py        # template, versão, campos, modos, fingerprint
  domain/import_job.py             # metadados do arquivo/job e cancelamento inicial
  infrastructure/import_models.py
  infrastructure/template_repository.py
  infrastructure/job_repository.py
  README.md
migrations/versions/0012_create_import_foundation.py
tests/unit/modules/governance/
tests/integration/test_import_foundation.py
docs/sprint-4-product-import.md
```

Nos lotes seguintes: application/api M23, staging/validation/commit_batch, contratos públicos
de bulk data do M2, adapter S3 em platform/storage e telas em apps/web. Nenhum ORM cruza a porta.

## 8. Migrations

0012 após 0011: schema governance; import_template (MASTER), import_template_version (VERSION),
import_job (TRANSACTION). UUIDs, TIMESTAMPTZ, created/updated_by, constraints, índices por tenant.
FKs compostas impedem usar template/versão de outra empresa. Trigger recusa UPDATE de versões
publicadas; novo layout exige INSERT com número novo. Repositório não oferece delete de histórico.
Job tem version e cancelamento com CAS; fases posteriores exigirão extensão explícita do domínio/schema.
Downgrade destrutivo para os objetos novos: ida/volta somente em banco descartável.

## 9. APIs planejadas

Base `/api/v1/data`: GET /import-templates e /{id}/download-model; POST /imports; GET /imports/{id};
POST /imports/{id}/validate, /preview, /confirm, /commit, /cancel; GET /imports/{id}/rejected-file.
Company scope obrigatório, DTOs sem ORM, If-Match em comandos concorrentes, Idempotency-Key
em efeitos repetíveis; falhas seguem Error Contract. Nenhuma dessas rotas é habilitada em 040–042.

## 10. Events / Contracts

M23: ImportJobCreated, ImportValidationCompleted, ImportPreviewReady, ImportCommitted,
ImportPartiallyCommitted e ImportFailed v1, quando suas fases forem implementadas.
ImportApprovalRequested é request M22 para mudanças materiais; não é autorização RBAC.
M2: ProductBulkDataAdapter / ImportValidationProvider / ImportCommitProvider, conforme Etapa 4.
Validação, autorização, versão e escrita de produtos continuam dentro do owner M2.
Contratos e fronteira transacional serão testados antes de habilitar o modo ALL_OR_NOTHING;
nunca simular atomicidade de lote encadeando chamadas que façam commit individualmente.

## 11. Permissions / Scope / SoD

Permissões específicas da Etapa 5: data.import.execute e data.import.confirm, somadas às
permissões M2 de criação/atualização aplicáveis. Não usar o exemplo genérico governance.import.commit
como grant alternativo implícito. Revalidar grants/empresa antes de confirmação, execução e replay.
Contas de worker não recebem escopo global automático. Upload crítico não aprova o próprio lote.

## 12. Audit

Upload aceito, confirmação, cancelamento e commit público terão ator/empresa, request/correlation
IDs, snapshots/fingerprint e Audit/Outbox transacionais. 040–042 persistem apenas metadados
internos e actor stamps: não constituem ainda o fluxo público auditado nem carga operacional.

## 13. Tests

Domínio puro; fronteiras AST; PostgreSQL real; FKs compostas; unicidade por empresa;
round-trip; rollback; template imutável; concorrência de versões; job CAS; ator obrigatório;
negação de tenant forjado, inclusive no save. Meta: M23 100% com branches, M2 100% preservado,
gate global existente sem redução. Depois: XLSX hostil, replay, RBAC, preview obsoleto,
rollback integral/partial/batch conforme modo, E2E Chromium/MinIO/M2/eventos.

## 14. Observability

Usar logging JSON e Error Contract existentes. Nenhum conteúdo de planilha, token ou URL
assinada em logs. Fases públicas registrarão job_id/company_id, contagens, duração, falhas,
request/correlation IDs. Métricas não usarão identificadores livres como labels de alta cardinalidade.

## 15. Atomic Commit Plan

| Commit | Entrega | Aceite |
| --- | --- | --- |
| 040 | feat(governance): define import foundation aggregates | Domínio puro, fingerprint, testes |
| 041 | migration(governance): add tenant-owned import foundation | 0012, constraints, imutabilidade |
| 042 | feat(governance): persist scoped templates and jobs | Isolamento, rollback, CAS, gates |
| 043 | feat(governance): provide versioned XLSX templates | Modelo e storage privado testados |
| 044 | feat(governance): stage product import uploads | Upload seguro, parsing, jobs/Audit/Outbox |
| 045 | feat(governance): validate product import rows | Estrutura + contrato semântico M2 |
| 046 | feat(governance): preview import differences | Current/new/diff, erros, fingerprint |
| 047 | feat(governance): confirm scoped import jobs | RBAC, SoD, versão e revalidação |
| 048 | feat(governance): commit products through owner contracts | Modos por template, atomicidade, replay |
| 049 | test(governance): complete product import vertical slice | Wizard, rejected rows, E2E e runbook |

## 16. DoD Check

Lote inicial: domínio/persistência testados, migration revisada/aplicada/ida-volta isolada,
Ruff/mypy e cobertura verdes, fronteiras limpas e documentação. Não equivale à Sprint completa.
Slice final: API/UI/storage/worker, RBAC/SoD, Audit/Outbox, testes e reconciliação da importação,
homologação local do usuário. Não marcar DONE apenas por existir staging ou retornar HTTP 202.

## 17. Exit Criteria

Usuário autorizado baixa template, envia XLSX, inspeciona erros/preview, confirma uma carga
permitida e encontra os produtos no M2 sem duplicação após retry. Empresas isoladas e rejeições
rastreáveis. Mudança de dados/escopo/versão desde o preview impede confirmação obsoleta.
Sprint 5 somente após homologação explícita da Sprint 4.

## Evidências do primeiro lote — 2026-09-08

- 040: `d4a7e3a`, domínio/planejamento; 041: `feda4df`, migration/mapeamentos/constraints;
  042: persistência e gates (hash no log Git).
- **391 testes aprovados** na regressão completa, incluindo PostgreSQL, RabbitMQ e Chromium do M2.
- M23 **100,00%** com branches: 256 statements, 64 branches; M2 **100,00%** preservado;
  ERP global **94,49%**. A cobertura Python não mede JavaScript.
- Ruff check/format limpos; mypy strict: 211 arquivos sem erros. Nenhuma dependência adicionada.
- CI mantém o piso global existente e inclui gate explícito `--fail-under=100` para M23 e M2.
- Gate arquitetural adicional impede imports M23 de APIs/repositórios internos de M1/M2.
- Alembic local em **0012**. Banco descartável validou `base → 0012 → 0011 → 0012`, seguido
  dos 15 testes reais de schema. Somente esse banco temporário foi removido; banco homologado
  não sofreu downgrade. Fixtures M23 removidas exclusivamente por seus IDs/empresas de teste.
- UPDATE de template_version e alteração da identidade/fonte do job recusados pelo PostgreSQL.
  FK composta impede template/versão de outra empresa e modo não autorizado é recusado.
- Duas sessões disputando a mesma versão de job têm um vencedor; publicação concorrente da
  mesma versão de template também tem um vencedor. Repositórios não confirmam transações.
- Um aviso de depreciação Starlette/AnyIO de terceiro permanece, sem falhas.

Reprodução local (infraestrutura ativa e sem flags Dev Auth do servidor herdadas):

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m mypy erp tests migrations
.\.venv\Scripts\python.exe -m pytest --cov=erp --cov-report=term-missing --cov-report=xml
.\.venv\Scripts\python.exe -m coverage report --include='erp/modules/governance/*' --fail-under=100 --precision=2
.\.venv\Scripts\python.exe -m coverage report --include='erp/modules/product/*' --fail-under=100 --precision=2
```

Lote 040–042 concluído tecnicamente para homologação. Upload/preview/confirm/commit e telas de
importação ainda não estão implementados. Modo inicial do template aguarda definição do usuário;
criação e atualização por SKU já foram confirmadas. Não confundir essa fundação com Sprint 4 concluída.
