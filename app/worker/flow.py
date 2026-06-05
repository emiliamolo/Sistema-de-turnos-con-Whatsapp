import json
import logging
from datetime import datetime, timedelta, date, time as time_type, timezone

from sqlalchemy.exc import IntegrityError

from ..core.database import SessionLocal
from ..models import domain
from ..core.config import settings
from ..services import db_service as dbs
from ..services.ai_classifier import get_classifier, ai_or_exact
from .sender import send_whatsapp_buttons

logger = logging.getLogger("turnos_worker")

STATE_EXPIRATION = 1800
WEEKS_TO_SCAN = 12
WEEKS_PER_PAGE = 3


def get_available_slots(db, service_id, target_date, staff_id=None, exclude_booking_id=None):
    service = dbs.get_service(db, service_id)
    if not service or not service.active:
        return []

    rooms = [r for r in service.rooms if r.active]
    if not rooms:
        return []

    duration = service.duration_minutes
    start_of_day = datetime.combine(target_date, time_type(9, 0))
    end_of_day = datetime.combine(target_date, time_type(18, 0))

    slots = []
    current = start_of_day
    while current + timedelta(minutes=duration) <= end_of_day:
        slot_end = current + timedelta(minutes=duration)
        for room in rooms:
            conflicts = dbs.check_booking_conflicts(
                db, current, slot_end,
                room_id=str(room.id),
                staff_id=str(staff_id) if staff_id else None,
                exclude_booking_id=exclude_booking_id,
            )
            if conflicts:
                continue
            if staff_id and dbs.check_staff_availability(db, str(staff_id), current, slot_end):
                continue
            slots.append({"time": current.isoformat(), "room_id": str(room.id)})
            break
        current += timedelta(minutes=duration)

    return slots


def _format_week_label(week_start):
    return f"Sem. {week_start.strftime('%d/%m')}"


def get_available_weeks(db, service_id, staff_id=None):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    weeks = []

    for w in range(WEEKS_TO_SCAN):
        week_start = monday + timedelta(weeks=w)
        slots = get_week_slots(db, service_id, week_start, "morning", staff_id=staff_id)
        afternoon_slots = get_week_slots(db, service_id, week_start, "afternoon", staff_id=staff_id)
        total = len(slots) + len(afternoon_slots)
        weeks.append({
            "iso": week_start.isoformat(),
            "label": _format_week_label(week_start),
            "has_slots": total > 0,
        })

    weeks.sort(key=lambda w: (not w["has_slots"], w["iso"]))
    return weeks


def _build_week_buttons(weeks, offset):
    remaining = len(weeks) - offset
    has_more = offset + WEEKS_PER_PAGE < len(weeks)
    has_prev = offset > 0

    nav_slots = (1 if has_more else 0) + (1 if has_prev else 0)
    available_for_weeks = min(WEEKS_PER_PAGE, 3 - nav_slots, remaining)

    page = weeks[offset:offset + available_for_weeks]
    buttons = [w["label"] for w in page]

    if has_prev:
        buttons.insert(0, "← Anteriores")
    if has_more:
        buttons.append("Más semanas →")

    return buttons, page


def get_week_slots(db, service_id, week_start, period, staff_id=None, exclude_booking_id=None):
    service = dbs.get_service(db, service_id)
    if not service or not service.active:
        return []

    rooms = [r for r in service.rooms if r.active]
    if not rooms:
        return []

    duration = service.duration_minutes

    if period == "morning":
        period_start_hour = 9
        period_end_hour = 13
    else:
        period_start_hour = 13
        period_end_hour = 18

    today = date.today()
    day_names = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

    slots = []
    for day_offset in range(6):
        target_date = week_start + timedelta(days=day_offset)
        if target_date <= today:
            continue

        start_of_day = datetime.combine(target_date, time_type(period_start_hour, 0))
        end_of_day = datetime.combine(target_date, time_type(period_end_hour, 0))

        current = start_of_day
        while current + timedelta(minutes=duration) <= end_of_day:
            slot_end = current + timedelta(minutes=duration)
            for room in rooms:
                conflicts = dbs.check_booking_conflicts(
                    db, current, slot_end,
                    room_id=str(room.id),
                    staff_id=str(staff_id) if staff_id else None,
                    exclude_booking_id=exclude_booking_id,
                )
                if conflicts:
                    continue
                if staff_id and dbs.check_staff_availability(db, str(staff_id), current, slot_end):
                    continue
                day_abbr = day_names[target_date.weekday()]
                display = f"{day_abbr} {target_date.strftime('%d/%m')} {current.strftime('%H:%M')}"
                slots.append({
                    "time": current.isoformat(),
                    "room_id": str(room.id),
                    "display": display,
                })
                break
            current += timedelta(minutes=duration)

    return slots


def _show_main_menu(customer_phone, redis_client, redis_state_key):
    send_whatsapp_buttons(customer_phone, "¿En qué más puedo ayudarte?",
                          ["Pedir Nuevo Turno", "Ver Mis Turnos"])
    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
        "phase": "WAITING_MAIN_MENU",
    }))


def _show_week_selection(customer_phone, redis_client, redis_state_key, state, db,
                          is_reschedule=False, prefix=""):
    available_weeks = get_available_weeks(db,
                                           state.get("reschedule_service_id") or state.get("service_id"),
                                           staff_id=state.get("staff_id"))
    state["available_weeks"] = available_weeks
    state["week_offset"] = 0
    state["phase"] = "WAITING_WEEK_SELECTION"
    buttons, _ = _build_week_buttons(available_weeks, 0)
    period_prefix = "Reprogramar:" if is_reschedule else ""
    msg = f"{period_prefix} {prefix}¿Qué semana preferís?".strip()
    send_whatsapp_buttons(customer_phone, msg, buttons)
    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))


def process_message(data: dict, redis_client):
    customer_phone = data.get("from")
    if settings.ENVIRONMENT == "development":
        if customer_phone and customer_phone.startswith("549341"):
            customer_phone = "5434115" + customer_phone[6:]
    message_text = data.get("text", "").strip().lower()

    classifier = get_classifier()

    redis_state_key = f"flow_state:{customer_phone}"
    raw_state = redis_client.get(redis_state_key)
    state = None
    if raw_state:
        try:
            state = json.loads(raw_state)
        except (json.JSONDecodeError, TypeError):
            state = None

    db = SessionLocal()

    try:
        customer = dbs.get_customer_by_phone(db, customer_phone)
        if not customer:
            profile_name = data.get("profile_name")
            customer = dbs.create_customer(db, customer_phone, full_name=profile_name)

        # --- CASO 1: PRIMER CONTACTO ---
        if state is None:
            limite = datetime.now(timezone.utc) - timedelta(days=1)
            bookings = dbs.query_bookings(db)
            booking = next(
                (b for b in bookings if b.customer_id == customer.id and b.status == "pending" and b.start_time >= limite),
                None,
            )
            if not booking:
                from sqlalchemy import and_
                booking = db.query(domain.Booking).filter(
                    domain.Booking.customer_id == customer.id,
                    domain.Booking.status == "pending",
                    domain.Booking.start_time >= limite,
                ).order_by(domain.Booking.start_time.asc()).first()

            if booking:
                fecha_str = booking.start_time.strftime("%d/%m a las %H:%M")
                msg = f"¡Hola! Tenés un turno pendiente para el día {fecha_str}. ¿Qué te gustaría hacer?"
                send_whatsapp_buttons(customer_phone, msg, ["Confirmar Asistencia", "Cancelar Turno"])
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                    "phase": "WAITING_BOOKING_CONFIRMATION",
                }))
            else:
                matched = ai_or_exact(message_text, ["Pedir Nuevo Turno", "Ver Mis Turnos"], classifier, "primer contacto: si pide reprogramar, cancelar, modificar o ver sus turnos, elegí Ver Mis Turnos")
                if matched == "Ver Mis Turnos":
                    state = {"phase": "WAITING_MAIN_MENU"}
                    message_text = "ver mis turnos"
                elif matched == "Pedir Nuevo Turno":
                    state = {"phase": "WAITING_MAIN_MENU"}
                    message_text = "pedir nuevo turno"
                else:
                    msg = "¡Hola! Bienvenido. ¿En qué puedo ayudarte hoy?"
                    send_whatsapp_buttons(customer_phone, msg, ["Pedir Nuevo Turno", "Ver Mis Turnos"])
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                        "phase": "WAITING_MAIN_MENU",
                    }))
                    return

        phase = state.get("phase", "")

        # --- CASO 2: BOOKING CONFIRMATION ---
        if phase == "WAITING_BOOKING_CONFIRMATION":
            booking = db.query(domain.Booking).filter(
                domain.Booking.customer_id == customer.id,
                domain.Booking.status == "pending",
            ).order_by(domain.Booking.start_time.asc()).first()

            if not booking:
                send_whatsapp_buttons(customer_phone, "No encontré turnos pendientes activos.",
                                      ["Volver al inicio"])
                redis_client.delete(redis_state_key)
                return

            options = ["Confirmar Asistencia", "Cancelar Turno"]
            matched = ai_or_exact(message_text, options, classifier, "confirmación de turno pendiente")
            if matched == "Confirmar Asistencia":
                booking.status = "confirmed"
                db.commit()
                logger.info(f"Booking {booking.id} confirmado vía WhatsApp.")
                send_whatsapp_buttons(customer_phone,
                                      "¡Muchas gracias! Tu asistencia fue registrada con éxito.", [])
                redis_client.delete(redis_state_key)
            elif matched == "Cancelar Turno":
                booking.status = "cancelled"
                db.commit()
                logger.info(f"Booking {booking.id} cancelado vía WhatsApp.")
                send_whatsapp_buttons(customer_phone,
                                      "Entendido. El turno fue cancelado. Que tengas un buen día.", [])
                redis_client.delete(redis_state_key)
            else:
                send_whatsapp_buttons(customer_phone,
                                      "Por favor, seleccioná una de las opciones de los botones para continuar:",
                                      options)
            return

        # --- CASO 3: MAIN MENU ---
        if phase == "WAITING_MAIN_MENU":
            matched = ai_or_exact(message_text, ["Pedir Nuevo Turno", "Ver Mis Turnos"], classifier, "menú principal")
            if matched == "Pedir Nuevo Turno":
                services = dbs.get_active_services(db)
                services = [s for s in services if s.rooms]

                if not services:
                    send_whatsapp_buttons(customer_phone,
                                          "No hay servicios disponibles en este momento.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                displayed = services[:3]
                service_buttons = [s.name for s in displayed]
                send_whatsapp_buttons(customer_phone, "¿Qué servicio te interesa?", service_buttons)
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                    "phase": "WAITING_SERVICE_SELECTION",
                    "services": [{"id": str(s.id), "name": s.name} for s in displayed],
                }))

            elif matched == "Ver Mis Turnos":
                bookings = db.query(domain.Booking).filter(
                    domain.Booking.customer_id == customer.id,
                    domain.Booking.status.in_(["pending", "confirmed"]),
                    domain.Booking.start_time >= datetime.now(timezone.utc),
                ).order_by(domain.Booking.start_time.asc()).limit(3).all()

                if not bookings:
                    send_whatsapp_buttons(customer_phone, "No tenés turnos activos.",
                                          ["Pedir Nuevo Turno", "Volver al inicio"])
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                        "phase": "WAITING_MAIN_MENU",
                    }))
                else:
                    lines = ["Tus próximos turnos:"]
                    for i, b in enumerate(bookings, 1):
                        fecha = b.start_time.strftime("%d/%m a las %H:%M")
                        servicio = b.service.name if b.service else "Servicio"
                        estado_map = {"pending": "Pendiente", "confirmed": "Confirmado", "cancelled": "Cancelado"}
                        estado = estado_map.get(b.status, b.status)
                        lines.append(f"{i}. {fecha} - {servicio} ({estado})")
                    lines.append("\n¿Qué querés hacer con tus turnos?")
                    send_whatsapp_buttons(customer_phone, "\n".join(lines),
                                          ["Reprogramar", "Cancelar", "Volver"])
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps({
                        "phase": "WAITING_BOOKING_ACTION",
                        "bookings": [{"id": str(b.id), "fecha": b.start_time.strftime("%d/%m a las %H:%M"),
                                      "servicio": b.service.name if b.service else "Servicio",
                                      "status": b.status} for b in bookings],
                    }))
            else:
                send_whatsapp_buttons(customer_phone, "Por favor, seleccioná una opción de los botones:",
                                      ["Pedir Nuevo Turno", "Ver Mis Turnos"])
            return

        # --- CASO 4: SERVICE SELECTION ---
        if phase == "WAITING_SERVICE_SELECTION":
            services_list = state.get("services", [])
            service_names = [s["name"] for s in services_list]
            matched = ai_or_exact(message_text, service_names, classifier, "selección de servicio")
            selected = next((s for s in services_list if s["name"] == matched), None)

            if not selected:
                send_whatsapp_buttons(customer_phone, "Por favor seleccioná un servicio de la lista:",
                                      [s["name"] for s in services_list])
                return

            state["service_id"] = selected["id"]
            state["service_name"] = selected["name"]

            service = dbs.get_service(db, selected["id"])
            active_staff = [s for s in (service.staff_members if service else []) if s.active]

            if len(active_staff) == 1:
                state["staff_id"] = str(active_staff[0].id)
                state["staff_name"] = active_staff[0].name
                _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                     db, prefix=f"Elegiste: {selected['name']} con {active_staff[0].name}. ")
                return
            elif len(active_staff) > 1:
                displayed_staff = active_staff[:3]
                staff_buttons = [s.name for s in displayed_staff]
                send_whatsapp_buttons(customer_phone, "¿Con qué profesional querés el turno?", staff_buttons)
                state["phase"] = "WAITING_STAFF_SELECTION"
                state["available_staff"] = [{"id": str(s.id), "name": s.name} for s in displayed_staff]
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            else:
                _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                     db, prefix=f"Elegiste: {selected['name']}. ")
                return
            return

        # --- CASO 4b: STAFF SELECTION ---
        if phase == "WAITING_STAFF_SELECTION":
            available_staff = state.get("available_staff", [])
            staff_names = [s["name"] for s in available_staff]
            matched = ai_or_exact(message_text, staff_names, classifier, "selección de profesional")
            selected_staff = next((s for s in available_staff if s["name"] == matched), None)

            if not selected_staff:
                send_whatsapp_buttons(customer_phone, "Por favor seleccioná un profesional de la lista:",
                                      [s["name"] for s in available_staff])
                return

            state["staff_id"] = selected_staff["id"]
            state["staff_name"] = selected_staff["name"]
            _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                 db, prefix=f"Elegiste: {state.get('service_name', 'el servicio')} con {selected_staff['name']}. ")
            return

        # --- CASO 4c: WEEK SELECTION ---
        if phase == "WAITING_WEEK_SELECTION":
            is_reschedule = bool(state.get("reschedule_booking_id"))
            period_prefix = "Reprogramar:" if is_reschedule else ""

            available_weeks = state.get("available_weeks")
            if not available_weeks:
                service_id = state.get("reschedule_service_id") or state.get("service_id")
                available_weeks = get_available_weeks(db, service_id, staff_id=state.get("staff_id"))
                state["available_weeks"] = available_weeks
                state["week_offset"] = 0

            offset = state.get("week_offset", 0)
            buttons, page = _build_week_buttons(available_weeks, offset)

            matched = ai_or_exact(message_text, buttons, classifier, "selección de semana")
            if matched == "Más semanas →":
                state["week_offset"] = offset + len(page)
            elif matched == "← Anteriores":
                state["week_offset"] = max(offset - WEEKS_PER_PAGE, 0)
            elif matched:
                selected = next((w for w in available_weeks if w["label"] == matched), None)
                if selected:
                    state["week_start"] = selected["iso"]
                    state.pop("available_weeks", None)
                    state.pop("week_offset", None)
                    send_whatsapp_buttons(customer_phone,
                                          f"{period_prefix} ¿Qué horario preferís?",
                                          ["Mañana (9-13hs)", "Tarde (13-18hs)"])
                    state["phase"] = "WAITING_PERIOD_SELECTION"
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                    return

            offset = state.get("week_offset", 0)
            buttons, page = _build_week_buttons(available_weeks, offset)
            send_whatsapp_buttons(customer_phone,
                                  f"{period_prefix} ¿Qué semana preferís?",
                                  buttons)
            redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            return

        # --- CASO 4d: PERIOD SELECTION ---
        if phase == "WAITING_PERIOD_SELECTION":
            matched = ai_or_exact(message_text, ["Mañana (9-13hs)", "Tarde (13-18hs)"], classifier, "selección de horario mañana/tarde")
            if matched == "Mañana (9-13hs)":
                period = "morning"
            elif matched == "Tarde (13-18hs)":
                period = "afternoon"
            else:
                send_whatsapp_buttons(customer_phone, "Por favor seleccioná mañana o tarde:",
                                      ["Mañana (9-13hs)", "Tarde (13-18hs)"])
                return

            week_start = date.fromisoformat(state["week_start"])
            is_reschedule = bool(state.get("reschedule_booking_id"))

            if is_reschedule:
                service_id = state.get("reschedule_service_id")
                booking_id = state.get("reschedule_booking_id")
                slots = get_week_slots(db, service_id, week_start, period,
                                       staff_id=state.get("staff_id"),
                                       exclude_booking_id=booking_id)
            else:
                service_id = state.get("service_id")
                slots = get_week_slots(db, service_id, week_start, period,
                                       staff_id=state.get("staff_id"))

            if not slots:
                send_whatsapp_buttons(customer_phone,
                                      "No hay horarios disponibles en ese período. ¿Querés probar otra combinación?",
                                      ["Otro período", "Otra semana", "Volver al inicio"])
                state["phase"] = "WAITING_SLOT_RETRY"
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                return

            displayed = slots[:3]
            slot_buttons = [s["display"] for s in displayed]
            send_whatsapp_buttons(customer_phone,
                                  "Horarios disponibles:",
                                  slot_buttons)
            next_phase = "WAITING_RESCHEDULE_TIME_SELECTION" if is_reschedule else "WAITING_TIME_SELECTION"
            state["phase"] = next_phase
            state["slots"] = displayed
            redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            return

        # --- CASO 4e: SLOT RETRY ---
        if phase == "WAITING_SLOT_RETRY":
            matched = ai_or_exact(message_text, ["Otro período", "Otra semana", "Volver al inicio"], classifier, "reintento de horario")
            if matched == "Otro período":
                is_reschedule = bool(state.get("reschedule_booking_id"))
                period_prefix = "Reprogramar:" if is_reschedule else ""
                send_whatsapp_buttons(customer_phone,
                                      f"{period_prefix} ¿Qué horario preferís?",
                                      ["Mañana (9-13hs)", "Tarde (13-18hs)"])
                state["phase"] = "WAITING_PERIOD_SELECTION"
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            elif matched == "Otra semana":
                is_reschedule = bool(state.get("reschedule_booking_id"))
                _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                     db, is_reschedule=is_reschedule)
                return
            elif matched == "Volver al inicio":
                _show_main_menu(customer_phone, redis_client, redis_state_key)
            else:
                send_whatsapp_buttons(customer_phone, "Por favor, seleccioná una opción:",
                                      ["Otro período", "Otra semana", "Volver al inicio"])
            return

        # --- CASO 5: TIME SELECTION ---
        if phase == "WAITING_TIME_SELECTION":
            slots = state.get("slots", [])
            display = state.get("service_name", "el servicio")
            selected_slot = None

            if slots and "display" in (slots[0] or {}):
                slot_options = [s["display"] for s in slots]
            else:
                slot_options = [datetime.fromisoformat(s["time"]).strftime("%H:%M") for s in slots]
            matched = ai_or_exact(message_text, slot_options, classifier, "selección de horario")
            if matched:
                if slots and "display" in (slots[0] or {}):
                    selected_slot = next((s for s in slots if s["display"] == matched), None)
                else:
                    selected_slot = next(
                        (s for s in slots if datetime.fromisoformat(s["time"]).strftime("%H:%M") == matched),
                        None,
                    )

            if not selected_slot:
                if slots and "display" in (slots[0] or {}):
                    slot_buttons = [s["display"] for s in slots]
                else:
                    slot_buttons = [datetime.fromisoformat(s["time"]).strftime("%H:%M") for s in slots]
                send_whatsapp_buttons(customer_phone, "Por favor seleccioná un horario de la lista:",
                                      slot_buttons)
                return

            slot_time = datetime.fromisoformat(selected_slot["time"])
            msg = (
                f"Confirmá tu turno:\n"
                f"* {display}\n"
                f"* {slot_time.strftime('%d/%m/%Y')}\n"
                f"* {slot_time.strftime('%H:%M')} hs\n\n"
                f"¿Confirmás?"
            )
            send_whatsapp_buttons(customer_phone, msg, ["Confirmar Turno", "Cancelar"])
            state["phase"] = "WAITING_BOOKING_CREATION"
            state["selected_slot"] = selected_slot
            redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            return

        # --- CASO 6: BOOKING CREATION ---
        if phase == "WAITING_BOOKING_CREATION":
            matched = ai_or_exact(message_text, ["Confirmar Turno", "Cancelar"], classifier, "confirmación de turno")
            if matched == "Confirmar Turno":
                service_id = state.get("service_id")
                selected_slot = state.get("selected_slot", {})
                slot_start = datetime.fromisoformat(selected_slot["time"])
                room_id = selected_slot.get("room_id")
                staff_id = state.get("staff_id")

                service = dbs.get_service(db, service_id)
                if not service or not service.active:
                    send_whatsapp_buttons(customer_phone,
                                          "El servicio seleccionado ya no está disponible.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                slot_end = slot_start + timedelta(minutes=service.duration_minutes)

                room = dbs.get_room(db, room_id)
                if not room or not room.active:
                    send_whatsapp_buttons(customer_phone,
                                          "La sala ya no está disponible. Intentá con otro horario.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                if staff_id:
                    staff_member = dbs.get_staff(db, staff_id)
                    if not staff_member or not staff_member.active:
                        staff_id = None

                conflicts = dbs.check_booking_conflicts(
                    db, slot_start, slot_end,
                    room_id=room_id,
                    staff_id=str(staff_id) if staff_id else None,
                )
                if conflicts:
                    send_whatsapp_buttons(customer_phone,
                                          "Ese horario ya no está disponible. ¿Querés intentar con otro?",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                try:
                    dbs.create_booking(db, service_id, slot_start, slot_end,
                                       customer_id=str(customer.id), room_id=room_id,
                                       staff_id=staff_id, status="confirmed")
                except IntegrityError:
                    send_whatsapp_buttons(customer_phone,
                                          "Ese horario ya no está disponible. ¿Querés intentar con otro?",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                fecha_str = slot_start.strftime("%d/%m a las %H:%M")
                send_whatsapp_buttons(customer_phone,
                                      f"¡Turno confirmado! Te esperamos el {fecha_str}. ¡Gracias!",
                                      [])
                logger.info(f"Booking creado vía WhatsApp: cliente {customer.id}, servicio {service_id}, {fecha_str}")
                redis_client.delete(redis_state_key)

            elif matched == "Cancelar":
                _show_main_menu(customer_phone, redis_client, redis_state_key)
            else:
                send_whatsapp_buttons(customer_phone,
                                      "Por favor seleccioná 'Confirmar Turno' o 'Cancelar'.",
                                      ["Confirmar Turno", "Cancelar"])
            return

        # --- CASO 7: BOOKING ACTION (Reprogramar / Cancelar desde Mis Turnos) ---
        if phase == "WAITING_BOOKING_ACTION":
            bookings_data = state.get("bookings", [])

            matched = ai_or_exact(message_text, ["Reprogramar", "Cancelar", "Volver"], classifier, "acción sobre mis turnos")

            if matched == "Volver":
                _show_main_menu(customer_phone, redis_client, redis_state_key)
                return

            if matched == "Reprogramar":
                if len(bookings_data) == 1:
                    booking = dbs.get_booking(db, bookings_data[0]["id"])
                    if not booking or booking.status not in ("pending", "confirmed"):
                        send_whatsapp_buttons(customer_phone, "Ese turno ya no está disponible.",
                                              ["Volver al inicio"])
                        redis_client.delete(redis_state_key)
                        return
                    state["reschedule_booking_id"] = str(booking.id)
                    state["reschedule_service_id"] = str(booking.service_id) if booking.service_id else None
                    state["reschedule_service_name"] = booking.service.name if booking.service else "Servicio"

                    active_staff = [s for s in (booking.service.staff_members if booking.service else []) if s.active]
                    if len(active_staff) == 1:
                        state["staff_id"] = str(active_staff[0].id)
                        state["staff_name"] = active_staff[0].name
                        _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                             db, is_reschedule=True,
                                             prefix=f"{state['reschedule_service_name']} con {active_staff[0].name}. ")
                        return
                    elif len(active_staff) > 1:
                        displayed_staff = active_staff[:3]
                        staff_buttons = [s.name for s in displayed_staff]
                        send_whatsapp_buttons(customer_phone, "¿Con qué profesional querés reprogramar?", staff_buttons)
                        state["phase"] = "WAITING_RESCHEDULE_STAFF_SELECTION"
                        state["available_staff"] = [{"id": str(s.id), "name": s.name} for s in displayed_staff]
                    else:
                        _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                             db, is_reschedule=True,
                                             prefix=f"{state['reschedule_service_name']}. ")
                        return
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                else:
                    lines = ["¿Cuál turno querés reprogramar? Respondé con el número:"]
                    for i, b in enumerate(bookings_data, 1):
                        lines.append(f"{i}. {b['fecha']} - {b['servicio']}")
                    send_whatsapp_buttons(customer_phone, "\n".join(lines), [])
                    state["phase"] = "WAITING_BOOKING_SELECTION"
                    state["pending_action"] = "reprogramar"
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                return

            if matched == "Cancelar":
                if len(bookings_data) == 1:
                    booking = dbs.get_booking(db, bookings_data[0]["id"])
                    if not booking or booking.status not in ("pending", "confirmed"):
                        send_whatsapp_buttons(customer_phone, "Ese turno ya no está disponible.",
                                              ["Volver al inicio"])
                        redis_client.delete(redis_state_key)
                        return
                    dbs.cancel_booking(db, booking)
                    send_whatsapp_buttons(customer_phone,
                                          f"Turno del {bookings_data[0]['fecha']} cancelado.",
                                          ["Volver al inicio"])
                    logger.info(f"Booking {booking.id} cancelado vía WhatsApp.")
                    redis_client.delete(redis_state_key)
                else:
                    lines = ["¿Cuál turno querés cancelar? Respondé con el número:"]
                    for i, b in enumerate(bookings_data, 1):
                        lines.append(f"{i}. {b['fecha']} - {b['servicio']}")
                    send_whatsapp_buttons(customer_phone, "\n".join(lines), [])
                    state["phase"] = "WAITING_BOOKING_SELECTION"
                    state["pending_action"] = "cancelar"
                    redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                return

            send_whatsapp_buttons(customer_phone, "Por favor seleccioná una opción:",
                                  ["Reprogramar", "Cancelar", "Volver"])
            return

        # --- CASO 8: BOOKING SELECTION (para reprogramar/cancelar un turno específico) ---
        if phase == "WAITING_BOOKING_SELECTION":
            bookings_data = state.get("bookings", [])
            pending_action = state.get("pending_action", "")

            try:
                idx = int(message_text) - 1
                if idx < 0 or idx >= len(bookings_data):
                    raise ValueError
            except ValueError:
                lines = ["Por favor respondé con un número válido:"]
                for i, b in enumerate(bookings_data, 1):
                    lines.append(f"{i}. {b['fecha']} - {b['servicio']}")
                send_whatsapp_buttons(customer_phone, "\n".join(lines), [])
                return

            selected_booking = bookings_data[idx]
            booking = dbs.get_booking(db, selected_booking["id"])

            if not booking or booking.status not in ("pending", "confirmed"):
                send_whatsapp_buttons(customer_phone, "Ese turno ya no está disponible.",
                                      ["Volver al inicio"])
                redis_client.delete(redis_state_key)
                return

            if pending_action == "cancelar":
                dbs.cancel_booking(db, booking)
                send_whatsapp_buttons(customer_phone,
                                      f"Turno del {selected_booking['fecha']} cancelado.",
                                      ["Volver al inicio"])
                logger.info(f"Booking {booking.id} cancelado vía WhatsApp.")
                redis_client.delete(redis_state_key)
            elif pending_action == "reprogramar":
                state["reschedule_booking_id"] = str(booking.id)
                state["reschedule_service_id"] = str(booking.service_id) if booking.service_id else None
                state["reschedule_service_name"] = booking.service.name if booking.service else "Servicio"

                active_staff = [s for s in (booking.service.staff_members if booking.service else []) if s.active]
                if len(active_staff) == 1:
                    state["staff_id"] = str(active_staff[0].id)
                    state["staff_name"] = active_staff[0].name
                    _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                         db, is_reschedule=True,
                                         prefix=f"{state['reschedule_service_name']} con {active_staff[0].name}. ")
                    return
                elif len(active_staff) > 1:
                    displayed_staff = active_staff[:3]
                    staff_buttons = [s.name for s in displayed_staff]
                    send_whatsapp_buttons(customer_phone, "Con que profesional queres reprogramar?", staff_buttons)
                    state["phase"] = "WAITING_RESCHEDULE_STAFF_SELECTION"
                    state["available_staff"] = [{"id": str(s.id), "name": s.name} for s in displayed_staff]
                else:
                    _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                         db, is_reschedule=True,
                                         prefix=f"{state['reschedule_service_name']}. ")
                    return
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            return

        # --- CASO 9: RESCHEDULE STAFF SELECTION ---
        if phase == "WAITING_RESCHEDULE_STAFF_SELECTION":
            available_staff = state.get("available_staff", [])
            staff_names = [s["name"] for s in available_staff]
            matched = ai_or_exact(message_text, staff_names, classifier, "selección de profesional para reprogramar")
            selected_staff = next((s for s in available_staff if s["name"] == matched), None)

            if not selected_staff:
                send_whatsapp_buttons(customer_phone, "Por favor seleccioná un profesional de la lista:",
                                      [s["name"] for s in available_staff])
                return

            state["staff_id"] = selected_staff["id"]
            state["staff_name"] = selected_staff["name"]
            _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                 db, is_reschedule=True,
                                 prefix=f"{state.get('reschedule_service_name', 'el servicio')} con {selected_staff['name']}. ")
            return

        # --- CASO 10: RESCHEDULE TIME SELECTION ---
        if phase == "WAITING_RESCHEDULE_TIME_SELECTION":
            slots = state.get("slots", [])
            selected_slot = None

            if slots and "display" in (slots[0] or {}):
                slot_options = [s["display"] for s in slots]
            else:
                slot_options = [datetime.fromisoformat(s["time"]).strftime("%H:%M") for s in slots]
            matched = ai_or_exact(message_text, slot_options, classifier, "selección de horario para reprogramar")
            if matched:
                if slots and "display" in (slots[0] or {}):
                    selected_slot = next((s for s in slots if s["display"] == matched), None)
                else:
                    selected_slot = next(
                        (s for s in slots if datetime.fromisoformat(s["time"]).strftime("%H:%M") == matched),
                        None,
                    )

            if not selected_slot:
                if slots and "display" in (slots[0] or {}):
                    slot_buttons = [s["display"] for s in slots]
                else:
                    slot_buttons = [datetime.fromisoformat(s["time"]).strftime("%H:%M") for s in slots]
                send_whatsapp_buttons(customer_phone, "Por favor selecciona un horario de la lista:",
                                      slot_buttons)
                return

            service_name = state.get("reschedule_service_name", "el servicio")
            slot_time = datetime.fromisoformat(selected_slot["time"])
            msg = (
                f"Confirma la reprogramacion:\n"
                f"* {service_name}\n"
                f"* {slot_time.strftime('%d/%m/%Y')}\n"
                f"* {slot_time.strftime('%H:%M')} hs\n\n"
                f"Confirmas el nuevo horario?"
            )
            send_whatsapp_buttons(customer_phone, msg, ["Confirmar Cambio", "Cancelar"])
            state["phase"] = "WAITING_RESCHEDULE_CONFIRMATION"
            state["selected_slot"] = selected_slot
            redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
            return

        # --- CASO 11: RESCHEDULE CONFIRMATION ---
        if phase == "WAITING_RESCHEDULE_CONFIRMATION":
            matched = ai_or_exact(message_text, ["Confirmar Cambio", "Cancelar"], classifier, "confirmación de reprogramación")
            if matched == "Confirmar Cambio":
                booking_id = state.get("reschedule_booking_id")
                selected_slot = state.get("selected_slot", {})
                slot_start = datetime.fromisoformat(selected_slot["time"])
                room_id = selected_slot.get("room_id")
                staff_id = state.get("staff_id")

                booking = dbs.get_booking(db, booking_id)
                if not booking:
                    send_whatsapp_buttons(customer_phone,
                                          "El turno original ya no existe.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                service = dbs.get_service(db, booking.service_id)
                if not service or not service.active:
                    send_whatsapp_buttons(customer_phone,
                                          "El servicio ya no está disponible.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                slot_end = slot_start + timedelta(minutes=service.duration_minutes)

                room = dbs.get_room(db, room_id)
                if not room or not room.active:
                    send_whatsapp_buttons(customer_phone,
                                          "La sala ya no está disponible.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                if staff_id:
                    staff_member = dbs.get_staff(db, staff_id)
                    if not staff_member or not staff_member.active or not dbs.staff_offers_service(db, staff_id, str(booking.service_id)):
                        staff_id = None

                conflicts = dbs.check_booking_conflicts(
                    db, slot_start, slot_end,
                    room_id=room_id,
                    staff_id=str(staff_id) if staff_id else None,
                    exclude_booking_id=booking_id,
                )
                if conflicts:
                    send_whatsapp_buttons(customer_phone,
                                          "Ese horario ya no está disponible. Intentá con otro.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return

                try:
                    dbs.update_booking_times(db, booking, slot_start, slot_end)
                except IntegrityError:
                    send_whatsapp_buttons(customer_phone,
                                          "Ese horario ya no está disponible. Intentá con otro.",
                                          ["Volver al inicio"])
                    redis_client.delete(redis_state_key)
                    return
                updates = {}
                if room_id and str(booking.room_id) != room_id:
                    updates["room_id"] = room_id
                if staff_id and str(booking.staff_id) != staff_id:
                    updates["staff_id"] = staff_id
                if updates:
                    try:
                        dbs.update_booking_fields(db, booking, **updates)
                    except IntegrityError:
                        send_whatsapp_buttons(customer_phone,
                                              "Ese horario ya no está disponible. Intentá con otro.",
                                              ["Volver al inicio"])
                        redis_client.delete(redis_state_key)
                        return
                logger.info(f"Booking {booking.id} reprogramado vía WhatsApp: {slot_start}")

                fecha_str = slot_start.strftime("%d/%m a las %H:%M")
                send_whatsapp_buttons(customer_phone,
                                      f"¡Turno reprogramado! Tu nuevo turno es el {fecha_str}. ¡Gracias!",
                                      [])
                redis_client.delete(redis_state_key)

            elif matched == "Cancelar":
                _show_main_menu(customer_phone, redis_client, redis_state_key)
            else:
                send_whatsapp_buttons(customer_phone,
                                      "Por favor seleccioná 'Confirmar Cambio' o 'Cancelar'.",
                                      ["Confirmar Cambio", "Cancelar"])
            return

        # --- CASO 12: REMINDER ACTION ---
        if phase == "WAITING_REMINDER_ACTION":
            booking_id = state.get("reminder_booking_id")
            booking = dbs.get_booking(db, booking_id)

            if not booking or booking.status != "confirmed":
                send_whatsapp_buttons(customer_phone, "Ese turno ya no está disponible.",
                                      ["Volver al inicio"])
                redis_client.delete(redis_state_key)
                return

            matched = ai_or_exact(message_text, ["Confirmar Asistencia", "Reprogramar", "Cancelar Turno"], classifier, "recordatorio de turno")
            if matched == "Confirmar Asistencia":
                send_whatsapp_buttons(customer_phone,
                                      "¡Gracias por confirmar! Te esperamos. Cualquier cosa nos avisás.",
                                      [])
                logger.info(f"Booking {booking.id} reconfirmado desde recordatorio.")
                redis_client.delete(redis_state_key)
                return

            if matched == "Cancelar Turno":
                booking.status = "cancelled"
                db.commit()
                send_whatsapp_buttons(customer_phone, "Turno cancelado. Que tengas buen día.",
                                      [])
                logger.info(f"Booking {booking.id} cancelado desde recordatorio vía WhatsApp.")
                redis_client.delete(redis_state_key)
                return

            if matched == "Reprogramar":
                state["reschedule_booking_id"] = str(booking.id)
                state["reschedule_service_id"] = str(booking.service_id) if booking.service_id else None
                state["reschedule_service_name"] = booking.service.name if booking.service else "Servicio"

                active_staff = [s for s in (booking.service.staff_members if booking.service else []) if s.active]
                if len(active_staff) == 1:
                    state["staff_id"] = str(active_staff[0].id)
                    state["staff_name"] = active_staff[0].name
                    _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                         db, is_reschedule=True,
                                         prefix=f"{state['reschedule_service_name']} con {active_staff[0].name}. ")
                    return
                elif len(active_staff) > 1:
                    displayed_staff = active_staff[:3]
                    staff_buttons = [s.name for s in displayed_staff]
                    send_whatsapp_buttons(customer_phone, "¿Con qué profesional querés reprogramar?", staff_buttons)
                    state["phase"] = "WAITING_RESCHEDULE_STAFF_SELECTION"
                    state["available_staff"] = [{"id": str(s.id), "name": s.name} for s in displayed_staff]
                else:
                    _show_week_selection(customer_phone, redis_client, redis_state_key, state,
                                         db, is_reschedule=True,
                                         prefix=f"{state['reschedule_service_name']}. ")
                    return
                redis_client.setex(redis_state_key, STATE_EXPIRATION, json.dumps(state))
                return

            send_whatsapp_buttons(customer_phone, "Por favor seleccioná una opción:",
                                  ["Confirmar Asistencia", "Reprogramar", "Cancelar Turno"])
            return

        # --- FALLBACK ---
        logger.warning(f"Unknown phase '{phase}' for customer {customer_phone}, resetting")
        redis_client.delete(redis_state_key)
        _show_main_menu(customer_phone, redis_client, redis_state_key)

    except Exception as e:
        db.rollback()
        logger.error(f"Error procesando lógica de negocio en el worker: {e}", exc_info=True)
        try:
            if customer_phone:
                send_whatsapp_buttons(customer_phone,
                                      "Ocurrió un error inesperado. Por favor intentá de nuevo más tarde.",
                                      [])
            redis_client.delete(redis_state_key)
        except Exception:
            pass
    finally:
        db.close()
