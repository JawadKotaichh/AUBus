from __future__ import annotations
from datetime import datetime
import sqlite3
from typing import Iterable, Mapping, Optional, Tuple, Dict
from models import Message, db_msg_type, db_msg_status
from db_connection import DB_CONNECTION


DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

DAY_TO_COLS: Dict[str, Tuple[str, str]] = {
    d.lower(): (f"{d}_departure_time", f"{d}_return_time") for d in DAY_NAMES
}


class ScheduleDay:
    departure_time: datetime
    return_time: datetime

    def __init__(self, departure_time: datetime, return_time: datetime):
        self.departure_time = departure_time
        self.return_time = return_time


_SQLITE_TS_FMT = "%Y-%m-%d %H:%M:%S"  # SQLite CURRENT_TIMESTAMP format


def _dump_dt(dt: datetime) -> str:
    return dt.replace(microsecond=0).strftime(_SQLITE_TS_FMT)


def _norm_day(day: str) -> Tuple[Message, str]:
    d = day.strip().lower()
    if d not in DAY_TO_COLS:
        return (
            Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"Invalid day name:{d}",
            ),
            "",
        )
    return (
        Message(
            type=db_msg_type.TYPE_CHECK,
            status=db_msg_status.OK,
            payload="Creation Succeded",
        ),
        d,
    )


def _validate_schedule_day(sd: ScheduleDay) -> Tuple[Message, Optional[ScheduleDay]]:
    dep, ret = sd.departure_time, sd.return_time
    if dep is None or ret is None:
        return (
            Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"Both departure_time and return_time must be set together: dep={dep}, ret={ret}",
            ),
            None,
        )
    if ret < dep:
        return (
            Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"return_time must be >= departure_time: dep={dep}, ret={ret}",
            ),
            None,
        )
    return (
        Message(
            type=db_msg_type.TYPE_CHECK,
            status=db_msg_status.OK,
            payload="Success",
        ),
        ScheduleDay(departure_time=dep, return_time=ret),
    )


def _day_check(dep_col: str, ret_col: str) -> str:
    return f"({ret_col} >= {dep_col})"


def init_schema_schedule() -> None:
    checks = ",\n        ".join(
        f"CHECK({_day_check(dep, ret)}) /* ck_{day} */"
        for day, (dep, ret) in DAY_TO_COLS.items()
    )

    DB_CONNECTION.executescript(f"""
    CREATE TABLE IF NOT EXISTS schedule (
        id INTEGER PRIMARY KEY,
        Monday_departure_time    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Monday_return_time       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Tuesday_departure_time   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Tuesday_return_time      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Wednesday_departure_time TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Wednesday_return_time    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Thursday_departure_time  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Thursday_return_time     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Friday_departure_time    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Friday_return_time       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Saturday_departure_time  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Saturday_return_time     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Sunday_departure_time    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        Sunday_return_time       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        created_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        {checks}
    );
    """)
    DB_CONNECTION.commit()


ALL_COLS: Iterable[str] = tuple(
    col for d in DAY_NAMES for col in (f"{d}_departure_time", f"{d}_return_time")
)


def create_schedule(*, days: Mapping[str, ScheduleDay] | None = None) -> int:
    """
    Insert a row using the provided day times, and let SQLite defaults fill the rest.
    Example:
        create_schedule(days={
            "monday": ScheduleDay(dep_dt, ret_dt),
            "wednesday": ScheduleDay(dep_dt2, ret_dt2),
        })
    """
    days = days or {}
    normalized: Dict[str, ScheduleDay] = {}
    for k, v in days.items():
        m1, key = _norm_day(k)
        if m1.status != db_msg_status.OK:
            raise ValueError(m1.payload)
        m2, ok_sd = _validate_schedule_day(v)
        if m2.status != db_msg_status.OK or ok_sd is None:
            raise ValueError(m2.payload)
        normalized[key] = ok_sd
    cols: list[str] = []
    vals: list[str] = []
    for day in DAY_NAMES:
        key = day.lower()
        sd = normalized.get(key)
        if sd:
            dep_col, ret_col = DAY_TO_COLS[key]
            cols.extend([dep_col, ret_col])
            vals.extend([_dump_dt(sd.departure_time), _dump_dt(sd.return_time)])

    if cols:
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO schedule ({', '.join(cols)}) VALUES ({placeholders})"
        cur = DB_CONNECTION.execute(sql, vals)
    else:
        cur = DB_CONNECTION.execute("INSERT INTO schedule DEFAULT VALUES")

    DB_CONNECTION.commit()
    return int(cur.lastrowid)


def _user_exists(user_id: int) -> bool:
    cur = DB_CONNECTION.execute("SELECT 1 FROM users WHERE id = ?", (user_id,))
    return cur.fetchone() is not None


def _schedule_exists(schedule_id: int) -> bool:
    cur = DB_CONNECTION.execute("SELECT 1 FROM schedule WHERE id = ?", (schedule_id,))
    return cur.fetchone() is not None


def update_schedule(
    *,
    schedule_id: int,
    user_id: int,
    days: Mapping[str, ScheduleDay] | None = None,
) -> Message:
    """
    Update selected day times for a schedule row.
    - Verifies the user exists.
    - Verifies the schedule row exists.
    - Only updates the days provided in `days` (others remain unchanged).
    """
    # --- user present? ---
    if not _user_exists(user_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"User not found: user_id={user_id}",
        )

    if not _schedule_exists(schedule_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"Schedule not found: id={schedule_id}",
        )

    days = days or {}
    if not days:
        return Message(
            type=db_msg_type.TYPE_CHECK,
            status=db_msg_status.OK,
            payload=f"No changes requested for schedule id={schedule_id}.",
        )

    normalized: Dict[str, ScheduleDay] = {}
    for k, v in days.items():
        m1, key = _norm_day(k)
        if m1.status != db_msg_status.OK:
            return m1
        m2, ok_sd = _validate_schedule_day(v)
        if m2.status != db_msg_status.OK or ok_sd is None:
            return m2
        normalized[key] = ok_sd

    set_parts: list[str] = []
    params: list[str] = []

    for day in DAY_NAMES:
        key = day.lower()
        sd = normalized.get(key)
        if sd is not None:
            dep_col, ret_col = DAY_TO_COLS[key]
            set_parts.append(f"{dep_col} = ?")
            set_parts.append(f"{ret_col} = ?")
            params.append(_dump_dt(sd.departure_time))
            params.append(_dump_dt(sd.return_time))

    if not set_parts:
        return Message(
            type=db_msg_type.TYPE_CHECK,
            status=db_msg_status.OK,
            payload=f"No valid day fields to update for schedule id={schedule_id}.",
        )

    sql = f"UPDATE schedule SET {', '.join(set_parts)} WHERE id = ?"
    params.append(str(schedule_id))

    try:
        cur = DB_CONNECTION.execute(sql, params)
        DB_CONNECTION.commit()
    except sqlite3.IntegrityError as e:
        # Likely CHECK(ret >= dep) violation or similar
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Update failed due to constraint: {e}",
        )

    # In sqlite3, rowcount is reliable for UPDATE — make sure something changed
    if cur.rowcount == 0:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"No rows updated for schedule id={schedule_id}.",
        )

    # If you have a SCHEDULE_UPDATED type, use it; else keep SCHEDULE_CREATED.
    return Message(
        type=db_msg_type.SCHEDULE_UPDATED,
        status=db_msg_status.OK,
        payload=f"Schedule {schedule_id} updated successfully.",
    )
