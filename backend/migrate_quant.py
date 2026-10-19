"""Migration: create quant_signals table.

Run: cd backend && python migrate_quant.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"


def migrate():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Check if table already exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quant_signals'")
    if cur.fetchone():
        print("Table quant_signals already exists, skipping creation.")
        conn.close()
        return

    cur.execute("""
        CREATE TABLE quant_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(20) NOT NULL,
            date DATETIME NOT NULL,
            metric VARCHAR(30) NOT NULL,
            value FLOAT,
            percentile FLOAT,
            updated_at DATETIME
        )
    """)
    cur.execute("CREATE INDEX ix_quant_signals_symbol ON quant_signals (symbol)")
    cur.execute("CREATE INDEX ix_quant_signals_symbol_metric ON quant_signals (symbol, metric)")
    
    conn.commit()
    print("✅ Created table: quant_signals")
    conn.close()


if __name__ == "__main__":
    migrate()
