from sqlmodel import SQLModel, create_engine, Session
from app.config import settings

import os

db_url = settings.database_url
# Vercel's file system is read-only. If using default local sqlite, move it to /tmp
if db_url == "sqlite:///./nombarecur.db" and os.environ.get("VERCEL"):
    db_url = "sqlite:////tmp/nombarecur.db"

engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False},  # SQLite only
    echo=(settings.app_env == "sandbox"),       # SQL logging in sandbox
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
