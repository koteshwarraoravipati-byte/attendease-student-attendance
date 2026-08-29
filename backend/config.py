import os
from dotenv import load_dotenv

load_dotenv()


def database_url():
    url = os.getenv("DATABASE_URL", "sqlite:///attendance.db").strip()
    # Supabase and most managed PostgreSQL providers expose postgres:// URLs.
    # SQLAlchemy needs an installed PostgreSQL driver and an explicit dialect.
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


class Config:
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"pool_pre_ping": True, "pool_recycle": 300}
        if not SQLALCHEMY_DATABASE_URI.startswith("sqlite")
        else {}
    )
    ACTIVITY_LOG_FILE = os.getenv("ACTIVITY_LOG_FILE", os.path.join(os.path.dirname(__file__), "activity_logs.jsonl"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-this-secret-key-32chars")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB = os.getenv("MONGO_DB", "attendease_logs")
