# ERP Big Star / Forma Kids
## Consolidação Geral da Arquitetura M1–M23
### Etapa 8 — Infraestrutura, Deployment, Observabilidade e Segurança Operacional

**Status:** FORMALMENTE APROVADA  
**Versão:** 1.0  
**Data de consolidação:** 2026-09-06  
**Escopo:** Infraestrutura, ambientes, containers, deployment, observabilidade, backup, disaster recovery, segurança operacional, capacity planning e operação produtiva do ERP M1–M23.  
**Objetivo:** Definir como o ERP será executado, publicado, monitorado, protegido, restaurado, escalado e operado em produção, preservando disponibilidade, integridade, auditabilidade e evolução futura.

---

# 1. Objetivo da Etapa 8

Esta etapa define como o ERP M1–M23 será executado, publicado, monitorado, protegido, restaurado e operado em produção.

A arquitetura precisa garantir:

```text
Disponibilidade
Integridade
Rastreabilidade
Segurança
Recuperação
Escalabilidade
Observabilidade
Operação previsível
```

Princípio:

```text
Application Architecture
+
Operational Architecture
=
Production Architecture
```

Um ERP tecnicamente correto, mas sem backup, monitoramento, failover e operação controlada, não será considerado pronto para produção.

---

# 2. Baseline de Infraestrutura

Componentes oficiais:

```text
Frontend Web / PWA
FastAPI Backend
Celery Workers
Celery Beat

PostgreSQL OLTP
PostgreSQL Analytics separado

RabbitMQ
Redis

S3 / MinIO Object Storage

Reverse Proxy / API Ingress

Observability Stack
Backup Infrastructure
CI/CD
Secrets Management
```

---

# 3. Visão Macro

```text
                         INTERNET / LAN
                               │
                               ▼
                     Reverse Proxy / Ingress
                               │
                     ┌─────────┴─────────┐
                     ▼                   ▼
                  Frontend            FastAPI
                                         │
                   ┌─────────────────────┼─────────────────────┐
                   ▼                     ▼                     ▼
              PostgreSQL              RabbitMQ               Redis
                 OLTP                     │
                                          ▼
                                   Celery Workers
                                          │
                                          ▼
                                    Object Storage

                     ┌──────────────────────────────┐
                     │      Analytics Pipeline      │
                     └──────────────┬───────────────┘
                                    ▼
                          PostgreSQL Analytics
```

---

# 4. Estratégia de Containers

Todo componente de aplicação será containerizado.

Baseline:

```text
Docker / OCI containers
```

Benefícios:

- ambiente reproduzível;
- build imutável;
- deploy previsível;
- rollback;
- isolamento;
- escalabilidade.

---

# 5. Ambientes

Existirão no mínimo:

```text
LOCAL
DEV
HOMOLOGATION
PRODUCTION
```

Opcionalmente:

```text
QA
STAGING
```

quando o time crescer.

---

# 6. Isolamento

Nunca compartilhar banco de produção com:

```text
DEV
HOMOLOGATION
TEST
```

Cada ambiente possui:

- PostgreSQL;
- RabbitMQ;
- Redis;
- Object Storage;
- credenciais;
- URLs;
- secrets próprios.

---

# 7. Desenvolvimento Local

Desenvolvimento poderá usar:

```text
Docker Compose
```

subindo:

```text
API
PostgreSQL
RabbitMQ
Redis
MinIO
Workers
```

com configuração simplificada.

---

# 8. Produção

A infraestrutura de produção deverá ser compatível com orquestração de containers.

Baseline arquitetural:

```text
Kubernetes-compatible deployment
```

podendo ser:

- Kubernetes gerenciado;
- cluster privado;
- distribuição leve homologada para on-premise.

O código não dependerá de uma distribuição específica.

---

# 9. Monólito Modular não Significa Processo Único

Mesmo sendo um Modular Monolith, poderemos executar:

```text
API replicas
Worker replicas
Scheduler
specialized workers
```

separadamente.

Exemplo:

```text
erp-api

erp-worker-default
erp-worker-marketplace
erp-worker-fiscal
erp-worker-finance
erp-worker-import
erp-worker-analytics
```

Todos utilizam o mesmo código-base versionado, mas filas e responsabilidades operacionais diferentes.

---

# 10. Stateless API

FastAPI deverá ser predominantemente stateless.

Não armazenar sessão essencial em memória local.

Assim:

```text
API Replica 1
API Replica 2
API Replica 3
```

podem atender qualquer request.

---

# 11. Horizontal Scaling

API:

```text
scale horizontally
```

quando CPU, memória, latência ou throughput exigirem.

Workers também escalam por fila.

---

# 12. Celery Workers por Domínio Operacional

Não usar apenas uma fila gigante.

Sugestão:

```text
erp.default

erp.marketplace
erp.fiscal
erp.finance
erp.notifications
erp.imports
erp.exports
erp.analytics
erp.maintenance
```

---

# 13. Worker Concurrency

Concurrency deve ser ajustada conforme carga.

```text
CPU-bound
→ menor concurrency

I/O-bound
→ maior concurrency
```

---

# 14. Celery Beat

Apenas uma instância efetivamente ativa por ambiente.

Responsável por:

- expiração de reservas;
- alertas;
- reconciliações periódicas;
- refresh jobs;
- scheduled reports;
- maintenance schedules.

---

# 15. RabbitMQ

RabbitMQ é o durable broker oficial.

Uso:

```text
events
requests
retries
DLQ
scheduled/retry routing
```

---

# 16. RabbitMQ HA

Produção deverá suportar cluster.

Preferência:

```text
3 nodes
```

quando HA for requerido.

Para filas críticas:

```text
Quorum Queues
```

quando compatível com volume e configuração operacional.

---

# 17. Persistent Messages

Eventos críticos:

```text
delivery_mode = persistent
```

e filas duráveis.

---

# 18. RabbitMQ não é Banco Histórico

Mensageria não substitui:

```text
PostgreSQL Outbox
Inbox
Audit
```

---

# 19. RabbitMQ Monitoring

Métricas:

```text
queue_depth
consumer_count
publish_rate
delivery_rate
ack_rate

unacked_messages
oldest_message_age

retry_queue_depth
dlq_depth
```

---

# 20. Redis

Redis será usado exclusivamente para:

```text
cache
rate limiting
debounce
distributed locks
circuit breaker state
short-lived read models
session/security auxiliary state
```

Nunca como única verdade durável.

---

# 21. Redis Failure

Se Redis cair:

```text
ERP não pode perder verdade de negócio
```

Dependendo da função:

- cache degrada;
- rate limiting usa fallback controlado;
- locks críticos devem falhar com segurança;
- read model é reconstruível.

---

# 22. PostgreSQL OLTP

É o principal banco transacional.

Responsável pelos schemas:

```text
platform
admin
product
...
workflow
governance
```

exceto M21 analítico.

---

# 23. PostgreSQL Production

Configuração deverá considerar:

```text
CPU
RAM
IOPS
storage latency
connection limits
WAL
autovacuum
checkpoint
```

Não usar configuração default de laboratório em produção.

---

# 24. Connection Pool

FastAPI utilizará pooling.

```text
API
→ SQLAlchemy Pool
→ PostgreSQL
```

Pode ser complementado por:

```text
PgBouncer
```

quando a escala justificar.

---

# 25. PostgreSQL HA

Arquitetura recomendada:

```text
Primary
+
Streaming Replica
```

Para ambientes críticos:

```text
Primary
+
2 Standbys
```

com ferramenta de failover automatizado ou serviço gerenciado equivalente.

---

# 26. Read Replica

Read replicas poderão servir consultas pesadas apropriadas, mas não operações que exijam leitura imediatamente consistente.

---

# 27. Analytics Separado

Conforme M21:

```text
OLTP PostgreSQL
≠
Analytics PostgreSQL
```

O banco analítico nasce fisicamente separado.

---

# 28. Pipeline Analítico

```text
OLTP
↓
Outbox / incremental extraction
↓
Analytics Pipeline
↓
Data Warehouse
```

Near real-time para domínios definidos no M21.

---

# 29. Object Storage

Arquivos binários vão para:

```text
S3-compatible Object Storage
```

Exemplo:

```text
MinIO
ou serviço S3 equivalente
```

---

# 30. Não Armazenar BLOB Grande no PostgreSQL

Evitar armazenar diretamente no OLTP:

```text
PDF
XML
imagem
ZPL
laudo
certificado
```

PostgreSQL guarda:

```text
storage_key
checksum
metadata
classification
```

---

# 31. Object Storage Versioning

Para documentos críticos:

```text
versioning enabled
```

quando infraestrutura permitir.

---

# 32. Hash

Arquivos críticos terão:

```text
SHA-256
```

para integridade.

---

# 33. Retenção

M23 governa políticas de retenção.

Infraestrutura executa:

```text
archive
retain
expire
```

conforme política.

---

# 34. Reverse Proxy / Ingress

Responsabilidades:

```text
TLS termination
routing
rate limiting
request size limits
headers
access logging
```

---

# 35. TLS

Todo tráfego de produção:

```text
HTTPS
```

---

# 36. TLS Interno

Quando justificável:

```text
TLS/mTLS
```

entre componentes críticos poderá ser adotado.

---

# 37. Segmentação de Rede

Separar logicamente:

```text
Public/Ingress Zone
Application Zone
Data Zone
Management Zone
```

---

# 38. PostgreSQL Internet Exposure

Proibido:

```text
PostgreSQL → Internet
```

---

# 39. RabbitMQ Internet Exposure

RabbitMQ e sua interface de administração não devem ficar publicamente expostos.

---

# 40. Redis Exposure

Redis nunca ficará diretamente acessível pela internet.

---

# 41. Secrets Management

Segredos não ficam em:

```text
source code
Dockerfile
Git
plain .env committed
```

---

# 42. Tipos de Secret

Exemplos:

```text
DB credentials
RabbitMQ credentials
Redis credentials
OAuth secrets
Fiscal provider keys
Bank API secrets
SMTP secrets
S3 credentials
JWT signing keys
```

---

# 43. Secret Provider

Utilizar mecanismo adequado de secrets, como:

- Kubernetes Secrets com proteção apropriada;
- Vault;
- cloud secret manager;
- solução equivalente.

---

# 44. Rotação

Segredos críticos devem ser rotacionáveis sem mudança de código.

---

# 45. JWT / Token Signing

Chaves de assinatura devem ser protegidas, versionadas e rotacionáveis.

---

# 46. CI/CD

Pipeline oficial:

```text
Commit
↓
Lint
↓
Static Analysis
↓
Unit Tests
↓
Contract Tests
↓
Security Scan
↓
Build Container
↓
Integration Tests
↓
Publish Image
↓
Deploy
↓
Smoke Tests
```

---

# 47. Branch Strategy

Modelo preferencial:

```text
main
feature branches
```

com pull request.

---

# 48. Pull Request

Mudança crítica exige revisão, testes e checks automatizados.

---

# 49. Container Build

Build deve ser:

```text
reproducible
immutable
versioned
```

Imagem identificada por commit SHA e release version.

---

# 50. Não Usar `latest` como Release de Produção

Produção utiliza tag imutável.

Exemplo:

```text
erp-api:1.8.3
```

---

# 51. Database Migration

Alembic executado de forma controlada.

```text
backup/check
↓
migration job
↓
application rollout
```

---

# 52. Migration Compatibility

Preferir:

```text
expand
→ migrate
→ contract
```

---

# 53. Migration Destrutiva

Operações como:

```text
DROP COLUMN
DROP TABLE
```

não entram em deploy comum sem revisão arquitetural.

---

# 54. Rollback

Application rollback:

```text
container image rollback
```

Database rollback:

```text
não presumir downgrade automático
```

---

# 55. Deployment Strategy

Padrão:

```text
Rolling Deployment
```

Para releases de maior risco:

```text
Blue/Green
```

---

# 56. Health Checks

FastAPI:

```text
/health/live
/health/ready
```

---

# 57. Liveness

Responde:

```text
process is alive?
```

---

# 58. Readiness

Responde:

```text
instance can safely receive traffic?
```

---

# 59. Worker Health

Workers terão:

```text
heartbeat
consumer status
last task processed
queue lag
```

---

# 60. Observability Stack

Baseline recomendada:

```text
OpenTelemetry
Prometheus
Grafana
Loki
Tempo
Alertmanager
```

ou equivalentes.

---

# 61. Três Pilares

```text
LOGS
METRICS
TRACES
```

---

# 62. Structured Logging

Logs JSON com:

```text
timestamp
level
service
environment
request_id
correlation_id
causation_id
user_id
system_actor
module
operation
error_code
```

---

# 63. Dados Sensíveis em Logs

Nunca logar:

- senha;
- access token;
- refresh token;
- secret;
- dado bancário completo;
- documentos confidenciais;
- payload de RH sem necessidade.

---

# 64. PII Masking

Aplicar masking quando necessário.

---

# 65. Log Levels

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

---

# 66. Retenção de Logs

Retenção considera custo, segurança, auditoria e LGPD.

Logs de aplicação não substituem `audit_event`.

---

# 67. Metrics

Métricas técnicas:

```text
CPU
RAM
disk
IOPS
network
request rate
error rate
latency
```

---

# 68. RED Method

```text
Rate
Errors
Duration
```

---

# 69. USE Method

```text
Utilization
Saturation
Errors
```

---

# 70. Tracing Distribuído

Rastrear:

```text
API
→ Application Service
→ DB
→ RabbitMQ
→ Worker
→ External Provider
```

---

# 71. OpenTelemetry

Propagar:

```text
trace_id
span_id
correlation_id
```

---

# 72. Business Correlation

`correlation_id` continua separado do trace técnico.

---

# 73. Dashboards Operacionais

Devem existir dashboards para:

```text
API Health
Database Health
RabbitMQ
Redis
Workers
External Integrations
Object Storage
Analytics Pipeline
```

---

# 74. Dashboard de Aplicação

```text
requests/sec
p95 latency
5xx rate
409 rate
429 rate
active users
job throughput
```

---

# 75. Dashboard RabbitMQ

```text
publish rate
consume rate
queue depth
consumer lag
DLQ
```

---

# 76. Dashboard PostgreSQL

```text
connections
slow queries
locks
deadlocks
replication lag
buffer cache
WAL
disk growth
autovacuum
```

---

# 77. Slow Query Monitoring

`pg_stat_statements` ou equivalente deverá ser habilitado.

---

# 78. Redis Monitoring

```text
memory
evictions
hit rate
latency
connected clients
```

---

# 79. Object Storage Monitoring

```text
capacity
errors
latency
replication
failed uploads
```

---

# 80. External Integration Monitoring

Cada adapter terá:

```text
availability
latency
rate limit
error rate
last successful sync
```

---

# 81. Circuit Breaker

Aplicável a:

```text
Marketplaces
Fiscal Provider
Banks
Payroll
```

---

# 82. Alertas

Alertas devem ser acionáveis.

---

# 83. Severidade Operacional

```text
SEV1
SEV2
SEV3
SEV4
```

---

# 84. SEV1

Exemplos:

```text
ERP indisponível
Database primary unavailable
Inventory corruption suspected
Financial duplicate execution
Fiscal critical outage
Security incident critical
```

---

# 85. SEV2

Exemplos:

```text
Marketplace integration down
Payment processing unavailable
RabbitMQ critical queue backlog
Regulatory gate unavailable
```

---

# 86. SEV3

Exemplos:

```text
Analytics delayed
Scheduled report failures
non-critical queue backlog
```

---

# 87. Alert Fatigue

Alertas baseados em impacto, duração e threshold.

---

# 88. SLOs

Baseline inicial:

| Serviço | SLO |
|---|---:|
| ERP API principal | 99,9% |
| M5 Inventory critical operations | 99,95% |
| M12 Finance critical operations | 99,9% |
| M11 Fiscal orchestration | 99,9% interno |
| M22 Workflow | 99,9% |
| M21 Analytics | 99,5% |

---

# 89. Latência

Objetivos iniciais:

```text
Interactive API internal:
p95 < 500 ms

Common list/search:
p95 < 1 s

Operational scanner:
p95 < 300 ms quando local/internal
```

---

# 90. Marketplace Stock Sync

Objetivo:

```text
p95 < 10 seconds
```

quando canal estiver disponível.

---

# 91. Error Budget

SLOs poderão utilizar `error budget`.

---

# 92. Backup — PostgreSQL

Estratégia:

```text
Full/Base Backup
+
Continuous WAL Archiving
```

---

# 93. Point-in-Time Recovery

PITR obrigatório para produção.

---

# 94. Backup Encryption

Backups criptografados em repouso e trânsito.

---

# 95. Backup Imutável

Quando possível:

```text
immutable / object-lock backup
```

---

# 96. Backup fora do Ambiente Primário

```text
backup
≠
mesmo disco do banco
```

---

# 97. Regra 3-2-1

Objetivo:

```text
3 cópias
2 meios/locais distintos
1 cópia off-site
```

---

# 98. Backup do Object Storage

Documentos críticos também precisam de proteção/replicação.

---

# 99. RabbitMQ Backup

Definitions reproduzíveis por IaC.

Outbox/Inbox garantem que mensageria não seja a única cópia de um fato crítico.

---

# 100. Redis Backup

Somente conforme necessidade específica.

---

# 101. Analytics Backup

Data Warehouse deve ser recuperável por backup ou rebuild pipeline.

Snapshots mensais imutáveis do M21 permanecem preservados.

---

# 102. RPO

## Tier 1 — Crítico

```text
Inventory
Finance
Fiscal
Accounting
Orders
Workflow
```

Objetivo:

```text
RPO ≤ 5 minutos
```

## Tier 2

```text
RPO ≤ 30 minutos
```

## Analytics

RPO maior é aceitável quando reconstruível.

---

# 103. RTO

Objetivos iniciais:

```text
Core ERP Tier 1:
RTO ≤ 2 horas

Tier 2:
RTO ≤ 4 horas

Analytics:
RTO ≤ 8 horas
```

---

# 104. Disaster Recovery

DR cobre:

```text
database loss
server loss
cluster loss
storage loss
network outage
ransomware
human error
```

---

# 105. DR Site

Quando maturidade exigir:

```text
secondary site / secondary region
```

---

# 106. Restore Test

```text
backup não testado
≠
backup confiável
```

---

# 107. Frequência de Testes

Sugestão inicial:

```text
Restore técnico mensal
DR exercise semestral
```

---

# 108. Runbooks

Exemplos:

```text
PostgreSQL Failover
RabbitMQ Queue Backlog
DLQ Reprocessing
Marketplace Outage
Fiscal Provider Outage
Redis Failure
Worker Failure
Storage Full
Rollback Deployment
Security Incident
```

---

# 109. Runbook Structure

```text
Symptoms
Impact
Checks
Immediate Mitigation
Recovery Steps
Validation
Escalation
Post-Incident Actions
```

---

# 110. Incident Management

Incidente terá:

```text
incident_id
severity
started_at
detected_at
resolved_at
owner
timeline
root cause
```

---

# 111. Postmortem

Incidentes SEV1/SEV2 geram:

```text
What happened?
Impact
Timeline
Root cause
Contributing factors
Corrective actions
Preventive actions
```

---

# 112. Security Vulnerability Management

Pipeline inclui:

```text
dependency scan
container scan
static analysis
secret scan
```

---

# 113. Dependências Python

Bibliotecas serão versionadas, pinadas e atualizadas de forma controlada.

---

# 114. SBOM

Release deverá estar preparada para gerar:

```text
Software Bill of Materials
```

---

# 115. Vulnerability Severity

```text
CRITICAL
HIGH
MEDIUM
LOW
```

---

# 116. Critical Vulnerability

Correção emergencial ou mitigação imediata conforme exposição.

---

# 117. OS Patching

Nodes/hosts terão política de atualização.

---

# 118. Database Patching

Atualizações PostgreSQL testadas em homologação antes da produção.

---

# 119. Dependency Update

Evitar misturar grandes upgrades de dependência com alterações funcionais críticas.

---

# 120. Access to Production

Acesso administrativo restrito:

```text
VPN / private access
MFA
named accounts
audit
```

---

# 121. Shared Admin Accounts

Proibido como prática normal.

---

# 122. SSH Access

Se necessário:

- chave individual;
- MFA/VPN;
- mínimo privilégio;
- logs.

---

# 123. Database Access

Desenvolvedor não utiliza superuser como rotina.

---

# 124. Break Glass Infrastructure

Credencial emergencial:

- protegida;
- auditada;
- rotacionada após uso.

---

# 125. Environment Configuration

Separar:

```text
code
config
secret
```

---

# 126. Feature Flags

Podem ser usadas para rollout, funcionalidades experimentais e ativação por empresa.

```text
feature flag
≠
permissão de segurança
```

---

# 127. Configuration Versioning

Configurações operacionais críticas possuem histórico.

---

# 128. Infrastructure as Code

Infraestrutura automatizável por:

```text
Terraform
Ansible
Helm
Kubernetes manifests
```

ou equivalentes.

---

# 129. Não Configurar Produção Manualmente sem Registro

Mudança manual emergencial deverá ser posteriormente reconciliada com IaC.

---

# 130. Capacity Planning

Observar:

```text
orders/day
marketplace messages
inventory postings
production reports
financial transactions
concurrent users
database growth
object storage growth
```

---

# 131. Baseline de Volume

Marketplace:

```text
5.000–10.000 orders/day
```

---

# 132. Load Testing

Cenários:

```text
order burst
marketplace synchronization
inventory reservation contention
WMS scanning
billing batch
finance reconciliation
import job
analytics load
```

---

# 133. Stress Testing

Descobrir:

```text
breaking point
degradation behavior
recovery behavior
```

---

# 134. Inventory Concurrency Test

M5 exige testes de:

```text
parallel reservations
same SKU
same pool
same lot
```

---

# 135. Marketplace Burst

Simular picos após campanhas.

---

# 136. Fiscal Batch

Testar emissão em lote com latência, rejeição, timeout e retry.

---

# 137. Backup Capacity

Monitorar crescimento de WAL e backups.

---

# 138. Disk Full Protection

Alertas:

```text
70%
80%
90%
```

---

# 139. Database Growth

Monitorar crescimento especialmente de:

```text
audit_event
inventory_posting
outbox_event
inbox_event
time_punch
marketplace payloads
```

---

# 140. Data Archiving

M23 governa e infraestrutura executa jobs de archival.

---

# 141. Outbox Retention

Após período seguro:

```text
archive / purge governed
```

---

# 142. Inbox Retention

Janela de idempotência deve impedir replay indesejado.

---

# 143. DLQ Operations

Cockpit técnico permite:

```text
inspect
retry
replay
quarantine
```

por usuário autorizado.

---

# 144. Nunca Editar Mensagem da DLQ

Se conteúdo estiver errado:

```text
new corrective message
```

---

# 145. External Provider Failure

Categorias normalizadas:

```text
RETRYABLE
NON_RETRYABLE
RATE_LIMITED
AUTH_FAILED
CIRCUIT_OPEN
```

---

# 146. Credential Expiration Monitoring

Monitorar:

- OAuth token;
- certificados;
- API keys;
- TLS certificates.

---

# 147. Certificate Expiry Alerts

Alertar antes de TLS/certificados técnicos vencerem.

---

# 148. Clock Synchronization

Hosts/nodes usam NTP.

---

# 149. Timezone Interno

Infraestrutura opera preferencialmente em UTC.

---

# 150. Security Incident

Exemplos:

```text
credential leak
suspicious login
mass export
privilege escalation
malware/ransomware
data exfiltration
```

---

# 151. Audit Preservation

Audit logs críticos devem ser preservados contra alteração.

---

# 152. Operational Security Events

M1 poderá publicar eventos de segurança e M21 poderá analisá-los.

---

# 153. WAF

Pode ser introduzido quando houver exposição externa relevante.

---

# 154. DDoS

Infraestrutura deverá considerar proteção upstream para serviços públicos.

---

# 155. Public Marketplace Webhooks

Somente endpoints estritamente necessários ficam públicos.

---

# 156. Admin Interfaces

Interfaces administrativas devem preferencialmente exigir rede privada/VPN.

---

# 157. Security Headers

Manter baseline da Etapa 6.

---

# 158. File Upload Security

Uploads passam por:

```text
size validation
mime validation
extension validation
checksum
authorization
```

Opcionalmente antivírus/malware scanning.

---

# 159. Executable Upload

Arquivos executáveis não serão aceitos em rotinas comuns.

---

# 160. Object Storage Access

Bucket não é público por padrão.

Downloads usam:

```text
authorized signed URL
```

de curta duração.

---

# 161. Production Data em DEV

Proibido copiar produção diretamente para DEV com dados sensíveis sem anonimização.

---

# 162. Homologação com Dados Produtivos

Quando necessário:

```text
masked/anonymized dataset
```

governado pelo M23.

---

# 163. Monitoring de Jobs

Cada job expõe:

```text
started_at
finished_at
duration
status
attempt_count
error_code
```

---

# 164. Scheduler Delay

Monitorar atraso do scheduler.

---

# 165. Business-Critical Technical Metrics

Além da infraestrutura:

```text
orders waiting ingestion
inventory sync lag
fiscal pending age
payment pending transmission
production event lag
workflow pending request age
```

---

# 166. Technical Cockpit

Tela administrativa consolidada:

```text
API
Workers
Queues
DLQ
DB
Redis
Object Storage
External Providers
Analytics Pipeline
Backups
```

---

# 167. Backup Cockpit

Mostrar:

```text
last successful backup
last WAL archive
backup age
restore test date
backup size
```

---

# 168. Deploy Cockpit

Opcional:

```text
current version
deployed_at
commit SHA
environment
```

---

# 169. Release Notes

Cada release registra:

- funcionalidades;
- migrations;
- breaking changes;
- flags;
- riscos;
- rollback considerations.

---

# 170. Change Management

Deploy produtivo é rastreável.

---

# 171. Emergency Hotfix

Fluxo simplificado, ainda com:

- revisão mínima;
- testes essenciais;
- versionamento;
- registro.

---

# 172. Smoke Tests

Após deploy:

```text
login
basic API
DB connectivity
RabbitMQ
Redis
critical read
critical write sandbox/test
```

---

# 173. Synthetic Monitoring

Pode executar testes periódicos com identidade técnica dedicada.

---

# 174. Failover Testing

Failover de banco e mensageria será testado periodicamente.

---

# 175. Deployment Freeze

Períodos críticos poderão ter freeze.

Exemplos:

- fechamento financeiro;
- inventário;
- datas fiscais críticas;
- campanha comercial relevante.

---

# 176. Auditabilidade Operacional

Deve ser possível responder:

```text
qual versão estava em produção?
quem publicou?
quando?
quais migrations rodaram?
qual configuração estava ativa?
```

---

# 177. Configuration Drift

Infraestrutura deverá detectar/reduzir divergência entre configuração desejada e real.

---

# 178. Minimum Production Topology

Baseline mínima recomendada:

```text
2+ API replicas
2+ worker replicas conforme fila
PostgreSQL primary
PostgreSQL standby
RabbitMQ HA conforme criticidade
Redis HA/failover quando necessário
Object Storage redundante
Dedicated Analytics DB
```

---

# 179. Small Initial Deployment

Se o volume inicial não justificar toda HA física:

```text
logical architecture remains the same
```

Componentes podem iniciar single-node com backups, desde que a limitação seja formalmente registrada.

---

# 180. Escala Horizontal sem Redesign

Meta:

```text
increase replicas
rather than rewrite architecture
```

---

# 181. No Single Point of Failure Crítico

Em produção madura:

```text
Database
Object Storage
Message Broker
Ingress
```

não devem permanecer como SPOF.

---

# 182. Critérios de Aceite da Etapa 8

1. ambientes definidos.
2. produção isolada.
3. containers como baseline.
4. Docker Compose local.
5. orquestração produtiva container-compatible.
6. API stateless.
7. workers separáveis por fila.
8. Celery Beat singleton lógico.
9. RabbitMQ durable.
10. RabbitMQ HA previsto.
11. DLQ monitorada.
12. Redis não é verdade durável.
13. PostgreSQL OLTP principal.
14. PostgreSQL Analytics separado.
15. pooling definido.
16. HA PostgreSQL previsto.
17. Object Storage S3-compatible.
18. documentos fora de grandes BLOBs do OLTP.
19. TLS obrigatório.
20. banco não exposto à internet.
21. RabbitMQ não exposto.
22. Redis não exposto.
23. secrets fora do código.
24. rotação de secrets.
25. CI/CD definido.
26. imagens imutáveis.
27. `latest` não é release oficial.
28. Alembic controlado.
29. destructive migration revisada.
30. rollback strategy.
31. health checks.
32. worker health.
33. logs estruturados.
34. métricas.
35. traces.
36. sem dados sensíveis em logs.
37. stack de observabilidade.
38. slow query monitoring.
39. RabbitMQ monitoring.
40. Redis monitoring.
41. external integration monitoring.
42. alertas com severidade.
43. SLOs.
44. RPO.
45. RTO.
46. PITR PostgreSQL.
47. backups criptografados.
48. backup fora do host primário.
49. Object Storage protegido.
50. restore test.
51. DR exercise.
52. runbooks.
53. incident management.
54. postmortem.
55. vulnerability scanning.
56. dependency pinning.
57. secret scan.
58. container scan.
59. patch management.
60. acesso produtivo restrito.
61. contas compartilhadas proibidas.
62. IaC.
63. capacity planning.
64. load testing.
65. inventory concurrency test.
66. marketplace burst test.
67. disk monitoring.
68. data growth monitoring.
69. outbox/inbox retention.
70. DLQ reprocessing controlado.
71. credential expiry monitoring.
72. NTP.
73. uploads protegidos.
74. produção não copiada sem masking.
75. job monitoring.
76. technical cockpit.
77. backup cockpit.
78. releases rastreáveis.
79. smoke tests.
80. failover testing.
81. deployment freeze.
82. configuration drift controlado.
83. SPOFs críticos elimináveis.
84. scale-out sem redesign.
85. infraestrutura respeita Etapas 1–7.

---

# 183. Decisões Arquiteturais Consolidadas

## A. Containers são o padrão operacional

## B. Monólito Modular pode ter múltiplos processos e réplicas

## C. FastAPI será stateless

## D. RabbitMQ é broker durável, não histórico oficial

## E. Redis é acelerador, nunca System of Record

## F. PostgreSQL OLTP é a verdade transacional

## G. Analytics fica fisicamente separado

## H. Object Storage guarda binários

## I. TLS é obrigatório

## J. Secrets ficam fora do código

## K. CI/CD produz artefatos imutáveis

## L. Migration de banco é processo controlado

## M. Logs + Metrics + Traces são obrigatórios

## N. Backup deve suportar PITR

## O. Restore é testado periodicamente

## P. Segurança operacional faz parte da arquitetura

## Q. Produção não depende de configuração manual informal

## R. Scale-out deve ocorrer sem redesign dos domínios

## S. Falha externa nunca pode gerar sucesso silencioso

## T. Infraestrutura também deve ser auditável

---

# 184. Visão Consolidada de Produção

```text
                         USERS / DEVICES
                               │
                               ▼
                     TLS / Reverse Proxy
                               │
                     ┌─────────┴─────────┐
                     ▼                   ▼
                Frontend/PWA       FastAPI Replicas
                                         │
              ┌──────────────────────────┼──────────────────────┐
              ▼                          ▼                      ▼
        PostgreSQL OLTP               RabbitMQ                Redis
              │                          │
              │                 ┌────────┼─────────┐
              │                 ▼        ▼         ▼
              │              Workers   Workers   Workers
              │
              ├──────────────► Object Storage
              │
              └──────────────► Analytics Pipeline
                                      │
                                      ▼
                              PostgreSQL Analytics

       ┌─────────────────────────────────────────────────────┐
       │                  OBSERVABILITY                      │
       │ Prometheus | Grafana | Loki | Tempo | Alertmanager │
       └─────────────────────────────────────────────────────┘

       ┌─────────────────────────────────────────────────────┐
       │                BACKUP / DISASTER RECOVERY           │
       │ WAL | Base Backup | Object Backup | Restore Tests   │
       └─────────────────────────────────────────────────────┘
```

---

# 185. Status Formal da Etapa 8

A **Etapa 8 — Infraestrutura, Deployment, Observabilidade e Segurança Operacional** está:

```text
FORMALMENTE APROVADA
```

Este documento passa a ser baseline oficial para:

- ambientes;
- containers;
- orchestration;
- PostgreSQL;
- RabbitMQ;
- Redis;
- Object Storage;
- CI/CD;
- migrations;
- observabilidade;
- backup;
- DR;
- SLO/RPO/RTO;
- segurança operacional;
- capacity planning;
- runbooks;
- incident response;
- deployment e rollback.

Alterações incompatíveis devem seguir:

```text
ARCHITECTURE CHANGE REQUEST
```

---

# 186. Próxima Etapa

```text
ETAPA 9
ROADMAP DE IMPLEMENTAÇÃO, FASES, DEPENDÊNCIAS E CRITÉRIOS DE GO-LIVE
```

A próxima etapa consolidará:

- ordem macro de construção;
- ondas de implementação;
- dependências técnicas;
- dependências funcionais;
- foundation first;
- MVP vs fases posteriores;
- módulos bloqueadores;
- critérios de entrada e saída por fase;
- estratégia de piloto;
- coexistência com legado;
- migração progressiva;
- go-live por domínio;
- critérios de readiness;
- critérios de rollback;
- cutover.

---

**Fim da Etapa 8 — Infraestrutura, Deployment, Observabilidade e Segurança Operacional**
