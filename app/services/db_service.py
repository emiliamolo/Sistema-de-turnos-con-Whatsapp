"""
Database access layer for the single-tenant booking system.

This module is the SINGLE point of SQLAlchemy access to PostgreSQL.
No API route should import domain models or use `db.query()` directly.
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract, and_
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from typing import Optional, List, Tuple

from ..models import domain


# =============================================================================
# ROOMS
# =============================================================================

def get_rooms(db: Session):
    return db.query(domain.Room).all()


def get_room(db: Session, room_id: str):
    return db.query(domain.Room).filter(domain.Room.id == room_id).first()


def get_room_by_name(db: Session, name: str):
    return db.query(domain.Room).filter_by(name=name).first()


def count_rooms(db: Session):
    return db.query(domain.Room).count()


def create_room(db: Session, name: str, description: str = None, capacity: int = 1) -> domain.Room:
    room = domain.Room(name=name, description=description, capacity=capacity)
    db.add(room)
    db.commit()
    db.expire_all()
    return room


def update_room(db: Session, room: domain.Room, name: str, description: str, capacity: int):
    room.name = name
    room.description = description
    room.capacity = capacity
    db.commit()


def delete_room(db: Session, room: domain.Room):
    db.delete(room)
    db.commit()


# =============================================================================
# SERVICES
# =============================================================================

def get_services(db: Session, with_rooms: bool = False):
    opts = [joinedload(domain.Service.rooms)] if with_rooms else []
    q = db.query(domain.Service)
    if opts:
        q = q.options(*opts)
    return q.all()


def get_service(db: Session, service_id: str, with_rooms: bool = False):
    opts = [joinedload(domain.Service.rooms)] if with_rooms else []
    q = db.query(domain.Service).filter(domain.Service.id == service_id)
    if opts:
        q = q.options(*opts)
    return q.first()


def get_active_services(db: Session):
    return db.query(domain.Service).filter_by(active=True).all()


def get_service_by_name(db: Session, name: str):
    return db.query(domain.Service).filter_by(name=name).first()


def count_services(db: Session):
    return db.query(func.count(domain.Service.id)).scalar()


def create_service(db: Session, name: str, description: str = None,
                   duration_minutes: int = 30, price: float = 0,
                   commission_type: Optional[str] = None,
                   commission_value: Optional[float] = None,
                   room_ids: Optional[List[str]] = None) -> domain.Service:
    s = domain.Service(
        name=name,
        description=description,
        duration_minutes=duration_minutes,
        price=price,
        commission_type=commission_type or None,
        commission_value=commission_value or None,
    )
    db.add(s)
    db.flush()
    if room_ids:
        rooms = db.query(domain.Room).filter(domain.Room.id.in_(room_ids)).all()
        s.rooms = rooms
    db.commit()
    db.expire_all()
    return s


def update_service(db: Session, service: domain.Service, name: str, description: str,
                   duration_minutes: int, price: float,
                   commission_type: Optional[str], commission_value: Optional[float],
                   room_ids: Optional[List[str]]):
    service.name = name
    service.description = description
    service.duration_minutes = duration_minutes
    service.price = price
    service.commission_type = commission_type or None
    service.commission_value = commission_value or None
    if room_ids:
        rooms = db.query(domain.Room).filter(domain.Room.id.in_(room_ids)).all()
        service.rooms = rooms
    elif room_ids is not None:
        service.rooms = []
    db.commit()


def delete_service(db: Session, service: domain.Service):
    db.delete(service)
    db.commit()


def room_in_service(db: Session, service_id: str, room_id: str) -> bool:
    return db.query(domain.service_rooms).filter_by(
        service_id=service_id, room_id=room_id,
    ).first() is not None


def count_bookings(db: Session):
    return db.query(func.count(domain.Booking.id)).scalar()


# =============================================================================
# STAFF
# =============================================================================

def get_staff_list(db: Session):
    q = db.query(domain.Staff).options(joinedload(domain.Staff.user))
    return q.all()


def get_staff(db: Session, staff_id: str):
    q = db.query(domain.Staff).options(joinedload(domain.Staff.user)).filter(domain.Staff.id == staff_id)
    return q.first()


def get_staff_by_user_id(db: Session, user_id: str):
    return db.query(domain.Staff).filter_by(user_id=user_id).first()


def get_staff_by_name(db: Session, name: str):
    return db.query(domain.Staff).filter_by(name=name).first()


def count_staff(db: Session):
    return db.query(domain.Staff).count()


def create_staff(db: Session, name: str, specialty: str = None) -> domain.Staff:
    s = domain.Staff(name=name, specialty=specialty)
    db.add(s)
    db.flush()
    return s


def update_staff_user_id(db: Session, staff: domain.Staff, user_id: str):
    staff.user_id = user_id
    db.flush()


def update_staff_basic(db: Session, staff: domain.Staff, name: str, specialty: str, active: bool):
    staff.name = name
    staff.specialty = specialty
    staff.active = active
    db.commit()


def delete_staff(db: Session, staff: domain.Staff):
    db.delete(staff)
    db.commit()


def finish_staff_creation(db: Session):
    db.commit()
    db.expire_all()


# =============================================================================
# STAFF AVAILABILITIES
# =============================================================================

def get_staff_availabilities(db: Session, staff_id: str):
    return db.query(domain.StaffAvailability).filter_by(staff_id=staff_id).order_by(
        domain.StaffAvailability.day_of_week,
        domain.StaffAvailability.start_time,
    ).all()


def get_staff_availability_filtered(db: Session, staff_id: str, day_of_week: int,
                                    start_time: time, end_time: time):
    return db.query(domain.StaffAvailability).filter(
        domain.StaffAvailability.staff_id == staff_id,
        domain.StaffAvailability.day_of_week == day_of_week,
        domain.StaffAvailability.start_time <= start_time,
        domain.StaffAvailability.end_time >= end_time,
    ).first()


def delete_staff_availabilities(db: Session, staff_id: str):
    db.query(domain.StaffAvailability).filter_by(staff_id=staff_id).delete()


def add_staff_availability(db: Session, staff_id: str, day: int, start_t: time, end_t: time):
    db.add(domain.StaffAvailability(staff_id=staff_id, day_of_week=day, start_time=start_t, end_time=end_t))


# =============================================================================
# STAFF EXCEPTIONS
# =============================================================================

def get_staff_exceptions(db: Session, staff_id: str):
    return db.query(domain.StaffException).filter_by(staff_id=staff_id).order_by(
        domain.StaffException.exception_date.desc(),
    ).all()


def get_staff_exception_by_date(db: Session, staff_id: str, exception_date: date):
    return db.query(domain.StaffException).filter_by(
        staff_id=staff_id, exception_date=exception_date,
    ).first()


def get_staff_exception(db: Session, exception_id: str, staff_id: str):
    return db.query(domain.StaffException).filter_by(id=exception_id, staff_id=staff_id).first()


def create_staff_exception(db: Session, staff_id: str, exception_date: date, reason: str = ""):
    exc = domain.StaffException(staff_id=staff_id, exception_date=exception_date, reason=reason)
    db.add(exc)
    db.commit()


def delete_staff_exception(db: Session, exc: domain.StaffException):
    db.delete(exc)
    db.commit()


# =============================================================================
# STAFF SERVICES (association)
# =============================================================================

def staff_offers_service(db: Session, staff_id: str, service_id: str) -> bool:
    return db.query(domain.staff_services).filter_by(
        staff_id=staff_id, service_id=service_id,
    ).first() is not None


def toggle_staff_service(db: Session, staff: domain.Staff, service: domain.Service):
    if service in staff.services_offered:
        staff.services_offered.remove(service)
    else:
        staff.services_offered.append(service)
    db.commit()


# =============================================================================
# CUSTOMERS
# =============================================================================

def get_customers(db: Session):
    q = db.query(domain.Customer).order_by(domain.Customer.created_at.desc())
    return q.all()


def get_customers_sorted_by_name(db: Session):
    q = db.query(domain.Customer).order_by(domain.Customer.full_name)
    return q.all()


def get_customer(db: Session, customer_id: str):
    return db.query(domain.Customer).filter(domain.Customer.id == customer_id).first()


def get_customer_by_phone(db: Session, phone_number: str):
    return db.query(domain.Customer).filter_by(phone_number=phone_number).first()


def create_customer(db: Session, phone_number: str,
                    full_name: str = None, email: str = None) -> domain.Customer:
    c = domain.Customer(phone_number=phone_number, full_name=full_name, email=email)
    db.add(c)
    db.commit()
    db.expire_all()
    return c


def delete_customer(db: Session, customer: domain.Customer):
    db.delete(customer)
    db.commit()


# =============================================================================
# BOOKINGS
# =============================================================================

def get_bookings(db: Session):
    return db.query(domain.Booking).order_by(domain.Booking.start_time.asc()).all()


def get_booking(db: Session, booking_id: str):
    return db.query(domain.Booking).filter(domain.Booking.id == booking_id).first()


def get_today_bookings(db: Session):
    now_utc = datetime.now(timezone.utc)
    today_start = datetime.combine(now_utc.date(), time.min, tzinfo=timezone.utc)
    today_end = datetime.combine(now_utc.date(), time.max, tzinfo=timezone.utc)
    q = db.query(domain.Booking).filter(
        domain.Booking.start_time >= today_start,
        domain.Booking.start_time <= today_end,
    )
    return q.order_by(domain.Booking.start_time.asc()).all()


def query_bookings(db: Session,
                   date_filter: Optional[date] = None, service_id: Optional[str] = None,
                   room_id: Optional[str] = None, staff_id: Optional[str] = None):
    q = db.query(domain.Booking)
    if date_filter:
        q = q.filter(func.date(domain.Booking.start_time) == date_filter)
    if service_id:
        q = q.filter(domain.Booking.service_id == service_id)
    if room_id:
        q = q.filter(domain.Booking.room_id == room_id)
    if staff_id:
        q = q.filter(domain.Booking.staff_id == staff_id)
    return q.order_by(domain.Booking.start_time.asc()).all()


def get_calendar_bookings(db: Session, start_dt: datetime, end_dt: datetime,
                          service_id: Optional[str] = None,
                          room_id: Optional[str] = None,
                          staff_id: Optional[str] = None):
    q = db.query(domain.Booking).filter(
        domain.Booking.start_time >= start_dt,
        domain.Booking.start_time <= end_dt,
    )
    if service_id:
        q = q.filter(domain.Booking.service_id == service_id)
    if room_id:
        q = q.filter(domain.Booking.room_id == room_id)
    if staff_id:
        q = q.filter(domain.Booking.staff_id == staff_id)
    return q.all()


def get_available_days(
    db: Session,
    start_date: date,
    end_date: date,
    service_id: Optional[str] = None,
    room_id: Optional[str] = None,
    staff_id: Optional[str] = None,
) -> list:
    available = []
    if room_id:
        candidate_rooms = [room_id]
    elif service_id:
        srv = get_service(db, service_id, with_rooms=True)
        candidate_rooms = [str(r.id) for r in (srv.rooms if srv else [])]
    else:
        rooms = get_rooms(db)
        candidate_rooms = [str(r.id) for r in rooms]
    if not candidate_rooms:
        return []

    current_date = start_date
    while current_date <= end_date:
        day_start = datetime.combine(current_date, time(9, 0))
        day_end = datetime.combine(current_date, time(18, 0))
        cursor = day_start
        day_has_slot = False
        while cursor + timedelta(minutes=30) <= day_end:
            slot_end = cursor + timedelta(minutes=30)
            for rid in candidate_rooms:
                conflicts = check_booking_conflicts(db, cursor, slot_end, room_id=rid, staff_id=staff_id)
                if not conflicts:
                    day_has_slot = True
                    break
            if day_has_slot:
                break
            cursor += timedelta(minutes=30)
        if day_has_slot:
            available.append(current_date)
        current_date += timedelta(days=1)
    return available


def get_professional_bookings(db: Session, staff_id: str,
                              start_dt: datetime, end_dt: datetime):
    return db.query(domain.Booking).filter(
        domain.Booking.staff_id == staff_id,
        domain.Booking.start_time >= start_dt,
        domain.Booking.start_time <= end_dt,
    ).all()


def get_bookings_by_staff(db: Session, staff_id: str):
    return db.query(domain.Booking).filter_by(staff_id=staff_id).all()


def get_staff_bookings_for_period(db: Session, staff_id: str, period_start: datetime, period_end: datetime):
    return db.query(domain.Booking).filter(
        domain.Booking.staff_id == staff_id,
        domain.Booking.start_time >= period_start,
        domain.Booking.start_time <= period_end,
        domain.Booking.status.in_(["confirmed", "completed"]),
    ).order_by(domain.Booking.start_time).all()


def get_bookings_by_customer(db: Session, customer_id: str):
    return db.query(domain.Booking).filter_by(customer_id=customer_id).all()


def get_staff_bookings_month(db: Session, staff_id: str, year: int, month: int):
    return db.query(domain.Booking).filter(
        domain.Booking.staff_id == staff_id,
        extract('year', domain.Booking.start_time) == year,
        extract('month', domain.Booking.start_time) == month,
    ).order_by(domain.Booking.start_time.asc()).all()


def get_monthly_bookings_count(db: Session):
    first_of_month = date.today().replace(day=1)
    return db.query(func.count(domain.Booking.id)).filter(
        func.date(domain.Booking.created_at) >= first_of_month,
    ).scalar()


def create_booking(db: Session, service_id: str,
                   start_time: datetime, end_time: datetime,
                   customer_id: Optional[str] = None, room_id: Optional[str] = None,
                   staff_id: Optional[str] = None, status: str = "confirmed") -> domain.Booking:
    b = domain.Booking(
        customer_id=customer_id,
        service_id=service_id,
        room_id=room_id,
        staff_id=staff_id,
        start_time=start_time,
        end_time=end_time,
        status=status,
    )
    db.add(b)
    db.commit()
    db.expire_all()
    return b


def update_booking_fields(db: Session, booking: domain.Booking, **kwargs):
    for k, v in kwargs.items():
        if hasattr(booking, k):
            setattr(booking, k, v)
    db.commit()
    db.expire_all()


def update_booking_times(db: Session, booking: domain.Booking, start_time: datetime, end_time: datetime):
    booking.start_time = start_time
    booking.end_time = end_time
    db.commit()


def cancel_booking(db: Session, booking: domain.Booking):
    booking.status = "cancelled"
    db.commit()


def delete_booking(db: Session, booking: domain.Booking):
    db.delete(booking)
    db.commit()


# =============================================================================
# BOOKING CONFLICTS & AVAILABILITY
# =============================================================================

def check_booking_conflicts(
    db: Session,
    start_time: datetime,
    end_time: datetime,
    room_id: Optional[str] = None,
    staff_id: Optional[str] = None,
    exclude_booking_id: Optional[str] = None,
    for_update: bool = True,
) -> list:
    conflicts = []
    if room_id:
        q = db.query(domain.Booking).filter(
            domain.Booking.room_id == room_id,
            domain.Booking.start_time < end_time,
            domain.Booking.end_time > start_time,
            domain.Booking.status.in_(["pending", "confirmed"]),
        )
        if exclude_booking_id:
            q = q.filter(domain.Booking.id != exclude_booking_id)
        if for_update:
            q = q.with_for_update()
        if q.first():
            conflicts.append("la sala ya está ocupada en ese horario")
    if staff_id:
        q = db.query(domain.Booking).filter(
            domain.Booking.staff_id == staff_id,
            domain.Booking.start_time < end_time,
            domain.Booking.end_time > start_time,
            domain.Booking.status.in_(["pending", "confirmed"]),
        )
        if exclude_booking_id:
            q = q.filter(domain.Booking.id != exclude_booking_id)
        if for_update:
            q = q.with_for_update()
        if q.first():
            conflicts.append("el profesional ya tiene un turno en ese horario")
    return conflicts


def check_staff_availability(
    db: Session,
    staff_id: str,
    start_time: datetime,
    end_time: datetime,
) -> Optional[str]:
    start_date = start_time.date()
    exc = get_staff_exception_by_date(db, staff_id, start_date)
    if exc:
        return f"El día {start_date} es no laborable para el profesional: {exc.reason or 'sin motivo registrado'}."
    end_date = end_time.date()
    if end_date != start_date:
        exc2 = get_staff_exception_by_date(db, staff_id, end_date)
        if exc2:
            return f"El día {end_date} es no laborable para el profesional: {exc2.reason or 'sin motivo registrado'}."
    weekday = start_time.weekday()
    start_t = start_time.time()
    end_t = end_time.time()
    has_availability = get_staff_availability_filtered(db, staff_id, weekday, start_t, end_t)
    if not has_availability:
        avail_any = db.query(domain.StaffAvailability).filter_by(staff_id=staff_id).first()
        if avail_any:
            return "El profesional no tiene disponibilidad configurada para ese día y horario."
        return None
    return None


def check_staff_availability_simple(
    db: Session,
    staff_id: str,
    start_time: datetime,
    end_time: datetime,
) -> Optional[str]:
    start_date = start_time.date()
    exc = get_staff_exception_by_date(db, staff_id, start_date)
    if exc:
        return f"El día {start_date} es no laborable: {exc.reason or 'sin motivo registrado'}"
    end_date = end_time.date()
    if end_date != start_date:
        exc2 = get_staff_exception_by_date(db, staff_id, end_date)
        if exc2:
            return f"El día {end_date} es no laborable: {exc2.reason or 'sin motivo registrado'}"
    weekday = start_time.weekday()
    avail = get_staff_availability_filtered(db, staff_id, weekday, start_time.time(), end_time.time())
    if not avail:
        return "No tenés disponibilidad configurada para el día y horario seleccionados."
    return None


def check_professional_booking_conflict(
    db: Session,
    staff_id: str,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: str,
):
    return db.query(domain.Booking).filter(
        domain.Booking.staff_id == staff_id,
        domain.Booking.id != exclude_booking_id,
        domain.Booking.start_time < end_time,
        domain.Booking.end_time > start_time,
        domain.Booking.status.in_(["pending", "confirmed"]),
    ).with_for_update().first()


# =============================================================================
# PAYMENTS
# =============================================================================

def get_payments(db: Session,
                 customer_id: Optional[str] = None, status: Optional[str] = None,
                 date_from: Optional[datetime] = None, date_to: Optional[datetime] = None):
    q = db.query(domain.Payment)
    if customer_id:
        q = q.filter(domain.Payment.customer_id == customer_id)
    if status:
        q = q.filter(domain.Payment.status == status)
    if date_from:
        q = q.filter(domain.Payment.created_at >= date_from)
    if date_to:
        q = q.filter(domain.Payment.created_at <= date_to)
    return q.order_by(domain.Payment.created_at.desc()).all()


def get_payment(db: Session, payment_id: str):
    return db.query(domain.Payment).filter(domain.Payment.id == payment_id).first()


def get_payment_by_booking(db: Session, booking_id: str):
    return db.query(domain.Payment).filter_by(booking_id=booking_id).first()


def get_payments_by_customer(db: Session, customer_id: str):
    return db.query(domain.Payment).filter_by(customer_id=customer_id).order_by(domain.Payment.created_at.desc()).all()


def get_staff_payments(db: Session, staff_id: str,
                       status: Optional[str] = None,
                       date_from: Optional[datetime] = None,
                       date_to: Optional[datetime] = None):
    q = db.query(domain.Payment).join(
        domain.Booking, domain.Payment.booking_id == domain.Booking.id,
    ).filter(
        domain.Booking.staff_id == staff_id,
    )
    if status:
        q = q.filter(domain.Payment.status == status)
    if date_from:
        q = q.filter(domain.Payment.created_at >= date_from)
    if date_to:
        q = q.filter(domain.Payment.created_at <= date_to)
    return q.order_by(domain.Payment.created_at.desc()).all()


def create_payment(db: Session, amount: Decimal,
                   booking_id: Optional[str] = None, customer_id: Optional[str] = None,
                   payment_method: str = "cash", status: str = "paid",
                   notes: Optional[str] = None) -> domain.Payment:
    p = domain.Payment(
        booking_id=booking_id,
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        status=status,
        notes=notes,
    )
    db.add(p)
    db.commit()
    db.expire_all()
    return p


def update_payment_fields(db: Session, payment: domain.Payment, **kwargs):
    for k, v in kwargs.items():
        if hasattr(payment, k):
            setattr(payment, k, v)
    db.commit()


def delete_payment(db: Session, payment: domain.Payment):
    db.delete(payment)
    db.commit()


# =============================================================================
# STAFF SETTLEMENTS
# =============================================================================

def get_staff_settlements(db: Session, staff_id: str):
    return db.query(domain.StaffSettlement).filter_by(staff_id=staff_id).order_by(
        domain.StaffSettlement.created_at.desc(),
    ).all()


def get_settlement(db: Session, settlement_id: str, staff_id: str):
    return db.query(domain.StaffSettlement).filter_by(id=settlement_id, staff_id=staff_id).first()


def create_settlement_head(db: Session, staff_id: str,
                           period_start: date, period_end: date, total_services: int) -> domain.StaffSettlement:
    s = domain.StaffSettlement(
        staff_id=staff_id,
        period_start=period_start, period_end=period_end,
        total_services=total_services,
    )
    db.add(s)
    db.flush()
    return s


def add_settlement_item(db: Session, settlement_id: str, booking_id: str,
                        service_name: str, service_price: Decimal,
                        commission_type: Optional[str], commission_value: Optional[Decimal],
                        commission_amount: Decimal, booking_date: date):
    item = domain.StaffSettlementItem(
        settlement_id=settlement_id,
        booking_id=booking_id,
        service_name=service_name,
        service_price=service_price,
        commission_type=commission_type,
        commission_value=commission_value,
        commission_amount=commission_amount,
        booking_date=booking_date,
    )
    db.add(item)
    return item


def finalize_settlement(db: Session, settlement: domain.StaffSettlement,
                        total_amount: Decimal, total_commission: Decimal):
    settlement.total_amount = total_amount
    settlement.total_commission = total_commission
    db.commit()


def mark_settlement_paid(db: Session, settlement: domain.StaffSettlement):
    settlement.status = "paid"
    settlement.paid_at = datetime.now(timezone.utc)
    db.commit()


# =============================================================================
# USERS
# =============================================================================

def get_user_by_email(db: Session, email: str):
    return db.query(domain.User).filter_by(email=email).first()


def get_user(db: Session, user_id: str):
    return db.query(domain.User).filter_by(id=user_id).first()


def get_user_by_id_and_role(db: Session, user_id: str, role: str):
    return db.query(domain.User).filter_by(id=user_id, role=role).first()


def create_user(db: Session, **kwargs) -> domain.User:
    u = domain.User(**kwargs)
    db.add(u)
    db.flush()
    return u
