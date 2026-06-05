from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, DECIMAL, Text, Date, Time, UniqueConstraint, Table
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from ..core.database import Base

service_rooms = Table(
    "service_rooms",
    Base.metadata,
    Column("service_id", UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    Column("room_id", UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
)

staff_services = Table(
    "staff_services",
    Base.metadata,
    Column("staff_id", UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), default="admin")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    staff_member = relationship("Staff", back_populates="user", uselist=False)

class Room(Base):
    __tablename__ = "rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    capacity = Column(Integer, default=1)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    bookings = relationship("Booking", back_populates="room")
    services = relationship("Service", secondary=service_rooms, back_populates="rooms")

class StaffAvailability(Base):
    __tablename__ = "staff_availabilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_id = Column(UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    staff = relationship("Staff", back_populates="availabilities")


class StaffException(Base):
    __tablename__ = "staff_exceptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_id = Column(UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    exception_date = Column(Date, nullable=False)
    reason = Column(String(200))

    staff = relationship("Staff", back_populates="exceptions")


class Staff(Base):
    __tablename__ = "staff"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    name = Column(String(100), nullable=False)
    specialty = Column(String(100))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="staff_member")
    bookings = relationship("Booking", back_populates="staff_member")
    settlements = relationship("StaffSettlement", back_populates="staff")
    services_offered = relationship("Service", secondary=staff_services, back_populates="staff_members")
    availabilities = relationship("StaffAvailability", back_populates="staff", cascade="all, delete-orphan")
    exceptions = relationship("StaffException", back_populates="staff", cascade="all, delete-orphan")
    commission_rate = Column(DECIMAL(5, 2))

class Service(Base):
    __tablename__ = "services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    duration_minutes = Column(Integer, default=30)
    price = Column(DECIMAL(10, 2))
    active = Column(Boolean, default=True)
    commission_type = Column(String(20))
    commission_value = Column(DECIMAL(10, 2))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    bookings = relationship("Booking", back_populates="service")
    rooms = relationship("Room", secondary=service_rooms, back_populates="services")
    staff_members = relationship("Staff", secondary=staff_services, back_populates="services_offered")

class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint('phone_number', name='idx_customers_phone'),
        UniqueConstraint('email', name='idx_customers_email'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(20), nullable=False)
    email = Column(String(100))
    hashed_password = Column(Text)
    full_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    bookings = relationship("Booking", back_populates="customer")
    payments = relationship("Payment", back_populates="customer", cascade="all, delete-orphan")

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"))
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"))
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"))
    staff_id = Column(UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"))
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), default="pending")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    customer = relationship("Customer", back_populates="bookings")
    service = relationship("Service", back_populates="bookings")
    room = relationship("Room", back_populates="bookings")
    staff_member = relationship("Staff", back_populates="bookings")
    payments = relationship("Payment", back_populates="booking", cascade="all, delete-orphan")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL"))
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"))
    amount = Column(DECIMAL(10, 2), nullable=False)
    payment_method = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    transaction_id = Column(String(100))
    notes = Column(Text)
    external_reference = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    booking = relationship("Booking", back_populates="payments")
    customer = relationship("Customer", back_populates="payments")

class StaffSettlement(Base):
    __tablename__ = "staff_settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_id = Column(UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"))
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    total_services = Column(Integer, default=0)
    total_amount = Column(DECIMAL(10, 2), default=0)
    total_commission = Column(DECIMAL(10, 2), default=0)
    status = Column(String(20), default="pending")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True))

    staff = relationship("Staff", back_populates="settlements")
    items = relationship("StaffSettlementItem", back_populates="settlement", cascade="all, delete-orphan")


class StaffSettlementItem(Base):
    __tablename__ = "staff_settlement_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_id = Column(UUID(as_uuid=True), ForeignKey("staff_settlements.id", ondelete="CASCADE"))
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL"))
    service_name = Column(String(100), nullable=False)
    service_price = Column(DECIMAL(10, 2), nullable=False)
    commission_type = Column(String(20))
    commission_value = Column(DECIMAL(10, 2))
    commission_amount = Column(DECIMAL(10, 2), default=0)
    booking_date = Column(Date)

    settlement = relationship("StaffSettlement", back_populates="items")
    booking = relationship("Booking")
