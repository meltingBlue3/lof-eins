"""
Migration: Update limit_events table schema (002_update_limit_events.py)

Updates existing fund_status.db files to the new schema with enhanced columns:
- is_open_ended: Computed column identifying open-ended limits
- source_announcement_ids: JSON array tracking announcement sources
- Additional indexes for query performance

Usage:
    python src/data/migrations/002_update_limit_events.py --db data/mock/config/fund_status.db
    python src/data/migrations/002_update_limit_events.py --db data/real_all_lof/config/fund_status.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path


class MigrationError(Exception):
    """Custom exception for migration errors."""

    pass


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table.

    Note: This also works for generated columns which don't appear in PRAGMA table_info.
    """
    # Check regular columns via PRAGMA table_info
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name in columns:
        return True

    # For generated columns, try to query them directly
    try:
        cursor.execute(f"SELECT {column_name} FROM {table_name} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def index_exists(cursor: sqlite3.Cursor, table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=? AND tbl_name=?",
        (index_name, table_name),
    )
    return cursor.fetchone() is not None


def migrate_limit_events(db_path: Path) -> dict:
    """
    Migrate the limit_events table to the new schema.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        dict: Migration results with status and details.

    Raises:
        MigrationError: If migration fails and rollback is needed.
    """
    results = {
        "success": False,
        "added_columns": [],
        "added_indexes": [],
        "initialized_count": 0,
        "warnings": [],
        "error": None,
    }

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")  # Disable FK constraints during migration

    try:
        cursor = conn.cursor()

        # Check if limit_events table exists
        if not table_exists(cursor, "limit_events"):
            raise MigrationError(
                "Table 'limit_events' does not exist. "
                "Please ensure you're migrating a valid fund_status.db file."
            )

        # Store current schema for rollback info
        cursor.execute("PRAGMA table_info(limit_events)")
        original_columns = {row[1]: row for row in cursor.fetchall()}

        # Step 1: Add source_announcement_ids column if not exists
        if not column_exists(cursor, "limit_events", "source_announcement_ids"):
            print("  -> Adding column: source_announcement_ids")
            cursor.execute(
                """
                ALTER TABLE limit_events
                ADD COLUMN source_announcement_ids TEXT DEFAULT '[]'
            """
            )
            results["added_columns"].append("source_announcement_ids")

            # Initialize existing records with empty JSON array
            cursor.execute(
                """
                UPDATE limit_events
                SET source_announcement_ids = '[]'
                WHERE source_announcement_ids IS NULL
            """
            )
            results["initialized_count"] = cursor.rowcount
            print(f"     Initialized {cursor.rowcount} existing records")
        else:
            print("  -> Column already exists: source_announcement_ids")
            results["warnings"].append("source_announcement_ids already exists")

        # Step 2: Add is_open_ended generated column if not exists
        # SQLite ALTER TABLE doesn't support adding GENERATED columns directly
        # We need to use table recreation for generated columns
        if not column_exists(cursor, "limit_events", "is_open_ended"):
            print("  -> Adding generated column: is_open_ended")

            # Create new table with desired schema
            cursor.execute(
                """
                CREATE TABLE limit_events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    max_amount REAL NOT NULL,
                    reason TEXT,
                    source_announcement_ids TEXT DEFAULT '[]',
                    is_open_ended INTEGER GENERATED ALWAYS AS (
                        CASE WHEN end_date IS NULL THEN 1 ELSE 0 END
                    ) STORED
                )
            """
            )

            # Copy data from old table to new table
            # Note: source_announcement_ids was just added, so it will be '[]'
            cursor.execute(
                """
                INSERT INTO limit_events_new (
                    id, ticker, start_date, end_date, max_amount, reason,
                    source_announcement_ids
                )
                SELECT
                    id, ticker, start_date, end_date, max_amount, reason,
                    COALESCE(source_announcement_ids, '[]')
                FROM limit_events
            """
            )
            migrated_count = cursor.rowcount
            print(f"     Migrated {migrated_count} records to new table")

            # Drop old table
            cursor.execute("DROP TABLE limit_events")

            # Rename new table
            cursor.execute("ALTER TABLE limit_events_new RENAME TO limit_events")

            results["added_columns"].append("is_open_ended")
        else:
            print("  -> Column already exists: is_open_ended")
            results["warnings"].append("is_open_ended already exists")

        # Step 3: Create index on is_open_ended if not exists
        if not index_exists(cursor, "limit_events", "idx_limit_events_is_open_ended"):
            print("  -> Creating index: idx_limit_events_is_open_ended")
            cursor.execute(
                """
                CREATE INDEX idx_limit_events_is_open_ended
                ON limit_events(is_open_ended)
            """
            )
            results["added_indexes"].append("idx_limit_events_is_open_ended")
        else:
            print("  -> Index already exists: idx_limit_events_is_open_ended")
            results["warnings"].append("idx_limit_events_is_open_ended already exists")

        # Step 4: Create index on ticker if not exists
        if not index_exists(cursor, "limit_events", "idx_limit_events_ticker"):
            print("  -> Creating index: idx_limit_events_ticker")
            cursor.execute(
                """
                CREATE INDEX idx_limit_events_ticker
                ON limit_events(ticker)
            """
            )
            results["added_indexes"].append("idx_limit_events_ticker")
        else:
            print("  -> Index already exists: idx_limit_events_ticker")
            results["warnings"].append("idx_limit_events_ticker already exists")

        # Verify the schema
        # Note: Use column_exists which handles both regular and generated columns
        required_columns = [
            "id",
            "ticker",
            "start_date",
            "end_date",
            "max_amount",
            "reason",
            "source_announcement_ids",
            "is_open_ended",
        ]

        missing_columns = [
            col
            for col in required_columns
            if not column_exists(cursor, "limit_events", col)
        ]
        if missing_columns:
            raise MigrationError(
                f"Migration incomplete. Missing columns: {set(missing_columns)}"
            )

        conn.commit()
        results["success"] = True
        print("  -> Migration committed successfully")

    except sqlite3.Error as e:
        conn.rollback()
        results["error"] = f"SQLite error: {e}"
        raise MigrationError(f"Database error during migration: {e}") from e
    except Exception as e:
        conn.rollback()
        results["error"] = str(e)
        raise MigrationError(f"Unexpected error during migration: {e}") from e
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    return results


def verify_migration(db_path: Path) -> bool:
    """
    Verify that the migration was successful.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        bool: True if verification passed.
    """
    print("\n>>> Verifying migration...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check table exists
        if not table_exists(cursor, "limit_events"):
            print("  [FAIL] Table 'limit_events' not found")
            return False

        # Check columns (including generated columns)
        required = ["source_announcement_ids", "is_open_ended"]
        for col in required:
            if not column_exists(cursor, "limit_events", col):
                print(f"  [FAIL] Missing column: {col}")
                return False
            print(f"  [OK] Column exists: {col}")

        # Check is_open_ended is a generated column by querying SQLite schema
        cursor.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type='table' AND name='limit_events'
        """
        )
        create_sql = cursor.fetchone()[0]
        if "GENERATED ALWAYS" in create_sql and "is_open_ended" in create_sql:
            print("  [OK] is_open_ended is a generated column")

        # Check indexes
        for idx_name in ["idx_limit_events_is_open_ended", "idx_limit_events_ticker"]:
            if not index_exists(cursor, "limit_events", idx_name):
                print(f"  [FAIL] Missing index: {idx_name}")
                return False
            print(f"  [OK] Index exists: {idx_name}")

        # Check sample data
        cursor.execute("SELECT COUNT(*), SUM(is_open_ended) FROM limit_events")
        total, open_ended = cursor.fetchone()
        print(f"  [OK] Total limit events: {total}, Open-ended: {open_ended or 0}")

        print("\n[SUCCESS] Migration verification passed")
        return True

    except Exception as e:
        print(f"  [FAIL] Verification error: {e}")
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate limit_events table to new schema (002)"
    )
    parser.add_argument(
        "--db",
        type=str,
        required=True,
        help="Path to fund_status.db file to migrate",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify the schema, do not migrate",
    )

    args = parser.parse_args()

    db_path = Path(args.db)

    if not db_path.exists():
        print(f"[ERROR] Database file not found: {db_path}")
        sys.exit(1)

    print(f">>> Migration 002: Updating limit_events schema")
    print(f"    Database: {db_path}")

    if args.verify_only:
        success = verify_migration(db_path)
        sys.exit(0 if success else 1)

    try:
        results = migrate_limit_events(db_path)

        print(f"\n>>> Migration Summary")
        print(f"    Added columns: {', '.join(results['added_columns']) or 'None'}")
        print(f"    Added indexes: {', '.join(results['added_indexes']) or 'None'}")
        print(f"    Records initialized: {results['initialized_count']}")

        if results["warnings"]:
            print(f"\n>>> Warnings ({len(results['warnings'])}):")
            for warning in results["warnings"]:
                print(f"    - {warning}")

        # Verify after migration
        success = verify_migration(db_path)
        sys.exit(0 if success else 1)

    except MigrationError as e:
        print(f"\n[ERROR] Migration failed: {e}")
        print("       Changes have been rolled back.")
        sys.exit(1)


if __name__ == "__main__":
    main()
