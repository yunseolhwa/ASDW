PRAGMA foreign_keys = ON;

INSERT INTO schema_migrations (migration_id, description) VALUES
  ('002_pm_session_layer', 'Three independent PM sessions, style-specific scorecards, decision gates, freshness policies, assumptions, and source conflicts.');

INSERT INTO pm_sessions (
  session_id,
  theme_id,
  screen_run_id,
  session_style,
  session_label,
  objective,
  owner_role,
  as_of_date,
  status
) VALUES
  (1, 1, 1, 'public_equity_diligence', 'Issuer diligence session', 'Build a source-backed diligence queue from the initial sample theme screen.', 'public equity PM', '2026-06-16', 'completed'),
  (2, 1, 1, 'long_short_hf', 'Long/short hedge fund session', 'Separate variant wedge, catalyst path, shortability, and scenario skew from the diligence queue.', 'long/short PM', '2026-06-16', 'completed'),
  (3, 1, 1, 'long_only_pm', 'Long-only PM session', 'Assess benchmark fit, quality durability, downside capture, and add/trim discipline separately.', 'long-only PM', '2026-06-16', 'completed');

INSERT INTO pm_score_dimensions (
  dimension_id,
  session_style,
  dimension_name,
  dimension_group,
  weight,
  direction,
  required_flag
) VALUES
  (1, 'public_equity_diligence', 'source_pack_completeness', 'evidence', 0.30, 'higher_is_better', 1),
  (2, 'public_equity_diligence', 'exposure_strength', 'theme_linkage', 0.30, 'higher_is_better', 1),
  (3, 'public_equity_diligence', 'data_freshness', 'evidence', 0.20, 'higher_is_better', 1),
  (4, 'public_equity_diligence', 'next_evidence_clarity', 'workflow', 0.20, 'higher_is_better', 1),
  (5, 'long_short_hf', 'variant_wedge', 'alpha', 0.30, 'higher_is_better', 1),
  (6, 'long_short_hf', 'catalyst_quality', 'timing', 0.25, 'higher_is_better', 1),
  (7, 'long_short_hf', 'shortability_borrow', 'implementation', 0.20, 'higher_is_better', 1),
  (8, 'long_short_hf', 'scenario_skew', 'risk_reward', 0.25, 'higher_is_better', 1),
  (9, 'long_only_pm', 'benchmark_fit', 'portfolio_role', 0.25, 'higher_is_better', 1),
  (10, 'long_only_pm', 'quality_durability', 'fundamental_quality', 0.30, 'higher_is_better', 1),
  (11, 'long_only_pm', 'downside_capture', 'risk', 0.25, 'higher_is_better', 1),
  (12, 'long_only_pm', 'valuation_entry', 'entry_discipline', 0.20, 'higher_is_better', 1);

INSERT INTO pm_session_candidates (
  session_candidate_id,
  session_id,
  security_id,
  pathway_id,
  decision_bucket,
  actionability,
  direction,
  variant_wedge,
  why_now,
  priced_in,
  first_rejection,
  investable_if,
  kill_if,
  next_workflow,
  is_actionable
) VALUES
  (1, 1, 1, 2, 'Advance to deeper work', 'research only', 'diligence', 'Source-backed revenue exposure may support revisions beyond consensus if margin follow-through holds.', 'The next evidence window is the earnings and model update cycle.', 'The current setup may already discount strong AI infrastructure demand.', 'Reject if source-backed revenue exposure does not translate to margin or estimate revision durability.', 'Advance if model work shows revenue and margin revisions can continue without heroic assumptions.', 'Kill if backlog, revenue, or margin proof fails or valuation already discounts the upside case.', 'equity-model-update', 0),
  (2, 1, 2, 1, 'Exposure not yet proven', 'wait for proof', 'watchlist', 'The market may conflate broad electrical exposure with AI-specific demand.', 'Theme visibility is high, but company-specific attribution is not yet proven.', 'Some electrification upside may already be capitalized.', 'Reject first because current evidence is keyword-only.', 'Advance only if filings or transcripts tie AI data-center demand to orders, backlog, revenue, margins, or estimate revisions.', 'Kill if the link remains generic or stale.', 'none', 0),
  (3, 2, 1, 2, 'Watchlist / needs trigger', 'wait for proof', 'long', 'Possible long setup exists, but the variant wedge needs catalyst timing and valuation reset work.', 'Estimate revisions and AI infrastructure debate keep the name on the monitor list.', 'The market may already be paying for the upside case.', 'Reject as a long/short pitch if no catalyst or scenario skew emerges.', 'Advance to pitch only if catalyst path and downside skew become clearly underwritten.', 'Kill if borrow/crowding, valuation, or catalyst quality makes timing unattractive.', 'none', 0),
  (4, 2, 2, 1, 'Exposure not yet proven', 'wait for proof', 'watchlist', 'A short-screen flag may exist if AI exposure is overstated, but exposure attribution is not proven.', 'Narrative visibility can create expectations risk before company-specific proof exists.', 'Some AI-adjacent electrification benefit may already be embedded.', 'Reject first because a keyword-only gap is not enough for a short pitch.', 'Advance only if source work shows expectations exceed verifiable exposure.', 'Kill if filings substantiate orders, backlog, revenue, margins, or revisions.', 'none', 0),
  (5, 3, 1, 2, 'Valuation / expectations gated', 'wait for proof', 'long', 'Quality and theme exposure are credible, but long-only entry discipline depends on valuation and downside capture.', 'Benchmark-relative PMs need evidence before add/trim decisions.', 'A strong AI infrastructure runway may be partly capitalized.', 'Reject as a new long if valuation already pays for the upside case.', 'Advance only if downside and valuation entry support a durable benchmark-relative add.', 'Kill if quality remains good but the stock thesis is already fully priced.', 'none', 0),
  (6, 3, 2, 1, 'Pass', 'pass', 'none', 'No long-only variant wedge is established from keyword-only AI exposure.', 'The theme can remain monitored without becoming a portfolio candidate.', 'Broad electrical exposure may already be understood by the market.', 'Reject first because the exposure link is not specific enough.', 'Re-open only if quantified exposure and valuation support improve.', 'Kill if source work stays generic or benchmark-relative downside is unattractive.', 'none', 0);

INSERT INTO pm_candidate_scores (
  score_id,
  session_candidate_id,
  dimension_id,
  raw_score,
  normalized_score,
  evidence_id,
  rationale
) VALUES
  (1, 1, 1, 85, 85, 1, 'Diligence source pack has a source-backed filing-derived excerpt.'),
  (2, 1, 2, 82, 82, 1, 'Theme exposure is linked to revenue in the demo evidence.'),
  (3, 1, 3, 90, 90, 1, 'VRT demo evidence and market inputs match the screen as-of date.'),
  (4, 1, 4, 80, 80, 1, 'Next work is clearly an equity model update and earnings evidence check.'),
  (5, 2, 1, 45, 45, 2, 'ETN has a management-claim excerpt but lacks economic attribution.'),
  (6, 2, 2, 35, 35, NULL, 'Exposure is keyword-only in the core screen.'),
  (7, 2, 3, 35, 35, 2, 'Demo market and estimate inputs are stale versus the screen date.'),
  (8, 2, 4, 60, 60, 2, 'The next evidence need is specific but unresolved.'),
  (9, 3, 5, 65, 65, 1, 'Variant wedge is plausible but not yet strong enough for a pitch.'),
  (10, 3, 6, 55, 55, 1, 'Catalyst path remains an evidence-window watch item.'),
  (11, 3, 7, 50, 50, NULL, 'Borrow and crowding evidence is not populated in the demo seed.'),
  (12, 3, 8, 58, 58, 1, 'Scenario skew needs valuation and downside work.'),
  (13, 4, 5, 50, 50, 2, 'Potential negative variant view depends on proving overstated expectations.'),
  (14, 4, 6, 45, 45, 2, 'No hard catalyst is established.'),
  (15, 4, 7, 50, 50, NULL, 'Borrow and crowding evidence is absent.'),
  (16, 4, 8, 48, 48, 2, 'Short setup is not underwritten while exposure remains keyword-only.'),
  (17, 5, 9, 70, 70, 1, 'VRT can fit a benchmark-relative AI infrastructure watchlist.'),
  (18, 5, 10, 72, 72, 1, 'Quality durability remains plausible but needs model work.'),
  (19, 5, 11, 55, 55, 1, 'Downside capture is unresolved without valuation scenarios.'),
  (20, 5, 12, 40, 40, 1, 'Entry discipline is valuation-gated.'),
  (21, 6, 9, 45, 45, 2, 'ETN does not qualify as a long-only candidate from the demo theme evidence.'),
  (22, 6, 10, 60, 60, 2, 'Quality is not the gating issue; exposure proof is.'),
  (23, 6, 11, 45, 45, 2, 'Downside capture is not underwritten in the demo data.'),
  (24, 6, 12, 42, 42, 2, 'Valuation entry cannot compensate for missing theme attribution.');

INSERT INTO pm_decision_gates (
  gate_id,
  session_candidate_id,
  gate_name,
  gate_status,
  gate_reason,
  evidence_id,
  required_flag
) VALUES
  (1, 1, 'exposure_proof', 'pass', 'Revenue exposure is source-backed in the demo filing-derived evidence.', 1, 1),
  (2, 1, 'source_pack', 'pass', 'Core filing-derived evidence is present for first-pass diligence.', 1, 1),
  (3, 1, 'data_freshness', 'pass', 'VRT demo market, valuation, and estimate rows match the screen as-of date.', 1, 1),
  (4, 2, 'exposure_proof', 'fail', 'ETN remains keyword-only without orders, backlog, revenue, margin, or estimate-revision proof.', 2, 1),
  (5, 2, 'data_freshness', 'watch', 'ETN demo market and estimate rows predate the screen as-of date.', 2, 1),
  (6, 3, 'exposure_proof', 'pass', 'VRT passes economic exposure proof but still needs pitch-quality catalyst work.', 1, 1),
  (7, 3, 'catalyst', 'watch', 'Catalyst timing is not strong enough for a long/short pitch.', 1, 1),
  (8, 3, 'borrow_crowding', 'watch', 'Borrow, positioning, and factor crowding are not populated in the demo seed.', NULL, 1),
  (9, 4, 'exposure_proof', 'fail', 'ETN cannot become a short pitch merely from keyword-only AI exposure.', 2, 1),
  (10, 4, 'catalyst', 'watch', 'No hard timing catalyst is established.', 2, 1),
  (11, 5, 'exposure_proof', 'pass', 'VRT has source-backed theme exposure.', 1, 1),
  (12, 5, 'benchmark_fit', 'pass', 'VRT can remain a benchmark-relative watchlist candidate.', 1, 1),
  (13, 5, 'valuation', 'watch', 'Long-only entry discipline remains valuation-gated.', 1, 1),
  (14, 6, 'exposure_proof', 'fail', 'ETN remains keyword-only for this theme.', 2, 1),
  (15, 6, 'benchmark_fit', 'fail', 'Missing source-backed theme exposure prevents a long-only candidate designation.', 2, 1);

UPDATE pm_session_candidates
SET is_actionable = 1
WHERE session_candidate_id = 1;

INSERT INTO pm_cross_session_conflicts (
  conflict_id,
  screen_run_id,
  security_id,
  conflict_type,
  diligence_decision,
  long_short_decision,
  long_only_decision,
  resolution_note,
  next_research_owner,
  status
) VALUES
  (1, 1, 1, 'style_divergence', 'Advance to deeper work', 'Watchlist / needs trigger', 'Valuation / expectations gated', 'Same source-backed exposure supports issuer diligence, but investability differs by hedge-fund catalyst timing and long-only valuation discipline.', 'public equity PM', 'open'),
  (2, 1, 2, 'data_gap', 'Exposure not yet proven', 'Exposure not yet proven', 'Pass', 'Keyword-only exposure remains the shared blocker; no session should aggregate it into a positive conclusion.', 'coverage analyst', 'open');

INSERT INTO freshness_policies (
  policy_id,
  data_table,
  observation_type,
  metric_name,
  max_age_days,
  severity,
  policy_notes
) VALUES
  (1, 'market_observations', 'price', NULL, 1, 'high', 'Price observations should be same-day or previous trading day for screen decisions.'),
  (2, 'valuation_snapshots', NULL, 'EV/EBITDA', 5, 'medium', 'Valuation snapshots should be refreshed within one trading week.'),
  (3, 'estimate_snapshots', NULL, 'Adjusted EBITDA', 5, 'medium', 'Consensus snapshots should be refreshed within one trading week or after the latest print.'),
  (4, 'estimate_revisions', NULL, 'Adjusted EBITDA', 5, 'medium', 'Revision windows should be refreshed within one trading week.'),
  (5, 'company_metric_facts', NULL, 'Revenue', 120, 'low', 'Reported annual facts can be older if fiscal period and source are explicit.');

INSERT INTO assumption_register (
  assumption_id,
  screen_run_id,
  session_id,
  security_id,
  assumption_text,
  sensitivity,
  evidence_gap,
  owner_role,
  review_by,
  status
) VALUES
  (1, 1, 2, 1, 'Long/short actionability requires catalyst timing and positioning evidence beyond the demo source pack.', 'high', 'Borrow, crowding, and factor exposure are not populated.', 'long/short PM', '2026-07-01', 'open'),
  (2, 1, 3, 1, 'Long-only entry depends on valuation scenarios rather than business quality alone.', 'high', 'Downside and valuation-entry scenarios are not built in this schema seed.', 'long-only PM', '2026-07-01', 'open'),
  (3, 1, 1, 2, 'ETN should not advance until AI data-center exposure is economically attributed.', 'high', 'Orders, backlog, revenue, margin, or estimate-revision proof is missing.', 'public equity PM', '2026-07-01', 'open');

INSERT INTO source_conflicts (
  conflict_id,
  screen_run_id,
  security_id,
  source_a_id,
  source_b_id,
  data_table,
  row_a_pk,
  row_b_pk,
  metric_name,
  value_a,
  value_b,
  conflict_summary,
  resolution_status,
  resolution_note
) VALUES
  (1, 1, 2, 2, 4, 'theme_exposures', '2', NULL, 'AI data center', 'management claim mentions AI demand', 'no estimate revision proof in demo consensus export', 'Management-claim visibility conflicts with the lack of quantified exposure or revision evidence.', 'open', 'Resolve by retrieving source-backed orders, backlog, revenue, margin, or estimate-revision attribution.');
