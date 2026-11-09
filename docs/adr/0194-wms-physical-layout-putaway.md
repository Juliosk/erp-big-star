# ADR 0194 — WMS, endereçamento físico e putaway

- Status: Accepted
- Data: 2026-11-08
- Entrega: Sprint Dupla, Trilha B, Commit 208

## Contexto e DoR

O WMS M10 já gerencia ondas, separação, embalagem e expedição. O M5 possui
`Warehouse`, `WarehouseLocation`, reservas, saldo e ledger imutável. A evolução
do layout deve acrescentar regras operacionais de endereçamento e capacidade
sem criar uma segunda fonte de saldo físico. O aceite deste slice é domínio
puro, permissões explícitas e testes de capacidade/zoneamento por empresa.

## Ownership e fronteiras

- M5 permanece proprietário do depósito/local físico, saldos, reservas e ledger.
- M10 mantém coordenadas operacionais, restrições por bin, políticas de putaway
  e projeções de ocupação, ligadas logicamente por `inventory_location_id`.
- `WarehouseAddress` identifica empresa + depósito + coordenadas; `WarehouseBin`
  congela capacidade, tipo, ocupação projetada, bloqueio e versão.
- O serviço de aplicação futuro valida pelo contrato público do M5 que o local
  existe e pertence à mesma empresa/depósito. Um UUID no VO não comprova essa
  existência; a verificação persistida é obrigatória antes da movimentação.
- M17 decide a condição de qualidade; M5 executa a mudança de estado. Endereçar
  material não pode convertê-lo de quarentena/avaria para disponível.

Os domínios não importam outros módulos, SQLAlchemy, FastAPI ou Pydantic. A
composição entre owners ocorre em `erp.apps` por portas públicas. Nenhum SQL
cross-domain, FK de negócio cross-domain ou acesso direto ao repositório M5 é
introduzido neste commit.

## Endereçamento hierárquico e coordenadas

Hierarquia obrigatória: Zona -> Corredor -> Estante -> Prateleira -> Bin.

Exemplo canônico: `A/01/R1/02/003`.

Cada coordenada admite 1 a 16 caracteres ASCII alfanuméricos/underscore,
iniciando por letra ou número. Espaços externos são removidos e letras viram
maiúsculas. Zeros à esquerda são preservados; separadores dentro da coordenada
são rejeitados. `parse` exige exatamente cinco níveis. A chave de unicidade
futura será `(company_id, warehouse_id, code)`; o mesmo código pode existir em
depósitos ou empresas distintos.

Os eixos físicos largura/profundidade/altura são informados explicitamente,
em metros. Códigos hierárquicos não são distâncias e não induzem rota ótima.
Mapas cartesianos e distâncias de deslocamento exigirão contrato próprio.

## Capacidade e ocupação imutável

Medidas usam `Decimal` finito com até seis casas, sem `float` ou conversão de
unidade implícita. Dimensões e peso individual devem ser positivos e inferiores
a 1.000.000; limites inteiros de unidades ficam entre 1 e 1.000.000. Peso em kg,
volume em m³; produtos de dimensões preservam até 18 casas, calculados em
contexto Decimal local para evitar dependência da precisão do chamador.

Uma carga precisa respeitar simultaneamente:

1. dimensão individual em cada eixo, sem rotação implícita;
2. total de unidades do bin;
3. peso acumulado máximo;
4. volume acumulado máximo.

Um teste de volume não é prova de encaixe geométrico de múltiplas embalagens.
Este slice aplica limites conservadores por eixo e volume; otimização de
packing 3D permanece evolução separada.

Estados de ocupação são derivados para impedir combinações incoerentes:

| Estado | Regra |
| --- | --- |
| `EMPTY` | zero unidades, peso e volume |
| `PARTIAL` | ocupação positiva abaixo de todos os limites |
| `FULL` | qualquer limite de unidades/peso/volume atingido |
| `BLOCKED` | bloqueio operacional, preservando a ocupação existente |

O método puro `plan_putaway` devolve um novo bin com versão incrementada e
preserva o objeto anterior. Ele não confirma movimentação física, não reserva
espaço de forma concorrente nem altera estoque. A persistência futura deverá
revalidar a versão e os limites na mesma transação da confirmação M5.

## Zoneamento e políticas de armazenagem

Toda política tem empresa, depósito e allowlist imutável de zonas. Lista vazia,
duplicada ou inválida é rejeitada; não existe fallback para qualquer zona.

| Condição do material | Tipos de armazenagem permitidos |
| --- | --- |
| `AVAILABLE` | `PICKING`, `RESERVE` (pulmão) |
| `DAMAGED` | `DAMAGED` (avaria) |
| `QUARANTINE` | `QUARANTINE` |

Bin bloqueado não recebe carga. O motor rejeita empresa/depósito divergentes
no endereço, carga ou política. Mistura de lotes, FEFO, incompatibilidades
químicas, temperatura e risco regulatório exigirão políticas explícitas antes
de habilitar essas operações; não há autorização implícita neste VO.

## Integração atômica com o ledger M5

O futuro comando de aplicação de confirmação deve executar:

1. autenticar, verificar `wms.inventory.movement` e acesso à empresa;
2. validar chave idempotente, versão da ocupação e local tenant-bound do M5;
3. travar origem/destino em ordem estável, revalidar saldo, reservas e capacidade;
4. solicitar ao contrato M5 o movimento balanceado (saída/entrada), mantendo
   produto, lote, pool e condição física, sem criar estoque líquido;
5. persistir nova ocupação WMS, ledger/saldos M5, Audit e Outbox no mesmo
   transaction boundary do monólito modular;
6. confirmar tudo ou reverter tudo; publicar no broker somente após o commit.

Concorrência exige lock transacional nos saldos e versão otimista na projeção.
Inbox deduplica eventos de confirmação por empresa; cursores monotônicos
impedem regressão de projeções em entregas atrasadas. Replay deve retornar o
movimento original, sem segunda baixa. Em falha de infraestrutura, a transação
inteira é revertida e o retry usa a mesma chave idempotente.

O Commit 208 estabelece esse contrato arquitetural; não implementa ainda o
comando transacional, migration, endpoint ou consumer de movimentação.

## RBAC e erros

| Permissão | Risco | Finalidade |
| --- | --- | --- |
| `wms.locations.read` | MEDIUM | consultar endereços/capacidades |
| `wms.locations.write` | HIGH | configurar layout e bloqueios |
| `wms.inventory.movement` | CRITICAL | confirmar movimentações físicas |

As permissões são adicionadas ao registro existente, sem concessões automáticas
às identidades atuais. `WmsAuthorization` combina DEFAULT DENY e empresa.
Permissões anteriores de picking/packing/expedição continuam independentes.

Erros puros: `INVALID_WMS_LOCATION`, `BIN_CAPACITY_EXCEEDED` e
`PUTAWAY_ZONE_FORBIDDEN`. A camada HTTP futura traduzirá esses códigos para o
Error Contract e usará `If-Match`/ETag e Idempotency-Key. Auditoria registrará
ator, antes/depois, motivo, empresa, versão, request/correlation/causation IDs.

## DoD e próximos slices

Testes puros cobrem formatação/parse, imutabilidade, construção direta, todos os
tipos de armazenagem, limites exatos e excedidos, bloqueios, dimensão por eixo,
matriz de condições e escopo por empresa/depósito. Gates: cobertura de linhas e
branches do novo domínio, fronteiras arquiteturais, Mypy, Ruff e regressão WMS.

Próximos slices: schema tenant-bound do layout, repositório versionado,
confirmação atômica M10/M5, APIs e cockpit de putaway com E2E Chromium. A
fundação pura deste commit não requer migration nem altera os saldos atuais.

## Evidência local — Commit 208

- 2.166 testes globais não-browser aprovados, incluindo PostgreSQL real;
- 285 testes focados de localização, permissões e fronteiras aprovados;
- novo domínio de localização: 100% de linhas e branches (160 statements,
  66 branches);
- Mypy limpo em 891 arquivos; Ruff aprovado em `erp`, `tests` e `migrations`;
- único warning da regressão: depreciação externa Starlette/AnyIO;
- nenhuma migration ou operação de estoque ativada neste slice.
