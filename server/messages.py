import enum
from typing import Any, Dict, TypedDict


class msg_type(enum.IntEnum):
    REGISTER = 1
    REGISTER_ACK = 2
    LOGIN = 3
    LOGIN_ACK = 4
    SEARCH_DRIVERS = 5
    SEARCH_DRIVERS_ACK = 6
    RIDE_REQUEST = 7
    RIDE_REQUEST_ACK = 8
    RIDE_MATCH = 9
    RIDE_MATCH_ACK = 10
    RIDE_COMPLETE = 11
    RIDE_COMPLETE_ACK = 12
    HELLO = 13
    HELLO_ACK = 14
    BYE = 15
    BYE_ACK = 16
    PROFILE_UPDATE = 17
    PROFILE_UPDATE_ACK = 18
    LOGOUT = 19
    LOGOUT_ACK = 20
    RIDE_ACCEPT = 21
    ERROR = 22


class msg_status(enum.IntEnum):
    OK = 1
    PENDING = 2
    MISSING_FIELDS = 3
    NETWORK_ERROR = 4
    INVALID_INPUT = 5
    AUTH_FAILED = 6
    ALREADY_EXISTS = 7


class Msg(TypedDict, total=False):
    type: msg_type
    seq: int  # client-chosen sequence number
    status: msg_status
    payload: Dict[str, Any]

    def __init__(self, type: msg_type, status: msg_status, payload: Dict[str, Any]):
        self.type = type
        self.status = status
        self.payload = payload
