"""Bravel Radni Nalozi — FastAPI aplikacija (backend)."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import flota
from . import podsjetnici
from .config import settings
from .database import Base, SessionLocal, engine
from .migrate import migrate
from .routers import auth, dijelovi, evidencija, korisnici, nalozi, paznja, plan, poslovodja, prijave, primke, push, stete, ucinak, vozaci, vozila, zaduzenja
from .routers.vozaci import seed_vozaci
from .norme import seed_norme, uskladi_norme
from .obracun_radione import auto_sync_pri_pokretanju
from .routers import flota as flota_router
from .seed import (
    backfill_povijest_gotovih,
    jednokratna_reaktivacija_roka,
    jednokratno_deaktiviraj_bivse,
    osiguraj_mihaela_i_zvonimira,
    osiguraj_pristup_zvonimir,
    ukloni_duplikat_mihael,
    uvezi_evidenciju_iz_gs,
    uvezi_evidenciju_novo_gs,
    uvezi_sifre_iz_gs,
    spoji_azinovica,
    subote_bez_15,
    teren_vremena,
    subote_x15_od_rujna,
    migriraj_zaduzene_u_radnike,
    ocisti_mjerace_bez_radnika,
    osiguraj_kovacevica,
    oznaci_neprijavljene_radnike,
    osiguraj_aktivnog_voditelja,
    osiguraj_poslovodju,
    osiguraj_dodatne_korisnike,
    osiguraj_vlasnika,
    osiguraj_vozilo_483,
    obavijesti_osvjezi,
    preimenuj_naslove_naloga,
    seed,
    seed_radnici,
    uvezi_povijest_rada,
    uvezi_vozila_matica,
    uvezi_preglede_iz_gs,
    uvezi_vozace_gb,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate(engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed(db)
        seed_radnici(db)
        uvezi_povijest_rada(db)
        migriraj_zaduzene_u_radnike(db)
        osiguraj_aktivnog_voditelja(db)
        jednokratna_reaktivacija_roka(db)
        osiguraj_dodatne_korisnike(db)
        osiguraj_vlasnika(db)
        jednokratno_deaktiviraj_bivse(db)
        uvezi_evidenciju_iz_gs(db)
        uvezi_sifre_iz_gs(db)
        osiguraj_mihaela_i_zvonimira(db)
        osiguraj_pristup_zvonimir(db)
        ukloni_duplikat_mihael(db)
        uvezi_evidenciju_novo_gs(db)
        spoji_azinovica(db)
        subote_bez_15(db)
        teren_vremena(db)
        subote_x15_od_rujna(db)
        preimenuj_naslove_naloga(db)
        ocisti_mjerace_bez_radnika(db)
        backfill_povijest_gotovih(db)
        oznaci_neprijavljene_radnike(db)
        osiguraj_poslovodju(db)
        osiguraj_kovacevica(db)
        osiguraj_vozilo_483(db)
        uvezi_vozila_matica(db)
        uvezi_preglede_iz_gs(db)
        uvezi_vozace_gb(db)
        obavijesti_osvjezi(db)
        seed_vozaci(db)
        seed_norme(db)
        uskladi_norme(db)
        auto_sync_pri_pokretanju(db)
    # Flota OS (GPS) nadzor — pokreni samo ako je konfigurirano.
    flota_task = None
    if flota.konfigurirano():
        flota_task = asyncio.create_task(flota.petlja())
    else:
        log.info("Flota GPS integracija nije konfigurirana (preskačem).")
    # Podsjetnici za parkiranje nezaduženih šlepa (radi i bez GPS-a; detekcija koristi Flota OS).
    parking_task = asyncio.create_task(podsjetnici.petlja())
    log.info("Bravel Radni Nalozi backend spreman.")
    yield
    if flota_task:
        flota_task.cancel()
    parking_task.cancel()


app = FastAPI(title="Bravel Radni Nalozi", version="1.0.0", lifespan=lifespan)


class SigurnosniZaglavlja(BaseHTTPMiddleware):
    """Dodaje osnovna sigurnosna HTTP zaglavlja na svaki odgovor."""

    async def dispatch(self, request: Request, call_next) -> Response:
        odgovor = await call_next(request)
        odgovor.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Plan radione se prikazuje u <iframe> unutar appa (isti origin) → SAMEORIGIN; inače DENY.
        odgovor.headers["X-Frame-Options"] = (
            "SAMEORIGIN" if request.url.path == "/plan-demo.html" else "DENY"
        )
        odgovor.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        odgovor.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(self), microphone=(self)")
        # HSTS — promet ide preko HTTPS-a (Fly force_https).
        odgovor.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        return odgovor


app.add_middleware(SigurnosniZaglavlja)

# CORS: kad su domene eksplicitno navedene dopuštamo kolačiće/kredencijale;
# uz zamjenski znak "*" (razvoj) kredencijali se ne smiju kombinirati.
_cors = settings.cors_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Poslužuj uploadane fotografije
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(auth.router, prefix="/api")
app.include_router(korisnici.router, prefix="/api")
app.include_router(vozila.router, prefix="/api")
app.include_router(prijave.router, prefix="/api")
app.include_router(nalozi.router, prefix="/api")
app.include_router(plan.router, prefix="/api")
app.include_router(stete.router, prefix="/api")
app.include_router(primke.router, prefix="/api")
app.include_router(evidencija.router, prefix="/api")
app.include_router(dijelovi.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(zaduzenja.router, prefix="/api")
app.include_router(vozaci.router, prefix="/api")
app.include_router(poslovodja.router, prefix="/api")
app.include_router(paznja.router, prefix="/api")
app.include_router(ucinak.router, prefix="/api")
app.include_router(flota_router.router, prefix="/api")


@app.get("/api/zdrav")
def zdrav():
    return {"status": "ok"}


# --- Posluživanje izgrađenog PWA frontenda (SPA) -----------------------------
_dist = Path(settings.frontend_dist)
# Datoteke koje browser NIKAD ne smije poslužiti iz keša bez provjere sa
# serverom — inače nakon deploya ostane stari index.html koji gađa obrisane
# (hashirane) assete → bijeli ekran. ETag/Last-Modified i dalje vrijede pa je
# revalidacija jeftina (304 kad nema promjene). Hashirani /assets/* se smiju
# keširati zauvijek jer im se ime mijenja svaki build.
_BEZ_KESA = {"index.html", "sw.js", "registerSW.js", "manifest.webmanifest"}


def _spa_response(datoteka: Path) -> FileResponse:
    odgovor = FileResponse(datoteka)
    if datoteka.name in _BEZ_KESA or datoteka.suffix == ".html":
        odgovor.headers["Cache-Control"] = "no-cache"
    return odgovor


if _dist.is_dir():
    # Statičke datoteke (assets, ikone) i SPA fallback na index.html.
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{putanja:path}")
    def spa(putanja: str, request: Request):
        if putanja.startswith(("api/", "uploads/")):
            raise HTTPException(status_code=404, detail="Not found")
        datoteka = _dist / putanja
        if putanja and datoteka.is_file():
            return _spa_response(datoteka)
        index = _dist / "index.html"
        if index.is_file():
            return _spa_response(index)
        raise HTTPException(status_code=404, detail="Frontend nije izgrađen")

    log.info("Poslužujem frontend iz %s", _dist)

