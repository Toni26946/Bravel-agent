"""Spremanje uploadanih fotografija na disk."""
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import settings

DOZVOLJENI = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_EKST = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def _dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def spremi_sliku(file: UploadFile) -> str:
    if file.content_type not in DOZVOLJENI:
        raise HTTPException(status_code=415, detail="Podržane su samo slike (JPG, PNG, WEBP, GIF)")
    podaci = file.file.read()
    if len(podaci) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Slika je veća od {settings.max_upload_mb} MB")
    naziv = secrets.token_hex(16) + _EKST.get(file.content_type, ".bin")
    putanja = _dir() / naziv
    with open(putanja, "wb") as f:
        f.write(podaci)
    # Vraćamo relativnu web putanju (poslužuje se preko /uploads)
    return f"/uploads/{naziv}"


def obrisi_sliku(web_putanja: str) -> None:
    try:
        naziv = os.path.basename(web_putanja)
        (Path(settings.upload_dir) / naziv).unlink(missing_ok=True)
    except Exception:
        pass
