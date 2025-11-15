import enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


JSONPayload = Dict[str, Any]


class db_request_type(enum.IntEnum):
    CREATE_SCHEDULE = 1
    CREATE_SESSION = 2
    CREATE_RIDE = 3
    UPDATE_SCHEDULE = 4
    UPDATE_RIDE = 5
    DELETE_RIDE = 6
    CREATE_USER = 7
    UPDATE_USER = 8
    AUTHENTICATE_USER = 9
    FIND_RIDES = 10
    UPDATE_RATING = 11
    TYPE_CHECK = 12


@dataclass(frozen=True)
class DBRequest:
    type: db_request_type
    payload: Optional[JSONPayload] = None


class db_response_type(enum.IntEnum):
    ERROR = 1
    SCHEDULE_CREATED = 2
    SESSION_CREATED = 3
    RIDE_CREATED = 4
    TYPE_CHECK = 5
    SCHEDULE_UPDATED = 6
    RIDE_UPDATED = 7
    RIDE_DELETED = 8
    USER_CREATED = 9
    USER_UPDATED = 10
    USER_AUTHENTICATED = 11
    RIDES_FOUND = 12
    RATING_UPDATED = 13


class db_msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class DBResponse:
    type: db_response_type
    status: db_msg_status
    payload: JSONPayload
