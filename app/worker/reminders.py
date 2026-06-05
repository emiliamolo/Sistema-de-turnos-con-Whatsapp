import json
import logging
from datetime import datetime, timedelta, date, timezone

from ..core.database import SessionLocal
from ..models import domain
from .sender import send_whatsapp_template
from .flow import STATE_EXPIRATION

logger = logging.getLogger("turnos_worker")


def check_and_send_reminders(redis_client):
    db = SessionLocal()
    try:
        tomorrow = date.today() + timedelta(days=1)
        tomorrow_start = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)
        tomorrow_end = tomorrow_start + timedelta(days=1)

        bookings = db.query(domain.Booking).filter(
            domain.Booking.status == "confirmed",
            domain.Booking.start_time >= tomorrow_start,
            domain.Booking.start_time < tomorrow_end,
        ).all()

        for booking in bookings:
            redis_key = f"reminder_sent:{booking.id}"
            if redis_client.exists(redis_key):
                continue

            customer = booking.customer
            if not customer:
                continue

            customer_name = customer.full_name or "cliente"
            fecha_dia = booking.start_time.strftime("%d/%m/%Y")
            fecha_hora = booking.start_time.strftime("%H:%M")
            info = f"{fecha_hora} hs"

            send_whatsapp_template(
                customer.phone_number,
                "recordatorio_turno_cliente",
                "es_AR",
                [customer_name, fecha_dia, info],
            )

            redis_state_key = f"flow_state:{customer.phone_number}"
            redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                "phase": "WAITING_REMINDER_ACTION",
                "reminder_booking_id": str(booking.id),
                "reminder_service_id": str(booking.service_id) if booking.service_id else None,
                "reminder_service_name": booking.service.name if booking.service else "tu turno",
            }))

            redis_client.setex(redis_key, 86400 * 2, "1")
            logger.info(f"Reminder sent for booking {booking.id} to {customer.phone_number}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error in check_and_send_reminders: {e}", exc_info=True)
    finally:
        db.close()
