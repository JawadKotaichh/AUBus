from dotenv import load_dotenv
import os
import sqlite3

load_dotenv()


def sqlite3_from_db_url():
    raw = os.getenv("DB_URL")
    if not raw or not raw.startswith("sqlite"):
        raise RuntimeError("DB_URL must be a sqlite URL for sqlite3 stdlib use")
    if raw.startswith("sqlite:///"):
        path = raw.replace("sqlite:///", "", 1)
        con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    elif raw.startswith("sqlite:"):
        con = sqlite3.connect(
            raw.replace("sqlite:", "", 1),
            uri=True,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
    else:
        raise RuntimeError(f"Unsupported sqlite URL: {raw!r}")

    con.execute("PRAGMA foreign_keys = ON;")
    return con


DB_CONNECTION = sqlite3_from_db_url()
