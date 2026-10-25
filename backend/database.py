import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


class Base(DeclarativeBase):
    pass


DATABASE_URL = os.getenv("RONIN_DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'data' / 'ronin.db').as_posix()}")
if DATABASE_URL.startswith("sqlite"):
    Path(DATABASE_URL.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_missing_columns(bind) -> None:
    """Bring an older SQLite database up to the current models by adding missing nullable columns."""
    # shortcut: add-only, no renames or drops, use Alembic once the schema changes shape.
    if bind.dialect.name != "sqlite":
        return
    existing_tables = set(inspect(bind).get_table_names())
    with bind.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table.name})"))}
            for column in table.columns:
                if column.name not in present and column.nullable:
                    connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(bind.dialect)}"))
        if "rabbit_holes" in existing_tables:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_rabbit_holes_slug ON rabbit_holes(slug)"))
