from typing import Any, Dict
from server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)


def _ok_server(
    payload: Dict[str, Any], resp_type: server_response_type
) -> ServerResponse:
    return ServerResponse(
        type=resp_type,
        status=msg_status.OK,
        payload={"output": payload, "error": None},
    )


def _error_server(
    message: str, status: msg_status = msg_status.INVALID_INPUT
) -> ServerResponse:
    return ServerResponse(
        type=server_response_type.ERROR,
        status=status,
        payload={"output": None, "error": message},
    )
