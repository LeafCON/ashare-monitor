"""One-time migration: convert fake-symbol alert entries (e.g. GOOGL_280)
to proper multi-level alerts with is_primary/label fields.

Also removes the UNIQUE constraint on symbol to allow multiple alerts per ticker.

Run: cd backend && python -m migrate_alerts
"""

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"


def migrate():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Step 1: Check if migration already done
    cols = [row[1] for row in cur.execute("PRAGMA table_info(alert_settings)").fetchall()]

    if "is_primary" not in cols:
        cur.execute("ALTER TABLE alert_settings ADD COLUMN is_primary BOOLEAN DEFAULT 1")
        print("Added column: is_primary")
    if "label" not in cols:
        cur.execute("ALTER TABLE alert_settings ADD COLUMN label TEXT")
        print("Added column: label")
    if "amount" not in cols:
        cur.execute("ALTER TABLE alert_settings ADD COLUMN amount VARCHAR(200)")
        print("Added column: amount")
    if "expires_at" not in cols:
        cur.execute("ALTER TABLE alert_settings ADD COLUMN expires_at DATETIME")
        print("Added column: expires_at")
    if "last_triggered_at" not in cols:
        cur.execute("ALTER TABLE alert_settings ADD COLUMN last_triggered_at DATETIME")
        print("Added column: last_triggered_at")
    conn.commit()

    # Step 2: Recreate table without UNIQUE constraint on symbol
    # SQLite doesn't support DROP CONSTRAINT, so we recreate.
    print("\nRecreating table without UNIQUE constraint on symbol...")

    cur.execute("ALTER TABLE alert_settings RENAME TO alert_settings_old")

    cur.execute("""
        CREATE TABLE alert_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(20) NOT NULL,
            name VARCHAR(100) NOT NULL DEFAULT '',
            market VARCHAR(2) NOT NULL DEFAULT 'us',
            target_buy FLOAT,
            target_sell FLOAT,
            stop_loss FLOAT,
            enabled BOOLEAN DEFAULT 1,
            is_primary BOOLEAN DEFAULT 1,
            label TEXT,
            amount VARCHAR(200),
            expires_at DATETIME,
            last_triggered_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS ix_alert_settings_symbol ON alert_settings (symbol)")

    cur.execute("""
        INSERT INTO alert_settings
            (id, symbol, name, market, target_buy, target_sell, stop_loss, enabled, is_primary, label, amount, expires_at, last_triggered_at, created_at, updated_at)
        SELECT
            id, symbol, name, market, target_buy, target_sell, stop_loss, enabled,
            COALESCE(is_primary, 1), label, NULL, NULL, NULL, created_at, updated_at
        FROM alert_settings_old
    """)

    cur.execute("DROP TABLE alert_settings_old")
    conn.commit()
    print("Table recreated successfully.")

    # Step 3: Convert fake-symbol entries
    rows = cur.execute("SELECT * FROM alert_settings ORDER BY symbol").fetchall()
    fake_pattern = re.compile(r'^([A-Z]+(?:\d+\.SS)?)_(\d+)$')

    updates = []
    for row in rows:
        symbol = row["symbol"]
        m = fake_pattern.match(symbol)
        if m:
            real_symbol = m.group(1)
            price_level = m.group(2)

            parts = []
            if row["target_buy"]:
                parts.append(f"${int(row['target_buy'])}买")
            if row["target_sell"]:
                parts.append(f"${int(row['target_sell'])}卖")
            if row["stop_loss"]:
                parts.append(f"${int(row['stop_loss'])}止损")
            label = "/".join(parts) if parts else f"${price_level}档"

            # Use the parent name (without the price suffix)
            parent = cur.execute(
                "SELECT name FROM alert_settings WHERE symbol=? AND is_primary=1",
                (real_symbol,)
            ).fetchone()
            name = parent["name"] if parent else row["name"].split("$")[0].strip()

            print(f"  Converting: {symbol} -> {real_symbol} (sub-level, label={label})")
            updates.append((real_symbol, name, 0, label, row["id"]))

    for real_symbol, name, is_primary, label, alert_id in updates:
        cur.execute(
            "UPDATE alert_settings SET symbol=?, name=?, is_primary=?, label=? WHERE id=?",
            (real_symbol, name, is_primary, label, alert_id),
        )

    # Step 4: Mark remaining entries as primary where not yet set
    cur.execute("UPDATE alert_settings SET is_primary=1 WHERE is_primary IS NULL")

    conn.commit()
    print(f"\nMigration complete. Converted {len(updates)} fake-symbol entries.")

    # Show final state
    rows = cur.execute(
        "SELECT id, symbol, name, is_primary, label, target_buy, target_sell, stop_loss "
        "FROM alert_settings ORDER BY symbol, is_primary DESC"
    ).fetchall()
    print(f"\nFinal alert_settings ({len(rows)} rows):")
    for r in rows:
        primary = "PRIMARY" if r["is_primary"] else "  sub  "
        label = r["label"] or ""
        buy = f"buy=${r['target_buy']}" if r['target_buy'] else ""
        sell = f"sell=${r['target_sell']}" if r['target_sell'] else ""
        stop = f"stop=${r['stop_loss']}" if r['stop_loss'] else ""
        targets = " ".join(filter(None, [buy, sell, stop]))
        print(f"  [{primary}] id={r['id']:2d} {r['symbol']:12s} {targets:40s} {label}")

    conn.close()


if __name__ == "__main__":
    migrate()
