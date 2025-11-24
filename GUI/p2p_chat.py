from __future__ import annotations

import base64
import json
import secrets
import select
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class PeerChatError(RuntimeError):
    """Raised when the peer-to-peer chat service encounters a failure."""


@dataclass
class PeerEndpoint:
    host: str
    port: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class PeerChatNode(QObject):
    """
    Lightweight peer-to-peer chat transport.

    Each client hosts a tiny TCP listener that exchanges newline-delimited JSON
    packets.  Messages can represent plain text or base64-encoded attachments
    (voice notes, photos, etc.).  The node emits Qt signals so the GUI can stay
    responsive without polling background threads.
    """

    message_received = pyqtSignal(str, dict)
    chat_ready = pyqtSignal(str)
    chat_error = pyqtSignal(str, str)

    def __init__(
        self,
        listen_host: str = "0.0.0.0",
        listen_port: int = 0,
        *,
        storage_dir: Optional[Path] = None,
        connect_timeout: float = 4.0,
    ) -> None:
        super().__init__()
        self.listen_host = listen_host
        self._requested_port = listen_port
        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._peers: Dict[str, PeerEndpoint] = {}
        self._storage_root = Path(storage_dir or (Path.cwd() / "chat_media"))
        self._storage_root.mkdir(parents=True, exist_ok=True)
        self._storage_dir = self._storage_root
        self._connect_timeout = connect_timeout
        self._listening_port: int = 0

    @property
    def port(self) -> int:
        return self._listening_port

    def set_user_namespace(
        self, *, user_id: Optional[int] = None, username: Optional[str] = None
    ) -> None:
        """
        Isolate chat history/attachments per local user so accounts do not
        leak conversations into each other when sharing the same device.
        """
        namespace: Optional[str] = None
        if user_id is not None:
            try:
                namespace = f"user-{int(user_id)}"
            except (TypeError, ValueError):
                namespace = None
        if namespace is None and username:
            safe = "".join(
                c for c in str(username).lower() if c.isalnum() or c in {"-", "_"}
            )
            if safe:
                namespace = f"user-{safe}"
        target_dir = self._storage_root / namespace if namespace else self._storage_root
        target_dir.mkdir(parents=True, exist_ok=True)
        self._storage_dir = target_dir
        self._peers.clear()

    def start(self) -> None:
        if self._server_thread and self._server_thread.is_alive():
            return
        self._stop_event.clear()
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.listen_host, self._requested_port))
        self._server_socket.listen(5)
        self._listening_port = self._server_socket.getsockname()[1]
        self._server_thread = threading.Thread(
            target=self._serve, name="PeerChatServer", daemon=True
        )
        self._server_thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)
        self._server_socket = None

    def clear(self) -> None:
        """Forget all peer registrations (used on logout)."""
        self._peers.clear()

    def register_peer(
        self,
        chat_id: str,
        *,
        host: str,
        port: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not chat_id:
            raise PeerChatError("chat_id is required to register a peer.")
        self._peers[chat_id] = PeerEndpoint(
            host=host, port=int(port), metadata=dict(metadata or {})
        )
        self.chat_ready.emit(chat_id)

    def is_ready(self, chat_id: str) -> bool:
        return chat_id in self._peers

    def load_history(self, chat_id: str) -> list[Dict[str, Any]]:
        """Load past messages from disk."""
        history_file = self._history_file(chat_id)
        if not history_file.exists():
            return []
        messages = []
        try:
            for line in history_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    messages.append(json.loads(line))
        except Exception:
            pass  # Ignore corrupted history
        return messages

    def _history_file(self, chat_id: str) -> Path:
        chat_dir = self._storage_dir / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir / "messages.jsonl"

    def _append_to_history(self, chat_id: str, message: Dict[str, Any]) -> None:
        try:
            line = json.dumps(message) + "\n"
            with self._history_file(chat_id).open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # Don't crash on logging failure


    def send_text(self, chat_id: str, sender: str, body: str) -> Dict[str, Any]:
        if not body.strip():
            raise PeerChatError("Message body cannot be empty.")
        packet = self._build_packet(
            chat_id=chat_id, sender=sender, media_type="text", body=body.strip()
        )
        self._transmit(packet)
        message = self._make_message(packet, direction="outgoing")
        self._append_to_history(chat_id, message)
        return message

    def send_photo(self, chat_id: str, sender: str, file_path: str) -> Dict[str, Any]:
        return self._send_attachment(
            chat_id=chat_id,
            sender=sender,
            file_path=file_path,
            media_type="photo",
        )

    def send_voice(self, chat_id: str, sender: str, file_path: str) -> Dict[str, Any]:
        return self._send_attachment(
            chat_id=chat_id, sender=sender, file_path=file_path, media_type="voice"
        )

    def _serve(self) -> None:
        assert self._server_socket is not None
        while not self._stop_event.is_set():
            if self._server_socket is None:
                break
            try:
                readable, _, _ = select.select(
                    [self._server_socket], [], [], 0.4
                )
            except OSError:
                break
            if not readable:
                continue
            try:
                conn, addr = self._server_socket.accept()
            except OSError:
                break
            threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True
            ).start()

    def _handle_client(self, conn: socket.socket, addr) -> None:
        with conn:
            buffer = b""
            while not self._stop_event.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    if not raw_line.strip():
                        continue
                    try:
                        packet = json.loads(raw_line.decode("utf-8"))
                        chat_id = packet.get("chat_id")
                        if not chat_id:
                            raise ValueError("chat_id missing in packet")
                        message = self._make_message(packet, direction="incoming")
                        self._append_to_history(chat_id, message)
                        self.message_received.emit(chat_id, message)
                    except Exception as exc:  # noqa: BLE001
                        chat_id_hint = packet.get("chat_id") if "packet" in locals() else ""
                        self.chat_error.emit(
                            chat_id_hint or "",
                            f"Failed to parse incoming packet from {addr}: {exc}",
                        )

    def _send_attachment(
        self,
        *,
        chat_id: str,
        sender: str,
        file_path: str,
        media_type: str,
    ) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise PeerChatError(f"File not found: {file_path}")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        filename = path.name
        if media_type == "voice":
            filename = self._random_filename("voice", path.suffix or ".m4a")
        packet = self._build_packet(
            chat_id=chat_id,
            sender=sender,
            media_type=media_type,
            body=f"{media_type.title()} shared: {filename}",
            filename=filename,
            data=data,
        )
        stored_path = self._store_attachment(chat_id, filename, path.read_bytes())
        self._transmit(packet)
        message = self._make_message(packet, direction="outgoing")
        message["attachment_path"] = str(stored_path)
        self._append_to_history(chat_id, message)
        return message

    def _build_packet(
        self,
        *,
        chat_id: str,
        sender: str,
        media_type: str,
        body: str = "",
        filename: Optional[str] = None,
        data: Optional[str] = None,
    ) -> Dict[str, Any]:
        endpoint = self._peers.get(chat_id)
        if not endpoint:
            raise PeerChatError("Peer endpoint is not registered for this chat.")
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        packet: Dict[str, Any] = {
            "chat_id": chat_id,
            "sender": sender,
            "media_type": media_type,
            "body": body,
            "timestamp": timestamp,
        }
        if filename:
            packet["filename"] = filename
        if data:
            packet["data"] = data
        return packet

    def _make_message(self, packet: Dict[str, Any], *, direction: str) -> Dict[str, Any]:
        media_type = (packet.get("media_type") or "text").lower()
        attachment_path: Optional[str] = None
        if media_type != "text" and "data" in packet:
            raw_data = packet.get("data")
            if isinstance(raw_data, str):
                try:
                    blob = base64.b64decode(raw_data.encode("ascii"))
                except Exception:  # noqa: BLE001
                    blob = b""
            else:
                blob = b""
            filename = packet.get("filename") or f"attachment-{int(time.time())}"
            attachment_path = str(self._store_attachment(packet["chat_id"], filename, blob))
        else:
            filename = packet.get("filename")
        return {
            "chat_id": packet.get("chat_id"),
            "sender": packet.get("sender"),
            "body": packet.get("body") or "",
            "media_type": media_type,
            "filename": filename,
            "attachment_path": attachment_path,
            "timestamp": packet.get("timestamp"),
            "direction": direction,
        }

    def _store_attachment(self, chat_id: str, filename: str, data: bytes) -> Path:
        sanitized = "".join(c for c in filename if c.isalnum() or c in {"-", "_", "."})
        if not sanitized:
            sanitized = f"attachment-{int(time.time())}"
        chat_dir = self._storage_dir / chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        target = chat_dir / sanitized
        # Avoid clobbering an existing attachment if the sender reused a filename.
        if target.exists():
            base = target.stem
            suffix = target.suffix
            counter = 1
            while target.exists():
                target = chat_dir / f"{base}-{counter}{suffix}"
                counter += 1
        target.write_bytes(data)
        return target

    def _random_filename(self, prefix: str, suffix: str) -> str:
        clean_prefix = "".join(c for c in prefix if c.isalnum() or c in {"-", "_"})
        if not clean_prefix:
            clean_prefix = "voice"
        clean_suffix = suffix if suffix.startswith(".") else f".{suffix.lstrip('.')}"
        token = secrets.token_hex(4)
        return f"{clean_prefix}-{token}{clean_suffix}"

    def _transmit(self, packet: Dict[str, Any]) -> None:
        chat_id = packet.get("chat_id")
        endpoint = self._peers.get(chat_id)
        if not endpoint:
            raise PeerChatError("No peer endpoint available for this chat.")
        payload = json.dumps(packet).encode("utf-8") + b"\n"
        try:
            with socket.create_connection(
                (endpoint.host, endpoint.port), timeout=self._connect_timeout
            ) as conn:
                conn.sendall(payload)
        except OSError as exc:  # pragma: no cover - network errors depend on env
            raise PeerChatError(f"Unable to reach peer at {endpoint.host}:{endpoint.port}") from exc
