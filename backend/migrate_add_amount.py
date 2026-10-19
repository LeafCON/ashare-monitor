"""Migration: Add 'amount' column to alert_settings table."""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"


def migrate():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}, will be created on first run.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(alert_settings)")
    columns = [row[1] for row in cursor.fetchall()]

    if "amount" not in columns:
        cursor.execute("ALTER TABLE alert_settings ADD COLUMN amount VARCHAR(200)")
        conn.commit()
        print("✅ Added 'amount' column to alert_settings table.")
    else:
        print("ℹ️  'amount' column already exists, skipping.")

    conn.close()


if __name__ == "__main__":
    migrate()
