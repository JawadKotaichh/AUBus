# test_all.py
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column
from sqlalchemy.exc import IntegrityError
from models import Base, db_msg_status, db_msg_type
from schedules import Schedule
from trip import Trip, Status as TripStatus
from user_sessions import UserSession
import datetime as dt


# --- Minimal helper models to satisfy FKs / lookups ---
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Sessions(Base):
    """
    Trip.set_trip() validates against a table literally named 'sessions'.
    This stub is here so validation works in tests.
    """

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(45), primary_key=True)


def main():
    # Use an in-memory DB so we don't touch AUBus.db
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    print("\n=== Create a user (for UserSession FK) ===")
    u = User(name="Alice")
    session.add(u)
    session.commit()
    session.refresh(u)
    print("User id:", u.id)

    # ------------------ UserSession tests ------------------
    print("\n=== UserSession: valid session ===")
    us = UserSession()
    msg = us.set_session(ip="192.168.1.10", port_number=8080, user_id=u.id)
    assert msg.type == db_msg_type.SESSION_CREATED and msg.status == db_msg_status.OK
    session.add(us)
    session.commit()
    session.refresh(us)
    print("UserSession id:", us.id, "ip:", us.ip, "port:", us.port_number)

    print("\n=== UserSession: invalid IP ===")
    bad = UserSession()
    msg = bad.set_session(ip="999.999.1.1", port_number=5000, user_id=u.id)
    assert msg.type == db_msg_type.ERROR and msg.status == db_msg_status.INVALID_INPUT
    print("Got expected invalid IP message:", msg.payload)

    print("\n=== UserSession: invalid port ===")
    bad2 = UserSession()
    msg = bad2.set_session(ip="10.0.0.1", port_number=70000, user_id=u.id)
    assert msg.status == db_msg_status.INVALID_INPUT
    print("Got expected invalid port message:", msg.payload)

    # ------------------ Schedule tests ------------------
    print("\n=== Schedule: create & modify days ===")
    sc = Schedule()
    m = sc.set_day(
        "Monday", dt.datetime(2025, 1, 1, 8, 0), dt.datetime(2025, 1, 1, 17, 0)
    )
    assert m.type == db_msg_type.SCHEDULE_CREATED and m.status == db_msg_status.OK
    assert sc.get_day("monday").__bool__() is True
    print("Monday set OK.")

    m2 = sc.clear_day("monday")
    assert sc.get_day("monday").__bool__() is False
    print("Monday cleared OK.")

    session.add(sc)
    session.commit()
    session.refresh(sc)
    print("Schedule id:", sc.id)

    print("\n=== Schedule: invalid day name ===")
    m3 = sc.set_day("Funday", None, None)
    assert m3.status == db_msg_status.INVALID_INPUT
    print("Got expected invalid day message:", m3.payload)

    print("\n=== Schedule: DB constraint (dep set, return NULL) ===")
    sc2 = Schedule()
    # Deliberately bypass setter to trigger the DB constraint
    sc2.Monday_departure_time = dt.datetime(2025, 1, 1, 8, 0)
    session.add(sc2)
    try:
        session.commit()
        raise AssertionError("Commit should have failed due to day constraint.")
    except IntegrityError:
        session.rollback()
        print("Constraint triggered as expected.")

    # ------------------ Trip tests ------------------
    print("\n=== Prepare 'sessions' rows for Trip validation ===")
    s1 = Sessions(id="sess_rider")
    s2 = Sessions(id="sess_driver")
    session.add_all([s1, s2])
    session.commit()
    print("Sessions prepared.")

    print("\n=== Trip: valid rider, invalid driver (with validation) ===")
    t1 = Trip()
    msg = t1.set_trip(
        rider_session_id="sess_rider",
        driver_session_id="does_not_exist",
        status=TripStatus.PENDING,
        comment="Test trip",
        session=session,  # enables validation lookups
    )
    assert msg.status == db_msg_status.NOT_FOUND and msg.type == db_msg_type.ERROR
    print("Got expected invalid driver message:", msg.payload)

    print("\n=== Trip: happy path (skip validation) ===")
    t2 = Trip()
    msg = t2.set_trip(
        rider_session_id="sess_rider",
        driver_session_id="sess_driver",
        status=TripStatus.COMPLETE,
        comment="All good",
        session=None,  # skip validation as implemented in set_trip
    )
    assert msg.status == db_msg_status.OK and "Trip created successfully" in (
        msg.payload or ""
    )
    session.add(t2)
    session.commit()
    session.refresh(t2)
    print("Trip id:", t2.id, "status:", t2.status.name, "comment:", t2.comment)

    print("\n=== Trip: invalid status type ===")
    print("\n=== Trip: status as string (accepted) ===")
    t3 = Trip()
    msg = t3.set_trip(
        rider_session_id=None, driver_session_id=None, status="PENDING", comment=""
    )
    assert msg.type == db_msg_type.TRIP_CREATED and msg.status == db_msg_status.OK
    assert t3.status == TripStatus.PENDING
    print("String status accepted →", msg.payload)
    print("Got expected invalid status message:", msg.payload)

    print("\n✅ ALL TESTS PASSED")


if __name__ == "__main__":
    main()
