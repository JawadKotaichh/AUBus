import enum


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
    HELLO = 11
    HELLO_ACK = 12
    BYE = 13
    BYE_ACK = 14
    REQUEST_CHATS = 15
    REQUEST_CHATS_ACK = 16


class msg_status(enum.IntEnum):
    OK = 1
    MISSING_FIELDS = 2
    NETWORK_ERROR = 3


class message:
    def __init__(self, type: msg_type, status: msg_status, seq, payload):
        self.type = type
        self.status = status
        self.seq = seq
        self.payload = payload
