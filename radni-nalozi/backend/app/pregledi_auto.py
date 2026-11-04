"""Automatske operacije za periodične zakonske provjere vozila.

Kad se rok približi (≤ PRAG_DANA, zadano 14) ili je prošao, za to vozilo se u
aktivni radni nalog (ili u novootvoreni) sam doda operacija te provjere —
periodički pregled, baždarenje tahografa, PP aparati i registracija — da se vidi
u Planu radione i da joj se može dodijeliti mehaničar (obična operacija, bez
unaprijed dodijeljenog radnika).

Idempotentno: ista vrsta provjere se NE dodaje dvaput dok već postoji na nekom
aktivnom nalogu tog vozila. Kad se operacija dovrši i nalog zatvori, a rok se u
Pregledima pomakne naprijed, idući ciklus je opet doda.

Rokovi su isti kao na kartici „Pregledi vozila": datum zadnje provjere + interval
(mjeseci), a za registraciju izravan datum isteka."""
import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func

from .config import settings
from .database import SessionLocal
from .models import (
    Korisnik, Nalog, Operacija, RegistarVozila, StatusNaloga, StatusVozila,
    Uloga, Vozilo, Zadatak,
)

log = logging.getLogger("pregledi_auto")

PRAG_DANA = 14              # koliko prije roka se operacija pojavi (~2 tjedna)
_INTERVAL_S = 6 * 3600      # provjera svakih 6 h
_AKTIVNI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)


def _plus_mj(d: date, n: int) -> date:
    """Datum + n mjeseci (zadrži dan, podreži na kraj kraćeg mjeseca)."""
    if not n:
        return d
    mj = d.month - 1 + int(n)
    god = d.year + mj // 12
    mj = mj % 12 + 1
    dan = min(d.day, calendar.monthrange(god, mj)[1])
    return date(god, mj, dan)


def _rok(datum: date | None, interval_mj: int | None) -> date | None:
    if not datum:
        return None
    return _plus_mj(datum, int(interval_mj)) if interval_mj else datum


# (kategorija operacije, opis zadatka, funkcija koja vrati rok iz RegistarVozila)
VRSTE = [
    ("PERIODIČKI PREGLED", "Periodični pregled", lambda r: _rok(r.periodicki_datum, r.periodicki_int)),
    ("BAŽDARENJE TAHOGRAFA", "Baždarenje tahografa", lambda r: _rok(r.taho_datum, r.taho_int)),
    ("PP APARATI", "Servis PP aparata", lambda r: _rok(r.pp_datum, r.pp_int)),
    ("REGISTRACIJA", "Produženje registracije", lambda r: r.registracija_istek),
]


def _vozilo_za_gb(db, gb: str) -> Vozilo:
    """Dohvati (ili stvori minimalni) Vozilo za garažni broj — treba ga nalog."""
    voz = db.query(Vozilo).filter(Vozilo.gb == gb).first()
    if voz is None:
        g = gb.lstrip("0") or gb
        voz = db.query(Vozilo).filter(Vozilo.gb == g).first()
    if voz is None:
        voz = Vozilo(gb=gb)
        db.add(voz)
        db.flush()
    return voz


def _aktivni_nalog(db, voz: Vozilo, voditelj: Korisnik) -> Nalog:
    """Najnoviji aktivni nalog vozila ili novootvoreni (za upis provjera)."""
    from .routers.nalozi import _sljedeci_broj
    n = (
        db.query(Nalog)
        .filter(Nalog.vozilo_id == voz.id, Nalog.status.in_(_AKTIVNI))
        .order_by(Nalog.kreiran.desc())
        .first()
    )
    if n is None:
        n = Nalog(
            broj=_sljedeci_broj(db), vozilo_id=voz.id, naslov=(voz.gb or "Pregledi"),
            kreirao_id=voditelj.id, voditelj_id=voditelj.id, status=StatusNaloga.otvoren,
        )
        db.add(n)
        db.flush()
    return n


def _vec_na_aktivnom(db, voz_id: int, kategorija: str) -> bool:
    """Postoji li već operacija te kategorije na bilo kojem aktivnom nalogu vozila."""
    return (
        db.query(Operacija.id)
        .join(Nalog, Operacija.nalog_id == Nalog.id)
        .filter(Nalog.vozilo_id == voz_id, Nalog.status.in_(_AKTIVNI),
                func.upper(Operacija.kategorija) == kategorija.upper())
        .first()
        is not None
    )


def tik(db) -> int:
    """Jedan prolaz: dodaj operacije za provjere kojima je rok ≤ PRAG_DANA.
    Vraća broj dodanih operacija. Bez aktivnog voditelja ne radi ništa."""
    voditelj = (
        db.query(Korisnik)
        .filter(Korisnik.uloga == Uloga.voditelj, Korisnik.aktivan.is_(True))
        .order_by(Korisnik.id)
        .first()
    )
    if not voditelj:
        return 0
    danas = date.today()
    prag = danas + timedelta(days=PRAG_DANA)
    dodano = 0
    vozila = (
        db.query(RegistarVozila)
        .filter(RegistarVozila.status != StatusVozila.prodano)
        .all()
    )
    for r in vozila:
        # Samo NADOLAZEĆI rokovi (danas → +14 dana). Davno dospjele (stari/zaostali
        # datumi) namjerno preskačemo da ne poplave plan — hvatamo svaki ~2 tj. prije.
        dospjele = [(kat, opis, rok) for (kat, opis, fn) in VRSTE
                    if (rok := fn(r)) and danas <= rok <= prag]
        if not dospjele:
            continue
        voz = _vozilo_za_gb(db, r.gb)
        nalog = _aktivni_nalog(db, voz, voditelj)
        for kat, opis, rok in dospjele:
            if _vec_na_aktivnom(db, voz.id, kat):
                continue
            op = Operacija(nalog_id=nalog.id, kategorija=kat, redoslijed=len(nalog.operacije))
            nalog.operacije.append(op)
            db.flush()
            db.add(Zadatak(operacija_id=op.id, opis=f"{opis} — rok {rok.strftime('%d.%m.%Y')}", redoslijed=0))
            dodano += 1
    if dodano:
        db.commit()
    return dodano


_KATEGORIJE = {k for (k, _o, _f) in VRSTE}


def ocisti_jednokratno(db) -> None:
    """Jednokratno: makni auto-operacije pregleda koje je PRVA verzija stvorila i za
    davno dospjele rokove (poplava od 146). Briše operacije tih kategorija čiji zadatak
    ima ' — rok ' u opisu, pa prazne auto-naloge nastale u zadnja 24 h. Pokreće se
    jednom (zastavica na volumenu); redovni tik (nadolazeći rokovi) radi dalje normalno."""
    zastavica = Path(settings.upload_dir).parent / ".ocisti_auto_preglede_v1"
    if zastavica.exists():
        return
    ops = db.query(Operacija).filter(Operacija.kategorija.in_(_KATEGORIJE)).all()
    obrisano = 0
    dirnuti: set[int] = set()
    for op in ops:
        zs = op.zadaci
        if len(zs) == 1 and " — rok " in (zs[0].opis or ""):
            dirnuti.add(op.nalog_id)
            db.delete(op)
            obrisano += 1
    db.flush()
    granica = datetime.now(timezone.utc) - timedelta(hours=24)
    naloga = 0
    for nid in dirnuti:
        n = db.get(Nalog, nid)
        if not n:
            continue
        kreiran = n.kreiran if n.kreiran.tzinfo else n.kreiran.replace(tzinfo=timezone.utc)
        if (not n.operacije and not n.radni_sati and not n.dijelovi and not n.fotografije
                and n.prijava_id is None and n.plan_rang is None and kreiran >= granica):
            db.delete(n)
            naloga += 1
    db.commit()
    zastavica.parent.mkdir(parents=True, exist_ok=True)
    zastavica.write_text("done", encoding="utf-8")
    log.info("Očišćeno auto-pregleda (prva verzija): %d operacija, %d praznih naloga.", obrisano, naloga)


async def petlja() -> None:
    log.info("Auto-pregledi pokrenut (prag %s dana, interval %s h).", PRAG_DANA, _INTERVAL_S // 3600)
    while True:
        try:
            with SessionLocal() as db:
                n = tik(db)
                if n:
                    log.info("Auto-pregledi: dodano %s operacija u naloge.", n)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — ne ruši petlju
            log.warning("Auto-pregledi tik greška: %s", e)
        await asyncio.sleep(_INTERVAL_S)
