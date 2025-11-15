import enum
from dataclasses import dataclass
from typing import Dict, Any

# JSON-like payload alias
JSONPayload = Dict[str, Any]

# ==== CLIENT → SERVER ====


class client_request_type(enum.IntEnum):
    # AUTH
    REGISTER_USER = 1
    LOGIN_USER = 2

    # CORE DOMAIN
    CREATE_SCHEDULE = 3
    CREATE_SESSION = 4
    CREATE_RIDE = 5
    UPDATE_SCHEDULE = 6
    UPDATE_RIDE = 7
    DELETE_RIDE = 8

    TYPE_CHECK = 9


@dataclass(frozen=True)
class ClientRequest:
    type: client_request_type
    payload: JSONPayload


# ==== SERVER → CLIENT ====


class server_response_type(enum.IntEnum):
    ERROR = 1

    # AUTH
    USER_REGISTERED = 2
    USER_LOGGED_IN = 3
    SESSION_CREATED = 4

    # DOMAIN
    SCHEDULE_CREATED = 5
    RIDE_CREATED = 6
    SCHEDULE_UPDATED = 7
    RIDE_UPDATED = 8
    RIDE_DELETED = 9

    TYPE_CHECK = 10


class msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class ServerResponse:
    type: server_response_type
    status: msg_status
    payload: JSONPayload
