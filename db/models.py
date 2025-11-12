import enum
from dataclasses import dataclass
from typing import Optional


class db_msg_type(enum.IntEnum):
    ERROR = 1
    SCHEDULE_CREATED = 2
    SESSION_CREATED = 3
    TRIP_CREATED = 4
    TYPE_CHECK = 5


class db_msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class Message:
    type: db_msg_type
    status: db_msg_status
    payload: Optional[str] = None
