# Public Equity Theme Research Environment Lock

Last verified: 2026-06-18 KST

This project is now scoped to public-equity theme research: SQLite schema validation, seeded PM-session data, and a Vite onboarding dashboard.

## Runtime

- Python: stdlib-only for SQLite build/export/validation scripts
- Node.js/npm: required only for the React/Vite dashboard
- Database: SQLite generated from `research/public_equity_theme_schema/schema.sql`
- Frontend: `research/public_equity_theme_schema/visual_onboarding`

## Verification

Run schema and PM-session checks from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_public_equity_project.ps1
```

Build the local SQLite artifact and dashboard JSON:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_public_equity_database.ps1
```

Run the dashboard when Node.js/npm is available:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_public_equity_dashboard.ps1
```

## Generated Outputs

- `artifacts/public_equity_theme_schema.sqlite`
- `research/public_equity_theme_schema/visual_onboarding/src/data/theme-dashboard-data.json`
- `research/public_equity_theme_schema/visual_onboarding/dist/`

Generated outputs can be recreated from source. Do not treat them as source-of-truth investment data.
