from sqlmodel import SQLModel, create_engine, Session
from app.config import settings

import os
import ssl
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

db_url = settings.database_url
# Vercel's file system is read-only. If using default local sqlite, move it to /tmp
if db_url == "sqlite:///./nombarecur.db" and os.environ.get("VERCEL"):
    db_url = "sqlite:////tmp/nombarecur.db"

_connect_args = {}

if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
    # Use pg8000 (pure Python, no C deps) — works on any serverless/Lambda runtime.
    # pg8000 doesn't accept sslmode in the URL; strip it and pass an ssl_context instead.
    parsed = urlparse(db_url)
    qs = parse_qs(parsed.query)
    needs_ssl = qs.pop("sslmode", ["disable"])[0] in ("require", "verify-ca", "verify-full")
    clean_query = urlencode({k: v[0] for k, v in qs.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query, scheme="postgresql+pg8000"))
    db_url = clean_url
    if needs_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _connect_args["ssl_context"] = ctx
else:
    # SQLite only
    _connect_args["check_same_thread"] = False

engine = create_engine(
    db_url,
    connect_args=_connect_args,
    echo=(settings.app_env == "sandbox"),       # SQL logging in sandbox
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
