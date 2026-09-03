"""Početni podaci — kreira prvog voditelja ako u bazi nema nijednog korisnika."""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .auth import hash_lozinka
from .config import settings
from .models import Korisnik, Uloga

log = logging.getLogger("seed")


def seed(db: Session) -> None:
    if db.query(Korisnik).count() > 0:
        return
    voditelj = Korisnik(
        ime=settings.seed_admin_ime,
        korisnicko_ime=settings.seed_admin_username,
        lozinka_hash=hash_lozinka(settings.seed_admin_password),
        uloga=Uloga.voditelj,
    )
    db.add(voditelj)
    db.commit()
    log.info(
        "Kreiran početni voditelj '%s' (promijenite lozinku nakon prve prijave).",
        settings.seed_admin_username,
    )


# --- Jednokratni uvoz radnika radione (popis iz kolovoza 2026.) --------------
_ASCII = str.maketrans({
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d",
    "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d",
})

RADNICI_POCETNI = [
    "Kobeščak Davor", "Habijanec Pejković Marina", "Azinović Mario", "Karthik Raju",
    "Svečnjak Alen", "Kahlina Igor", "Baček Matija", "Poslon Božidar", "Kuzmić Zlatko",
    "Hasan Matija", "Pavliukh Vasyl", "Baranov Gennadiy", "Borovyk Yevhen",
    "Liushnenko Miykhailo", "Serniak Ivan", "Elson Jacob", "Konathukatiil Akshay",
    "Ankudy Midhun Hari", "Antony Jeffin", "Gmitrović Miloš", "Balaško Florijan",
    "Jambrač Brigita", "Ronquillo Rickey", "Kovačević Dario", "Dominik Bahal", "Sergej Haver",
]


def _slug(ime: str) -> str:
    baza = ime.translate(_ASCII).lower()
    rijeci = ["".join(c for c in r if c.isalnum()) for r in baza.split()]
    return ".".join(r for r in rijeci if r) or "radnik"


# --- Jednokratni reset lozinke (zaboravljena lozinka voditelja) --------------
# Ključne riječi imena/korisničkog imena -> privremena lozinka.
# Reset se izvrši SAMO JEDNOM (zastavica na trajnom volumenu), pa nakon što
# korisnik promijeni lozinku ostaje njegova nova. Ukloniti nakon uporabe.
_RESETI: list[tuple[set[str], str]] = [
    ({"roko", "jendris"}, settings.seed_admin_password),  # bravel123
]


def _rijeci(*vrijednosti: str) -> set[str]:
    spojeno = " ".join(vrijednosti).translate(_ASCII).lower().replace(".", " ")
    return {r for r in spojeno.split() if r}


def jednokratni_reset_lozinke(db: Session) -> None:
    zastavica = Path(settings.upload_dir).parent / ".reset_lozinke_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    promijenjeno = 0
    for k in db.query(Korisnik).all():
        tokeni = _rijeci(k.ime or "", k.korisnicko_ime or "")
        for kljucne, temp in _RESETI:
            if kljucne <= tokeni:
                k.lozinka_hash = hash_lozinka(temp)
                promijenjeno += 1
                log.info("Reset lozinke za korisnika '%s' (%s).", k.ime, k.korisnicko_ime)
    if promijenjeno:
        db.commit()
        try:
            zastavica.parent.mkdir(parents=True, exist_ok=True)
            zastavica.write_text("done", encoding="utf-8")
        except OSError:
            pass


def seed_radnici(db: Session, lozinka: str = "radnik123") -> None:
    """Kreira početni popis radnika — samo ako u bazi još nema nijednog radnika
    (idempotentno; ne uskrsava pojedinačno obrisane radnike kasnije)."""
    if db.query(Korisnik).filter(Korisnik.uloga == Uloga.radnik).count() > 0:
        return
    zauzeti = {k.korisnicko_ime for k in db.query(Korisnik).all()}
    dodano = 0
    for ime in RADNICI_POCETNI:
        baza = _slug(ime)
        kor, i = baza, 1
        while kor in zauzeti:
            i += 1
            kor = f"{baza}{i}"
        zauzeti.add(kor)
        db.add(Korisnik(
            ime=ime, korisnicko_ime=kor,
            lozinka_hash=hash_lozinka(lozinka), uloga=Uloga.radnik,
        ))
        dodano += 1
    db.commit()
    log.info("Uvezeno %d radnika (početna lozinka '%s').", dodano, lozinka)
