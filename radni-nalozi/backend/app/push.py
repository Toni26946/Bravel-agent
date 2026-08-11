"""Web Push (VAPID) obavijesti — opcionalno; radi samo ako su ključevi postavljeni."""
import json
import logging

from sqlalchemy.orm import Session

from .config import settings
from .models import Korisnik, Uloga

log = logging.getLogger("push")

try:
    from pywebpush import WebPushException, webpush
except Exception:  # pragma: no cover
    webpush = None
    WebPushException = Exception


def push_omogucen() -> bool:
    return bool(webpush and settings.vapid_private_key and settings.vapid_public_key)


def _posalji(sub_json: str, naslov: str, tijelo: str, url: str = "/") -> bool:
    if not push_omogucen():
        return False
    try:
        webpush(
            subscription_info=json.loads(sub_json),
            data=json.dumps({"naslov": naslov, "tijelo": tijelo, "url": url}),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return True
    except WebPushException as e:
        log.warning("Push neuspješan: %s", e)
        return False
    except Exception as e:  # pragma: no cover
        log.warning("Push greška: %s", e)
        return False


def obavijesti_korisnika(db: Session, korisnik_id: int, naslov: str, tijelo: str, url: str = "/") -> None:
    k = db.get(Korisnik, korisnik_id)
    if k and k.push_subscription:
        _posalji(k.push_subscription, naslov, tijelo, url)


def obavijesti_ulogu(db: Session, uloga: Uloga, naslov: str, tijelo: str, url: str = "/") -> None:
    for k in db.query(Korisnik).filter(Korisnik.uloga == uloga, Korisnik.aktivan.is_(True)).all():
        if k.push_subscription:
            _posalji(k.push_subscription, naslov, tijelo, url)
