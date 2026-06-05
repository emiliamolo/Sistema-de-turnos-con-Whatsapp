from fastapi import APIRouter, Request, Depends, Response, HTTPException, status, Body
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, date, time, timezone
from decimal import Decimal
import io
from ..core.database import get_db
from ..core.dependencies import get_templates
from ..core.auth import get_current_user_required
from ..models import domain
from ..services import db_service as dbs

ROOM_PALETTE = [
    "#15803d", "#0f766e", "#047857", "#4d7c0f",
    "#166534", "#115e59", "#065f46", "#3f6212",
    "#14532d", "#134e4a", "#064e3b", "#365314",
]


def get_room_color(room_id):
    if room_id:
        return ROOM_PALETTE[room_id.int % len(ROOM_PALETTE)]
    return "#94a3b8"


def _parse_multi_value(form, key):
    if hasattr(form, 'getlist'):
        return form.getlist(key)
    values = []
    i = 0
    while True:
        val = form.get(f"{key}[{i}]") or form.get(key)
        if not val:
            val = None
        if val is None:
            break
        values.append(val)
        i += 1
    if not values:
        raw = form.get(key)
        if raw:
            values = [v.strip() for v in raw.split(",") if v.strip()]
    return values


router = APIRouter(prefix="/admin", tags=["admin"])


# =========================================================================
# DASHBOARD
# =========================================================================

@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    bookings_count = dbs.count_bookings(db)
    services_count = dbs.count_services(db)
    today_bookings = dbs.get_today_bookings(db)

    context = {
        "user": user,
        "bookings_count": bookings_count,
        "services_count": services_count,
        "bookings": today_bookings,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="admin/dashboard_content.html", context=context)
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


# =========================================================================
# ROOMS
# =========================================================================

@router.get("/rooms")
async def list_rooms(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    rooms = dbs.get_rooms(db)
    context = {"request": request, "rooms": rooms, "user": user}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="rooms/list.html", context=context)
    context["content_template"] = "rooms/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/rooms")
async def create_room(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    form = await request.form()
    name = form.get("name")

    existing = dbs.get_room_by_name(db, name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Ya existe una sala llamada '{name}'.")

    dbs.create_room(db, name, form.get("description"), int(form.get("capacity", 1)))
    rooms = dbs.get_rooms(db)
    return templates.TemplateResponse(request=request, name="rooms/table_rows.html", context={"rooms": rooms})


@router.get("/rooms/{room_id}/edit")
async def edit_room_form(
    room_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    room = dbs.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="La sala no existe.")
    return templates.TemplateResponse(request=request, name="rooms/edit_modal.html", context={"room": room})


@router.post("/rooms/{room_id}")
async def update_room(
    room_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    room = dbs.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="La sala no existe o no tienes permiso para modificarla.")
    form = await request.form()
    dbs.update_room(db, room, form.get("name"), form.get("description"), int(form.get("capacity")))
    rooms = dbs.get_rooms(db)
    return templates.TemplateResponse(request=request, name="rooms/table_rows.html", context={"rooms": rooms})


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    room = dbs.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="La sala no existe o no pertenece a este negocio.")
    dbs.delete_room(db, room)
    rooms = dbs.get_rooms(db)
    return templates.TemplateResponse(request=request, name="rooms/table_rows.html", context={"rooms": rooms})


# =========================================================================
# SERVICES
# =========================================================================

@router.get("/services")
async def list_services(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    services = dbs.get_services(db, with_rooms=True)
    rooms = dbs.get_rooms(db)
    context = {"request": request, "services": services, "rooms": rooms, "user": user}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="services/list.html", context=context)
    context["content_template"] = "services/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/services")
async def create_service(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    form = await request.form()
    name = form.get("name")

    existing = dbs.get_service_by_name(db, name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Ya existe un servicio llamado '{name}'.")

    room_ids = _parse_multi_value(form, "room_ids")
    dbs.create_service(
        db, name,
        description=form.get("description"),
        duration_minutes=int(form.get("duration", 30)),
        price=float(form.get("price", 0)),
        commission_type=form.get("commission_type"),
        commission_value=float(form.get("commission_value")) if form.get("commission_value") else None,
        room_ids=room_ids if room_ids else None,
    )
    services = dbs.get_services(db, with_rooms=True)
    return templates.TemplateResponse(request=request, name="services/table_rows.html", context={"services": services})


@router.get("/services/{service_id}/edit")
async def edit_service_form(
    service_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    service = dbs.get_service(db, service_id, with_rooms=True)
    if not service:
        raise HTTPException(status_code=404, detail="El servicio no existe.")
    rooms = dbs.get_rooms(db)
    assigned_room_ids = [str(r.id) for r in service.rooms]
    return templates.TemplateResponse(
        request=request, name="services/edit_modal.html",
        context={"service": service, "rooms": rooms, "assigned_room_ids": assigned_room_ids},
    )


@router.post("/services/{service_id}")
async def update_service(
    service_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="El servicio no existe o no tienes permiso para modificarlo.")
    form = await request.form()
    room_ids = _parse_multi_value(form, "room_ids")
    dbs.update_service(
        db, service,
        name=form.get("name"),
        description=form.get("description"),
        duration_minutes=int(form.get("duration")),
        price=float(form.get("price")),
        commission_type=form.get("commission_type"),
        commission_value=float(form.get("commission_value")) if form.get("commission_value") else None,
        room_ids=room_ids if room_ids else [],
    )
    services = dbs.get_services(db, with_rooms=True)
    return templates.TemplateResponse(request=request, name="services/table_rows.html", context={"services": services})


@router.delete("/services/{service_id}")
async def delete_service(
    service_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="El servicio no existe o no pertenece a este negocio.")
    dbs.delete_service(db, service)
    services = dbs.get_services(db, with_rooms=True)
    return templates.TemplateResponse(request=request, name="services/table_rows.html", context={"services": services})


# =========================================================================
# BOOKINGS
# =========================================================================

@router.get("/bookings")
async def list_bookings(
    request: Request,
    date: str = None,
    service_id: str = None,
    room_id: str = None,
    staff_id: str = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    filter_date = None
    if date:
        try:
            filter_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            pass

    bookings = dbs.query_bookings(db, date_filter=filter_date,
                                  service_id=service_id, room_id=room_id, staff_id=staff_id)
    customers = dbs.get_customers(db)
    services = dbs.get_services(db, with_rooms=True)
    rooms = dbs.get_rooms(db)
    staff = dbs.get_staff_list(db)

    context = {
        "request": request,
        "user": user,
        "today": datetime.now().strftime("%Y-%m-%d"),
        "bookings": bookings,
        "customers": customers,
        "services": services,
        "rooms": rooms,
        "staff": staff,
        "filters": {
            "date": date or "",
            "service_id": service_id or "",
            "room_id": room_id or "",
            "staff_id": staff_id or "",
        },
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="bookings/list.html", context=context)
    context["content_template"] = "bookings/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/bookings")
async def create_booking(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    form = await request.form()
    service_id = form.get("service_id")
    if not service_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El ID del servicio es requerido.")

    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El servicio seleccionado no existe.")

    staff_id = form.get("staff_id") if form.get("staff_id") else None

    try:
        start_time = datetime.fromisoformat(form.get("start_time"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha y hora de inicio no tienen un formato válido.")

    room_id = form.get("room_id")
    if room_id:
        if not dbs.room_in_service(db, service_id, room_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La sala seleccionada no está disponible para este servicio.")

    end_time = start_time + timedelta(minutes=service.duration_minutes)

    conflicts = dbs.check_booking_conflicts(db, start_time, end_time, room_id=room_id, staff_id=staff_id)
    if conflicts:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto de horario: " + " y ".join(conflicts) + ".")

    if staff_id:
        avail_error = dbs.check_staff_availability(db, staff_id, start_time, end_time)
        if avail_error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=avail_error)

    try:
        dbs.create_booking(db, service_id, start_time, end_time,
                           customer_id=form.get("customer_id"), room_id=room_id, staff_id=staff_id, status="confirmed")
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El horario ya no está disponible. Otro turno fue reservado en simultáneo.")

    bookings = dbs.get_bookings(db)
    return templates.TemplateResponse(request=request, name="bookings/table_rows.html", context={"bookings": bookings})


@router.get("/bookings/{booking_id}/edit")
async def edit_booking_form(
    booking_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="El turno no existe.")

    customers = dbs.get_customers(db)
    services = dbs.get_services(db, with_rooms=True)
    rooms = dbs.get_rooms(db)
    staff = dbs.get_staff_list(db)

    return templates.TemplateResponse(request=request, name="bookings/edit_modal.html", context={
        "booking": booking, "customers": customers, "services": services,
        "rooms": rooms, "staff": staff,
    })


@router.post("/bookings/{booking_id}")
async def update_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="El turno no existe.")

    form = await request.form()
    service_id = form.get("service_id")
    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="El servicio no existe.")

    try:
        start_time = datetime.fromisoformat(form.get("start_time"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Formato de fecha inválido.")

    end_time = start_time + timedelta(minutes=service.duration_minutes)
    room_id = form.get("room_id")
    staff_id = form.get("staff_id") if form.get("staff_id") else None

    if room_id:
        if not dbs.room_in_service(db, service_id, room_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La sala seleccionada no está disponible para este servicio.")

    conflicts = dbs.check_booking_conflicts(db, start_time, end_time,
                                            room_id=room_id, staff_id=staff_id, exclude_booking_id=booking_id)
    if conflicts:
        raise HTTPException(status_code=409, detail="Conflicto de horario: " + " y ".join(conflicts) + ".")

    if staff_id:
        avail_error = dbs.check_staff_availability(db, staff_id, start_time, end_time)
        if avail_error:
            raise HTTPException(status_code=409, detail=avail_error)

    try:
        dbs.update_booking_fields(db, booking,
                                  customer_id=form.get("customer_id"),
                                  service_id=service_id,
                                  room_id=room_id,
                                  staff_id=staff_id,
                                  start_time=start_time,
                                  end_time=end_time,
                                  status=form.get("status", booking.status))
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El horario ya no está disponible. Otro turno fue reservado en simultáneo.")

    bookings = dbs.get_bookings(db)
    return templates.TemplateResponse(request=request, name="bookings/table_rows.html", context={"bookings": bookings})


@router.delete("/bookings/{booking_id}")
async def delete_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="La reserva no existe.")
    dbs.delete_booking(db, booking)
    bookings = dbs.get_bookings(db)
    return templates.TemplateResponse(request=request, name="bookings/table_rows.html", context={"bookings": bookings})


# =========================================================================
# CALENDAR
# =========================================================================

@router.get("/calendar")
async def calendar_view(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    context = {
        "request": request, "user": user,
        "services": dbs.get_services(db),
        "rooms": dbs.get_rooms(db),
        "staff": dbs.get_staff_list(db),
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="calendar/view.html", context=context)
    context["content_template"] = "calendar/view.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/api/calendar/events")
async def get_calendar_events(
    start: str, end: str,
    service_id: str = None,
    room_id: str = None,
    staff_id: str = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
):
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    bookings = dbs.get_calendar_bookings(db, start_dt, end_dt, service_id, room_id, staff_id)
    events = []
    for b in bookings:
        events.append({
            "id": str(b.id),
            "title": f"{b.customer.full_name if b.customer else 'Cliente'} - {b.service.name if b.service else 'Servicio'}",
            "start": b.start_time.isoformat(),
            "end": b.end_time.isoformat(),
            "color": get_room_color(b.room_id),
        })
    return events


@router.put("/api/calendar/events/{booking_id}")
async def update_calendar_event(
    booking_id: str,
    start: str = Body(...),
    end: str = Body(...),
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
):
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    try:
        new_start = datetime.fromisoformat(start)
        new_end = datetime.fromisoformat(end)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")

    conflicts = dbs.check_booking_conflicts(db, new_start, new_end,
                                            room_id=booking.room_id, staff_id=booking.staff_id,
                                            exclude_booking_id=booking_id)
    if conflicts:
        raise HTTPException(status_code=409, detail="Conflicto de horario: " + " y ".join(conflicts) + ".")

    if booking.staff_id:
        avail_error = dbs.check_staff_availability(db, booking.staff_id, new_start, new_end)
        if avail_error:
            raise HTTPException(status_code=409, detail=avail_error)

    try:
        dbs.update_booking_times(db, booking, new_start, new_end)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El horario ya no está disponible. Otro turno fue reservado en simultáneo.")
    return {"ok": True, "id": booking_id}


@router.get("/api/calendar/available-days")
async def get_available_days(
    start: str, end: str,
    service_id: str = None,
    room_id: str = None,
    staff_id: str = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
):
    try:
        start_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
        end_date = datetime.strptime(end[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []

    available_dates = dbs.get_available_days(db, start_date, end_date, service_id, room_id, staff_id)
    return {"available_dates": [d.strftime("%Y-%m-%d") for d in available_dates]}


@router.get("/available-slots")
async def get_available_slots(
    date: str,
    service_id: str,
    room_id: str = None,
    staff_id: str = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
):
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usá YYYY-MM-DD.")

    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")

    if room_id:
        room = dbs.get_room(db, room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Sala no encontrada.")
        if not dbs.room_in_service(db, service_id, room_id):
            raise HTTPException(status_code=400, detail="La sala no está asignada a este servicio.")

    if staff_id:
        staff_member = dbs.get_staff(db, staff_id)
        if not staff_member:
            raise HTTPException(status_code=404, detail="Profesional no encontrado.")

    duration = service.duration_minutes
    start_of_day = datetime.combine(target_date, time(9, 0))
    end_of_day = datetime.combine(target_date, time(18, 0))

    slots = []
    current = start_of_day
    while current + timedelta(minutes=duration) <= end_of_day:
        slot_end = current + timedelta(minutes=duration)
        conflicts = dbs.check_booking_conflicts(db, current, slot_end, room_id=room_id, staff_id=staff_id, for_update=False)
        if conflicts:
            current += timedelta(minutes=duration)
            continue
        if staff_id:
            avail_error = dbs.check_staff_availability(db, staff_id, current, slot_end)
            if avail_error:
                current += timedelta(minutes=duration)
                continue
        slots.append({"time": current.strftime("%H:%M"), "iso": current.isoformat()})
        current += timedelta(minutes=duration)
    return slots


# =========================================================================
# STAFF
# =========================================================================

@router.get("/staff")
async def list_staff(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff = dbs.get_staff_list(db)
    context = {"request": request, "staff": staff, "user": user}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="staff/list.html", context=context)
    context["content_template"] = "staff/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/staff")
async def create_staff(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    from ..core.auth import get_password_hash
    form = await request.form()
    name = form.get("name")
    email = form.get("email", "").strip()
    password = form.get("password", "").strip()

    existing = dbs.get_staff_by_name(db, name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Ya existe un profesional llamado '{name}'.")

    if email:
        email_exists = dbs.get_user_by_email(db, email)
        if email_exists:
            raise HTTPException(status_code=400, detail=f"El email '{email}' ya está en uso.")

    new_staff = dbs.create_staff(db, name, form.get("specialty"))

    if email and password:
        prof_user = dbs.create_user(db, email=email,
                                     hashed_password=get_password_hash(password),
                                     full_name=name, role="professional")
        dbs.update_staff_user_id(db, new_staff, prof_user.id)

    dbs.finish_staff_creation(db)
    staff = dbs.get_staff_list(db)
    return templates.TemplateResponse(request=request, name="staff/table_rows.html", context={"staff": staff})


@router.get("/staff/{staff_id}/edit")
async def edit_staff_form(
    staff_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff_member = dbs.get_staff(db, staff_id)
    if not staff_member:
        raise HTTPException(status_code=404, detail="El miembro del personal no existe.")
    return templates.TemplateResponse(request=request, name="staff/edit_modal.html", context={"staff_member": staff_member})


@router.post("/staff/{staff_id}")
async def update_staff(
    staff_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    from ..core.auth import get_password_hash
    staff_member = dbs.get_staff(db, staff_id)
    if not staff_member:
        raise HTTPException(status_code=404, detail="El miembro del personal no existe o no tienes permiso para modificarlo.")

    form = await request.form()
    name = form.get("name")
    specialty = form.get("specialty")
    active = form.get("active") == "on"
    email = form.get("email", "").strip()
    password = form.get("password", "").strip()

    if email:
        existing_user = dbs.get_user_by_email(db, email)
        if existing_user and existing_user.id != (staff_member.user_id if staff_member.user else None):
            raise HTTPException(status_code=400, detail=f"El email '{email}' ya está en uso.")
        if staff_member.user:
            staff_member.user.email = email
            if password:
                staff_member.user.hashed_password = get_password_hash(password)
        else:
            prof_user = dbs.create_user(db, email=email,
                                         hashed_password=get_password_hash(password or "changeme"),
                                         full_name=name, role="professional")
            dbs.update_staff_user_id(db, staff_member, prof_user.id)

    dbs.update_staff_basic(db, staff_member, name, specialty, active)
    staff = dbs.get_staff_list(db)
    return templates.TemplateResponse(request=request, name="staff/table_rows.html", context={"staff": staff})


@router.delete("/staff/{staff_id}")
async def delete_staff(
    staff_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff_member = dbs.get_staff(db, staff_id)
    if not staff_member:
        raise HTTPException(status_code=404, detail="El miembro del personal no existe.")
    dbs.delete_staff(db, staff_member)
    staff = dbs.get_staff_list(db)
    return templates.TemplateResponse(request=request, name="staff/table_rows.html", context={"staff": staff})


@router.get("/staff/{staff_id}/history")
async def staff_history(
    staff_id: str,
    request: Request,
    year: int = None,
    month: int = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff_member = dbs.get_staff(db, staff_id)
    if not staff_member:
        raise HTTPException(status_code=404, detail="El miembro del personal no existe.")

    today = date.today()
    filter_year = year or today.year
    filter_month = month or today.month

    bookings = dbs.get_staff_bookings_month(db, staff_id, filter_year, filter_month)
    total_revenue = sum([b.service.price for b in bookings if b.service and b.service.price])
    display_date = date(filter_year, filter_month, 1)

    context = {
        "request": request, "staff_member": staff_member, "bookings": bookings,
        "total_revenue": total_revenue, "current_month_name": display_date.strftime('%B %Y'),
        "filters": {"year": filter_year, "month": filter_month},
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="staff/history.html", context=context)
    context["content_template"] = "staff/history.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


# =========================================================================
# CUSTOMERS
# =========================================================================

@router.get("/customers")
async def list_customers(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    customers = dbs.get_customers(db)
    context = {"request": request, "customers": customers, "user": user}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="customers/list.html", context=context)
    context["content_template"] = "customers/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/customers")
async def create_customer(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    form = await request.form()
    phone = form.get("phone_number")
    existing = dbs.get_customer_by_phone(db, phone)
    if existing:
        raise HTTPException(status_code=400, detail=f"Ya existe un cliente con el teléfono '{phone}'.")
    dbs.create_customer(db, phone, full_name=form.get("full_name"), email=form.get("email"))
    customers = dbs.get_customers(db)
    return templates.TemplateResponse(request=request, name="customers/table_rows.html", context={"customers": customers})


@router.delete("/customers/{customer_id}")
async def delete_customer(
    customer_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    customer = dbs.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="El cliente no existe.")
    dbs.delete_customer(db, customer)
    customers = dbs.get_customers(db)
    return templates.TemplateResponse(request=request, name="customers/table_rows.html", context={"customers": customers})


# =========================================================================
# PAYMENTS
# =========================================================================

def _parse_date(dt_str):
    if dt_str:
        try:
            return datetime.strptime(dt_str, "%Y-%m-%d")
        except ValueError:
            pass
    return None


@router.get("/payments")
async def list_payments(
    request: Request,
    customer_id: str = None,
    status: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    payments = dbs.get_payments(db, customer_id=customer_id, status=status,
                                 date_from=_parse_date(date_from),
                                 date_to=_parse_date(date_to) + timedelta(days=1) if _parse_date(date_to) else None)
    total = sum(p.amount for p in payments if p.status == "paid")

    all_bookings = dbs.get_bookings(db)
    unpaid_total = Decimal("0")
    unpaid_count = 0
    for b in all_bookings:
        paid = any(py.status in ("paid", "approved") for py in b.payments)
        if not paid and b.service and b.service.price:
            unpaid_total += b.service.price
            unpaid_count += 1

    customers = dbs.get_customers_sorted_by_name(db)
    context = {
        "request": request, "user": user, "payments": payments,
        "total_collected": total, "total_pending": unpaid_total,
        "unpaid_count": unpaid_count, "customers": customers,
        "filters": {"customer_id": customer_id or "", "status": status or "",
                     "date_from": date_from or "", "date_to": date_to or ""},
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="payments/list.html", context=context)
    context["content_template"] = "payments/list.html"
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/payments")
async def create_payment(
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    form = await request.form()
    booking_id = form.get("booking_id")
    customer_id = form.get("customer_id")
    amount_str = form.get("amount")
    payment_method = form.get("payment_method", "cash")
    pmt_status = form.get("status", "paid")
    notes = form.get("notes")

    try:
        amount = Decimal(amount_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Monto inválido.")

    dbs.create_payment(db, amount, booking_id=booking_id if booking_id else None,
                       customer_id=customer_id, payment_method=payment_method,
                       status=pmt_status, notes=notes)
    bookings = dbs.get_bookings(db)
    return templates.TemplateResponse(request=request, name="bookings/table_rows.html", context={"bookings": bookings})


@router.get("/payments/{payment_id}/edit")
async def edit_payment_form(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    payment = dbs.get_payment(db, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    return templates.TemplateResponse(request=request, name="payments/edit_modal.html", context={"payment": payment})


@router.post("/payments/{payment_id}")
async def update_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    payment = dbs.get_payment(db, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    form = await request.form()
    try:
        amount = Decimal(form.get("amount"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Monto inválido.")
    dbs.update_payment_fields(db, payment, amount=amount,
                               payment_method=form.get("payment_method", payment.payment_method),
                               status=form.get("status", payment.status),
                               notes=form.get("notes"))
    return Response(status_code=200, headers={"HX-Trigger": "paymentUpdated"})


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    payment = dbs.get_payment(db, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    dbs.delete_payment(db, payment)
    payments = dbs.get_payments(db)
    return templates.TemplateResponse(request=request, name="payments/table_rows.html", context={"payments": payments})


@router.get("/payments/client/{customer_id}")
async def client_payment_history(
    customer_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    customer = dbs.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    payments = dbs.get_payments_by_customer(db, customer_id)
    bookings = dbs.get_bookings_by_customer(db, customer_id)
    total_service_amount = sum(b.service.price for b in bookings if b.service and b.service.price)
    total_paid = sum(p.amount for p in payments if p.status == "paid")
    total_pending = max(total_service_amount - total_paid, 0)

    return templates.TemplateResponse(request=request, name="payments/client_history.html", context={
        "request": request, "customer": customer, "payments": payments,
        "total_service_amount": total_service_amount, "total_paid": total_paid,
        "total_pending": total_pending, "bookings": bookings,
    })


@router.get("/payments/link/{booking_id}")
async def generate_payment_link(
    booking_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")

    existing = dbs.get_payment_by_booking(db, booking_id)
    already_paid = existing.status == "paid" if existing else False

    return templates.TemplateResponse(request=request, name="payments/link_modal.html", context={
        "booking": booking, "has_mercadopago": False,
        "already_paid": already_paid, "existing_payment": existing,
    })


# =========================================================================
# STAFF SETTLEMENTS
# =========================================================================

@router.get("/staff/{staff_id}/settlements")
async def list_staff_settlements(
    staff_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff = dbs.get_staff(db, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff no encontrado.")
    settlements = dbs.get_staff_settlements(db, staff_id)
    total_commission = sum(s.total_commission for s in settlements if s.status == "paid")
    return templates.TemplateResponse(request=request, name="staff/settlements.html", context={
        "request": request, "staff_member": staff, "settlements": settlements,
        "total_paid_commission": total_commission,
    })


@router.post("/staff/{staff_id}/settlements/generate")
async def generate_staff_settlement(
    staff_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff = dbs.get_staff(db, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff no encontrado.")

    form = await request.form()
    try:
        period_start = datetime.strptime(form.get("period_start"), "%Y-%m-%d").date()
        period_end = datetime.strptime(form.get("period_end"), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Fechas inválidas. Usá formato DD/MM/AAAA.")

    period_end_dt = datetime.combine(period_end, datetime.max.time())
    period_start_dt = datetime.combine(period_start, datetime.min.time())

    bookings = dbs.get_staff_bookings_for_period(db, staff_id, period_start_dt, period_end_dt)
    if not bookings:
        raise HTTPException(status_code=400, detail="No hay turnos para este profesional en el período seleccionado.")

    settlement = dbs.create_settlement_head(db, staff_id, period_start, period_end, len(bookings))

    total_amount = Decimal("0")
    total_commission = Decimal("0")
    for b in bookings:
        service = b.service
        price = service.price if service else Decimal("0")
        comm_type = service.commission_type if service and service.commission_type else None
        comm_value = service.commission_value if service else None
        comm_amount = Decimal("0")
        if comm_type == "percentage" and comm_value and price:
            comm_amount = price * (comm_value / Decimal("100"))
        elif comm_type == "fixed" and comm_value:
            comm_amount = comm_value
        dbs.add_settlement_item(
            db, settlement.id, b.id,
            service.name if service else "Servicio", price,
            comm_type, comm_value, comm_amount, b.start_time.date(),
        )
        total_amount += price
        total_commission += comm_amount

    dbs.finalize_settlement(db, settlement, total_amount, total_commission)
    return templates.TemplateResponse(request=request, name="staff/settlement_detail.html", context={
        "request": request, "settlement": settlement, "staff_member": staff,
    })


@router.get("/staff/{staff_id}/settlements/{settlement_id}")
async def view_staff_settlement(
    staff_id: str, settlement_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    staff = dbs.get_staff(db, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff no encontrado.")
    settlement = dbs.get_settlement(db, settlement_id, staff_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    return templates.TemplateResponse(request=request, name="staff/settlement_detail.html", context={
        "request": request, "settlement": settlement, "staff_member": staff,
    })


@router.post("/staff/{staff_id}/settlements/{settlement_id}/mark-paid")
async def mark_settlement_paid(
    staff_id: str, settlement_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: domain.User = Depends(get_current_user_required),
    templates: Jinja2Templates = Depends(get_templates),
):
    settlement = dbs.get_settlement(db, settlement_id, staff_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    dbs.mark_settlement_paid(db, settlement)
    return Response(status_code=200, headers={"HX-Trigger": "settlementUpdated"})
