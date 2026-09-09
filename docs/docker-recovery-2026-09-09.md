# Recuperação local do Docker — 2026-09-09

## Diagnóstico confirmado

Docker Desktop 4.89.0 falhava antes de iniciar o engine Linux. O log do backend registrou
erro Windows 1920 ao acessar/renomear `Docker/run/sailor-ingest.sock` para `.stale`.
O arquivo tinha zero bytes, data de 07/09/2026 e tag nativa **0x80000023 (AF_UNIX)**.
Não era um arquivo de banco de dados nem link para volume. O driver `afunix` estava RUNNING.

Mesmo sem processos do Desktop, consultas e operações de arquivo recusavam o soquete.
Isso confirma o bloqueio de inicialização por artefato residual de comunicação; não
determina por que o Windows deixou de aceitar operações sobre esse artefato. Não há
evidência suficiente para atribuir a origem a atualização, antivírus ou corrupção de disco.

Após isolar o primeiro conjunto, a inicialização avançou e revelou o mesmo problema em
`docker-secrets-engine/engine.sock`. Essa pasta continha somente esse soquete de zero bytes,
sem arquivos de segredos. Também foi preservada em quarentena.

## Ações e preservação

- Encerramento normal via `docker desktop stop --timeout 20` falhou. Foram encerrados somente
  processos identificados da instância já falhada, verificando o caminho do executável.
- Renomeação/remoção pontual do soquete foram recusadas; **nenhum arquivo foi apagado**.
- Validaram-se os caminhos absolutos e todos os filhos das pastas de comunicação antes de
  renomeá-las. Nenhuma pasta de dados, VHDX, distribuição WSL ou volume foi movido/alterado.
- Pastas preservadas, sem sobrescrita:
  - `C:\Users\Ti\AppData\Local\Docker\run.quarantine-20260909`
  - `C:\Users\Ti\AppData\Local\Docker\run.quarantine-20260909-retry`
  - `C:\Users\Ti\AppData\Local\docker-secrets-engine.quarantine-20260909`
- Criaram-se pastas de execução vazias nos caminhos originais e iniciou-se o Desktop.
  O Docker recriou os soquetes e o engine **29.7.2** respondeu normalmente.
- `docker compose up -d --no-recreate --wait` confirmou os quatro contêineres originais
  saudáveis. Não houve reset, prune, remoção de volumes ou recriação de contêineres.

Os volumes `bigstar_erp_postgres_data`, `bigstar_erp_minio_data`, `bigstar_erp_redis_data`
e `bigstar_erp_rabbitmq_data` mantêm a criação **2026-09-07T14:26:57Z**. PostgreSQL respondeu
e o Alembic confirmou **0013 (head)**. Os testes de integração foram retomados.
Isso comprova reutilização dos volumes e acesso operacional, não uma auditoria contábil de
cada registro anterior ao incidente.

## Se ocorrer novamente

Não automatizar exclusões de soquetes, não restaurar quarentena sobre uma instância ativa
e não aplicar este procedimento a outras pastas sem nova inspeção. Preservar os logs e
comparar o erro exato. Se os soquetes recém-criados também bloquearem uma reinicialização
futura, investigar a causa no Windows/Docker antes de repetir reparos.

Referências: [CLI do Docker Desktop](https://docs.docker.com/desktop/features/desktop-cli/),
[tags de reparse point da Microsoft](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4),
[operações sobre reparse points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations).
