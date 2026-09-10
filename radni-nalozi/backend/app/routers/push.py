"""Web Push pretplata — spremanje subscription objekta i javni VAPID ključ."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik
from ..config import settings
from ..database import get_db
from ..models import Korisnik
from ..push import obavijesti_korisnika, push_omogucen
from ..schemas import PushSubscription

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/kljuc")
def javni_kljuc():
    return {"omoguceno": push_omogucen(), "vapid_public_key": settings.vapid_public_key}


@router.post("/pretplata", status_code=204)
def pretplati(
    podaci: PushSubscription,
    korisnik: Korisnik = Depends(trenutni_korisnik),
    db: Session = Depends(get_db),
):
    korisnik.push_subscription = json.dumps(podaci.subscription)
    db.commit()


@router.delete("/pretplata", status_code=204)
def odjavi(korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    korisnik.push_subscription = None
    db.commit()


@router.post("/test")
def testna_obavijest(korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    """Pošalji testnu push obavijest trenutno prijavljenom korisniku."""
    if not push_omogucen():
        raise HTTPException(status_code=503, detail="Push nije konfiguriran na serveru.")
    if not korisnik.push_subscription:
        raise HTTPException(status_code=400, detail="Niste pretplaćeni na obavijesti — prvo uključite push.")
    obavijesti_korisnika(
        db, korisnik.id, "Test obavijest ✅",
        "Ovako izgleda obavijest iz Bravel Radnih naloga.", url="/izasli",
    )
    return {"poslano": True}
