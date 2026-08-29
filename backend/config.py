import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///attendance.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True} if not os.getenv("DATABASE_URL", "").startswith("sqlite") else {}
    ACTIVITY_LOG_FILE = os.getenv("ACTIVITY_LOG_FILE", os.path.join(os.path.dirname(__file__), "activity_logs.jsonl"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-this-secret-key-32chars")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB = os.getenv("MONGO_DB", "attendease_logs")
