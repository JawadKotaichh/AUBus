from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import composite
from dataclasses import dataclass
from sqlalchemy import CheckConstraint
from models import Base
from models import Message, db_msg_type, db_msg_status


@dataclass(frozen=True)
class ScheduleDay:
    departure_time: Optional[datetime]
    return_time: Optional[datetime]

    def __composite_values__(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        return (self.departure_time, self.return_time)

    def __bool__(self) -> bool:
        """True if day has both times set."""
        return self.departure_time is not None and self.return_time is not None


def day_check(dep_col: str, ret_col: str) -> str:
    return (
        f"(({dep_col} IS NULL AND {ret_col} IS NULL) OR "
        f"({dep_col} IS NOT NULL AND {ret_col} IS NOT NULL AND {ret_col} > {dep_col}))"
    )


class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[int] = mapped_column(primary_key=True)

    Monday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Monday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Monday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Monday_departure_time, Monday_return_time
    )
    Tuesday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Tuesday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Tuesday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Tuesday_departure_time, Tuesday_return_time
    )
    Wednesday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Wednesday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Wednesday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Wednesday_departure_time, Wednesday_return_time
    )
    Thursday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Thursday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Thursday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Thursday_departure_time, Thursday_return_time
    )
    Friday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Friday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Friday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Friday_departure_time, Friday_return_time
    )
    Saturday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Saturday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Saturday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Saturday_departure_time, Saturday_return_time
    )
    Sunday_departure_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Sunday_return_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    Sunday: Mapped[ScheduleDay] = composite(
        ScheduleDay, Sunday_departure_time, Sunday_return_time
    )

    __table_args__ = (
        CheckConstraint(
            day_check("Monday_departure_time", "Monday_return_time"), name="ck_monday"
        ),
        CheckConstraint(
            day_check("Tuesday_departure_time", "Tuesday_return_time"),
            name="ck_tuesday",
        ),
        CheckConstraint(
            day_check("Wednesday_departure_time", "Wednesday_return_time"),
            name="ck_wednesday",
        ),
        CheckConstraint(
            day_check("Thursday_departure_time", "Thursday_return_time"),
            name="ck_thursday",
        ),
        CheckConstraint(
            day_check("Friday_departure_time", "Friday_return_time"), name="ck_friday"
        ),
        CheckConstraint(
            day_check("Saturday_departure_time", "Saturday_return_time"),
            name="ck_saturday",
        ),
        CheckConstraint(
            day_check("Sunday_departure_time", "Sunday_return_time"), name="ck_sunday"
        ),
    )
    _NAME_TO_ATTR = {
        "monday": "Monday",
        "tuesday": "Tuesday",
        "wednesday": "Wednesday",
        "thursday": "Thursday",
        "friday": "Friday",
        "saturday": "Saturday",
        "sunday": "Sunday",
    }

    def set_day(
        self,
        day_name: str,
        departure_time: Optional[datetime],
        return_time: Optional[datetime],
    ) -> Message:
        key = day_name.strip().lower()
        attr = self._NAME_TO_ATTR.get(key)
        if not attr:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"Invalid day name: {day_name!r}",
            )
        setattr(self, attr, ScheduleDay(departure_time, return_time))
        return Message(type=db_msg_type.SCHEDULE_CREATED, status=db_msg_status.OK)

    def get_day(self, day_name: str) -> Optional[ScheduleDay]:
        key = day_name.strip().lower()
        attr = self._NAME_TO_ATTR.get(key)
        return getattr(self, attr) if attr else None

    def clear_day(self, day_name: str) -> Message:
        return self.set_day(day_name, None, None)
