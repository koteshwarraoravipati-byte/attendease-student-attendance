import sys
from pathlib import Path

# Make the backend package root importable in Vercel's Python runtime.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402,F401
