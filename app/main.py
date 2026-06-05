from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
from .api import whatsapp, admin, auth, professional
from .core.database import engine 
from .models.domain import Base
from contextlib import asynccontextmanager
from .core.setup import create_default_user
from .core.paths import get_template_dir, get_static_dir

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    create_default_user()
    yield

app = FastAPI(title="Turnos API", lifespan=lifespan)

# Mount static files with dynamic path
template_dir = get_template_dir()
static_dir = get_static_dir()

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates = Jinja2Templates(directory=template_dir)
templates.env.globals["now"] = lambda: datetime.now(timezone.utc)

# Make templates available to the app for routers
app.state.templates = templates

# Routers
app.include_router(whatsapp.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(professional.router)

@app.get("/")
async def root():
    return {"message": "Welcome to Turnos API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
