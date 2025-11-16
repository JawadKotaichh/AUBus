import json
from typing import Any, Dict

from server.server_client_protocol import (
    ClientRequest,
    ServerResponse,
    client_request_type,
)


def decode_client_request(line: str) -> ClientRequest:
    """
    Parse one JSON line from client into a ClientRequest.
    line should NOT contain the trailing newline.
    """
    obj: Dict[str, Any] = json.loads(line)
    request_type = client_request_type(obj["type"])
    payload = obj.get("payload")
    return ClientRequest(type=request_type, payload=payload)


def encode_server_response(resp: ServerResponse) -> bytes:
    """
    Serialize ServerResponse to newline-terminated JSON bytes.
    """
    obj = {
        "type": int(resp.type),
        "status": int(resp.status),
        "payload": resp.payload,
    }
    return (json.dumps(obj) + "\n").encode("utf-8")
