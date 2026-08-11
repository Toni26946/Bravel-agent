"""Web Push pretplata — spremanje subscription objekta i javni VAPID ključ."""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik
from ..config import settings
from ..database import get_db
from ..models import Korisnik
from ..push import push_omogucen
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
