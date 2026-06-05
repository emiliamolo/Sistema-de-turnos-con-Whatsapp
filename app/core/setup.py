from sqlalchemy.orm import Session
from .database import SessionLocal
from .auth import get_password_hash
from .config import settings
from ..models import domain
from ..services import db_service as dbs
import logging

logger = logging.getLogger(__name__)


def create_default_user():
    if not settings.CREATE_DEFAULT_SUPERADMIN:
        logger.info("CREATE_DEFAULT_SUPERADMIN=False, skipping default user creation")
        return

    db = SessionLocal()
    try:
        super_user = dbs.get_user_by_email(db, settings.SUPERADMIN_EMAIL)
        if not super_user:
            super_user = domain.User(
                email=settings.SUPERADMIN_EMAIL,
                hashed_password=get_password_hash(settings.SUPERADMIN_PASSWORD),
                full_name="Administrador",
                role="admin",
            )
            db.add(super_user)
            db.commit()
            logger.info(f"Created default admin user: {settings.SUPERADMIN_EMAIL}")
            logger.warning("CHANGE YOUR PASSWORD IMMEDIATELY AFTER FIRST LOGIN!")
        else:
            logger.info(f"Admin user already exists: {settings.SUPERADMIN_EMAIL}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating default user: {e}")
    finally:
        db.close()
