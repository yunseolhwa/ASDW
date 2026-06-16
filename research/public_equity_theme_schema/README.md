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
- hand off candidates to later workflows such as `earnings-deep-dive`, `equity-model-update`, or `long-short-pitch`.

The Investment Banking tag is represented only as optional event metadata for capital-markets and transaction-like catalysts, such as `ecm`, `dcm`, `mna`, and `restructuring`. The schema does not create a banker execution workflow, CIM workflow, financing recommendation, or board package.

## Design Principles

- **Ticker is not an identifier.** `securities` stores active listings, while `security_identifiers` stores provider-specific identifiers such as CIK and FIGI.
- **Raw and normalized data stay separate.** `raw_payloads` stores provider JSON with `json_valid(...)`; analytical fields live in normalized tables.
- **Evidence is first-class.** `evidence_items` and `evidence_fts` preserve searchable excerpts and source labels.
- **Theme exposure must be proven.** `v_candidate_readiness` only marks a candidate as advance-eligible when exposure is source-backed by `orders`, `backlog`, `revenue`, `margin`, or `estimate_revision`.
- **Keyword-only is not enough.** `keyword_only` and unsupported management-claim exposure remain `Exposure not yet proven`.
- **As-of dates matter.** `v_stale_market_data` flags market, valuation, and estimate rows older than the screen run date.

## Files

- `schema.sql` - SQLite DDL, indexes, FTS5 table, triggers, and views.
- `seed_demo.sql` - synthetic demo data for `AI infrastructure`.
- `tests/validate_schema.py` - in-memory validation of DDL, seed data, constraints, FTS search, views, and handoffs.

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

## Validation

Run from the repository root:

```powershell
& "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\research\public_equity_theme_schema\tests\validate_schema.py
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
- Default universe is liquid listed equities with U.S. SEC support first.
- Non-U.S. issuers are supported through generic source, identifier, metric, and document fields.
- Stored language should remain `candidate`, `watchlist`, or `requires diligence`; it should not become a final trade recommendation.
