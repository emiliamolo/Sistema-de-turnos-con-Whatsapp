from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Form
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import timedelta
import logging

from ..core.database import get_db
from ..core.dependencies import get_templates
from ..core.auth import authenticate_user, create_access_token
from ..core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# =========================================================================
# LOGIN
# =========================================================================

@router.get("/login")
async def login_page(request: Request, templates: Jinja2Templates = Depends(get_templates)):
    return templates.TemplateResponse(request=request, name="auth/login.html", context={})


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
    if not user:
        return templates.TemplateResponse(request=request, name="auth/login.html", context={"error": "Email o contraseña incorrectos"})

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
    }
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    template_response = templates.TemplateResponse(request=request, name="auth/login_success.html", context={})
    template_response.set_cookie(
        key="access_token", value=f"Bearer {access_token}",
        httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax", secure=settings.ENVIRONMENT == "production",
    )
    return template_response


@router.get("/logout")
async def logout(response: Response):
    response = Response(status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Location"] = "/auth/login"
    response.delete_cookie("access_token")
    return response
