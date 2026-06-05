from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # ==================== APPLICATION ====================
    PROJECT_NAME: str = "Turnos"
    ENVIRONMENT: str = "development"
    
    # ==================== DATABASE ====================
    DATABASE_URL: str
    REDIS_URL: str
    
    # ==================== SECURITY ====================
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # ==================== AI (GEMINI) ====================
    GEMINI_API_KEY: Optional[str] = None

    # ==================== WHATSAPP ====================
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    
    # ==================== SUPER-ADMIN SETUP ====================
    CREATE_DEFAULT_SUPERADMIN: bool = False  # Always False in production
    SUPERADMIN_EMAIL: str = "admin@turnos.io"
    SUPERADMIN_PASSWORD: str
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore" # Ignora POSTGRES_USER y demás variables de Docker sin romper
    )

settings = Settings()
