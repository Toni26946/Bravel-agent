"""Integracija s Flota OS (GPS).

Periodično dohvaća pozicije vozila i, ako vozilo s nalogom u statusu "u radu"
napusti geokrug radione, javlja voditeljima (jednom po izlasku) da provjere je
li vozilo završeno. Radi samo ako je konfigurirano (ključ/račun + koordinate).
"""
import asyncio
import logging
import math
import time
from datetime import datetime, timezone

import httpx

from .config import settings
from .database import SessionLocal
from .models import Nalog, StatusNaloga, Uloga
from .push import obavijesti_ulogu, push_omogucen

log = logging.getLogger("flota")

_token: str | None = None  # JWT za lokalni račun (opcija bez servisnog ključa)

# Dijagnostika (za /api/flota/status) — stanje zadnjeg ciklusa nadzora.
_zadnje_osvjezeno: datetime | None = None   # zadnji uspješan dohvat pozicija
_zadnji_pokusaj: datetime | None = None     # zadnji pokušaj (uspješan ili ne)
_broj_pozicija: int = 0
_zadnja_greska: str | None = None
_zadnje_pozicije: dict = {}                 # keš zadnjih pozicija po GB-u


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


def _zabiljezi(pozicije: dict | None, greska: str | None) -> None:
    """Spremi stanje zadnjeg ciklusa za dijagnostiku (/api/flota/status)."""
    global _zadnji_pokusaj, _zadnje_osvjezeno, _broj_pozicija, _zadnja_greska, _zadnje_pozicije
    _zadnji_pokusaj = datetime.now(timezone.utc)
    _zadnja_greska = greska
    if pozicije is not None:
        _zadnje_osvjezeno = _zadnji_pokusaj
        _broj_pozicija = len(pozicije)
        _zadnje_pozicije = pozicije


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


# --- Zaduženje vozila (za "nezadužene šlepe") ------------------------------
_zaduzenje_kes: dict = {}   # gb -> (monotonic_ts, rezultat)
_ZAD_TTL = 600              # 10 min


async def zaduzenje(gb: str) -> dict | None:
    """Dohvati zaduženje vozila iz Flota OS: /api/flota/zaduzenje?gb=.

    Vraća {gb, tip, prikolica, zaduzeno, kamion, ym} ili None (nedostupno/greška).
    Keširano 10 min po GB-u.
    """
    global _token
    gb = str(gb or "").strip()
    if not gb:
        return None
    sad = time.monotonic()
    kes = _zaduzenje_kes.get(gb)
    if kes and sad - kes[0] < _ZAD_TTL:
        return kes[1]
    base = settings.flota_api_base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=20) as client:
        if settings.flota_service_key:
            headers = {"X-Service-Key": settings.flota_service_key}
        else:
            if not _token:
                await _prijava(client)
            headers = {"Authorization": f"Bearer {_token}"} if _token else {}
        try:
            r = await client.get("/api/flota/zaduzenje", params={"gb": gb}, headers=headers)
            if r.status_code == 401 and not settings.flota_service_key:
                await _prijava(client)
                headers = {"Authorization": f"Bearer {_token}"} if _token else {}
                r = await client.get("/api/flota/zaduzenje", params={"gb": gb}, headers=headers)
            if r.status_code != 200:
                return None
            d = r.json()
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(d, dict) or d.get("greska"):
        return None
    _zaduzenje_kes[gb] = (sad, d)
    return d


def je_nezaduzena_slepa(z: dict | None) -> bool:
    """Prikolica/šlepa koja trenutno nije ni u jednoj kompoziciji (slobodna)."""
    return bool(z and z.get("prikolica") and not z.get("zaduzeno"))


_prikolice_kes: dict = {"ts": 0.0, "podaci": None}
_PRIK_TTL = 600  # 10 min


async def nezaduzene_prikolice_raw() -> dict | None:
    """Puni odgovor Flota OS-a: /api/flota/nezaduzene-prikolice. Keš 10 min.

    Vraća {ym, broj, prikolice, dijag} ili None (nedostupno / greška / status).
    """
    global _token
    sad = time.monotonic()
    if _prikolice_kes["podaci"] is not None and sad - _prikolice_kes["ts"] < _PRIK_TTL:
        return _prikolice_kes["podaci"]
    base = settings.flota_api_base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=25) as client:
        if settings.flota_service_key:
            headers = {"X-Service-Key": settings.flota_service_key}
        else:
            if not _token:
                await _prijava(client)
            headers = {"Authorization": f"Bearer {_token}"} if _token else {}
        try:
            r = await client.get("/api/flota/nezaduzene-prikolice", headers=headers)
            if r.status_code == 401 and not settings.flota_service_key:
                await _prijava(client)
                headers = {"Authorization": f"Bearer {_token}"} if _token else {}
                r = await client.get("/api/flota/nezaduzene-prikolice", headers=headers)
            if r.status_code != 200:
                return None
            d = r.json()
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(d, dict) or d.get("greska"):
        return None
    _prikolice_kes["podaci"] = d
    _prikolice_kes["ts"] = sad
    return d


async def nezaduzene_prikolice() -> list | None:
    """Popis slobodnih šlepa [{gb, tip, reg}] ili None (nedostupno)."""
    d = await nezaduzene_prikolice_raw()
    return None if d is None else (d.get("prikolice") or [])


_vozila_kes: dict = {"ts": 0.0, "podaci": None}
_VOZ_TTL = 600  # 10 min


async def vozila_flota() -> list | None:
    """Matični popis svih vozila iz Flota OS-a: [{gb, reg, tip, kategorija}] ili None.

    Keš 10 min. Izvor za sinkronizaciju matičnog popisa vozila u radionici."""
    global _token
    sad = time.monotonic()
    if _vozila_kes["podaci"] is not None and sad - _vozila_kes["ts"] < _VOZ_TTL:
        return _vozila_kes["podaci"]
    base = settings.flota_api_base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=25) as client:
        if settings.flota_service_key:
            headers = {"X-Service-Key": settings.flota_service_key}
        else:
            if not _token:
                await _prijava(client)
            headers = {"Authorization": f"Bearer {_token}"} if _token else {}
        try:
            r = await client.get("/api/flota/vozila", headers=headers)
            if r.status_code == 401 and not settings.flota_service_key:
                await _prijava(client)
                headers = {"Authorization": f"Bearer {_token}"} if _token else {}
                r = await client.get("/api/flota/vozila", headers=headers)
            if r.status_code != 200:
                return None
            d = r.json()
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(d, dict) or d.get("greska"):
        return None
    vozila = d.get("vozila") or []
    _vozila_kes["podaci"] = vozila
    _vozila_kes["ts"] = sad
    return vozila


async def probaj_rutu(putanja: str, params: dict | None = None) -> dict:
    """Dijagnostika: sirovi GET na Flota OS rutu — vrati točan HTTP status i kratak
    odlomak tijela (npr. poruku 403 „ključ nema pristup ruti"). Ne keširano."""
    global _token
    base = settings.flota_api_base.rstrip("/")
    rez: dict = {"ruta": putanja, "base": base}
    try:
        async with httpx.AsyncClient(base_url=base, timeout=25) as client:
            if settings.flota_service_key:
                headers = {"X-Service-Key": settings.flota_service_key}
                rez["auth"] = "service-key"
            else:
                if not _token:
                    await _prijava(client)
                headers = {"Authorization": f"Bearer {_token}"} if _token else {}
                rez["auth"] = "bearer" if _token else "nema"
            r = await client.get(putanja, params=params or {}, headers=headers)
            rez["status"] = r.status_code
            rez["tijelo"] = (r.text or "")[:300]
    except httpx.TimeoutException:
        rez["status"] = None
        rez["greska"] = "timeout"
    except Exception as e:  # noqa: BLE001
        rez["status"] = None
        rez["greska"] = f"{type(e).__name__}: {str(e)[:200]}"
    return rez


def _prestaro(vrijeme_iso: str | None) -> bool:
    """True ako je GPS zapis stariji od dopuštenog (ne javljaj lažne alarme)."""
    if not vrijeme_iso:
        return False  # nema oznake vremena — ne odbacuj samo zbog toga
    try:
        t = datetime.fromisoformat(vrijeme_iso)
    except (ValueError, TypeError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    starost = (datetime.now(timezone.utc) - t).total_seconds()
    return starost > settings.flota_max_starost_s


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
            if not p or p.get("zastarjelo") or _prestaro(p.get("vrijeme")):
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
            _zabiljezi(pozicije, None if pozicije is not None else "dohvat pozicija nije uspio")
            if pozicije:
                await asyncio.to_thread(obradi_pozicije, pozicije)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Flota tick greška: %s", e)
            _zabiljezi(None, str(e))
        await asyncio.sleep(interval)


def status() -> dict:
    """Dijagnostika Flota OS nadzora (za voditelje) — je li živ i što vidi."""
    from .database import SessionLocal
    from .models import Korisnik, Nalog, StatusNaloga, Uloga

    sada = datetime.now(timezone.utc)
    aktivni_info = []
    voditelja_s_pushom = 0
    with SessionLocal() as db:
        voditelja_s_pushom = (
            db.query(Korisnik)
            .filter(Korisnik.uloga == Uloga.voditelj, Korisnik.push_subscription.isnot(None))
            .count()
        )
        for n in db.query(Nalog).filter(Nalog.status == StatusNaloga.u_radu).all():
            gb = n.vozilo.gb if n.vozilo else None
            p = _zadnje_pozicije.get(str(gb)) if gb else None
            info = {
                "nalog_id": n.id, "gb": gb,
                "ima_poziciju": bool(p),
                "zastarjelo": bool(p and (p.get("zastarjelo") or _prestaro(p.get("vrijeme")))),
                "vec_javljeno": bool(n.izvan_radione_javljeno),
                "udaljenost_m": None, "vani": None,
            }
            if p and not info["zastarjelo"]:
                d = udaljenost_m(p["lat"], p["lon"], settings.radiona_lat, settings.radiona_lon)
                info["udaljenost_m"] = int(d)
                info["vani"] = d > settings.radiona_radius_m
            aktivni_info.append(info)

    def _iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "konfigurirano": konfigurirano(),
        "push_omogucen": push_omogucen(),
        "voditelja_s_pushom": voditelja_s_pushom,
        "zadnje_osvjezeno": _iso(_zadnje_osvjezeno),
        "zadnji_pokusaj": _iso(_zadnji_pokusaj),
        "sekundi_od_osvjezenja": int((sada - _zadnje_osvjezeno).total_seconds()) if _zadnje_osvjezeno else None,
        "broj_pozicija": _broj_pozicija,
        "zadnja_greska": _zadnja_greska,
        "radius_m": settings.radiona_radius_m,
        "interval_s": max(30, int(settings.flota_interval_s)),
        "aktivni_nalozi": aktivni_info,
    }
