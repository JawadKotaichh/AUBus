from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, CheckConstraint, ForeignKey
from models import Base
from models import Message, db_msg_status, db_msg_type
import ipaddress


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, index=True)
    port_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    __table_args__ = (
        CheckConstraint(
            "(port_number IS NULL) OR (port_number BETWEEN 0 AND 65535)",
            name="ck_port_range",
        ),
    )
    _NAME_TO_ATTR = {
        "id": "id",
        "ip": "IP",
        "port_number": "port_number",
        "user_id": "user_id",
    }

    def set_session(
        self,
        *,
        ip: Optional[str],
        port_number: Optional[int],
        user_id: int,
    ) -> Message:
        if ip is not None:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return Message(
                    type=db_msg_type.ERROR,
                    status=db_msg_status.INVALID_INPUT,
                    payload=f"Invalid IP address: {ip!r}",
                )

        if port_number is not None and not (0 <= port_number <= 65535):
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"Invalid port number: {port_number}",
            )
        self.ip = ip
        self.port_number = port_number
        self.user_id = user_id
        return Message(type=db_msg_type.SESSION_CREATED, status=db_msg_status.OK)
