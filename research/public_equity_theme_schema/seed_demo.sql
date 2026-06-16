PRAGMA foreign_keys = ON;

INSERT INTO themes (
  theme_id,
  theme_name,
  thesis_text,
  horizon_months,
  region_scope,
  status
) VALUES (
  1,
  'AI infrastructure',
  'Screen liquid listed equities that may benefit from rising AI data-center power, cooling, and electrical infrastructure demand.',
  18,
  'US listed equities',
  'active'
);

INSERT INTO theme_pathways (
  pathway_id,
  theme_id,
  pathway_name,
  demand_driver,
  value_chain_role,
  priority_order
) VALUES
  (1, 1, 'Power and electrical distribution', 'AI data-center load growth raises need for grid, switchgear, and power-distribution capacity.', 'electrical equipment', 1),
  (2, 1, 'Thermal management and critical power', 'Higher rack densities increase cooling, power-management, and uptime requirements.', 'data-center equipment', 2);

INSERT INTO theme_keywords (keyword_id, theme_id, keyword, keyword_type, weight) VALUES
  (1, 1, 'AI data center', 'driver', 2.0),
  (2, 1, 'power distribution', 'product', 1.5),
  (3, 1, 'thermal management', 'product', 1.5),
  (4, 1, 'backlog', 'risk', 1.0);

INSERT INTO screen_runs (
  screen_run_id,
  theme_id,
  run_label,
  as_of_date,
  mandate,
  universe_scope,
  source_notes,
  status
) VALUES (
  1,
  1,
  'AI infrastructure first-pass schema demo',
  '2026-06-16',
  'public_equity_diligence',
  'Liquid US-listed common equities; demo data only.',
  'Seed rows are synthetic examples used to validate schema behavior, not live investment data.',
  'completed'
);

INSERT INTO entities (
  entity_id,
  legal_name,
  cik,
  country,
  sector,
  industry,
  fiscal_year_end
) VALUES
  (1, 'Vertiv Holdings Co', '0001674101', 'US', 'Industrials', 'Electrical Equipment', '12-31'),
  (2, 'Eaton Corporation plc', '0001551182', 'IE', 'Industrials', 'Electrical Components and Equipment', '12-31');

INSERT INTO securities (
  security_id,
  entity_id,
  ticker,
  exchange_code,
  mic,
  currency,
  security_type,
  is_active
) VALUES
  (1, 1, 'VRT', 'NYSE', 'XNYS', 'USD', 'common_stock', 1),
  (2, 2, 'ETN', 'NYSE', 'XNYS', 'USD', 'common_stock', 1);

INSERT INTO security_identifiers (
  identifier_id,
  security_id,
  provider,
  id_type,
  id_value,
  is_active,
  valid_from
) VALUES
  (1, 1, 'SEC', 'CIK', '0001674101', 1, '2020-01-01'),
  (2, 2, 'SEC', 'CIK', '0001551182', 1, '2012-01-01'),
  (3, 1, 'OpenFIGI', 'FIGI', 'BBG000VRTDEM', 1, '2026-06-16'),
  (4, 2, 'OpenFIGI', 'FIGI', 'BBG000ETNDEM', 1, '2026-06-16');

INSERT INTO listing_history (
  listing_id,
  security_id,
  exchange_code,
  ticker,
  start_date,
  end_date
) VALUES
  (1, 1, 'NYSE', 'VRT', '2020-02-10', NULL),
  (2, 2, 'NYSE', 'ETN', '2012-11-30', NULL);

INSERT INTO ingestion_runs (
  ingestion_run_id,
  provider,
  started_at,
  completed_at,
  status,
  user_agent,
  rate_limit_notes,
  metadata_json
) VALUES
  (1, 'SEC EDGAR', '2026-06-16T00:00:00Z', '2026-06-16T00:00:01Z', 'completed', 'public-equity-theme-schema-demo contact@example.com', 'Respect 10 requests/second max request rate.', '{"endpoint":"companyfacts","demo":true}'),
  (2, 'Alpaca', '2026-06-16T00:00:02Z', '2026-06-16T00:00:03Z', 'completed', NULL, 'Provider entitlement and feed must be captured per observation.', '{"endpoint":"snapshot","demo":true}');

INSERT INTO raw_payloads (
  raw_payload_id,
  ingestion_run_id,
  provider,
  source_url,
  payload_json,
  payload_sha256,
  accessed_at
) VALUES
  (1, 1, 'SEC EDGAR', 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001674101.json', '{"demo":true,"company":"Vertiv Holdings Co","metric":"Revenue"}', 'demo-sec-vrt', '2026-06-16T00:00:01Z'),
  (2, 1, 'SEC EDGAR', 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001551182.json', '{"demo":true,"company":"Eaton Corporation plc","metric":"Revenue"}', 'demo-sec-etn', '2026-06-16T00:00:01Z'),
  (3, 2, 'Alpaca', 'https://data.alpaca.markets/v2/stocks/snapshots?symbols=VRT,ETN', '{"demo":true,"symbols":["VRT","ETN"]}', 'demo-alpaca-snapshots', '2026-06-16T00:00:03Z');

INSERT INTO sources (
  source_id,
  provider,
  source_type,
  title,
  source_url,
  published_at,
  accessed_at,
  reliability_tier,
  raw_payload_id,
  source_status
) VALUES
  (1, 'SEC EDGAR', 'sec_filing', 'Vertiv demo filing-derived excerpt', 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001674101.json', '2026-02-15', '2026-06-16T00:00:01Z', 1, 1, 'usable'),
  (2, 'SEC EDGAR', 'sec_filing', 'Eaton demo filing-derived excerpt', 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001551182.json', '2026-02-20', '2026-06-16T00:00:01Z', 1, 2, 'usable'),
  (3, 'Alpaca', 'market_data', 'Demo market-data snapshot', 'https://data.alpaca.markets/v2/stocks/snapshots', '2026-06-16', '2026-06-16T00:00:03Z', 3, 3, 'usable'),
  (4, 'Consensus export', 'estimate_export', 'Demo consensus export', NULL, '2026-06-16', '2026-06-16T00:00:04Z', 3, NULL, 'usable');

INSERT INTO source_documents (
  document_id,
  source_id,
  entity_id,
  form_type,
  accession_no,
  fiscal_period,
  document_date
) VALUES
  (1, 1, 1, '10-K', '0001674101-demo', 'FY2025', '2026-02-15'),
  (2, 2, 2, '10-K', '0001551182-demo', 'FY2025', '2026-02-20');

INSERT INTO evidence_items (
  evidence_id,
  source_id,
  document_id,
  evidence_label,
  excerpt,
  metric_name,
  period,
  as_of_date,
  confidence,
  raw_payload_id,
  source_url
) VALUES
  (1, 1, 1, 'fact', 'Demo excerpt: critical digital infrastructure revenue and backlog are used as source-backed exposure proof for data-center equipment demand.', 'revenue', 'FY2025', '2026-06-16', 0.90, 1, 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001674101.json'),
  (2, 2, 2, 'management_claim', 'Demo excerpt: management commentary mentions AI data-center electrical demand, but this seed intentionally does not quantify exposure.', 'AI data center', 'FY2025', '2026-06-16', 0.60, 2, 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001551182.json');

INSERT INTO metric_definitions (
  metric_id,
  metric_name,
  unit,
  taxonomy,
  sector_scope,
  is_standard
) VALUES
  (1, 'Revenue', 'USD', 'US-GAAP', 'Industrials', 1),
  (2, 'Adjusted EBITDA', 'USD', 'Non-GAAP', 'Industrials', 0);

INSERT INTO company_metric_facts (
  fact_id,
  entity_id,
  metric_id,
  period_end,
  fiscal_period,
  value,
  currency,
  source_id,
  as_of_date
) VALUES
  (1, 1, 1, '2025-12-31', 'FY2025', 100.0, 'USD', 1, '2026-06-16'),
  (2, 2, 1, '2025-12-31', 'FY2025', 100.0, 'USD', 2, '2026-06-16');

INSERT INTO market_observations (
  observation_id,
  security_id,
  observation_type,
  value,
  currency,
  feed,
  observed_at,
  as_of_date,
  source_id
) VALUES
  (1, 1, 'price', 100.0, 'USD', 'demo', '2026-06-16T00:00:03Z', '2026-06-16', 3),
  (2, 2, 'price', 200.0, 'USD', 'demo', '2026-06-10T00:00:03Z', '2026-06-10', 3);

INSERT INTO valuation_snapshots (
  snapshot_id,
  security_id,
  metric_name,
  value,
  denominator,
  period_basis,
  as_of_date,
  source_id
) VALUES
  (1, 1, 'EV/EBITDA', 24.0, 'FY2 adjusted EBITDA', 'FY2', '2026-06-16', 4),
  (2, 2, 'EV/EBITDA', 20.0, 'FY2 adjusted EBITDA', 'FY2', '2026-06-10', 4);

INSERT INTO estimate_snapshots (
  estimate_id,
  security_id,
  metric_name,
  fiscal_period,
  consensus_value,
  estimate_count,
  as_of_date,
  source_id
) VALUES
  (1, 1, 'Adjusted EBITDA', 'FY2026E', 100.0, 12, '2026-06-16', 4),
  (2, 2, 'Adjusted EBITDA', 'FY2026E', 100.0, 15, '2026-06-10', 4);

INSERT INTO estimate_revisions (
  revision_id,
  security_id,
  metric_name,
  fiscal_period,
  prior_value,
  current_value,
  revision_pct,
  window_days,
  as_of_date,
  source_id
) VALUES
  (1, 1, 'Adjusted EBITDA', 'FY2026E', 95.0, 100.0, 5.26, 30, '2026-06-16', 4),
  (2, 2, 'Adjusted EBITDA', 'FY2026E', 100.0, 100.0, 0.00, 30, '2026-06-10', 4);

INSERT INTO theme_universe (
  screen_run_id,
  security_id,
  pathway_id,
  inclusion_reason,
  status
) VALUES
  (1, 1, 2, 'Data-center critical power and thermal management candidate.', 'included'),
  (1, 2, 1, 'Electrical equipment candidate with thematic keyword exposure requiring attribution.', 'included');

INSERT INTO theme_exposures (
  exposure_id,
  screen_run_id,
  security_id,
  pathway_id,
  exposure_type,
  exposure_summary,
  evidence_id,
  strength_score
) VALUES
  (1, 1, 1, 2, 'revenue', 'Demo source-backed link from data-center infrastructure demand to company revenue exposure.', 1, 82.0),
  (2, 1, 2, 1, 'keyword_only', 'Demo keyword-only AI infrastructure mention without quantified orders, backlog, revenue, margins, or estimate revisions.', NULL, 35.0);

INSERT INTO candidate_scores (
  score_id,
  screen_run_id,
  security_id,
  valuation,
  growth,
  revisions,
  quality,
  momentum,
  catalysts,
  risk,
  liquidity,
  data_quality,
  composite_score
) VALUES
  (1, 1, 1, 45, 85, 78, 70, 75, 72, 58, 90, 80, 76),
  (2, 1, 2, 50, 70, 50, 75, 65, 55, 60, 95, 45, 61);

INSERT INTO candidate_assessments (
  assessment_id,
  screen_run_id,
  security_id,
  priority_bucket,
  actionability,
  variant_wedge,
  why_now,
  priced_in,
  first_rejection,
  investable_if,
  kill_if,
  next_workflow
) VALUES
  (1, 1, 1, 'Advance to deeper work', 'Candidate for deeper research only; not a trade recommendation.', 'Potential wedge is whether AI infrastructure demand can support revisions beyond current expectations.', 'Estimate revisions and data-center capex debate make the next evidence window relevant.', 'Valuation may already price a strong AI infrastructure runway.', 'Reject if revenue linkage is broad narrative without margin or estimate follow-through.', 'Advance if model work shows revenue and margin revisions can continue without heroic assumptions.', 'Kill if backlog/revenue proof fails or valuation already discounts the upside case.', 'equity-model-update'),
  (2, 1, 2, 'Exposure not yet proven', 'Watchlist only until exposure attribution is quantified.', 'The market may conflate broad electrical exposure with AI-specific demand.', 'Theme visibility is high, but company-specific evidence is not yet strong enough.', 'Some electrification upside may already be capitalized.', 'Reject first because current evidence is keyword-only.', 'Advance if filings or transcripts tie AI data-center demand to orders, backlog, revenue, margins, or estimate revisions.', 'Kill if the link remains generic or stale.', 'long-short-pitch');

INSERT INTO candidate_events (
  event_id,
  security_id,
  event_type,
  event_domain,
  event_date,
  event_window,
  importance,
  source_id
) VALUES
  (1, 1, 'Next earnings print', 'earnings', NULL, 'next 90 days', 4, 1),
  (2, 2, 'Potential capital markets read-through', 'ecm', NULL, 'monitoring item', 2, 2);

INSERT INTO theme_false_positive_flags (
  flag_id,
  screen_run_id,
  security_id,
  flag_type,
  reason,
  evidence_id
) VALUES
  (1, 1, 2, 'keyword_only', 'Theme mention is not enough to advance without orders, backlog, revenue, margin, or estimate-revision evidence.', 2);

INSERT INTO workflow_handoffs (
  handoff_id,
  screen_run_id,
  security_id,
  next_workflow,
  handoff_question,
  status
) VALUES
  (1, 1, 1, 'equity-model-update', 'Rebuild the FY2 revenue and margin bridge for AI infrastructure exposure.', 'open'),
  (2, 1, 1, 'earnings-deep-dive', 'Check whether the latest print validates backlog, revenue, margin, and guidance durability.', 'open'),
  (3, 1, 2, 'long-short-pitch', 'Do not pitch until exposure attribution is proven; pressure-test only if the data gap is resolved.', 'deferred');

INSERT INTO data_quality_flags (
  flag_id,
  table_name,
  row_pk,
  flag_type,
  severity,
  message
) VALUES
  (1, 'market_observations', '2', 'stale', 'medium', 'Demo ETN market observation predates the screen run as-of date.'),
  (2, 'theme_exposures', '2', 'data_gap', 'high', 'Demo ETN exposure is keyword-only and should not be treated as source-backed.');
