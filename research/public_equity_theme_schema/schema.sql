PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA user_version = 2;

CREATE TABLE schema_migrations (
  migration_id TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now')),
  description TEXT NOT NULL
);

CREATE TABLE themes (
  theme_id INTEGER PRIMARY KEY,
  theme_name TEXT NOT NULL UNIQUE,
  thesis_text TEXT NOT NULL,
  horizon_months INTEGER NOT NULL CHECK (horizon_months > 0),
  region_scope TEXT NOT NULL DEFAULT 'global',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('draft', 'active', 'archived'))
);

CREATE TABLE theme_pathways (
  pathway_id INTEGER PRIMARY KEY,
  theme_id INTEGER NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
  pathway_name TEXT NOT NULL,
  demand_driver TEXT NOT NULL,
  value_chain_role TEXT NOT NULL,
  priority_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (theme_id, pathway_name)
);

CREATE TABLE theme_keywords (
  keyword_id INTEGER PRIMARY KEY,
  theme_id INTEGER NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
  keyword TEXT NOT NULL,
  keyword_type TEXT NOT NULL
    CHECK (keyword_type IN ('driver', 'product', 'customer', 'competitor', 'risk', 'other')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK (weight >= 0),
  UNIQUE (theme_id, keyword, keyword_type)
);

CREATE TABLE screen_runs (
  screen_run_id INTEGER PRIMARY KEY,
  theme_id INTEGER NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
  run_label TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  mandate TEXT NOT NULL DEFAULT 'public_equity_diligence'
    CHECK (mandate IN (
      'long_only_pm',
      'long_short_hf',
      'sell_side_research',
      'etf_index_diligence',
      'public_equity_diligence',
      'other'
    )),
  universe_scope TEXT NOT NULL,
  source_notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('draft', 'completed', 'superseded'))
);

CREATE TABLE entities (
  entity_id INTEGER PRIMARY KEY,
  legal_name TEXT NOT NULL,
  cik TEXT UNIQUE,
  country TEXT NOT NULL,
  sector TEXT,
  industry TEXT,
  fiscal_year_end TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE securities (
  security_id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  ticker_upper TEXT GENERATED ALWAYS AS (upper(ticker)) VIRTUAL,
  exchange_code TEXT NOT NULL,
  mic TEXT,
  currency TEXT NOT NULL,
  security_type TEXT NOT NULL DEFAULT 'common_stock'
    CHECK (security_type IN ('common_stock', 'adr', 'gdr', 'preferred', 'etf', 'fund', 'other')),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE UNIQUE INDEX ux_securities_active_exchange_ticker
  ON securities(exchange_code, ticker_upper)
  WHERE is_active = 1;

CREATE TABLE security_identifiers (
  identifier_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  id_type TEXT NOT NULL,
  id_value TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  valid_from TEXT,
  valid_to TEXT
);

CREATE UNIQUE INDEX ux_security_identifiers_active_provider_value
  ON security_identifiers(provider, id_type, id_value)
  WHERE is_active = 1;

CREATE TABLE listing_history (
  listing_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  exchange_code TEXT NOT NULL,
  ticker TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT
);

CREATE TABLE ingestion_runs (
  ingestion_run_id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL
    CHECK (status IN ('started', 'completed', 'failed', 'skipped')),
  user_agent TEXT,
  rate_limit_notes TEXT,
  metadata_json TEXT CHECK (metadata_json IS NULL OR json_valid(metadata_json))
);

CREATE TABLE raw_payloads (
  raw_payload_id INTEGER PRIMARY KEY,
  ingestion_run_id INTEGER NOT NULL REFERENCES ingestion_runs(ingestion_run_id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  source_url TEXT,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  payload_sha256 TEXT,
  accessed_at TEXT NOT NULL
);

CREATE TABLE sources (
  source_id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  source_type TEXT NOT NULL
    CHECK (source_type IN (
      'sec_filing',
      'earnings_release',
      'transcript',
      'investor_presentation',
      'market_data',
      'estimate_export',
      'internal_research',
      'news',
      'provider_api',
      'other'
    )),
  title TEXT NOT NULL,
  source_url TEXT,
  published_at TEXT,
  accessed_at TEXT NOT NULL,
  reliability_tier INTEGER NOT NULL CHECK (reliability_tier BETWEEN 1 AND 5),
  raw_payload_id INTEGER REFERENCES raw_payloads(raw_payload_id) ON DELETE SET NULL,
  source_status TEXT NOT NULL DEFAULT 'usable'
    CHECK (source_status IN ('usable', 'stale', 'superseded', 'failed'))
);

CREATE TABLE source_documents (
  document_id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  entity_id INTEGER REFERENCES entities(entity_id) ON DELETE SET NULL,
  form_type TEXT,
  accession_no TEXT,
  fiscal_period TEXT,
  document_date TEXT,
  UNIQUE (source_id, accession_no)
);

CREATE TABLE evidence_items (
  evidence_id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  document_id INTEGER REFERENCES source_documents(document_id) ON DELETE SET NULL,
  evidence_label TEXT NOT NULL
    CHECK (evidence_label IN (
      'fact',
      'management_claim',
      'consensus',
      'market_data',
      'assumption',
      'pm_judgment',
      'data_gap'
    )),
  excerpt TEXT NOT NULL,
  metric_name TEXT,
  period TEXT,
  as_of_date TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
  raw_payload_id INTEGER REFERENCES raw_payloads(raw_payload_id) ON DELETE SET NULL,
  source_url TEXT
);

CREATE VIRTUAL TABLE evidence_fts USING fts5(
  excerpt,
  metric_name,
  content='evidence_items',
  content_rowid='evidence_id'
);

CREATE TRIGGER evidence_items_ai
AFTER INSERT ON evidence_items
BEGIN
  INSERT INTO evidence_fts(rowid, excerpt, metric_name)
  VALUES (new.evidence_id, new.excerpt, new.metric_name);
END;

CREATE TRIGGER evidence_items_ad
AFTER DELETE ON evidence_items
BEGIN
  INSERT INTO evidence_fts(evidence_fts, rowid, excerpt, metric_name)
  VALUES ('delete', old.evidence_id, old.excerpt, old.metric_name);
END;

CREATE TRIGGER evidence_items_au
AFTER UPDATE ON evidence_items
BEGIN
  INSERT INTO evidence_fts(evidence_fts, rowid, excerpt, metric_name)
  VALUES ('delete', old.evidence_id, old.excerpt, old.metric_name);
  INSERT INTO evidence_fts(rowid, excerpt, metric_name)
  VALUES (new.evidence_id, new.excerpt, new.metric_name);
END;

CREATE TABLE metric_definitions (
  metric_id INTEGER PRIMARY KEY,
  metric_name TEXT NOT NULL,
  unit TEXT NOT NULL,
  taxonomy TEXT,
  sector_scope TEXT,
  is_standard INTEGER NOT NULL DEFAULT 1 CHECK (is_standard IN (0, 1))
);

CREATE UNIQUE INDEX ux_metric_definitions_identity
  ON metric_definitions(metric_name, unit, ifnull(taxonomy, ''), ifnull(sector_scope, ''));

CREATE TABLE company_metric_facts (
  fact_id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  metric_id INTEGER NOT NULL REFERENCES metric_definitions(metric_id) ON DELETE CASCADE,
  period_end TEXT NOT NULL,
  fiscal_period TEXT NOT NULL,
  value REAL NOT NULL,
  currency TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
  as_of_date TEXT NOT NULL
);

CREATE TABLE market_observations (
  observation_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  observation_type TEXT NOT NULL
    CHECK (observation_type IN (
      'latest_trade',
      'latest_quote',
      'latest_bar',
      'snapshot',
      'volume',
      'price',
      'market_cap',
      'adv',
      'short_interest',
      'borrow',
      'ownership',
      'index_weight',
      'other'
    )),
  value REAL NOT NULL,
  currency TEXT,
  feed TEXT,
  observed_at TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT
);

CREATE TABLE valuation_snapshots (
  snapshot_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  value REAL NOT NULL,
  denominator TEXT,
  period_basis TEXT,
  as_of_date TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT
);

CREATE TABLE estimate_snapshots (
  estimate_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  fiscal_period TEXT NOT NULL,
  consensus_value REAL NOT NULL,
  estimate_count INTEGER CHECK (estimate_count IS NULL OR estimate_count >= 0),
  as_of_date TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT
);

CREATE TABLE estimate_revisions (
  revision_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  fiscal_period TEXT NOT NULL,
  prior_value REAL NOT NULL,
  current_value REAL NOT NULL,
  revision_pct REAL,
  window_days INTEGER NOT NULL CHECK (window_days > 0),
  as_of_date TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT
);

CREATE TABLE theme_universe (
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  pathway_id INTEGER NOT NULL REFERENCES theme_pathways(pathway_id) ON DELETE CASCADE,
  inclusion_reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'included'
    CHECK (status IN ('included', 'watchlist', 'excluded')),
  PRIMARY KEY (screen_run_id, security_id, pathway_id)
) WITHOUT ROWID;

CREATE TABLE theme_exposures (
  exposure_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  pathway_id INTEGER NOT NULL REFERENCES theme_pathways(pathway_id) ON DELETE CASCADE,
  exposure_type TEXT NOT NULL
    CHECK (exposure_type IN (
      'orders',
      'backlog',
      'revenue',
      'margin',
      'estimate_revision',
      'management_claim',
      'keyword_only'
    )),
  exposure_summary TEXT NOT NULL,
  evidence_id INTEGER REFERENCES evidence_items(evidence_id) ON DELETE SET NULL,
  strength_score REAL NOT NULL CHECK (strength_score >= 0 AND strength_score <= 100),
  CHECK (
    (exposure_type = 'keyword_only' AND evidence_id IS NULL)
    OR (exposure_type <> 'keyword_only' AND evidence_id IS NOT NULL)
  )
);

CREATE TABLE candidate_scores (
  score_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  valuation REAL NOT NULL CHECK (valuation BETWEEN 0 AND 100),
  growth REAL NOT NULL CHECK (growth BETWEEN 0 AND 100),
  revisions REAL NOT NULL CHECK (revisions BETWEEN 0 AND 100),
  quality REAL NOT NULL CHECK (quality BETWEEN 0 AND 100),
  momentum REAL NOT NULL CHECK (momentum BETWEEN 0 AND 100),
  catalysts REAL NOT NULL CHECK (catalysts BETWEEN 0 AND 100),
  risk REAL NOT NULL CHECK (risk BETWEEN 0 AND 100),
  liquidity REAL NOT NULL CHECK (liquidity BETWEEN 0 AND 100),
  data_quality REAL NOT NULL CHECK (data_quality BETWEEN 0 AND 100),
  composite_score REAL NOT NULL CHECK (composite_score BETWEEN 0 AND 100),
  UNIQUE (screen_run_id, security_id)
);

CREATE TABLE candidate_assessments (
  assessment_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  priority_bucket TEXT NOT NULL
    CHECK (priority_bucket IN (
      'Advance to deeper work',
      'Valuation / expectations gated',
      'Exposure not yet proven',
      'Deprioritized or reject'
    )),
  actionability TEXT NOT NULL,
  variant_wedge TEXT NOT NULL,
  why_now TEXT NOT NULL,
  priced_in TEXT NOT NULL,
  first_rejection TEXT NOT NULL,
  investable_if TEXT NOT NULL,
  kill_if TEXT NOT NULL,
  next_workflow TEXT NOT NULL
    CHECK (next_workflow IN (
      'earnings-deep-dive',
      'equity-model-update',
      'long-short-pitch',
      'earnings-preview',
      'thesis-tracker',
      'portfolio-risk-management',
      'event-driven-analyzer',
      'economic-impact-report',
      'catalyst-calendar',
      'company-tearsheet',
      'comps-valuation',
      'dcf-model-builder',
      'scenario-sensitivity-generator',
      'memo-builder',
      'credit-markets',
      'none'
    )),
  UNIQUE (screen_run_id, security_id)
);

CREATE TABLE candidate_events (
  event_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  event_domain TEXT NOT NULL
    CHECK (event_domain IN (
      'earnings',
      'product',
      'regulatory',
      'litigation',
      'index',
      'macro',
      'ecm',
      'dcm',
      'mna',
      'restructuring',
      'other'
    )),
  event_date TEXT,
  event_window TEXT,
  importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
  source_id INTEGER REFERENCES sources(source_id) ON DELETE SET NULL
);

CREATE TABLE theme_false_positive_flags (
  flag_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  flag_type TEXT NOT NULL
    CHECK (flag_type IN (
      'keyword_only',
      'valuation_gated',
      'expectations_heavy',
      'liquidity_insufficient',
      'sector_metric_mismatch',
      'unsupported_crowding',
      'data_gap',
      'other'
    )),
  reason TEXT NOT NULL,
  evidence_id INTEGER REFERENCES evidence_items(evidence_id) ON DELETE SET NULL
);

CREATE TABLE workflow_handoffs (
  handoff_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  next_workflow TEXT NOT NULL
    CHECK (next_workflow IN (
      'earnings-deep-dive',
      'equity-model-update',
      'long-short-pitch',
      'earnings-preview',
      'thesis-tracker',
      'portfolio-risk-management',
      'event-driven-analyzer',
      'economic-impact-report',
      'catalyst-calendar',
      'company-tearsheet',
      'comps-valuation',
      'dcf-model-builder',
      'scenario-sensitivity-generator',
      'memo-builder',
      'credit-markets'
    )),
  handoff_question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'in_progress', 'completed', 'deferred'))
);

CREATE TABLE data_quality_flags (
  flag_id INTEGER PRIMARY KEY,
  table_name TEXT NOT NULL,
  row_pk TEXT NOT NULL,
  flag_type TEXT NOT NULL
    CHECK (flag_type IN (
      'stale',
      'missing_source',
      'conflicting_source',
      'invalid_identifier',
      'unsupported_metric',
      'low_confidence',
      'data_gap',
      'other'
    )),
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE pm_sessions (
  session_id INTEGER PRIMARY KEY,
  theme_id INTEGER NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  session_style TEXT NOT NULL
    CHECK (session_style IN (
      'public_equity_diligence',
      'long_short_hf',
      'long_only_pm'
    )),
  session_label TEXT NOT NULL,
  objective TEXT NOT NULL,
  owner_role TEXT NOT NULL DEFAULT 'PM',
  as_of_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('draft', 'completed', 'superseded')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (screen_run_id, session_style)
);

CREATE TABLE pm_session_candidates (
  session_candidate_id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES pm_sessions(session_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  pathway_id INTEGER NOT NULL REFERENCES theme_pathways(pathway_id) ON DELETE CASCADE,
  decision_bucket TEXT NOT NULL
    CHECK (decision_bucket IN (
      'Advance to deeper work',
      'Valuation / expectations gated',
      'Exposure not yet proven',
      'Deprioritized or reject',
      'Long candidate',
      'Short candidate',
      'Pair / relative value candidate',
      'Watchlist / needs trigger',
      'Pass'
    )),
  actionability TEXT NOT NULL
    CHECK (actionability IN (
      'add',
      'press',
      'hold',
      'trim',
      'exit',
      'cover',
      'hedge',
      'watchlist',
      'pass',
      'wait for proof',
      're-underwrite',
      'research only'
    )),
  direction TEXT NOT NULL DEFAULT 'diligence'
    CHECK (direction IN ('long', 'short', 'pair', 'watchlist', 'diligence', 'none')),
  variant_wedge TEXT NOT NULL,
  why_now TEXT NOT NULL,
  priced_in TEXT NOT NULL,
  first_rejection TEXT NOT NULL,
  investable_if TEXT NOT NULL,
  kill_if TEXT NOT NULL,
  next_workflow TEXT NOT NULL DEFAULT 'none'
    CHECK (next_workflow IN (
      'earnings-deep-dive',
      'equity-model-update',
      'long-short-pitch',
      'earnings-preview',
      'thesis-tracker',
      'portfolio-risk-management',
      'event-driven-analyzer',
      'economic-impact-report',
      'catalyst-calendar',
      'company-tearsheet',
      'comps-valuation',
      'dcf-model-builder',
      'scenario-sensitivity-generator',
      'memo-builder',
      'credit-markets',
      'none'
    )),
  is_actionable INTEGER NOT NULL DEFAULT 0 CHECK (is_actionable IN (0, 1)),
  CHECK (is_actionable = 0 OR next_workflow <> 'none'),
  UNIQUE (session_id, security_id)
);

CREATE TABLE pm_score_dimensions (
  dimension_id INTEGER PRIMARY KEY,
  session_style TEXT NOT NULL
    CHECK (session_style IN (
      'public_equity_diligence',
      'long_short_hf',
      'long_only_pm'
    )),
  dimension_name TEXT NOT NULL,
  dimension_group TEXT NOT NULL,
  weight REAL NOT NULL CHECK (weight >= 0),
  direction TEXT NOT NULL DEFAULT 'higher_is_better'
    CHECK (direction IN ('higher_is_better', 'lower_is_better', 'neutral')),
  required_flag INTEGER NOT NULL DEFAULT 1 CHECK (required_flag IN (0, 1)),
  UNIQUE (session_style, dimension_name)
);

CREATE TABLE pm_candidate_scores (
  score_id INTEGER PRIMARY KEY,
  session_candidate_id INTEGER NOT NULL REFERENCES pm_session_candidates(session_candidate_id) ON DELETE CASCADE,
  dimension_id INTEGER NOT NULL REFERENCES pm_score_dimensions(dimension_id) ON DELETE RESTRICT,
  raw_score REAL NOT NULL CHECK (raw_score BETWEEN 0 AND 100),
  normalized_score REAL NOT NULL CHECK (normalized_score BETWEEN 0 AND 100),
  evidence_id INTEGER REFERENCES evidence_items(evidence_id) ON DELETE SET NULL,
  rationale TEXT NOT NULL,
  UNIQUE (session_candidate_id, dimension_id)
);

CREATE TABLE pm_decision_gates (
  gate_id INTEGER PRIMARY KEY,
  session_candidate_id INTEGER NOT NULL REFERENCES pm_session_candidates(session_candidate_id) ON DELETE CASCADE,
  gate_name TEXT NOT NULL
    CHECK (gate_name IN (
      'exposure_proof',
      'source_pack',
      'valuation',
      'catalyst',
      'liquidity',
      'borrow_crowding',
      'benchmark_fit',
      'risk_reward',
      'data_freshness',
      'other'
    )),
  gate_status TEXT NOT NULL
    CHECK (gate_status IN ('pass', 'watch', 'fail', 'not_applicable')),
  gate_reason TEXT NOT NULL,
  evidence_id INTEGER REFERENCES evidence_items(evidence_id) ON DELETE SET NULL,
  required_flag INTEGER NOT NULL DEFAULT 1 CHECK (required_flag IN (0, 1)),
  reviewed_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (session_candidate_id, gate_name)
);

CREATE TABLE pm_cross_session_conflicts (
  conflict_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER NOT NULL REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER NOT NULL REFERENCES securities(security_id) ON DELETE CASCADE,
  conflict_type TEXT NOT NULL
    CHECK (conflict_type IN (
      'style_divergence',
      'direction_conflict',
      'gate_conflict',
      'data_gap',
      'workflow_conflict',
      'other'
    )),
  diligence_decision TEXT,
  long_short_decision TEXT,
  long_only_decision TEXT,
  resolution_note TEXT NOT NULL,
  next_research_owner TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'resolved', 'deferred')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (screen_run_id, security_id, conflict_type)
);

CREATE TABLE freshness_policies (
  policy_id INTEGER PRIMARY KEY,
  data_table TEXT NOT NULL
    CHECK (data_table IN (
      'market_observations',
      'valuation_snapshots',
      'estimate_snapshots',
      'estimate_revisions',
      'company_metric_facts'
    )),
  observation_type TEXT,
  metric_name TEXT,
  max_age_days INTEGER NOT NULL CHECK (max_age_days >= 0),
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
  policy_notes TEXT NOT NULL,
  CHECK (observation_type IS NOT NULL OR metric_name IS NOT NULL)
);

CREATE TABLE assumption_register (
  assumption_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  session_id INTEGER REFERENCES pm_sessions(session_id) ON DELETE CASCADE,
  security_id INTEGER REFERENCES securities(security_id) ON DELETE CASCADE,
  assumption_text TEXT NOT NULL,
  sensitivity TEXT NOT NULL CHECK (sensitivity IN ('low', 'medium', 'high')),
  evidence_gap TEXT,
  owner_role TEXT NOT NULL,
  review_by TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'resolved', 'superseded')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (screen_run_id IS NOT NULL OR session_id IS NOT NULL)
);

CREATE TABLE source_conflicts (
  conflict_id INTEGER PRIMARY KEY,
  screen_run_id INTEGER REFERENCES screen_runs(screen_run_id) ON DELETE CASCADE,
  security_id INTEGER REFERENCES securities(security_id) ON DELETE CASCADE,
  source_a_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  source_b_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  data_table TEXT NOT NULL,
  row_a_pk TEXT,
  row_b_pk TEXT,
  metric_name TEXT,
  value_a TEXT,
  value_b TEXT,
  conflict_summary TEXT NOT NULL,
  resolution_status TEXT NOT NULL DEFAULT 'open'
    CHECK (resolution_status IN ('open', 'resolved', 'deferred')),
  resolution_note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (source_a_id <> source_b_id)
);

CREATE UNIQUE INDEX ux_freshness_policies_lookup
  ON freshness_policies(data_table, ifnull(observation_type, ''), ifnull(metric_name, ''));

CREATE TRIGGER pm_session_candidates_ai_actionable
BEFORE INSERT ON pm_session_candidates
WHEN new.is_actionable = 1
  AND (
    NOT EXISTS (
      SELECT 1
      FROM pm_sessions ps
      JOIN theme_exposures te
        ON te.screen_run_id = ps.screen_run_id
        AND te.security_id = new.security_id
      WHERE ps.session_id = new.session_id
        AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
        AND te.evidence_id IS NOT NULL
    )
    OR NOT EXISTS (
      SELECT 1
      FROM pm_decision_gates pdg
      WHERE pdg.session_candidate_id = new.session_candidate_id
        AND pdg.required_flag = 1
        AND pdg.gate_status = 'pass'
    )
    OR EXISTS (
      SELECT 1
      FROM pm_decision_gates pdg
      WHERE pdg.session_candidate_id = new.session_candidate_id
        AND pdg.required_flag = 1
        AND pdg.gate_status NOT IN ('pass', 'not_applicable')
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'actionable PM candidate requires source-backed exposure and passed required gates');
END;

CREATE TRIGGER pm_session_candidates_au_actionable
BEFORE UPDATE OF session_id, security_id, is_actionable ON pm_session_candidates
WHEN new.is_actionable = 1
  AND (
    NOT EXISTS (
      SELECT 1
      FROM pm_sessions ps
      JOIN theme_exposures te
        ON te.screen_run_id = ps.screen_run_id
        AND te.security_id = new.security_id
      WHERE ps.session_id = new.session_id
        AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
        AND te.evidence_id IS NOT NULL
    )
    OR NOT EXISTS (
      SELECT 1
      FROM pm_decision_gates pdg
      WHERE pdg.session_candidate_id = new.session_candidate_id
        AND pdg.required_flag = 1
        AND pdg.gate_status = 'pass'
    )
    OR EXISTS (
      SELECT 1
      FROM pm_decision_gates pdg
      WHERE pdg.session_candidate_id = new.session_candidate_id
        AND pdg.required_flag = 1
        AND pdg.gate_status NOT IN ('pass', 'not_applicable')
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'actionable PM candidate requires source-backed exposure and passed required gates');
END;

CREATE TRIGGER pm_candidate_scores_ai_dimension_style
BEFORE INSERT ON pm_candidate_scores
WHEN NOT EXISTS (
  SELECT 1
  FROM pm_session_candidates psc
  JOIN pm_sessions ps ON ps.session_id = psc.session_id
  JOIN pm_score_dimensions psd ON psd.dimension_id = new.dimension_id
  WHERE psc.session_candidate_id = new.session_candidate_id
    AND ps.session_style = psd.session_style
)
BEGIN
  SELECT RAISE(ABORT, 'score dimension style must match candidate session style');
END;

CREATE TRIGGER pm_candidate_scores_au_dimension_style
BEFORE UPDATE OF session_candidate_id, dimension_id ON pm_candidate_scores
WHEN NOT EXISTS (
  SELECT 1
  FROM pm_session_candidates psc
  JOIN pm_sessions ps ON ps.session_id = psc.session_id
  JOIN pm_score_dimensions psd ON psd.dimension_id = new.dimension_id
  WHERE psc.session_candidate_id = new.session_candidate_id
    AND ps.session_style = psd.session_style
)
BEGIN
  SELECT RAISE(ABORT, 'score dimension style must match candidate session style');
END;

CREATE INDEX idx_theme_pathways_theme_id ON theme_pathways(theme_id);
CREATE INDEX idx_theme_keywords_theme_id ON theme_keywords(theme_id);
CREATE INDEX idx_screen_runs_theme_id ON screen_runs(theme_id);
CREATE INDEX idx_securities_entity_id ON securities(entity_id);
CREATE INDEX idx_security_identifiers_security_id ON security_identifiers(security_id);
CREATE INDEX idx_listing_history_security_id ON listing_history(security_id);
CREATE INDEX idx_raw_payloads_ingestion_run_id ON raw_payloads(ingestion_run_id);
CREATE INDEX idx_sources_raw_payload_id ON sources(raw_payload_id);
CREATE INDEX idx_source_documents_source_id ON source_documents(source_id);
CREATE INDEX idx_source_documents_entity_id ON source_documents(entity_id);
CREATE INDEX idx_evidence_items_source_id ON evidence_items(source_id);
CREATE INDEX idx_evidence_items_document_id ON evidence_items(document_id);
CREATE INDEX idx_company_metric_facts_entity_id ON company_metric_facts(entity_id);
CREATE INDEX idx_company_metric_facts_metric_id ON company_metric_facts(metric_id);
CREATE INDEX idx_market_observations_security_id ON market_observations(security_id);
CREATE INDEX idx_valuation_snapshots_security_id ON valuation_snapshots(security_id);
CREATE INDEX idx_estimate_snapshots_security_id ON estimate_snapshots(security_id);
CREATE INDEX idx_estimate_revisions_security_id ON estimate_revisions(security_id);
CREATE INDEX idx_theme_universe_security_id ON theme_universe(security_id);
CREATE INDEX idx_theme_universe_pathway_id ON theme_universe(pathway_id);
CREATE INDEX idx_theme_exposures_screen_security ON theme_exposures(screen_run_id, security_id);
CREATE INDEX idx_theme_exposures_pathway_id ON theme_exposures(pathway_id);
CREATE INDEX idx_theme_exposures_evidence_id ON theme_exposures(evidence_id);
CREATE INDEX idx_candidate_scores_screen_security ON candidate_scores(screen_run_id, security_id);
CREATE INDEX idx_candidate_assessments_screen_security ON candidate_assessments(screen_run_id, security_id);
CREATE INDEX idx_candidate_events_security_id ON candidate_events(security_id);
CREATE INDEX idx_candidate_events_source_id ON candidate_events(source_id);
CREATE INDEX idx_false_positive_screen_security ON theme_false_positive_flags(screen_run_id, security_id);
CREATE INDEX idx_false_positive_evidence_id ON theme_false_positive_flags(evidence_id);
CREATE INDEX idx_workflow_handoffs_screen_security ON workflow_handoffs(screen_run_id, security_id);
CREATE INDEX idx_pm_sessions_screen_style ON pm_sessions(screen_run_id, session_style);
CREATE INDEX idx_pm_session_candidates_session_id ON pm_session_candidates(session_id);
CREATE INDEX idx_pm_session_candidates_security_id ON pm_session_candidates(security_id);
CREATE INDEX idx_pm_candidate_scores_dimension_id ON pm_candidate_scores(dimension_id);
CREATE INDEX idx_pm_decision_gates_candidate_status ON pm_decision_gates(session_candidate_id, gate_status);
CREATE INDEX idx_pm_conflicts_screen_security ON pm_cross_session_conflicts(screen_run_id, security_id);
CREATE INDEX idx_assumption_register_session_id ON assumption_register(session_id);
CREATE INDEX idx_source_conflicts_security_id ON source_conflicts(security_id);

CREATE VIEW v_candidate_readiness AS
SELECT
  ca.screen_run_id,
  ca.security_id,
  s.ticker_upper AS ticker,
  e.legal_name,
  ca.priority_bucket,
  ca.next_workflow,
  CASE
    WHEN EXISTS (
      SELECT 1
      FROM theme_exposures te
      WHERE te.screen_run_id = ca.screen_run_id
        AND te.security_id = ca.security_id
        AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
        AND te.evidence_id IS NOT NULL
    ) THEN 1
    ELSE 0
  END AS has_source_backed_exposure,
  CASE
    WHEN ca.priority_bucket = 'Advance to deeper work'
      AND EXISTS (
        SELECT 1
        FROM theme_exposures te
        WHERE te.screen_run_id = ca.screen_run_id
          AND te.security_id = ca.security_id
          AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
          AND te.evidence_id IS NOT NULL
      )
    THEN 1
    ELSE 0
  END AS advance_eligible
FROM candidate_assessments ca
JOIN securities s ON s.security_id = ca.security_id
JOIN entities e ON e.entity_id = s.entity_id;

CREATE VIEW v_pathway_ranked_candidates AS
SELECT
  tu.screen_run_id,
  tu.pathway_id,
  tp.pathway_name,
  tu.security_id,
  s.ticker_upper AS ticker,
  e.legal_name,
  ca.priority_bucket,
  cs.composite_score,
  cs.data_quality,
  cs.liquidity,
  row_number() OVER (
    PARTITION BY tu.screen_run_id, tu.pathway_id
    ORDER BY
      CASE ca.priority_bucket
        WHEN 'Advance to deeper work' THEN 1
        WHEN 'Valuation / expectations gated' THEN 2
        WHEN 'Exposure not yet proven' THEN 3
        ELSE 4
      END,
      cs.composite_score DESC,
      cs.data_quality DESC,
      cs.liquidity DESC,
      s.ticker_upper
  ) AS pathway_rank
FROM theme_universe tu
JOIN theme_pathways tp ON tp.pathway_id = tu.pathway_id
JOIN securities s ON s.security_id = tu.security_id
JOIN entities e ON e.entity_id = s.entity_id
LEFT JOIN candidate_scores cs
  ON cs.screen_run_id = tu.screen_run_id
  AND cs.security_id = tu.security_id
LEFT JOIN candidate_assessments ca
  ON ca.screen_run_id = tu.screen_run_id
  AND ca.security_id = tu.security_id;

CREATE VIEW v_stale_market_data AS
SELECT
  sr.screen_run_id,
  base.security_id,
  'market_observations' AS data_table,
  mo.observation_id AS row_id,
  mo.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  CAST(julianday(sr.as_of_date) - julianday(mo.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN market_observations mo
  ON mo.security_id = base.security_id
WHERE date(mo.as_of_date) < date(sr.as_of_date)
UNION ALL
SELECT
  sr.screen_run_id,
  base.security_id,
  'valuation_snapshots' AS data_table,
  vs.snapshot_id AS row_id,
  vs.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  CAST(julianday(sr.as_of_date) - julianday(vs.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN valuation_snapshots vs
  ON vs.security_id = base.security_id
WHERE date(vs.as_of_date) < date(sr.as_of_date)
UNION ALL
SELECT
  sr.screen_run_id,
  base.security_id,
  'estimate_snapshots' AS data_table,
  es.estimate_id AS row_id,
  es.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  CAST(julianday(sr.as_of_date) - julianday(es.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN estimate_snapshots es
  ON es.security_id = base.security_id
WHERE date(es.as_of_date) < date(sr.as_of_date)
UNION ALL
SELECT
  sr.screen_run_id,
  base.security_id,
  'estimate_revisions' AS data_table,
  er.revision_id AS row_id,
  er.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  CAST(julianday(sr.as_of_date) - julianday(er.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN estimate_revisions er
  ON er.security_id = base.security_id
WHERE date(er.as_of_date) < date(sr.as_of_date);

CREATE VIEW v_pm_session_candidate_readiness AS
SELECT
  psc.session_candidate_id,
  ps.session_id,
  ps.screen_run_id,
  ps.session_style,
  psc.security_id,
  s.ticker_upper AS ticker,
  e.legal_name,
  psc.decision_bucket,
  psc.actionability,
  psc.next_workflow,
  psc.is_actionable,
  CASE
    WHEN EXISTS (
      SELECT 1
      FROM theme_exposures te
      WHERE te.screen_run_id = ps.screen_run_id
        AND te.security_id = psc.security_id
        AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
        AND te.evidence_id IS NOT NULL
    ) THEN 1
    ELSE 0
  END AS has_source_backed_exposure,
  (
    SELECT count(*)
    FROM pm_decision_gates pdg
    WHERE pdg.session_candidate_id = psc.session_candidate_id
      AND pdg.required_flag = 1
      AND pdg.gate_status = 'pass'
  ) AS required_gate_pass_count,
  (
    SELECT count(*)
    FROM pm_decision_gates pdg
    WHERE pdg.session_candidate_id = psc.session_candidate_id
      AND pdg.required_flag = 1
      AND pdg.gate_status NOT IN ('pass', 'not_applicable')
  ) AS required_gate_blocker_count,
  CASE
    WHEN psc.is_actionable = 1
      AND psc.next_workflow <> 'none'
      AND EXISTS (
        SELECT 1
        FROM theme_exposures te
        WHERE te.screen_run_id = ps.screen_run_id
          AND te.security_id = psc.security_id
          AND te.exposure_type IN ('orders', 'backlog', 'revenue', 'margin', 'estimate_revision')
          AND te.evidence_id IS NOT NULL
      )
      AND EXISTS (
        SELECT 1
        FROM pm_decision_gates pdg
        WHERE pdg.session_candidate_id = psc.session_candidate_id
          AND pdg.required_flag = 1
          AND pdg.gate_status = 'pass'
      )
      AND NOT EXISTS (
        SELECT 1
        FROM pm_decision_gates pdg
        WHERE pdg.session_candidate_id = psc.session_candidate_id
          AND pdg.required_flag = 1
          AND pdg.gate_status NOT IN ('pass', 'not_applicable')
      )
    THEN 1
    ELSE 0
  END AS handoff_allowed
FROM pm_session_candidates psc
JOIN pm_sessions ps ON ps.session_id = psc.session_id
JOIN securities s ON s.security_id = psc.security_id
JOIN entities e ON e.entity_id = s.entity_id;

CREATE VIEW v_pm_active_handoff_violations AS
SELECT *
FROM v_pm_session_candidate_readiness
WHERE is_actionable = 1
  AND handoff_allowed = 0;

CREATE VIEW v_policy_stale_data AS
SELECT
  sr.screen_run_id,
  mo.security_id,
  'market_observations' AS data_table,
  mo.observation_id AS row_id,
  mo.observation_type,
  NULL AS metric_name,
  mo.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  fp.max_age_days,
  fp.severity,
  CAST(julianday(sr.as_of_date) - julianday(mo.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN market_observations mo
  ON mo.security_id = base.security_id
JOIN freshness_policies fp
  ON fp.data_table = 'market_observations'
  AND fp.observation_type = mo.observation_type
WHERE CAST(julianday(sr.as_of_date) - julianday(mo.as_of_date) AS INTEGER) > fp.max_age_days
UNION ALL
SELECT
  sr.screen_run_id,
  vs.security_id,
  'valuation_snapshots' AS data_table,
  vs.snapshot_id AS row_id,
  NULL AS observation_type,
  vs.metric_name,
  vs.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  fp.max_age_days,
  fp.severity,
  CAST(julianday(sr.as_of_date) - julianday(vs.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN valuation_snapshots vs
  ON vs.security_id = base.security_id
JOIN freshness_policies fp
  ON fp.data_table = 'valuation_snapshots'
  AND fp.metric_name = vs.metric_name
WHERE CAST(julianday(sr.as_of_date) - julianday(vs.as_of_date) AS INTEGER) > fp.max_age_days
UNION ALL
SELECT
  sr.screen_run_id,
  es.security_id,
  'estimate_snapshots' AS data_table,
  es.estimate_id AS row_id,
  NULL AS observation_type,
  es.metric_name,
  es.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  fp.max_age_days,
  fp.severity,
  CAST(julianday(sr.as_of_date) - julianday(es.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN estimate_snapshots es
  ON es.security_id = base.security_id
JOIN freshness_policies fp
  ON fp.data_table = 'estimate_snapshots'
  AND fp.metric_name = es.metric_name
WHERE CAST(julianday(sr.as_of_date) - julianday(es.as_of_date) AS INTEGER) > fp.max_age_days
UNION ALL
SELECT
  sr.screen_run_id,
  er.security_id,
  'estimate_revisions' AS data_table,
  er.revision_id AS row_id,
  NULL AS observation_type,
  er.metric_name,
  er.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  fp.max_age_days,
  fp.severity,
  CAST(julianday(sr.as_of_date) - julianday(er.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN estimate_revisions er
  ON er.security_id = base.security_id
JOIN freshness_policies fp
  ON fp.data_table = 'estimate_revisions'
  AND fp.metric_name = er.metric_name
WHERE CAST(julianday(sr.as_of_date) - julianday(er.as_of_date) AS INTEGER) > fp.max_age_days
UNION ALL
SELECT
  sr.screen_run_id,
  s.security_id,
  'company_metric_facts' AS data_table,
  cmf.fact_id AS row_id,
  NULL AS observation_type,
  md.metric_name,
  cmf.as_of_date,
  sr.as_of_date AS screen_as_of_date,
  fp.max_age_days,
  fp.severity,
  CAST(julianday(sr.as_of_date) - julianday(cmf.as_of_date) AS INTEGER) AS stale_days
FROM screen_runs sr
JOIN (SELECT DISTINCT screen_run_id, security_id FROM theme_universe) base
  ON base.screen_run_id = sr.screen_run_id
JOIN securities s
  ON s.security_id = base.security_id
JOIN company_metric_facts cmf
  ON cmf.entity_id = s.entity_id
JOIN metric_definitions md
  ON md.metric_id = cmf.metric_id
JOIN freshness_policies fp
  ON fp.data_table = 'company_metric_facts'
  AND fp.metric_name = md.metric_name
WHERE CAST(julianday(sr.as_of_date) - julianday(cmf.as_of_date) AS INTEGER) > fp.max_age_days;
