import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "spend_tracker.db"


def get_database_path() -> str:
    return os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_database_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    apply_schema(db)
    return db


def apply_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          amount REAL NOT NULL CHECK (amount > 0),
          category TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          expense_date TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_expenses_category_date
          ON expenses(user_id, category, expense_date);

        CREATE INDEX IF NOT EXISTS idx_expenses_date
          ON expenses(user_id, expense_date);
        """
    )
    if not has_column(db, "expenses", "user_id"):
        db.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER")
    db.commit()


def has_column(db: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row["name"] == column_name for row in db.execute(f"PRAGMA table_info({table_name})"))
