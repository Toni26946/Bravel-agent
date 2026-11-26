"""📺 Upute iz videa uz zadatak — unos YouTube linka (poslovođa / voditelj / vlasnik)."""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import video_upute
from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga, VideoUputa, Zadatak

router = APIRouter(prefix="/video-upute", tags=["video-upute"])
_urednik = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)


class LinkIn(BaseModel):
    url: str


def _zadatak(db: Session, zadatak_id: int) -> Zadatak:
    z = db.get(Zadatak, zadatak_id)
    if z is None:
        raise HTTPException(status_code=404, detail="Zadatak ne postoji")
    return z


@router.get("/zadatak/{zadatak_id}")
def dohvati(zadatak_id: int, _: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    z = _zadatak(db, zadatak_id)
    return video_upute.za_prikaz(z.video_uputa) or {"nema": True}


@router.post("/zadatak/{zadatak_id}")
def postavi(zadatak_id: int, p: LinkIn, pozadina: BackgroundTasks,
            k: Korisnik = Depends(_urednik), db: Session = Depends(get_db)):
    """Zalijepi YouTube link → obrada ide u pozadini (~20–60 s); status „obrada"."""
    z = _zadatak(db, zadatak_id)
    vid = video_upute.video_id(p.url)
    if not vid:
        raise HTTPException(status_code=400, detail="To nije YouTube poveznica")
    u = z.video_uputa
    if u is None:
        u = VideoUputa(zadatak_id=z.id, url="", video_id=vid)
        db.add(u)
    u.url = p.url.strip()[:300]
    u.video_id = vid
    u.status = "obrada"
    u.greska = None
    u.podaci = None
    u.naslov = None
    u.kreirao_id = k.id
    u.azurirano = datetime.now(timezone.utc)
    db.commit()
    db.refresh(u)
    pozadina.add_task(video_upute.obradi, u.id)
    return video_upute.za_prikaz(u)


@router.delete("/zadatak/{zadatak_id}")
def obrisi(zadatak_id: int, _: Korisnik = Depends(_urednik), db: Session = Depends(get_db)):
    z = _zadatak(db, zadatak_id)
    if z.video_uputa is not None:
        db.delete(z.video_uputa)
        db.commit()
    return {"ok": True}
