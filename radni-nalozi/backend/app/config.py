"""Konfiguracija aplikacije (čita se iz env varijabli / .env)."""
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("config")

# Placeholder koji se NE smije koristiti u produkciji.
_ZADANA_TAJNA = "promijeni-me-u-produkciji"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Baza: Postgres u produkciji, SQLite kao fallback za lokalni razvoj.
    database_url: str = "sqlite:///./radni_nalozi.db"

    # JWT
    jwt_secret: str = _ZADANA_TAJNA
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 dana

    # Upload fotografija
    upload_dir: str = "./uploads"
    max_upload_mb: int = 15

    # Izgrađeni frontend (PWA). Ako mapa postoji, backend je poslužuje na "/".
    frontend_dist: str = "./static"

    # CORS (zarezom odvojene domene; "*" = sve)
    cors_origins: str = "*"

    # AI glasovni unos (Claude) — opcionalno; ako prazno, endpoint vraća 503
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

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


@lru_cache
def jwt_secret() -> str:
    """Vraća efektivni JWT ključ.

    Ako je JWT_SECRET eksplicitno postavljen (env/secret), koristi se. Inače se
    generira nasumičan ključ i trajno pohranjuje uz podatke (npr. na Fly volumenu),
    pa preživljava restarte, ali nikad nije poznati zadani placeholder.
    """
    if settings.jwt_secret and settings.jwt_secret != _ZADANA_TAJNA:
        return settings.jwt_secret

    datoteka = Path(settings.upload_dir).parent / ".jwt_secret"
    try:
        if datoteka.exists():
            postojeci = datoteka.read_text(encoding="utf-8").strip()
            if postojeci:
                return postojeci
        datoteka.parent.mkdir(parents=True, exist_ok=True)
        novi = secrets.token_urlsafe(48)
        datoteka.write_text(novi, encoding="utf-8")
        try:
            os.chmod(datoteka, 0o600)
        except OSError:
            pass
        log.warning(
            "JWT_SECRET nije postavljen — generiran je nasumičan ključ i pohranjen u %s. "
            "Za višestruke instance postavite JWT_SECRET kao tajnu.",
            datoteka,
        )
        return novi
    except OSError:
        # Krajnji fallback: nasumičan ključ po procesu (tokeni ne preživljavaju restart,
        # ali nikad nije nesigurni zadani placeholder).
        log.error("Ne mogu pohraniti JWT ključ; koristim privremeni ključ po procesu.")
        return secrets.token_urlsafe(48)
