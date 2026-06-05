from fastapi import APIRouter, Request, Depends, Response, HTTPException, status, Body, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, date, time, timezone
from typing import Optional
from decimal import Decimal

from ..core.database import get_db
from ..core.dependencies import get_templates
from ..core.auth import authenticate_user, create_access_token, get_password_hash
from ..core.config import settings
from ..models import domain
from ..services import db_service as dbs

router = APIRouter(prefix="/professional", tags=["professional"])

PROFESSIONAL_TOKEN_COOKIE = "professional_token"


def get_current_professional(request: Request, db: Session = Depends(get_db)) -> domain.User:
    token_cookie = request.cookies.get(PROFESSIONAL_TOKEN_COOKIE)
    if not token_cookie or not token_cookie.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No has iniciado sesión como profesional.")
    token = token_cookie.split(" ")[1]
    try:
        from jose import jwt, JWTError
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role != "professional":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o no eres profesional.")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión expirada o alterada.")
    user = dbs.get_user_by_id_and_role(db, user_id, "professional")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Profesional no encontrado.")
    return user


def get_current_professional_with_staff(request: Request, db: Session = Depends(get_db)):
    user = get_current_professional(request, db)
    staff = dbs.get_staff_by_user_id(db, user.id)
    if not staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés un perfil de staff asociado.")
    if not staff.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu perfil de profesional está desactivado.")
    return user, staff


ROOM_PALETTE = [
    "#15803d", "#0f766e", "#047857", "#4d7c0f",
    "#166534", "#115e59", "#065f46", "#3f6212",
    "#14532d", "#134e4a", "#064e3b", "#365314",
]


def get_room_color(room_id):
    if room_id:
        return ROOM_PALETTE[room_id.int % len(ROOM_PALETTE)]
    return "#94a3b8"


# =========================================================================
# AUTH
# =========================================================================

@router.get("/login")
async def login_page(request: Request, templates: Jinja2Templates = Depends(get_templates)):
    return templates.TemplateResponse(request=request, name="professional/login.html", context={})


@router.post("/login")
async def login(
    response: Response,
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user = authenticate_user(db, email, password)
    if not user or user.role != "professional":
        return templates.TemplateResponse(request=request, name="professional/login.html",
                                          context={"error": "Email o contraseña incorrectos, o no tenés acceso como profesional."})
    staff = dbs.get_staff_by_user_id(db, user.id)
    if not staff or not staff.active:
        return templates.TemplateResponse(request=request, name="professional/login.html",
                                          context={"error": "Tu perfil de profesional no está activo. Contactá al administrador."})

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "staff_id": str(staff.id),
    }
    access_token = create_access_token(data=token_data, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    resp = RedirectResponse(url="/professional/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(key=PROFESSIONAL_TOKEN_COOKIE, value=f"Bearer {access_token}",
                    httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                    samesite="lax", secure=settings.ENVIRONMENT == "production")
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/professional/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(PROFESSIONAL_TOKEN_COOKIE)
    return resp


# =========================================================================
# DASHBOARD
# =========================================================================

@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    services = dbs.get_active_services(db)
    context = {"request": request, "user": user, "staff": staff, "services": services,
               "content_template": "professional/dashboard_content.html"}
    return templates.TemplateResponse(request=request, name="professional/dashboard.html", context=context)


# =========================================================================
# AVAILABILITY
# =========================================================================

@router.get("/availability")
async def availability_page(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    availabilities = dbs.get_staff_availabilities(db, staff.id)
    exceptions = dbs.get_staff_exceptions(db, staff.id)
    days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    context = {"request": request, "user": user, "staff": staff,
               "availabilities": availabilities, "exceptions": exceptions, "days": days}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="professional/availability.html", context=context)
    context["content_template"] = "professional/availability.html"
    return templates.TemplateResponse(request=request, name="professional/dashboard.html", context=context)


@router.post("/availability")
async def save_availability(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    form = await request.form()
    dbs.delete_staff_availabilities(db, staff.id)
    for day in range(7):
        start_val = form.get(f"start_{day}")
        end_val = form.get(f"end_{day}")
        if start_val and end_val:
            try:
                s = time.fromisoformat(start_val)
                e = time.fromisoformat(end_val)
                if s >= e:
                    continue
                dbs.add_staff_availability(db, staff.id, day, s, e)
            except (ValueError, TypeError):
                continue
    db.commit()

    days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    availabilities = dbs.get_staff_availabilities(db, staff.id)
    exceptions = dbs.get_staff_exceptions(db, staff.id)
    context = {"request": request, "user": user, "staff": staff,
               "availabilities": availabilities, "exceptions": exceptions, "days": days}
    return templates.TemplateResponse(request=request, name="professional/availability.html", context=context)


# =========================================================================
# EXCEPTIONS
# =========================================================================

@router.post("/exceptions")
async def add_exception(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    form = await request.form()
    exception_date = form.get("exception_date")
    reason = form.get("reason", "")
    if not exception_date:
        raise HTTPException(status_code=400, detail="La fecha es requerida.")
    try:
        exc_date = date.fromisoformat(exception_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Formato de fecha inválido.")

    existing = dbs.get_staff_exception_by_date(db, staff.id, exc_date)
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe una excepción para esa fecha.")
    dbs.create_staff_exception(db, staff.id, exc_date, reason)
    return RedirectResponse(url="/professional/availability", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/exceptions/{exception_id}")
async def delete_exception(
    exception_id: str,
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    exc = dbs.get_staff_exception(db, exception_id, staff.id)
    if not exc:
        raise HTTPException(status_code=404, detail="Excepción no encontrada.")
    dbs.delete_staff_exception(db, exc)
    return RedirectResponse(url="/professional/availability", status_code=status.HTTP_303_SEE_OTHER)


# =========================================================================
# SERVICES TOGGLE
# =========================================================================

@router.get("/services")
async def services_page(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    all_services = dbs.get_active_services(db)
    my_service_ids = {s.id for s in staff.services_offered}
    context = {"request": request, "user": user, "staff": staff, "services": all_services, "my_service_ids": my_service_ids}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="professional/services_toggle.html", context=context)
    context["content_template"] = "professional/services_toggle.html"
    return templates.TemplateResponse(request=request, name="professional/dashboard.html", context=context)


@router.post("/services/{service_id}/toggle")
async def toggle_service(
    service_id: str,
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    service = dbs.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    dbs.toggle_staff_service(db, staff, service)

    all_services = dbs.get_active_services(db)
    my_service_ids = {s.id for s in staff.services_offered}
    context = {"request": request, "user": user, "staff": staff, "services": all_services, "my_service_ids": my_service_ids}
    return templates.TemplateResponse(request=request, name="professional/services_toggle.html", context=context)


# =========================================================================
# CALENDAR
# =========================================================================

@router.get("/calendar")
async def calendar_view(
    request: Request,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)
    context = {"request": request, "user": user, "staff": staff}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="professional/calendar.html", context=context)
    context["content_template"] = "professional/calendar.html"
    return templates.TemplateResponse(request=request, name="professional/dashboard.html", context=context)


@router.get("/api/calendar/events")
async def get_calendar_events(
    start: str, end: str,
    db: Session = Depends(get_db),
    request: Request = None,
):
    user, staff = get_current_professional_with_staff(request, db)
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    bookings = dbs.get_professional_bookings(db, staff.id, start_dt, end_dt)
    events = []
    for b in bookings:
        events.append({
            "id": str(b.id),
            "title": f"{b.customer.full_name if b.customer else 'Cliente'} - {b.service.name if b.service else 'Servicio'}",
            "start": b.start_time.isoformat(),
            "end": b.end_time.isoformat(),
            "color": get_room_color(b.room_id),
            "status": b.status,
        })
    return events


@router.put("/api/calendar/events/{booking_id}")
async def update_calendar_event(
    booking_id: str,
    start: str = Body(...),
    end: str = Body(...),
    db: Session = Depends(get_db),
    request: Request = None,
):
    user, staff = get_current_professional_with_staff(request, db)
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Turno no encontrado o no te pertenece.")

    try:
        new_start = datetime.fromisoformat(start)
        new_end = datetime.fromisoformat(end)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    if new_start >= new_end:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser anterior al fin.")

    conflict = dbs.check_professional_booking_conflict(
        db, staff.id, new_start, new_end, booking_id,
    )
    if conflict:
        raise HTTPException(status_code=409, detail="Ya tenés otro turno en ese horario.")

    avail_error = dbs.check_staff_availability_simple(db, staff.id, new_start, new_end)
    if avail_error:
        raise HTTPException(status_code=409, detail=avail_error)

    try:
        dbs.update_booking_times(db, booking, new_start, new_end)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El horario ya no está disponible. Otro turno fue reservado en simultáneo.")
    return {"ok": True, "id": booking_id}


@router.post("/api/calendar/events/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    request: Request = None,
):
    user, staff = get_current_professional_with_staff(request, db)
    booking = dbs.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Turno no encontrado o no te pertenece.")
    dbs.cancel_booking(db, booking)
    return {"ok": True, "id": booking_id}


# =========================================================================
# PAYMENTS
# =========================================================================

@router.get("/payments")
async def payments_page(
    request: Request,
    status: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    templates: Jinja2Templates = Depends(get_templates),
):
    user, staff = get_current_professional_with_staff(request, db)

    df = None
    dt = None
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            pass

    payments = dbs.get_staff_payments(db, staff.id, status=status, date_from=df, date_to=dt)
    total_collected = sum(p.amount for p in payments if p.status == "paid")

    staff_bookings = dbs.get_bookings_by_staff(db, staff.id)
    unpaid_total = Decimal("0")
    unpaid_count = 0
    for b in staff_bookings:
        paid = any(py.status in ("paid", "approved") for py in b.payments)
        if not paid and b.service and b.service.price:
            unpaid_total += b.service.price
            unpaid_count += 1

    context = {
        "request": request, "user": user, "staff": staff, "payments": payments,
        "total_collected": total_collected, "total_pending": unpaid_total, "unpaid_count": unpaid_count,
        "filters": {"status": status or "", "date_from": date_from or "", "date_to": date_to or ""},
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request=request, name="professional/payments.html", context=context)
    context["content_template"] = "professional/payments.html"
    return templates.TemplateResponse(request=request, name="professional/dashboard.html", context=context)
