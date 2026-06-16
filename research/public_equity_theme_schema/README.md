# Public Equity Theme Screening SQLite Schema

This package defines a reusable SQLite schema for the first step of a public-equity market-theme workflow: turning a market theme into a source-backed research queue.

It is intentionally separate from the ASDW app. The schema supports research prioritization, not final trade recommendations.

## Scope

The schema follows the Public Equity Investing `idea-generation` workflow:

- define a market theme and beneficiary pathways;
- normalize listed-company candidates and identifiers;
- preserve raw provider payloads and source documents;
- link thematic exposure to evidence;
- score candidates across PM-relevant dimensions;
- classify candidates into research-priority buckets;
- run separate PM sessions for `public_equity_diligence`, `long_short_hf`, and `long_only_pm`;
- hand off candidates to later workflows such as `earnings-deep-dive`, `equity-model-update`, or `long-short-pitch`.

The Investment Banking tag is represented only as optional event metadata for capital-markets and transaction-like catalysts, such as `ecm`, `dcm`, `mna`, and `restructuring`. The schema does not create a banker execution workflow, CIM workflow, financing recommendation, or board package.

## Design Principles

- **Ticker is not an identifier.** `securities` stores active listings, while `security_identifiers` stores provider-specific identifiers such as CIK and FIGI.
- **Raw and normalized data stay separate.** `raw_payloads` stores provider JSON with `json_valid(...)`; analytical fields live in normalized tables.
- **Evidence is first-class.** `evidence_items` and `evidence_fts` preserve searchable excerpts and source labels.
- **Theme exposure must be proven.** `v_candidate_readiness` only marks a candidate as advance-eligible when exposure is source-backed by `orders`, `backlog`, `revenue`, `margin`, or `estimate_revision`.
- **Keyword-only is not enough.** `keyword_only` and unsupported management-claim exposure remain `Exposure not yet proven`.
- **As-of dates matter.** `v_stale_market_data` flags market, valuation, and estimate rows older than the screen run date.
- **PM sessions stay separate.** `pm_sessions` and related tables preserve independent diligence, long/short, and long-only conclusions instead of blending them into one score.
- **Actionability is gated.** `v_pm_session_candidate_readiness` and PM gate triggers require source-backed exposure and passed required gates before a PM session candidate can become actionable.

## Files

- `schema.sql` - SQLite DDL, indexes, FTS5 table, triggers, and views.
- `seed_demo.sql` - synthetic core demo data for the `AI infrastructure` initial sample theme.
- `seed_pm_sessions.sql` - synthetic PM session seed data for three independent investment-style sessions.
- `build_theme_database.py` - materializes a SQLite database from the schema and seed files.
- `tests/validate_schema.py` - in-memory validation of DDL, seed data, constraints, FTS search, views, and handoffs.
- `tests/validate_pm_database.py` - PM session validation plus file-database build validation.
- `visual_onboarding/` - Vercel-ready React/Vite dashboard that visualizes the PM session board, workflow cockpit, and schema map from exported SQLite summary data.

## Table Groups

### Theme Core

- `themes`
- `theme_pathways`
- `theme_keywords`
- `screen_runs`
- `theme_universe`

These tables define the screen: what theme is being tested, which value-chain pathways matter, which run produced the candidate set, and which securities are in scope.

### Security Master

- `entities`
- `securities`
- `security_identifiers`
- `listing_history`

Use these tables to avoid ticker-only joins. The schema supports CIK, FIGI, exchange code, MIC, ADR/local lines, inactive listings, and future provider mappings.

### Source And Evidence

- `ingestion_runs`
- `raw_payloads`
- `sources`
- `source_documents`
- `evidence_items`
- `evidence_fts`
- `data_quality_flags`

Use these tables to preserve provenance. FTS5 search is intentionally scoped to evidence excerpts, not every raw payload.

### Metrics And Market Data

- `metric_definitions`
- `company_metric_facts`
- `market_observations`
- `valuation_snapshots`
- `estimate_snapshots`
- `estimate_revisions`

These tables store normalized facts and dated market inputs. They are designed for source-backed screening, not a full financial model.

### Candidate Triage

- `theme_exposures`
- `candidate_scores`
- `candidate_assessments`
- `candidate_events`
- `theme_false_positive_flags`
- `workflow_handoffs`

These tables store PM-style triage outputs: why a name surfaced, what might be priced in, first rejection risk, investability conditions, kill criteria, and next workflow.

### PM Session Layer

- `pm_sessions`
- `pm_session_candidates`
- `pm_score_dimensions`
- `pm_candidate_scores`
- `pm_decision_gates`
- `pm_cross_session_conflicts`
- `freshness_policies`
- `assumption_register`
- `source_conflicts`

These tables let the same screen be reviewed as three separate PM sessions: public-equity diligence, long/short hedge fund, and long-only PM. A security can have different decision buckets, gates, actionability, and next workflows in each session.

## Example Queries

Rank candidates by beneficiary pathway:

```sql
SELECT pathway_name, pathway_rank, ticker, legal_name, priority_bucket, composite_score
FROM v_pathway_ranked_candidates
WHERE screen_run_id = 1
ORDER BY pathway_name, pathway_rank;
```

Find candidates that are not ready because exposure is only keyword-based:

```sql
SELECT s.ticker_upper AS ticker, e.legal_name, te.exposure_summary
FROM theme_exposures te
JOIN securities s ON s.security_id = te.security_id
JOIN entities e ON e.entity_id = s.entity_id
WHERE te.exposure_type = 'keyword_only';
```

Check advance eligibility:

```sql
SELECT ticker, legal_name, priority_bucket, has_source_backed_exposure, advance_eligible
FROM v_candidate_readiness
ORDER BY ticker;
```

Search evidence excerpts:

```sql
SELECT ei.evidence_id, ei.evidence_label, ei.excerpt
FROM evidence_fts fts
JOIN evidence_items ei ON ei.evidence_id = fts.rowid
WHERE evidence_fts MATCH 'backlog';
```

Find stale market inputs:

```sql
SELECT screen_run_id, security_id, data_table, row_id, as_of_date, screen_as_of_date, stale_days
FROM v_stale_market_data
ORDER BY security_id, data_table;
```

Review separate PM session conclusions:

```sql
SELECT session_style, ticker, decision_bucket, actionability, next_workflow, handoff_allowed
FROM v_pm_session_candidate_readiness
ORDER BY ticker, session_style;
```

Find policy-based stale inputs:

```sql
SELECT screen_run_id, security_id, data_table, coalesce(observation_type, metric_name) AS data_key, stale_days, max_age_days
FROM v_policy_stale_data
ORDER BY security_id, data_table;
```

Review cross-session conflicts:

```sql
SELECT security_id, conflict_type, diligence_decision, long_short_decision, long_only_decision, resolution_note
FROM pm_cross_session_conflicts
ORDER BY security_id, conflict_type;
```

## Validation

Run from the repository root:

```powershell
& "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\research\public_equity_theme_schema\tests\validate_schema.py
& "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\research\public_equity_theme_schema\tests\validate_pm_database.py
```

Build a local SQLite artifact:

```powershell
& "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\research\public_equity_theme_schema\build_theme_database.py --force
```

Run the visual onboarding dashboard locally:

```powershell
& "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\research\public_equity_theme_schema\visual_onboarding\export_dashboard_data.py
cd .\research\public_equity_theme_schema\visual_onboarding
pnpm install
pnpm run dev
```

The validator checks:

- schema and seed loading;
- `PRAGMA foreign_key_check`;
- invalid enum rejection;
- invalid JSON rejection;
- orphan FK rejection;
- duplicate active ticker/exchange rejection;
- duplicate active provider identifier rejection;
- FTS evidence search;
- pathway ranking;
- stale-data detection;
- keyword-only non-readiness;
- downstream handoffs.
- three independent PM sessions;
- session-specific decision buckets;
- score dimension/session-style compatibility;
- source-backed exposure and gate requirements for actionability;
- policy-based stale-data detection;
- generated SQLite database integrity, FTS search, and readiness views.

## Source Research Notes

- SQLite foreign keys require enforcement per connection, so callers must enable `PRAGMA foreign_keys=ON`: [SQLite Foreign Key Support](https://sqlite.org/foreignkeys.html).
- SQLite FTS5 uses virtual tables and is suitable for source excerpt search: [SQLite FTS5 Extension](https://sqlite.org/fts5.html).
- SQLite JSON functions support validating and querying JSON payloads: [SQLite JSON Functions](https://sqlite.org/json1.html).
- SQLite partial indexes support active-only uniqueness rules: [SQLite Partial Indexes](https://sqlite.org/partialindex.html).
- SQLite generated columns support computed values such as `ticker_upper`: [SQLite Generated Columns](https://sqlite.org/gencol.html).
- SEC EDGAR APIs expose company submissions and XBRL-derived company facts: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- SEC fair-access guidance currently states a 10 requests/second maximum rate: [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
- OpenFIGI is useful for mapping securities to FIGI and related identifiers: [OpenFIGI API Documentation](https://www.openfigi.com/api/documentation).
- Alpaca market-data snapshots include latest trade, quote, minute bar, daily bar, and previous daily bar data: [Alpaca Snapshot API](https://alpaca.markets/learn/snapshot-api).

## Operating Assumptions

- First implementation is schema and validation only, not live ingestion.
- Initial sample universe is liquid listed equities with U.S. SEC support first.
- Non-U.S. issuers are supported through generic source, identifier, metric, and document fields.
- Stored language should remain `candidate`, `watchlist`, or `requires diligence`; it should not become a final trade recommendation.
