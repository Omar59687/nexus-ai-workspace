
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from collections.abc import Generator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def create_database_engine() -> Engine:
    """Create a SQLAlchemy engine using local environment settings."""
    required_settings = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
    )

    missing_settings = [
        name for name in required_settings if not os.getenv(name)
    ]
    if missing_settings:
        raise RuntimeError(
            "Missing required database settings: "
            + ", ".join(missing_settings)
        )

    database_url = URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
    )

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )


engine = create_database_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)

def get_db() -> Generator[Session, None, None]:
    """Provide a database session and always close it afterward."""
    with SessionLocal() as session:
        yield session


def check_database_connection() -> int:
    """Verify the connection by executing a simple SQL query."""
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one()
