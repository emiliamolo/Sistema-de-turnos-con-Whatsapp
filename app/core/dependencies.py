"""
Dependency injectors for the API routers.
"""

from fastapi import Request, Depends
from fastapi.templating import Jinja2Templates


async def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates
