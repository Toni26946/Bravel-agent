"""Spremanje uploadanih fotografija na disk — uz automatsko smanjivanje.

Fotografije s mobitela su često 2–5 MB i otvaraju se sporo. Zato svaku sliku pri
uploadu smanjimo: najdulju stranicu skaliramo na `settings.slika_max_px` i spremimo
kao JPEG (kvaliteta `settings.slika_kvaliteta`). Tako 2 MB fotka padne na ~200–350 KB
i brzo se otvara. Sve slike u aplikaciji idu kroz `spremi_sliku`, pa je ovo jedino
mjesto koje treba dirati (dijelovi, narudžbe, primke, štete, prijave, slike vozila).
"""
import io
import logging
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import settings

log = logging.getLogger("storage")

DOZVOLJENI = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_EKST = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def _dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _smanji(podaci: bytes, content_type: str) -> tuple[bytes, str]:
    """Smanji sliku i vrati (novi_bajtovi, ekstenzija). Ako nešto ne uspije ili
    smanjivanje nema smisla, vrati original (robusno — upload nikad ne smije pući).

    GIF se NE dira (može biti animiran). Ostale slike skaliramo na najdulju stranicu
    `slika_max_px` i spremamo kao JPEG; slike s prozirnošću ostaju PNG (da se ne pocrni).
    """
    max_px = settings.slika_max_px or 0
    if max_px <= 0 or content_type == "image/gif":
        return podaci, _EKST.get(content_type, ".bin")
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(podaci))
        img = ImageOps.exif_transpose(img)  # ispravi orijentaciju s mobitela (EXIF)
        ima_prozirnost = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)

        # Skaliraj samo prema DOLJE (nikad ne povećavaj) ako je veća od praga.
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.LANCZOS)

        buf = io.BytesIO()
        if ima_prozirnost:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), ".png"
        img.convert("RGB").save(buf, format="JPEG", quality=settings.slika_kvaliteta, optimize=True)
        novi = buf.getvalue()
        # Ako je original slučajno manji (već optimiran), zadrži original s ispravnom ekstenzijom.
        if len(novi) >= len(podaci) and content_type == "image/jpeg":
            return podaci, ".jpg"
        return novi, ".jpg"
    except Exception as e:  # noqa: BLE001 — upload ne smije pući zbog problematične slike
        log.warning("Smanjivanje slike nije uspjelo (%s) — spremam original.", e)
        return podaci, _EKST.get(content_type, ".bin")


def spremi_sliku(file: UploadFile) -> str:
    if file.content_type not in DOZVOLJENI:
        raise HTTPException(status_code=415, detail="Podržane su samo slike (JPG, PNG, WEBP, GIF)")
    podaci = file.file.read()
    if len(podaci) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Slika je veća od {settings.max_upload_mb} MB")
    podaci, ekst = _smanji(podaci, file.content_type)
    naziv = secrets.token_hex(16) + ekst
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
