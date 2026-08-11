"""Konfiguracija aplikacije (čita se iz env varijabli / .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Baza: Postgres u produkciji, SQLite kao fallback za lokalni razvoj.
    database_url: str = "sqlite:///./radni_nalozi.db"

    # JWT
    jwt_secret: str = "promijeni-me-u-produkciji"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 dana

    # Upload fotografija
    upload_dir: str = "./uploads"
    max_upload_mb: int = 15

    # Izgrađeni frontend (PWA). Ako mapa postoji, backend je poslužuje na "/".
    frontend_dist: str = "./static"

    # CORS (zarezom odvojene domene; "*" = sve)
    cors_origins: str = "*"

    # Web Push (VAPID) — opcionalno; ako prazno, push se ne šalje
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:info@bravel.hr"

    # Početni voditelj (seed) — kreira se pri prvom pokretanju ako baza je prazna
    seed_admin_username: str = "voditelj"
    seed_admin_password: str = "bravel123"
    seed_admin_ime: str = "Glavni voditelj"

    @property
    def cors_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
