"""Bravel Radni Nalozi — FastAPI aplikacija (backend)."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .migrate import migrate
from .routers import auth, dijelovi, korisnici, nalozi, prijave, push, stete, vozila
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate(engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed(db)
    log.info("Bravel Radni Nalozi backend spreman.")
    yield


app = FastAPI(title="Bravel Radni Nalozi", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
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
app.include_router(stete.router, prefix="/api")
app.include_router(dijelovi.router, prefix="/api")
app.include_router(push.router, prefix="/api")


@app.get("/api/zdrav")
def zdrav():
    return {"status": "ok"}


# --- Posluživanje izgrađenog PWA frontenda (SPA) -----------------------------
_dist = Path(settings.frontend_dist)
if _dist.is_dir():
    # Statičke datoteke (assets, ikone) i SPA fallback na index.html.
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{putanja:path}")
    def spa(putanja: str, request: Request):
        if putanja.startswith(("api/", "uploads/")):
            raise HTTPException(status_code=404, detail="Not found")
        datoteka = _dist / putanja
        if putanja and datoteka.is_file():
            return FileResponse(datoteka)
        index = _dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend nije izgrađen")

    log.info("Poslužujem frontend iz %s", _dist)

