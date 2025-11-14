import enum
from dataclasses import dataclass
from typing import Optional


class db_msg_type(enum.IntEnum):
    ERROR = 1
    SCHEDULE_CREATED = 2
    SESSION_CREATED = 3
    RIDE_CREATED = 4
    TYPE_CHECK = 5
    SCHEDULE_UPDATED = 6
    RIDE_UPDATED = 7
    RIDE_DELETED = 8
    USER_CREATED=9
    USER_UPDATED=10
    USER_AUTHENTICATED=11
    RIDES_FOUND=12
    RATING_UPDATED=13



class db_msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class Server_DB_Message:
    type: db_msg_type
    status: db_msg_status
    payload: Optional[str] = None
