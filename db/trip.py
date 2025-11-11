from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Enum, text
from models import Base
from models import Message, db_msg_status, db_msg_type
import enum


class Status(enum.Enum):
    PENDING = 1
    CANCELED = 2
    COMPLETE = 3


class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rider_session_id: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )

    driver_session_id: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )
    status: Mapped[Status] = mapped_column(
        Enum(Status), nullable=False, default=Status.PENDING
    )
    comment: Mapped[str] = mapped_column(String, nullable=False, default="")
    __table_args__ = ()
    _NAME_TO_ATTR = {
        "id": "id",
        "rider_session_id": "rider_session_id",
        "driver_session_id": "driver_session_id",
        "status": "status",
        "comment": "comment",
    }

    def set_trip(
        self,
        *,
        rider_session_id: Optional[str],
        driver_session_id: Optional[str],
        status,
        comment: str = "",
        session=None,
    ) -> Message:
        if isinstance(status, str):
            try:
                status = Status[status]
            except KeyError:
                return Message(
                    type=db_msg_type.ERROR,
                    status=db_msg_status.INVALID_INPUT,
                    payload=f"Invalid status string: {status!r}",
                )

        if not isinstance(status, Status):
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload="Status must be a Trip Status enum (PENDING, COMPLETE,CANCELED)",
            )

        if session is not None:
            if rider_session_id:
                res = session.execute(
                    text("SELECT id FROM sessions WHERE id = :sid"),
                    {"sid": rider_session_id},
                )
                if res.scalar_one_or_none() is None:
                    return Message(
                        type=db_msg_type.ERROR,
                        status=db_msg_status.NOT_FOUND,
                        payload=f"Rider session id not found: {rider_session_id!r}",
                    )

            if driver_session_id:
                res = session.execute(
                    text("SELECT id FROM sessions WHERE id = :sid"),
                    {"sid": driver_session_id},
                )
                if res.scalar_one_or_none() is None:
                    return Message(
                        type=db_msg_type.ERROR,
                        status=db_msg_status.NOT_FOUND,
                        payload=f"Driver session id not found: {driver_session_id!r}",
                    )

        self.rider_session_id = rider_session_id
        self.driver_session_id = driver_session_id
        self.status = status
        self.comment = comment or ""

        return Message(
            type=db_msg_type.TRIP_CREATED,
            status=db_msg_status.OK,
            payload=f"Trip created successfully with status {self.status.name}",
        )
