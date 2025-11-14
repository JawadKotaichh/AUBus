import enum
from dataclasses import dataclass
from typing import Optional


class msg_type(enum.IntEnum):
    ERROR = 1
    SCHEDULE_CREATED = 2
    SESSION_CREATED = 3
    RIDE_CREATED = 4
    TYPE_CHECK = 5
    SCHEDULE_UPDATED = 6
    RIDE_UPDATED = 7
    RIDE_DELETED = 8


class msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class Server_Client_Message:
    type: msg_type
    status: msg_status
    payload: Optional[str] = None
