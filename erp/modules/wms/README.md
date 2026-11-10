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

`plan_putaway` e `plan_pick` calculam projeções físicas imutáveis. O Commit 212
confirmou o putaway com ledger M5, concorrência e Audit/Outbox atômicos. O
Commit 214 acrescenta ondas operacionais roteadas por endereço cartesiano,
baixa física `ISSUE` no M5, conferência EAN append-only e manifesto que prepara
pacotes `FINALIZED` e remessas `READY_TO_DISPATCH` para o fulfillment do
Commit 213. As tabelas `wms_*` da Migration 0060 complementam, sem substituir,
os contratos legados de ondas e pacotes da Migration 0025.

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/unit/modules/wms/domain/test_wms_location_rules.py --cov=erp.modules.wms.domain.locations --cov-branch --cov-fail-under=100 -q
```
