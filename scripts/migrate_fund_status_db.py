"""
Migration script for adding announcement_parses and limit_event_log tables.

This script adds two new tables to existing fund_status.db databases:
- announcement_parses: Stores raw LLM extraction results from PDF announcements
- limit_event_log: Provides audit trail for debugging timeline changes

Usage:
    python scripts/migrate_fund_status_db.py --db-path data/real_all_lof/config/fund_status.db
    python scripts/migrate_fund_status_db.py --db-path data/mock/config/fund_status.db
    python scripts/migrate_fund_status_db.py --all  # Migrate all databases in data/
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple


def migrate_database(db_path: Path) -> Tuple[bool, str]:
    """Migrate a single database file.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Tuple of (success: bool, message: str).
    """
    if not db_path.exists():
        return False, f"Database not found: {db_path}"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        migrations_applied = []

        # Check if announcement_parses table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='announcement_parses'
        """)
        if not cursor.fetchone():
            # Create announcement_parses table
            cursor.execute("""
                CREATE TABLE announcement_parses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    announcement_date DATE NOT NULL,
                    pdf_filename TEXT NOT NULL,
                    parse_result TEXT,
                    parse_type TEXT,
                    confidence REAL,
                    processed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX idx_announcement_parses_ticker 
                ON announcement_parses(ticker)
            """)
            cursor.execute("""
                CREATE INDEX idx_announcement_parses_processed 
                ON announcement_parses(processed)
            """)

            migrations_applied.append("announcement_parses table + indexes")

        # Check if limit_event_log table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='limit_event_log'
        """)
        if not cursor.fetchone():
            # Create limit_event_log table
            cursor.execute("""
                CREATE TABLE limit_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    old_start DATE,
                    old_end DATE,
                    new_start DATE,
                    new_end DATE,
                    triggered_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX idx_limit_event_log_ticker 
                ON limit_event_log(ticker)
            """)
            cursor.execute("""
                CREATE INDEX idx_limit_event_log_created_at 
                ON limit_event_log(created_at)
            """)

            migrations_applied.append("limit_event_log table + indexes")

        conn.commit()
        conn.close()

        if migrations_applied:
            return True, f"Applied migrations: {', '.join(migrations_applied)}"
        else:
            return True, "No migrations needed (tables already exist)"

    except sqlite3.Error as e:
        return False, f"SQLite error: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def find_databases(base_path: Path) -> List[Path]:
    """Find all fund_status.db files under base_path.

    Args:
        base_path: Base directory to search.

    Returns:
        List of paths to fund_status.db files.
    """
    databases = []
    for db_file in base_path.rglob("fund_status.db"):
        databases.append(db_file)
    return databases


def main():
    parser = argparse.ArgumentParser(
        description="Migrate fund_status.db databases to add new tables for PDF processing pipeline"
    )
    parser.add_argument(
        "--db-path", type=str, help="Path to specific database file to migrate"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Migrate all fund_status.db files in data/ directory",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./data",
        help="Base data directory (default: ./data)",
    )

    args = parser.parse_args()

    if not args.db_path and not args.all:
        parser.print_help()
        sys.exit(1)

    results = []

    if args.db_path:
        # Migrate specific database
        db_path = Path(args.db_path)
        success, message = migrate_database(db_path)
        results.append((db_path, success, message))

    elif args.all:
        # Migrate all databases
        base_path = Path(args.data_dir)
        if not base_path.exists():
            print(f"Error: Data directory not found: {base_path}")
            sys.exit(1)

        databases = find_databases(base_path)

        if not databases:
            print(f"No fund_status.db files found in {base_path}")
            sys.exit(0)

        print(f"Found {len(databases)} database(s) to migrate:\n")

        for db_path in databases:
            success, message = migrate_database(db_path)
            results.append((db_path, success, message))

    # Print results
    print("=" * 70)
    print("MIGRATION RESULTS")
    print("=" * 70)

    success_count = 0
    for db_path, success, message in results:
        status = "✓ OK" if success else "✗ FAIL"
        print(f"\n{status} {db_path}")
        print(f"    {message}")
        if success:
            success_count += 1

    print("\n" + "=" * 70)
    print(f"Summary: {success_count}/{len(results)} database(s) migrated successfully")
    print("=" * 70)

    sys.exit(0 if success_count == len(results) else 1)


if __name__ == "__main__":
    main()
