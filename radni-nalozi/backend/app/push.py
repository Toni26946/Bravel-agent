"""Web Push (VAPID) obavijesti — opcionalno; radi samo ako su ključevi postavljeni."""
import json
import logging

from sqlalchemy.orm import Session

from .config import settings, vapid_keypair
from .models import Korisnik, Uloga

log = logging.getLogger("push")

try:
    from pywebpush import WebPushException, webpush
except Exception:  # pragma: no cover
    webpush = None
    WebPushException = Exception


def push_omogucen() -> bool:
    pub, priv = vapid_keypair()
    return bool(webpush and pub and priv)


def _posalji(sub_json: str, naslov: str, tijelo: str, url: str = "/") -> bool:
    if not push_omogucen():
        return False
    _, priv = vapid_keypair()
    try:
        webpush(
            subscription_info=json.loads(sub_json),
            data=json.dumps({"naslov": naslov, "tijelo": tijelo, "url": url}),
            vapid_private_key=priv,
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


def obavijesti_ulogu(db: Session, uloga, naslov: str, tijelo: str, url: str = "/") -> None:
    """Pošalji push svim aktivnim korisnicima zadane uloge (ili više uloga).

    `uloga` može biti jedna Uloga ili lista/skup uloga. Svakom korisniku šalje
    se najviše jednom, čak i ako se pojavi u više uloga."""
    uloge = list(uloga) if isinstance(uloga, (list, tuple, set)) else [uloga]
    poslani: set[int] = set()
    for u in uloge:
        for k in db.query(Korisnik).filter(Korisnik.uloga == u, Korisnik.aktivan.is_(True)).all():
            if k.push_subscription and k.id not in poslani:
                _posalji(k.push_subscription, naslov, tijelo, url)
                poslani.add(k.id)
