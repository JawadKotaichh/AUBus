from dotenv import load_dotenv
import os
from pathlib import Path
import sqlite3
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")
DEFAULT_DB_PATH = (BASE_DIR / "AUBus.db").resolve()
DB_FILE_PATH: Optional[Path] = None


def _resolve_db_path(value: str) -> Path:
    raw_path = Path(value.strip())
    if raw_path.is_absolute():
        return raw_path.resolve()

    root_candidate = (PROJECT_ROOT / raw_path).resolve()
    if root_candidate.exists():
        return root_candidate

    base_candidate = (BASE_DIR / raw_path).resolve()
    if base_candidate.exists():
        return base_candidate

    # Default to storing DB files under the project root for consistency.
    return root_candidate


def _normalize_db_env_paths() -> None:
    """
    Ensure DB_PATH / DB_URL environment variables point to absolute paths so that
    the same database file is reused regardless of the process working directory.
    """
    normalized_path: Optional[Path] = None
    raw_path = os.getenv("DB_PATH")
    if raw_path:
        cleaned = raw_path.strip()
        if cleaned:
            normalized_path = _resolve_db_path(cleaned)
            os.environ["DB_PATH"] = str(normalized_path)

    raw_url = os.getenv("DB_URL")
    if raw_url:
        cleaned_url = raw_url.strip()
        if cleaned_url.startswith("sqlite:///"):
            path_part = cleaned_url.replace("sqlite:///", "", 1)
            if path_part:
                path = normalized_path or _resolve_db_path(path_part)
                os.environ["DB_URL"] = f"sqlite:///{path}"


_normalize_db_env_paths()


def _default_sqlite_url() -> str:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(DEFAULT_DB_PATH))
    return f"sqlite:///{DEFAULT_DB_PATH}"


def _set_db_file_path_from_connection(
    con: sqlite3.Connection, url: str | None = None
) -> None:
    """
    Capture the resolved sqlite file path (if any) so that other modules can
    inspect whether the database already exists on disk.
    """
    global DB_FILE_PATH
    try:
        cur = con.execute("PRAGMA database_list;")
        for _, name, file_path in cur.fetchall():
            if name == "main" and file_path:
                DB_FILE_PATH = Path(file_path).resolve()
                return
    except sqlite3.Error:
        pass

    # Fall back to DB_PATH env var or the default location if PRAGMA lookup fails.
    raw_path = os.getenv("DB_PATH")
    if raw_path:
        DB_FILE_PATH = Path(raw_path).expanduser().resolve()
    elif url and url.startswith("sqlite:///"):
        DB_FILE_PATH = Path(url.replace("sqlite:///", "", 1)).expanduser().resolve()
    else:
        DB_FILE_PATH = DEFAULT_DB_PATH


def sqlite3_from_db_url():
    raw = os.getenv("DB_URL")
    url = raw.strip() if raw and raw.strip() else _default_sqlite_url()
    if not url.startswith("sqlite"):
        raise RuntimeError("DB_URL must be a sqlite URL for sqlite3 stdlib use")
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        con = sqlite3.connect(
            path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
    elif url.startswith("sqlite:"):
        con = sqlite3.connect(
            url.replace("sqlite:", "", 1),
            uri=True,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
    else:
        raise RuntimeError(f"Unsupported sqlite URL: {url!r}")

    con.execute("PRAGMA foreign_keys = ON;")
    _set_db_file_path_from_connection(con, url)
    return con


DB_CONNECTION = sqlite3_from_db_url()


def get_db_file_path() -> Optional[Path]:
    """Return the sqlite file path for the primary database if available."""
    if DB_FILE_PATH is not None:
        return DB_FILE_PATH
    raw_path = os.getenv("DB_PATH")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return DEFAULT_DB_PATH


def db_file_exists() -> bool:
    """Check whether the sqlite database file already exists on disk."""
    path = get_db_file_path()
    return bool(path and path.exists())
