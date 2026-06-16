from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "schema.sql"
SEED_SQL = ROOT / "seed_demo.sql"


def connect_seeded() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    con.executescript(SEED_SQL.read_text(encoding="utf-8"))
    con.commit()
    return con


def expect_integrity_error(con: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    try:
        con.execute(sql, params)
    except sqlite3.IntegrityError:
        con.rollback()
        return
    raise AssertionError(f"Expected sqlite3.IntegrityError for SQL: {sql}")


def expect_operational_error(con: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    try:
        con.execute(sql, params)
    except sqlite3.OperationalError:
        con.rollback()
        return
    raise AssertionError(f"Expected sqlite3.OperationalError for SQL: {sql}")


def test_integrity(con: sqlite3.Connection) -> None:
    rows = con.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == [], rows


def test_negative_constraints(con: sqlite3.Connection) -> None:
    expect_integrity_error(
        con,
        """
        INSERT INTO securities (
          entity_id, ticker, exchange_code, mic, currency, security_type, is_active
        ) VALUES (1, 'VRT', 'NYSE', 'XNYS', 'USD', 'common_stock', 1)
        """,
    )

    expect_integrity_error(
        con,
        """
        INSERT INTO security_identifiers (
          security_id, provider, id_type, id_value, is_active
        ) VALUES (2, 'OpenFIGI', 'FIGI', 'BBG000VRTDEM', 1)
        """,
    )

    expect_integrity_error(
        con,
        """
        INSERT INTO raw_payloads (
          ingestion_run_id, provider, source_url, payload_json, accessed_at
        ) VALUES (1, 'SEC EDGAR', NULL, 'not-json', '2026-06-16T00:00:00Z')
        """,
    )

    expect_integrity_error(
        con,
        """
        INSERT INTO evidence_items (
          source_id, evidence_label, excerpt, as_of_date
        ) VALUES (1, 'rumor', 'bad label', '2026-06-16')
        """,
    )

    expect_integrity_error(
        con,
        """
        INSERT INTO theme_exposures (
          screen_run_id,
          security_id,
          pathway_id,
          exposure_type,
          exposure_summary,
          evidence_id,
          strength_score
        ) VALUES (999, 1, 1, 'revenue', 'orphan screen run', 1, 10)
        """,
    )

    expect_integrity_error(
        con,
        """
        INSERT INTO theme_exposures (
          screen_run_id,
          security_id,
          pathway_id,
          exposure_type,
          exposure_summary,
          evidence_id,
          strength_score
        ) VALUES (1, 1, 2, 'revenue', 'missing evidence should fail', NULL, 10)
        """,
    )


def test_fts(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT ei.evidence_id, ei.evidence_label
        FROM evidence_fts fts
        JOIN evidence_items ei ON ei.evidence_id = fts.rowid
        WHERE evidence_fts MATCH 'backlog'
        ORDER BY ei.evidence_id
        """
    ).fetchall()
    assert rows == [(1, "fact")], rows


def test_rankings(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT pathway_name, pathway_rank, ticker, priority_bucket, composite_score
        FROM v_pathway_ranked_candidates
        WHERE screen_run_id = 1
        ORDER BY pathway_name, pathway_rank
        """
    ).fetchall()
    assert len(rows) == 2, rows
    tickers = {row[2] for row in rows}
    assert tickers == {"VRT", "ETN"}, rows


def test_readiness(con: sqlite3.Connection) -> None:
    rows = dict(
        con.execute(
            """
            SELECT ticker, advance_eligible
            FROM v_candidate_readiness
            ORDER BY ticker
            """
        ).fetchall()
    )
    assert rows["VRT"] == 1, rows
    assert rows["ETN"] == 0, rows


def test_stale_data(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT s.ticker_upper, data_table, stale_days
        FROM v_stale_market_data stale
        JOIN securities s ON s.security_id = stale.security_id
        WHERE stale.screen_run_id = 1
        ORDER BY s.ticker_upper, data_table
        """
    ).fetchall()
    assert rows, rows
    assert any(row[0] == "ETN" and row[2] > 0 for row in rows), rows
    assert not any(row[0] == "VRT" for row in rows), rows


def test_keyword_only_non_readiness(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT s.ticker_upper, te.exposure_type, vr.advance_eligible
        FROM theme_exposures te
        JOIN securities s ON s.security_id = te.security_id
        JOIN v_candidate_readiness vr
          ON vr.screen_run_id = te.screen_run_id
          AND vr.security_id = te.security_id
        WHERE te.exposure_type = 'keyword_only'
        """
    ).fetchall()
    assert rows == [("ETN", "keyword_only", 0)], rows


def test_workflow_handoffs(con: sqlite3.Connection) -> None:
    workflows = {
        row[0]
        for row in con.execute(
            """
            SELECT next_workflow
            FROM workflow_handoffs
            WHERE screen_run_id = 1
            """
        ).fetchall()
    }
    assert {"earnings-deep-dive", "equity-model-update", "long-short-pitch"} <= workflows


def test_fts_virtual_table_exists(con: sqlite3.Connection) -> None:
    row = con.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'evidence_fts'
        """
    ).fetchone()
    assert row == ("evidence_fts",), row


def main() -> None:
    con = connect_seeded()
    try:
        test_integrity(con)
        test_negative_constraints(con)
        test_fts_virtual_table_exists(con)
        test_fts(con)
        test_rankings(con)
        test_readiness(con)
        test_stale_data(con)
        test_keyword_only_non_readiness(con)
        test_workflow_handoffs(con)
    finally:
        con.close()
    print("public_equity_theme_schema validation passed")


if __name__ == "__main__":
    main()
