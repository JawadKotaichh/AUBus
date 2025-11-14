import enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


# JSON-like payload alias
JSONPayload = Dict[str, Any]


# ==== CLIENT → SERVER ====


class client_request_type(enum.IntEnum):
    CREATE_SCHEDULE = 1
    CREATE_SESSION = 2
    CREATE_RIDE = 3
    UPDATE_SCHEDULE = 4
    UPDATE_RIDE = 5
    DELETE_RIDE = 6
    TYPE_CHECK = 7  # ping/healthcheck, etc.


@dataclass(frozen=True)
class ClientRequest:
    type: client_request_type
    payload: Optional[JSONPayload] = None


class server_response_type(enum.IntEnum):
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
class ServerResponse:
    type: server_response_type
    status: msg_status
    payload: Optional[JSONPayload] = None
