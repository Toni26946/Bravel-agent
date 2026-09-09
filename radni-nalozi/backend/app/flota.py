"""Integracija s Flota OS (GPS).

Periodično dohvaća pozicije vozila i, ako vozilo s nalogom u statusu "u radu"
napusti geokrug radione, javlja voditeljima (jednom po izlasku) da provjere je
li vozilo završeno. Radi samo ako je konfigurirano (ključ/račun + koordinate).
"""
import asyncio
import logging
import math

import httpx

from .config import settings
from .database import SessionLocal
from .models import Nalog, StatusNaloga, Uloga
from .push import obavijesti_ulogu

log = logging.getLogger("flota")

_token: str | None = None  # JWT za lokalni račun (opcija bez servisnog ključa)


def konfigurirano() -> bool:
    ima_auth = bool(settings.flota_service_key) or bool(settings.flota_email and settings.flota_lozinka)
    ima_lokaciju = bool(settings.radiona_lat) and bool(settings.radiona_lon)
    return ima_auth and ima_lokaciju


def udaljenost_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine udaljenost u metrima."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def _prijava(client: httpx.AsyncClient) -> str | None:
    """Lokalni račun (email+lozinka) → JWT (kad nema servisnog ključa)."""
    global _token
    try:
        r = await client.post(
            "/api/login",
            json={"email": settings.flota_email, "lozinka": settings.flota_lozinka},
        )
        if r.status_code == 200:
            d = r.json()
            _token = d.get("access_token") or d.get("token")
            return _token
        log.warning("Flota prijava HTTP %s", r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("Flota prijava neuspjela: %s", e)
    return None


async def dohvati_pozicije() -> dict | None:
    """Vrati {gb: {lat, lon, brzina, vrijeme, zastarjelo}} ili None na grešku."""
    global _token
    base = settings.flota_api_base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=20) as client:
        if settings.flota_service_key:
            headers = {"X-Service-Key": settings.flota_service_key}
        else:
            if not _token:
                await _prijava(client)
            headers = {"Authorization": f"Bearer {_token}"} if _token else {}
        try:
            r = await client.get("/api/flota/pozicije", headers=headers)
            # Token istekao (12 h) → ponovna prijava pa novi pokušaj.
            if r.status_code == 401 and not settings.flota_service_key:
                await _prijava(client)
                headers = {"Authorization": f"Bearer {_token}"} if _token else {}
                r = await client.get("/api/flota/pozicije", headers=headers)
            if r.status_code != 200:
                log.warning("Flota pozicije HTTP %s", r.status_code)
                return None
            data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("Flota pozicije greška: %s", e)
            return None
    # Flota OS greške dolaze kao {"greska": ...} uz HTTP 200 — provjeri tijelo.
    if isinstance(data, dict) and data.get("greska"):
        log.warning("Flota pozicije greška u tijelu: %s", data["greska"])
        return None
    zastarjelo = bool(data.get("zastarjelo")) if isinstance(data, dict) else False
    izlaz: dict = {}
    for v in (data.get("vozila") or []):
        gb = v.get("gb")
        if not gb or v.get("lat") is None or v.get("lon") is None:
            continue  # vozila bez GB-a ili bez pozicije preskačemo
        izlaz[str(gb)] = {
            "lat": float(v["lat"]), "lon": float(v["lon"]),
            "brzina": v.get("brzina"), "vrijeme": v.get("vrijeme"),
            "zastarjelo": zastarjelo,
        }
    return izlaz


def obradi_pozicije(pozicije: dict) -> int:
    """Za aktivne (u radu) naloge provjeri je li vozilo izvan geokruga radione.

    Vraća broj poslanih obavijesti. Javlja se jednom po izlasku; kad se vozilo
    vrati u krug, zastavica se resetira pa se sljedeći izlazak opet javi.
    """
    poslano = 0
    with SessionLocal() as db:
        aktivni = db.query(Nalog).filter(Nalog.status == StatusNaloga.u_radu).all()
        promjena = False
        for n in aktivni:
            gb = n.vozilo.gb if n.vozilo else None
            p = pozicije.get(str(gb)) if gb else None
            if not p or p.get("zastarjelo"):
                continue  # nema svježe pozicije za ovaj kamion
            d = udaljenost_m(p["lat"], p["lon"], settings.radiona_lat, settings.radiona_lon)
            vani = d > settings.radiona_radius_m
            if vani and not n.izvan_radione_javljeno:
                obavijesti_ulogu(
                    db, Uloga.voditelj, "Vozilo je napustilo radionu",
                    f"{gb}: nalog je još u radu, a vozilo je ~{int(d)} m izvan radione. "
                    f"Je li vozilo završeno?",
                    url=f"/nalozi/{n.id}",
                )
                n.izvan_radione_javljeno = True
                promjena = True
                poslano += 1
            elif not vani and n.izvan_radione_javljeno:
                n.izvan_radione_javljeno = False
                promjena = True
        if promjena:
            db.commit()
    return poslano


async def petlja() -> None:
    interval = max(30, int(settings.flota_interval_s))
    log.info("Flota GPS nadzor pokrenut (interval %ss, radijus %sm).", interval, settings.radiona_radius_m)
    while True:
        try:
            pozicije = await dohvati_pozicije()
            if pozicije:
                await asyncio.to_thread(obradi_pozicije, pozicije)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Flota tick greška: %s", e)
        await asyncio.sleep(interval)
