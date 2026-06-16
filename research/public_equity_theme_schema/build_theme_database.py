from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
SCHEMA_SQL = ROOT / "schema.sql"
CORE_SEED_SQL = ROOT / "seed_demo.sql"
PM_SEED_SQL = ROOT / "seed_pm_sessions.sql"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "public_equity_theme_schema.sqlite"


def execute_script(con: sqlite3.Connection, path: Path) -> None:
    con.executescript(path.read_text(encoding="utf-8"))


def build_database(output_path: Path, include_pm_sessions: bool = True, force: bool = False) -> Path:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        if not force:
            raise FileExistsError(f"{output_path} already exists; pass --force to replace it")
        output_path.unlink()

    con = sqlite3.connect(output_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        execute_script(con, SCHEMA_SQL)
        execute_script(con, CORE_SEED_SQL)
        if include_pm_sessions:
            execute_script(con, PM_SEED_SQL)
        fk_rows = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise RuntimeError(f"foreign key check failed: {fk_rows}")
        con.commit()
    except Exception:
        con.close()
        if output_path.exists():
            output_path.unlink()
        raise
    finally:
        try:
            con.close()
        except UnboundLocalError:
            pass

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the public-equity theme screening SQLite database."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"SQLite output path. Defaults to {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Load only schema.sql and seed_demo.sql, without PM session seed data.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the output database if it already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = build_database(
        args.output,
        include_pm_sessions=not args.core_only,
        force=args.force,
    )
    print(f"built {output_path}")


if __name__ == "__main__":
    main()
