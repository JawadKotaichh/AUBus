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
    LOGOUT_USER = 13

    # CORE DOMAIN
    CREATE_SCHEDULE = 3
    CREATE_SESSION = 4
    CREATE_RIDE = 5
    UPDATE_SCHEDULE = 6
    UPDATE_RIDE = 7
    DELETE_RIDE = 8

    TYPE_CHECK = 9
    UPDATE_PROFILE = 10
    FETCH_PROFILE = 11
    LOOKUP_AREA = 12
    FETCH_DRIVERS = 14
    AUTOMATED_RIDE_REQUEST = 15
    FETCH_DRIVER_REQUESTS = 16
    DRIVER_REQUEST_DECISION = 17
    FETCH_RIDE_REQUEST_STATUS = 18
    CONFIRM_RIDE_REQUEST = 19
    CANCEL_RIDE_REQUEST = 20
    REGISTER_CHAT_ENDPOINT = 21
    LIST_ACTIVE_CHATS = 22
    REQUEST_P2P_CHAT = 23
    COMPLETE_RIDE = 24
    RATE_DRIVER = 25
    LIST_TRIPS = 26


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
    P2P_CONNECTION = 11
    USER_FOUND = 12
    PROFILE_UPDATED = 13
    CHAT_ENDPOINT_REGISTERED = 14
    CHATS_LIST = 15


class msg_status(enum.IntEnum):
    OK = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3


@dataclass(frozen=True)
class ServerResponse:
    type: server_response_type
    status: msg_status
    payload: JSONPayload
