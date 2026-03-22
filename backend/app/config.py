from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL:    str = "postgresql+asyncpg://kiosk:kiosk_pass@localhost:5432/restaurant_db"
    SECRET_KEY:      str = "change-this-secret"
    ADMIN_USERNAME:  str = "admin"
    ADMIN_PASSWORD:  str = "admin123"
    UPLOAD_DIR:      str = "app/static/uploads"
    HOST:            str = "0.0.0.0"
    PORT:            int = 8000

    class Config:
        env_file = ".env"


settings = Settings()
