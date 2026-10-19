"""Database setup and session management."""

from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# Database file location
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "portfolio.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite needs this for FastAPI
    echo=False,
)


@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_conn, connection_record):
    """Enable WAL mode for better concurrent read/write performance."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and add columns introduced after the upstream schema."""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(alert_settings)").fetchall()
        columns = {row[1] for row in rows}
        if "pct_threshold" not in columns:
            conn.exec_driver_sql("ALTER TABLE alert_settings ADD COLUMN pct_threshold FLOAT")
