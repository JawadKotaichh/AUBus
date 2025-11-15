from dotenv import load_dotenv
import os
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DEFAULT_DB_PATH = (BASE_DIR / "AUBus.db").resolve()


def _default_sqlite_url() -> str:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(DEFAULT_DB_PATH))
    return f"sqlite:///{DEFAULT_DB_PATH}"


def sqlite3_from_db_url():
    raw = os.getenv("DB_URL")
    url = raw.strip() if raw and raw.strip() else _default_sqlite_url()
    if not url.startswith("sqlite"):
        raise RuntimeError("DB_URL must be a sqlite URL for sqlite3 stdlib use")
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    elif url.startswith("sqlite:"):
        con = sqlite3.connect(
            url.replace("sqlite:", "", 1),
            uri=True,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
    else:
        raise RuntimeError(f"Unsupported sqlite URL: {url!r}")

    con.execute("PRAGMA foreign_keys = ON;")
    return con


DB_CONNECTION = sqlite3_from_db_url()
