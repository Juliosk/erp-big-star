# WMS — layout físico, putaway e execução logística

O M10 mantém ondas, picking, packing e expedição e acrescenta o domínio puro de
layout conforme o [ADR 0194](../../../docs/adr/0194-wms-physical-layout-putaway.md).

- `domain/locations.py`: `WarehouseAddress`, `WarehouseBin`, dimensões,
  capacidade, estado derivado de ocupação e proposta imutável de putaway.
- `application/permissions.py`: RBAC WMS combinado com escopo por empresa.
- M5 continua proprietário dos locais físicos, saldos e ledger; M17 decide
  condições de qualidade. O WMS não promove material bloqueado a disponível.

Endereço: `ZONA/CORREDOR/ESTANTE/PRATELEIRA/BIN`. Unidades explícitas: metros,
kg, m³ e contagem inteira de unidades de armazenagem. Não há rotação ou
conversão implícita. Toda proposta respeita empresa, depósito, zona, condição,
dimensões individuais e limites acumulados de unidades/peso/volume.

`plan_putaway` calcula uma nova projeção; a confirmação física via contrato M5
com idempotência, controle de concorrência e Audit/Outbox atômicos pertence ao
próximo slice. O Commit 208 não cria migration ou endpoint de movimentação.

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/unit/modules/wms/domain/test_wms_location_rules.py --cov=erp.modules.wms.domain.locations --cov-branch --cov-fail-under=100 -q
```
