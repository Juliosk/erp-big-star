# Database migrations

The baseline owns only the shared `platform` schema and the first bounded context,
`admin`. Each future business module must own its tables and migration changes without
altering another module's schema.

Apply the current migration set with:

```powershell
uv run alembic upgrade head
```

Generate SQL for review without changing a database with:

```powershell
uv run alembic upgrade head --sql
```
