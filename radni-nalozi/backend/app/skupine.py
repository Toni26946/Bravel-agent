"""Skupine poslova — što koji majstor smije dobiti automatski (Toni 20.11.2026.).

Kategorije operacija (MOTOR, KOČNICE 2. OSOVINA, PRANJE VOZILA…) svrstavaju se u
8 skupina. Svaki majstor ima kućice za skupine koje smije raditi
(`Korisnik.skupine_poslova`, ključevi odvojeni zarezom). Automatsko popunjavanje
reda daje mu SAMO poslove iz njegovih skupina; kategorija koja ne spada ni u jednu
skupinu (RAZNO, TEREN…) ne ide nikome automatski — dodjeljuje se ručno.
Ručna dodjela smije sve (samo upozorenje u planu).
"""
from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# (ključ, naziv, prepoznavanje po dijelu naziva kategorije — bez dijakritika, velika slova).
# Redoslijed je bitan: prvo poklapanje pobjeđuje (npr. "PRANJE HLADNJAKA" = pranje,
# "OVJES … ZRAČNI JASTUCI" = podvozje prije "JASTUCI I ŠTICE" = limarija).
SKUPINE: list[tuple[str, str, tuple[str, ...]]] = [
    ("pranje", "Pranje i čišćenje",
     ("PRANJE", "CISCENJ", "SOBA ", "VESA", "OBILAZAK")),
    ("elektrika", "Elektrika, dijagnostika, klima",
     ("ELEKTRIK", "DIJAGNOSTIK", "AKUMULATOR", "KAMER", "SVJETL", "RASVJET", "ZARULJ",
      "SENZOR", "ABS", "EBS", "KLIMA", "WEBASTO", "GRIJANJ", "TAHOGRAF")),
    ("gume", "Gume",
     ("GUME", "GUMA", "VULKAN", "NAPLAT", "FELG")),
    ("podvozje", "Kočnice, osovine, ovjes, pneumatika",
     ("KOCNIC", "KLOBN", "CELJUST", "PNEUMATIK", "OSOVIN", "OVJES", "GIBNJ", "AMORTIZ",
      "KOTAC", "GLAVCIN", "UPRAVLJANJ", "SPUR", "SEDL", "VUCN", "VUCU", "KUKA", "RUDE",
      "KOMPRESOR")),
    ("hidraulika", "Hidraulika i dizalica",
     ("HIDRAUL", "DIZALIC", "RAZVODNIC", "SKARE", "CRIJEV", "BLOMBIR")),
    ("motor", "Motor i mjenjač",
     ("MOTOR", "MJENJAC", "GETRIB", "RETARDER", "INJEKTOR", "VENTIL", "HLADNJAK",
      "INTERCOOLER", "AUSPUH", "ISPUSN", "DPF", "TURBO", "KVACIL", "REMEN", "AD-BLUE",
      "ADBLUE", "AD BLUE", "GORIVO", "REZERVOAR", "DIFERENCIJAL")),
    ("limarija", "Limarija, zavarivanje, bojanje",
     ("LIMARIJ", "LIMOVI", "SASIJ", "BOJANJ", "BLATOBRAN", "BRANIK", "BOCNA", "BRAVARIJ",
      "ZAVAR", "BROJEVA", "STRANICA", "NADOGRADNJ", "JASTUC", "STIC", "RETROVIZOR")),
    ("servis", "Mali servis (ulje, filteri, podmazivanje)",
     ("SERVIS", "PODMAZIV", "ULJ", "FILTER")),
]
KLJUCEVI = [k for k, _n, _p in SKUPINE]
NAZIVI = {k: n for k, n, _p in SKUPINE}

# Početno popunjavanje iz povijesti: skupina se označi ako je čini barem PRAG_UDIO
# njegovih poslova (s prepoznatom skupinom) i barem PRAG_BROJ zapisa — da par
# usputnih poslova (npr. perač koji je 6 puta pomogao na motoru) ne da kućicu.
PRAG_UDIO = 0.15
PRAG_BROJ = 15
POVIJEST_DANA = 730
KLJUC_PREFILL = "skupine_poslova_prefill_v1"


def _bez_dijakritika(s: str) -> str:
    s = (s or "").replace("Đ", "DJ").replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def skupina_kategorije(kategorija: str | None) -> str | None:
    """Ključ skupine za kategoriju operacije, ili None (ne spada nikamo → ručno)."""
    k = " ".join(_bez_dijakritika(kategorija or "").upper().split())
    if not k:
        return None
    k = k + " "
    for kljuc, _naziv, uzorci in SKUPINE:
        if any(u in k for u in uzorci):
            return kljuc
    return None


def skupine_radnika(korisnik) -> set[str] | None:
    """Skup ključeva skupina majstora; None = još nije postavljeno."""
    v = getattr(korisnik, "skupine_poslova", None)
    if v is None:
        return None
    return {x.strip() for x in v.split(",") if x.strip() in NAZIVI}


def u_tekst(skupine) -> str:
    """Spremi skupine kao tekst (redoslijedom iz SKUPINE)."""
    s = set(skupine or [])
    return ",".join(k for k in KLJUCEVI if k in s)


def smije(korisnik, kategorija: str | None) -> bool:
    """Smije li majstor AUTOMATSKI dobiti operaciju te kategorije."""
    sk = skupina_kategorije(kategorija)
    if sk is None:
        return False
    moje = skupine_radnika(korisnik)
    return bool(moje) and sk in moje


def _kljuc_imena(ime: str | None) -> str:
    return " ".join(_bez_dijakritika(ime or "").upper().split())


def brojevi_iz_povijesti(db: Session, korisnici) -> dict[int, dict[str, int]]:
    """{korisnik_id: {skupina: broj poslova}} iz uvezene povijesti rada (zadnje 2 god.)
    i završenih zadataka u aplikaciji."""
    from .models import Korisnik, Operacija, PovijestRada, Zadatak

    po_imenu = {_kljuc_imena(k.ime): k.id for k in korisnici}
    ids = {k.id for k in korisnici}
    out: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    od = date.today() - timedelta(days=POVIJEST_DANA)
    for radnik, operacija in (db.query(PovijestRada.radnik, PovijestRada.operacija)
                              .filter(PovijestRada.datum >= od).all()):
        sk = skupina_kategorije(operacija)
        if sk is None:
            continue
        for ime in (radnik or "").split(","):
            rid = po_imenu.get(_kljuc_imena(ime))
            if rid is not None:
                out[rid][sk] += 1
    for kat, rid in (db.query(Operacija.kategorija, Korisnik.id)
                     .join(Zadatak, Zadatak.operacija_id == Operacija.id)
                     .join(Zadatak.radnici)
                     .filter(Zadatak.gotovo.is_(True)).all()):
        sk = skupina_kategorije(kat)
        if sk is not None and rid in ids:
            out[rid][sk] += 1
    return out


def predlozi_iz_povijesti(brojevi: dict[str, int]) -> set[str]:
    ukupno = sum(brojevi.values())
    if not ukupno:
        return set()
    return {sk for sk, c in brojevi.items() if c >= PRAG_BROJ and c / ukupno >= PRAG_UDIO}


def popuni_iz_povijesti(db: Session, samo_prazne: bool = True) -> dict[str, list[str]]:
    """Postavi kućice majstorima iz povijesti. Vraća {ime: [skupine]}."""
    from .models import Korisnik, Uloga
    from .routers.plan import _SERVISERI
    from sqlalchemy import or_

    meh = (db.query(Korisnik)
           .filter(or_(Korisnik.uloga.in_(_SERVISERI), Korisnik.radi_na_nalozima.is_(True)),
                   Korisnik.uloga != Uloga.skladistar)
           .all())
    brojevi = brojevi_iz_povijesti(db, meh)
    out = {}
    for k in meh:
        if samo_prazne and k.skupine_poslova is not None:
            continue
        sk = predlozi_iz_povijesti(brojevi.get(k.id, {}))
        k.skupine_poslova = u_tekst(sk)
        out[k.ime] = [s for s in KLJUCEVI if s in sk]
    db.commit()
    return out


def jednokratno_popuni(db: Session) -> None:
    """Pri startu: jednom popuni kućice iz povijesti (samo onima koji ih nemaju)."""
    from .norme import get_postavka, set_postavka
    try:
        if get_postavka(db, KLJUC_PREFILL) == "1":
            return
        rez = popuni_iz_povijesti(db)
        set_postavka(db, KLJUC_PREFILL, "1")
        db.commit()
        log.info("Skupine poslova popunjene iz povijesti: %s", rez)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("Skupine poslova: popunjavanje iz povijesti nije uspjelo: %s", e)
