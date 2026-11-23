"""Skupine poslova — što koji majstor smije dobiti automatski (Toni 20.11.2026.).

Kategorije operacija (MOTOR, KOČNICE 2. OSOVINA, PRANJE VOZILA…) svrstavaju se u
9 skupina (zavarivanje/bravarija je od 23.11.2026. zasebno od limarije i bojanja —
Toni, WhatsApp #365: „Zavarivanje treba biti posebno"). Svaki majstor ima kućice za skupine koje smije raditi
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
    ("elektrika", "Elektrika i svjetla",
     ("ELEKTRIK", "AKUMULATOR", "KAMER", "SVJETL", "RASVJET", "ZARULJ", "SENZOR", "TAHOGRAF")),
    ("dijagnostika", "Dijagnostika i elektronika",
     ("DIJAGNOSTIK", "ABS", "EBS")),
    ("klima", "Klima i grijanje",
     ("KLIMA", "WEBASTO", "GRIJANJ")),
    ("gume", "Gume",
     ("GUME", "GUMA", "VULKAN", "NAPLAT", "FELG")),
    # Kočnice moraju prije ovjesa/osovina ("KOČNICE 2. OSOVINA" = kočnice).
    ("kocnice", "Kočnice",
     ("KOCNIC", "KLOBN", "CELJUST")),
    ("pneumatika", "Pneumatika (zrak)",
     ("PNEUMATIK", "KOMPRESOR")),
    ("ovjes", "Ovjes, osovine, upravljanje, sedla",
     ("OSOVIN", "OVJES", "ZRACNI JASTU", "GIBNJ", "AMORTIZ", "KOTAC", "GLAVCIN", "UPRAVLJANJ", "SPUR",
      "SEDL", "VUCN", "VUCU", "KUKA", "RUDE")),
    ("hidraulika", "Hidraulika i dizalica",
     ("HIDRAUL", "DIZALIC", "RAZVODNIC", "SKARE", "CRIJEV", "BLOMBIR")),
    ("motor", "Motor i mjenjač",
     ("MOTOR", "MJENJAC", "GETRIB", "RETARDER", "INJEKTOR", "VENTIL", "HLADNJAK",
      "INTERCOOLER", "AUSPUH", "ISPUSN", "DPF", "TURBO", "KVACIL", "REMEN", "AD-BLUE",
      "ADBLUE", "AD BLUE", "GORIVO", "REZERVOAR", "DIFERENCIJAL")),
    ("zavarivanje", "Zavarivanje i bravarija",
     ("ZAVAR", "BRAVARIJ")),
    ("limarija", "Limarija i bojanje",
     ("LIMARIJ", "LIMOVI", "SASIJ", "BOJANJ", "BLATOBRAN", "BRANIK", "BOCNA",
      "BROJEVA", "STRANICA", "NADOGRADNJ", "JASTUC", "STIC", "RETROVIZOR")),
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
# v2: imena se spajaju i obrnutim redoslijedom („Antony Jeffin" = „Jeffin Antony").
KLJUC_PREFILL = "skupine_poslova_prefill_v2"
# 23.11.2026.: zavarivanje odvojeno od limarije — jednokratni prijenos kućica (vidi razdvoji_zavarivanje).
KLJUC_ZAVARIVANJE = "skupine_zavarivanje_v1"
# 23.11.2026.: podvozje → kočnice/pneumatika/ovjes, elektrika → elektrika/dijagnostika/klima.
KLJUC_RAZDVOJI2 = "skupine_razdvoji_v2"
RAZDVAJANJE = {
    "podvozje": ("kocnice", "pneumatika", "ovjes"),
    "elektrika": ("elektrika", "dijagnostika", "klima"),
}


def _bez_dijakritika(s: str) -> str:
    s = (s or "").replace("Đ", "DJ").replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def skupina_kategorije(kategorija: str | None) -> str | None:
    """Ključ skupine za kategoriju operacije, ili None (ne spada nikamo → ručno)."""
    k = " ".join(_bez_dijakritika(kategorija or "").upper().split())
    if not k:
        return None
    # „N. OSOVINA" samo kaže GDJE je posao, ne KOJI — „BLATOBRANI 2. OSOVINA" je limarija,
    # ne ovjes (23.11.2026.). Prvo bez oznake osovine; tek ako ništa ne pogodi, s njom.
    import re
    bez_osovine = re.sub(r"\b\d+\s*\.?\s*OSOVIN\w*", " ", k)
    for tekst in (bez_osovine + " ", k + " "):
        for kljuc, _naziv, uzorci in SKUPINE:
            if any(u in tekst for u in uzorci):
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


def _rijeci_imena(ime: str | None) -> list[str]:
    return [w for w in _bez_dijakritika(ime or "").upper().replace("-", " ").split() if len(w) > 1]


def _iste_rijeci(a: str, b: str) -> bool:
    from difflib import SequenceMatcher
    return a == b or (len(a) >= 5 and len(b) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.85)


def isto_ime(ime_a: str | None, ime_b: str | None) -> bool:
    """Ista osoba neovisno o redoslijedu (u aplikaciji „Antony Jeffin", u povijesti
    „Jeffin Antony") i sitnim tipfelerima („Miykhailo"/„Mykhailo"): svaka riječ
    kraćeg imena (barem 2 riječi) mora imati par u drugom."""
    a, b = _rijeci_imena(ime_a), _rijeci_imena(ime_b)
    if len(a) > len(b):
        a, b = b, a
    if len(a) < 2:
        return False
    ostatak = list(b)
    for w in a:
        par = next((x for x in ostatak if _iste_rijeci(w, x)), None)
        if par is None:
            return False
        ostatak.remove(par)
    return True


def brojevi_iz_povijesti(db: Session, korisnici) -> dict[int, dict[str, int]]:
    """{korisnik_id: {skupina: broj poslova}} iz uvezene povijesti rada (zadnje 2 god.)
    i završenih zadataka u aplikaciji."""
    from .models import Korisnik, Operacija, PovijestRada, Zadatak

    ids = {k.id for k in korisnici}
    out: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    od = date.today() - timedelta(days=POVIJEST_DANA)
    po_imenu: dict[str, int | None] = {}   # ime iz povijesti → korisnik (keš)

    def _rid(ime: str) -> int | None:
        if ime not in po_imenu:
            pog = [k.id for k in korisnici if isto_ime(k.ime, ime)]
            po_imenu[ime] = pog[0] if len(pog) == 1 else None   # dvojbeno → nitko
        return po_imenu[ime]

    for radnik, operacija in (db.query(PovijestRada.radnik, PovijestRada.operacija)
                              .filter(PovijestRada.datum >= od).all()):
        sk = skupina_kategorije(operacija)
        if sk is None:
            continue
        for ime in (radnik or "").split(","):
            ime = " ".join(ime.split())
            rid = _rid(ime) if ime else None
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


def popuni_iz_povijesti(db: Session) -> dict[str, list[str]]:
    """Postavi kućice majstorima iz povijesti. Ne dira one kojima je netko kućice
    već ručno mijenjao (zapis „skupine" u povijesti plana). Vraća {ime: [skupine]}."""
    from .models import Korisnik, PlanDogadaj, Uloga
    from .routers.plan import _SERVISERI
    from sqlalchemy import or_

    meh = (db.query(Korisnik)
           .filter(or_(Korisnik.uloga.in_(_SERVISERI), Korisnik.radi_na_nalozima.is_(True)),
                   Korisnik.uloga != Uloga.skladistar)
           .all())
    rucno = {rid for (rid,) in db.query(PlanDogadaj.radnik_id).filter(PlanDogadaj.tip == "skupine").all()}
    brojevi = brojevi_iz_povijesti(db, meh)
    out = {}
    for k in meh:
        if k.id in rucno:
            continue
        sk = predlozi_iz_povijesti(brojevi.get(k.id, {}))
        k.skupine_poslova = u_tekst(sk)
        out[k.ime] = [s for s in KLJUCEVI if s in sk]
    db.commit()
    return out


def jednokratno_popuni(db: Session) -> None:
    """Pri startu: jednom popuni kućice iz povijesti (osim ručno mijenjanih)."""
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


def razdvoji_zavarivanje(db: Session) -> dict[str, bool]:
    """Jednom nakon razdvajanja (23.11.2026.): tko je imao kućicu „limarija" dobiva i
    „zavarivanje" AKO je u povijesti radio zavarivanje/bravariju (barem PRAG_BROJ poslova)
    ili za njega povijesti nema (tada se zadržava dosadašnje ponašanje). Ostali (npr.
    lakireri) ostaju samo na limariji. Vraća {ime: dobio_zavarivanje}."""
    from .models import Korisnik

    meh = [k for k in db.query(Korisnik).filter(Korisnik.skupine_poslova.isnot(None)).all()
           if "limarija" in (skupine_radnika(k) or set())]
    if not meh:
        return {}
    brojevi = brojevi_iz_povijesti(db, meh)
    out = {}
    for k in meh:
        b = brojevi.get(k.id, {})
        dobio = not b or b.get("zavarivanje", 0) >= PRAG_BROJ
        if dobio:
            k.skupine_poslova = u_tekst((skupine_radnika(k) or set()) | {"zavarivanje"})
        out[k.ime] = dobio
    db.commit()
    return out


def jednokratno_razdvoji_zavarivanje(db: Session) -> None:
    """Pri startu: jednom prenesi kućice nakon odvajanja zavarivanja od limarije."""
    from .norme import get_postavka, set_postavka
    try:
        if get_postavka(db, KLJUC_ZAVARIVANJE) == "1":
            return
        rez = razdvoji_zavarivanje(db)
        set_postavka(db, KLJUC_ZAVARIVANJE, "1")
        db.commit()
        log.info("Skupina zavarivanje: kućice prenesene s limarije: %s", rez)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("Skupina zavarivanje: prijenos kućica nije uspio: %s", e)


def razdvoji_skupine_v2(db: Session) -> int:
    """Jednom (23.11.2026.): tko je imao staru skupinu podvozje dobiva kočnice+pneumatika+ovjes,
    tko je imao elektriku dobiva elektriku+dijagnostika+klima — dakle nitko ne gubi poslove
    koje je do sada smio; sužavanje je ručno (kućice u planu). Vraća broj promijenjenih."""
    from .models import Korisnik

    n = 0
    for k in db.query(Korisnik).filter(Korisnik.skupine_poslova.isnot(None)).all():
        stari = {x.strip() for x in (k.skupine_poslova or "").split(",") if x.strip()}
        novi = set(stari)
        for kljuc, nasljednici in RAZDVAJANJE.items():
            if kljuc in stari:
                novi.discard(kljuc)
                novi.update(nasljednici)
        novi &= set(NAZIVI)
        if novi != {x for x in stari if x in NAZIVI}:
            k.skupine_poslova = u_tekst(novi)
            n += 1
    db.commit()
    return n


def jednokratno_razdvoji_v2(db: Session) -> None:
    """Pri startu: jednom prenesi kućice nakon razdvajanja podvozja i elektrike."""
    from .norme import get_postavka, set_postavka
    try:
        if get_postavka(db, KLJUC_RAZDVOJI2) == "1":
            return
        n = razdvoji_skupine_v2(db)
        set_postavka(db, KLJUC_RAZDVOJI2, "1")
        db.commit()
        log.info("Skupine v2 (kočnice/ovjes/pneumatika, elektrika/dijagnostika/klima): preneseno %s majstora", n)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("Skupine v2: prijenos kućica nije uspio: %s", e)
