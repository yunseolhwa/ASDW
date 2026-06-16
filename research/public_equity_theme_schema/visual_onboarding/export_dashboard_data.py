from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parents[2]
DEFAULT_DB = REPO_ROOT / "artifacts" / "public_equity_theme_schema.sqlite"
DEFAULT_OUTPUT = APP_ROOT / "src" / "data" / "theme-dashboard-data.json"


SCHEMA_GROUPS = [
    {
        "id": "theme-core",
        "label": "Theme Core",
        "description": "테마, 수혜 경로, 스크린 실행, 후보 universe를 정의합니다.",
        "tables": ["themes", "theme_pathways", "theme_keywords", "screen_runs", "theme_universe"],
        "views": [],
    },
    {
        "id": "security-master",
        "label": "Security Master",
        "description": "티커를 영구 식별자로 쓰지 않고 issuer, listing, provider identifier를 분리합니다.",
        "tables": ["entities", "securities", "security_identifiers", "listing_history"],
        "views": [],
    },
    {
        "id": "source-evidence",
        "label": "Source / Evidence",
        "description": "원천 payload, 문서, 증거 excerpt, 품질 flag를 보존합니다.",
        "tables": [
            "ingestion_runs",
            "raw_payloads",
            "sources",
            "source_documents",
            "evidence_items",
            "evidence_fts",
            "data_quality_flags",
        ],
        "views": [],
    },
    {
        "id": "metrics-market-data",
        "label": "Metrics / Market Data",
        "description": "정규화된 회사 metric, 가격, valuation, consensus, revision 데이터를 저장합니다.",
        "tables": [
            "metric_definitions",
            "company_metric_facts",
            "market_observations",
            "valuation_snapshots",
            "estimate_snapshots",
            "estimate_revisions",
        ],
        "views": ["v_stale_market_data", "v_policy_stale_data"],
    },
    {
        "id": "candidate-triage",
        "label": "Candidate Triage",
        "description": "테마 노출, blended score, research bucket, event, false positive, workflow handoff를 담습니다.",
        "tables": [
            "theme_exposures",
            "candidate_scores",
            "candidate_assessments",
            "candidate_events",
            "theme_false_positive_flags",
            "workflow_handoffs",
        ],
        "views": ["v_candidate_readiness", "v_pathway_ranked_candidates"],
    },
    {
        "id": "pm-session-layer",
        "label": "PM Session Layer",
        "description": "public diligence, long/short HF, long-only PM 판단을 통합하지 않고 별도 세션으로 보존합니다.",
        "tables": [
            "pm_sessions",
            "pm_session_candidates",
            "pm_score_dimensions",
            "pm_candidate_scores",
            "pm_decision_gates",
            "pm_cross_session_conflicts",
            "freshness_policies",
            "assumption_register",
            "source_conflicts",
        ],
        "views": ["v_pm_session_candidate_readiness", "v_pm_active_handoff_violations"],
    },
]


def rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in con.execute(sql, params).fetchall()]


def row_count(con: sqlite3.Connection, name: str) -> int:
    quoted = '"' + name.replace('"', '""') + '"'
    return int(con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])


def export_dashboard_data(db_path: Path, output_path: Path) -> Path:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        db = {
            "path": str(db_path),
            "userVersion": con.execute("PRAGMA user_version").fetchone()[0],
            "tableCount": con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0],
            "viewCount": con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'view'").fetchone()[0],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "foreignKeyCheck": rows(con, "PRAGMA foreign_key_check"),
        }

        schema_groups = []
        for group in SCHEMA_GROUPS:
            schema_groups.append(
                {
                    **group,
                    "tableCounts": {name: row_count(con, name) for name in group["tables"]},
                    "viewCounts": {name: row_count(con, name) for name in group["views"]},
                }
            )

        data = {
            "db": db,
            "theme": rows(
                con,
                """
                SELECT theme_id, theme_name, thesis_text, horizon_months, region_scope, status
                FROM themes
                ORDER BY theme_id
                LIMIT 1
                """,
            )[0],
            "pathways": rows(
                con,
                """
                SELECT pathway_id, pathway_name, demand_driver, value_chain_role, priority_order
                FROM theme_pathways
                ORDER BY priority_order, pathway_id
                """,
            ),
            "sessions": rows(con, "SELECT * FROM pm_sessions ORDER BY session_id"),
            "candidates": rows(
                con,
                """
                SELECT *
                FROM v_pm_session_candidate_readiness
                ORDER BY ticker, session_style
                """,
            ),
            "sessionCandidates": rows(
                con,
                """
                SELECT psc.*, ps.session_style, s.ticker_upper AS ticker
                FROM pm_session_candidates psc
                JOIN pm_sessions ps ON ps.session_id = psc.session_id
                JOIN securities s ON s.security_id = psc.security_id
                ORDER BY psc.session_candidate_id
                """,
            ),
            "gates": rows(
                con,
                """
                SELECT pdg.*, psc.security_id, s.ticker_upper AS ticker, ps.session_style
                FROM pm_decision_gates pdg
                JOIN pm_session_candidates psc
                  ON psc.session_candidate_id = pdg.session_candidate_id
                JOIN pm_sessions ps ON ps.session_id = psc.session_id
                JOIN securities s ON s.security_id = psc.security_id
                ORDER BY pdg.session_candidate_id, pdg.gate_id
                """,
            ),
            "scores": rows(
                con,
                """
                SELECT pcs.*, psd.dimension_name, psd.dimension_group, psd.weight, ps.session_style, s.ticker_upper AS ticker
                FROM pm_candidate_scores pcs
                JOIN pm_score_dimensions psd ON psd.dimension_id = pcs.dimension_id
                JOIN pm_session_candidates psc ON psc.session_candidate_id = pcs.session_candidate_id
                JOIN pm_sessions ps ON ps.session_id = psc.session_id
                JOIN securities s ON s.security_id = psc.security_id
                ORDER BY pcs.session_candidate_id, psd.dimension_id
                """,
            ),
            "staleData": rows(con, "SELECT * FROM v_policy_stale_data ORDER BY security_id, data_table"),
            "pmConflicts": rows(con, "SELECT * FROM pm_cross_session_conflicts ORDER BY conflict_id"),
            "sourceConflicts": rows(con, "SELECT * FROM source_conflicts ORDER BY conflict_id"),
            "handoffs": rows(con, "SELECT * FROM workflow_handoffs ORDER BY handoff_id"),
            "readinessCore": rows(con, "SELECT * FROM v_candidate_readiness ORDER BY ticker"),
            "schemaGroups": schema_groups,
        }
    finally:
        con.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export visual onboarding data from the theme SQLite database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite input path. Defaults to {DEFAULT_DB}.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"JSON output path. Defaults to {DEFAULT_OUTPUT}.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = export_dashboard_data(args.db.resolve(), args.output.resolve())
    print(f"exported {out}")


if __name__ == "__main__":
    main()
