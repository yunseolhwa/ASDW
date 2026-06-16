from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "schema.sql"
CORE_SEED_SQL = ROOT / "seed_demo.sql"
PM_SEED_SQL = ROOT / "seed_pm_sessions.sql"
sys.path.insert(0, str(ROOT))

from build_theme_database import build_database  # noqa: E402


def connect_seeded() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    con.executescript(CORE_SEED_SQL.read_text(encoding="utf-8"))
    con.executescript(PM_SEED_SQL.read_text(encoding="utf-8"))
    con.commit()
    return con


def expect_integrity_error(con: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    try:
        con.execute(sql, params)
    except sqlite3.IntegrityError:
        con.rollback()
        return
    raise AssertionError(f"Expected sqlite3.IntegrityError for SQL: {sql}")


def test_integrity(con: sqlite3.Connection) -> None:
    rows = con.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == [], rows


def test_three_independent_sessions(con: sqlite3.Connection) -> None:
    styles = [
        row[0]
        for row in con.execute(
            """
            SELECT session_style
            FROM pm_sessions
            WHERE screen_run_id = 1
            ORDER BY session_style
            """
        ).fetchall()
    ]
    assert styles == ["long_only_pm", "long_short_hf", "public_equity_diligence"], styles


def test_session_specific_decisions(con: sqlite3.Connection) -> None:
    vrt_rows = con.execute(
        """
        SELECT ps.session_style, psc.decision_bucket, psc.actionability, psc.next_workflow
        FROM pm_session_candidates psc
        JOIN pm_sessions ps ON ps.session_id = psc.session_id
        WHERE psc.security_id = 1
        ORDER BY ps.session_style
        """
    ).fetchall()
    assert vrt_rows == [
        ("long_only_pm", "Valuation / expectations gated", "wait for proof", "none"),
        ("long_short_hf", "Watchlist / needs trigger", "wait for proof", "none"),
        ("public_equity_diligence", "Advance to deeper work", "research only", "equity-model-update"),
    ], vrt_rows

    etn_rows = con.execute(
        """
        SELECT ps.session_style, psc.decision_bucket, psc.is_actionable
        FROM pm_session_candidates psc
        JOIN pm_sessions ps ON ps.session_id = psc.session_id
        WHERE psc.security_id = 2
        ORDER BY ps.session_style
        """
    ).fetchall()
    assert etn_rows == [
        ("long_only_pm", "Pass", 0),
        ("long_short_hf", "Exposure not yet proven", 0),
        ("public_equity_diligence", "Exposure not yet proven", 0),
    ], etn_rows


def test_score_dimension_style_guard(con: sqlite3.Connection) -> None:
    expect_integrity_error(
        con,
        """
        INSERT INTO pm_candidate_scores (
          session_candidate_id, dimension_id, raw_score, normalized_score, rationale
        ) VALUES (1, 5, 50, 50, 'Wrong style dimension should fail.')
        """,
    )


def test_keyword_only_cannot_be_actionable(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT session_style, ticker, has_source_backed_exposure, is_actionable, handoff_allowed
        FROM v_pm_session_candidate_readiness
        WHERE ticker = 'ETN'
        ORDER BY session_style
        """
    ).fetchall()
    assert rows == [
        ("long_only_pm", "ETN", 0, 0, 0),
        ("long_short_hf", "ETN", 0, 0, 0),
        ("public_equity_diligence", "ETN", 0, 0, 0),
    ], rows

    expect_integrity_error(
        con,
        """
        UPDATE pm_session_candidates
        SET is_actionable = 1, next_workflow = 'long-short-pitch'
        WHERE session_candidate_id = 2
        """,
    )


def test_actionable_handoff_gate(con: sqlite3.Connection) -> None:
    allowed = con.execute(
        """
        SELECT ticker, session_style, is_actionable, handoff_allowed
        FROM v_pm_session_candidate_readiness
        WHERE session_candidate_id = 1
        """
    ).fetchone()
    assert allowed == ("VRT", "public_equity_diligence", 1, 1), allowed

    violations = con.execute(
        "SELECT count(*) FROM v_pm_active_handoff_violations"
    ).fetchone()
    assert violations == (0,), violations


def test_policy_stale_data(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT s.ticker_upper, data_table, coalesce(observation_type, metric_name), stale_days, max_age_days
        FROM v_policy_stale_data stale
        JOIN securities s ON s.security_id = stale.security_id
        WHERE stale.screen_run_id = 1
        ORDER BY s.ticker_upper, data_table
        """
    ).fetchall()
    assert rows == [
        ("ETN", "estimate_revisions", "Adjusted EBITDA", 6, 5),
        ("ETN", "estimate_snapshots", "Adjusted EBITDA", 6, 5),
        ("ETN", "market_observations", "price", 6, 1),
        ("ETN", "valuation_snapshots", "EV/EBITDA", 6, 5),
    ], rows


def test_conflicts_and_assumptions(con: sqlite3.Connection) -> None:
    conflict_count = con.execute(
        "SELECT count(*) FROM pm_cross_session_conflicts"
    ).fetchone()
    assert conflict_count == (2,), conflict_count

    assumption_count = con.execute("SELECT count(*) FROM assumption_register").fetchone()
    assert assumption_count == (3,), assumption_count

    source_conflict = con.execute(
        """
        SELECT metric_name, resolution_status
        FROM source_conflicts
        WHERE security_id = 2
        """
    ).fetchone()
    assert source_conflict == ("AI data center", "open"), source_conflict


def test_file_database_builder() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "theme.sqlite"
        built_path = build_database(output_path, include_pm_sessions=True, force=False)
        assert built_path == output_path.resolve(), built_path

        con = sqlite3.connect(built_path)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            assert con.execute("PRAGMA foreign_key_check").fetchall() == []
            assert con.execute(
                """
                SELECT count(*)
                FROM evidence_fts
                WHERE evidence_fts MATCH 'backlog'
                """
            ).fetchone() == (1,)
            assert con.execute(
                """
                SELECT count(*)
                FROM v_pm_session_candidate_readiness
                WHERE session_style IN (
                  'public_equity_diligence',
                  'long_short_hf',
                  'long_only_pm'
                )
                """
            ).fetchone() == (6,)
        finally:
            con.close()


def main() -> None:
    con = connect_seeded()
    try:
        test_integrity(con)
        test_three_independent_sessions(con)
        test_session_specific_decisions(con)
        test_score_dimension_style_guard(con)
        test_keyword_only_cannot_be_actionable(con)
        test_actionable_handoff_gate(con)
        test_policy_stale_data(con)
        test_conflicts_and_assumptions(con)
    finally:
        con.close()
    test_file_database_builder()
    print("public_equity_theme_schema PM database validation passed")


if __name__ == "__main__":
    main()
