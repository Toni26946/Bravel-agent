"""Cartec valjci — testovi kočnica s računala u radioni.

Tok:
1. Skripta na računalu s valjcima (cartec_skripta/cartec_salji.py) se jednom
   prijavi (POST /cartec/prijava) i dobije nasumičan token. Vlasnik je odobri u
   Šifrarnik → Integracije (nitko ne prepisuje ključeve ni lozinke).
2. Za svako mjerenje osovine (Cartec piše Logs\\AxleData_Service_NN.csv) skripta
   pošalje najveću silu lijevo/desno (POST /cartec/mjerenje).
3. Mjerenja istog vozila (ista Cartec „sesija" = do idućeg „novo vozilo") čine
   JEDAN test. Ponovljena osovina: vrijedi zadnje mjerenje, ranija = „ponovljeno".
4. Test se sam veže uz nalog na kojem se TOG TRENA radi (mjerač pokrenut), ili uz
   jedini otvoreni nalog s operacijom kočnica. Inače ostaje „nerazvrstan" i
   voditelj/mehaničar dobije pitanje „Test kočnica u HH:MM — koje vozilo?".
5. Vozilo = GB naloga (nikad registracija). Nalog s nerazvrstanim testom među
   kandidatima ne može se zatvoriti dok se test ne veže.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_ai_poslovodja
from ..database import get_db
from ..models import (
    CartecUredjaj,
    Korisnik,
    MjerenjeOsovine,
    Nalog,
    Operacija,
    StatusNaloga,
    TestKocnica,
    Uloga,
    Zadatak,
)

router = APIRouter(prefix="/cartec", tags=["cartec"])
samo_vlasnik = zahtijevaj_ai_poslovodja()

OTVORENI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)
MAX_NEODOBRENIH = 5          # zaštita od zatrpavanja prijavama
SESIJA_BEZ_OZNAKE_MIN = 60   # bez Cartec oznake vozila: isto vozilo = unutar 1 h


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sad() -> datetime:
    return datetime.now(timezone.utc)


def _utc(d: datetime) -> datetime:
    """SQLite vraća naivna vremena — tretiramo ih kao UTC."""
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --- uređaj (računalo s valjcima) -------------------------------------------
class PrijavaIn(BaseModel):
    naziv: str = Field(default="Cartec valjci", max_length=120)


@router.post("/prijava")
def prijava_uredjaja(p: PrijavaIn, db: Session = Depends(get_db)):
    """Skripta se prijavi i dobije token. Dok vlasnik ne odobri, mjerenja se odbijaju
    (skripta ih čuva i šalje kasnije)."""
    neodobreni = db.query(CartecUredjaj).filter(CartecUredjaj.odobren.is_(False)).count()
    if neodobreni >= MAX_NEODOBRENIH:
        raise HTTPException(status_code=429, detail="Previše neodobrenih uređaja — odobri ili obriši postojeće.")
    token = secrets.token_urlsafe(32)
    u = CartecUredjaj(naziv=(p.naziv or "Cartec valjci").strip()[:120], token_hash=_hash(token))
    db.add(u)
    db.commit()
    return {"id": u.id, "token": token, "odobren": False}


def _uredjaj(db: Session, token: str | None, *, mora_biti_odobren: bool = True) -> CartecUredjaj:
    if not token:
        raise HTTPException(status_code=401, detail="Nedostaje X-Cartec-Token")
    u = db.query(CartecUredjaj).filter(CartecUredjaj.token_hash == _hash(token)).first()
    if not u:
        raise HTTPException(status_code=401, detail="Nepoznat uređaj")
    u.zadnji_kontakt = _sad()
    if mora_biti_odobren and not u.odobren:
        db.commit()
        raise HTTPException(status_code=403, detail="Uređaj čeka odobrenje vlasnika")
    return u


@router.get("/ping")
def ping(x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    u = _uredjaj(db, x_cartec_token, mora_biti_odobren=False)
    db.commit()
    return {"id": u.id, "odobren": u.odobren}


class StanjeIn(BaseModel):
    verzija: str = Field(default="", max_length=20)
    dnevnik: str = Field(default="", max_length=20000)   # zadnji redovi dnevnika skripte


@router.post("/stanje")
def javi_stanje(p: StanjeIn, x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Skripta svakih par minuta javi verziju i dnevnik — da se kvar vidi bez AnyDeska.
    Smije i neodobren uređaj (samo upis stanja, ništa drugo)."""
    u = _uredjaj(db, x_cartec_token, mora_biti_odobren=False)
    u.verzija = (p.verzija or "")[:20] or None
    u.stanje = p.dnevnik[-20000:] or None
    u.stanje_vrijeme = _sad()
    db.commit()
    return {"ok": True, "odobren": u.odobren}


def _skripta_put():
    from pathlib import Path
    ovdje = Path(__file__).resolve()
    for kand in (ovdje.parents[2] / "cartec_skripta" / "cartec_salji.ps1",     # Docker: /app/cartec_skripta
                 ovdje.parents[3] / "cartec_skripta" / "cartec_salji.ps1"):    # repo: radni-nalozi/cartec_skripta
        if kand.exists():
            return kand
    return None


def _verzija_skripte(tekst: str) -> str:
    import re
    m = re.search(r"\$Verzija\s*=\s*'([^']+)'", tekst)
    return m.group(1) if m else ""


@router.get("/skripta")
def skripta(x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Najnovija skripta za samoažuriranje (samo odobreni uređaj)."""
    _uredjaj(db, x_cartec_token)
    db.commit()
    put = _skripta_put()
    if not put:
        raise HTTPException(status_code=404, detail="Skripta nije u paketu")
    tekst = put.read_text(encoding="utf-8-sig")
    return {"verzija": _verzija_skripte(tekst), "sadrzaj": tekst}


class MjerenjeIn(BaseModel):
    sesija: str | None = Field(default=None, max_length=40)  # vrijeme zadnjeg Cartec „novo vozilo"
    osovina: int = Field(ge=1, le=12)
    vrsta: str = Field(pattern="^(radna|parkirna)$")
    vrijeme: datetime                                        # kraj mjerenja (s vremenskom zonom)
    sila_lijevo: int = Field(ge=0, le=200000)
    sila_desno: int = Field(ge=0, le=200000)
    tezina: int | None = Field(default=None, ge=0, le=100000)
    otisak: str = Field(min_length=8, max_length=64)        # sha256 sadržaja datoteke


def _razlika(l: int, d: int) -> float:
    veca = max(l, d)
    return round(abs(l - d) / veca * 100, 1) if veca else 0.0


def _nadji_ili_kreiraj_test(db: Session, u: CartecUredjaj, p: MjerenjeIn, vrijeme: datetime) -> TestKocnica:
    sesija = (p.sesija or "").strip()
    if sesija:
        t = (db.query(TestKocnica)
             .filter(TestKocnica.uredjaj_id == u.id, TestKocnica.sesija == sesija).first())
        if t:
            return t
    else:
        # Bez oznake vozila: isto vozilo ako je prethodni test završio unutar 1 h.
        t = (db.query(TestKocnica).filter(TestKocnica.uredjaj_id == u.id)
             .order_by(TestKocnica.kraj.desc()).first())
        if t and timedelta(0) <= vrijeme - _utc(t.kraj) <= timedelta(minutes=SESIJA_BEZ_OZNAKE_MIN):
            return t
        sesija = "bez-" + vrijeme.strftime("%Y%m%d%H%M%S")
    t = TestKocnica(uredjaj_id=u.id, sesija=sesija, pocetak=vrijeme, kraj=vrijeme, status="nerazvrstan")
    db.add(t)
    db.flush()
    return t


def kandidati_naloga(db: Session) -> tuple[list[Nalog], set[int], set[int]]:
    """Nalozi na kojima se SAD radi (pokrenut mjerač), pa otvoreni s operacijom kočnica."""
    u_radu = (db.query(Nalog).join(Operacija, Operacija.nalog_id == Nalog.id)
              .join(Zadatak, Zadatak.operacija_id == Operacija.id)
              .filter(Nalog.status.in_(OTVORENI), Zadatak.zapoceto.isnot(None),
                      Zadatak.gotovo.is_(False))
              .all())
    kocnice = (db.query(Nalog).join(Operacija, Operacija.nalog_id == Nalog.id)
               .join(Zadatak, Zadatak.operacija_id == Operacija.id)
               .filter(Nalog.status.in_(OTVORENI), Zadatak.gotovo.is_(False))
               .all())
    kocnice = [n for n in kocnice if any(
        "koč" in (op.kategorija or "").lower() or "koc" in (op.kategorija or "").lower()
        or any("koč" in (z.opis or "").lower() for z in op.zadaci)
        for op in n.operacije)]
    # Bez DISTINCT u SQL-u (Postgres + JSON stupci) — dedupe po id-u ovdje.
    vidjeni: dict[int, Nalog] = {}
    for n in u_radu:
        vidjeni.setdefault(n.id, n)
    for n in kocnice:
        vidjeni.setdefault(n.id, n)
    return list(vidjeni.values()), {n.id for n in u_radu}, {n.id for n in kocnice}


def _broj_osovina(t: TestKocnica) -> int:
    return len({m.osovina for m in t.mjerenja if m.vrsta == "radna"})


def _prethodni_broj_osovina(db: Session, t: TestKocnica) -> int | None:
    if not t.gb:
        return None
    pr = (db.query(TestKocnica)
          .filter(TestKocnica.gb == t.gb, TestKocnica.id != t.id, TestKocnica.status == "vezan",
                  TestKocnica.pocetak < t.pocetak)
          .order_by(TestKocnica.pocetak.desc()).first())
    return _broj_osovina(pr) if pr else None


def _ocijeni(db: Session, t: TestKocnica, novi_test: bool) -> bool:
    """Postavi status testa. Vraća True kad treba pitati ljude (test je tek postao
    nerazvrstan / čeka potvrdu) — da se obavijest ne šalje za svaku osovinu."""
    if t.vezao_id:          # čovjek je vezao — ne diramo
        return False
    stari = t.status
    if t.nalog_id is None:
        svi, u_radu, kocnice = kandidati_naloga(db)
        izbor = None
        if len(u_radu) == 1:
            izbor = next(iter(u_radu))
        elif not u_radu and len(kocnice) == 1:
            izbor = next(iter(kocnice))
        t.kandidati = ",".join(str(n.id) for n in svi[:12]) or None
        if izbor:
            n = db.get(Nalog, izbor)
            t.nalog_id = n.id
            t.gb = n.vozilo.gb if n.vozilo else None
    if t.nalog_id is None:
        t.status = "nerazvrstan"
        t.napomena = "Više mogućih vozila — odaberi nalog." if t.kandidati else "Nijedan nalog nije u radu — odaberi nalog."
    else:
        prije = _prethodni_broj_osovina(db, t)
        sad = _broj_osovina(t)
        if prije is not None and sad > prije:
            t.status = "ceka_potvrdu"
            t.napomena = f"Izmjereno {sad} osovina, a prošli test GB {t.gb} imao je {prije} — potvrdi vozilo."
        else:
            t.status = "vezan"
            t.napomena = None
    return t.status != "vezan" and (novi_test or t.status != stari)


@router.post("/mjerenje")
def primi_mjerenje(p: MjerenjeIn, x_cartec_token: str | None = Header(default=None),
                   db: Session = Depends(get_db)):
    u = _uredjaj(db, x_cartec_token)
    if db.query(MjerenjeOsovine).filter(MjerenjeOsovine.otisak == p.otisak).first():
        db.commit()
        return {"ok": True, "duplikat": True}
    vrijeme = p.vrijeme if p.vrijeme.tzinfo else p.vrijeme.replace(tzinfo=timezone.utc)
    vrijeme = vrijeme.astimezone(timezone.utc)
    t = _nadji_ili_kreiraj_test(db, u, p, vrijeme)
    novi_test = not t.mjerenja
    # Ponovljeno mjerenje iste osovine: ranija više ne vrijede.
    for m in t.mjerenja:
        if m.osovina == p.osovina and m.vrsta == p.vrsta and m.vazece and _utc(m.vrijeme) <= vrijeme:
            m.vazece = False
    noviji = any(m.osovina == p.osovina and m.vrsta == p.vrsta and _utc(m.vrijeme) > vrijeme
                 for m in t.mjerenja)
    m = MjerenjeOsovine(test=t, otisak=p.otisak, osovina=p.osovina, vrsta=p.vrsta, vrijeme=vrijeme,
                        sila_lijevo=p.sila_lijevo, sila_desno=p.sila_desno,
                        razlika_pct=_razlika(p.sila_lijevo, p.sila_desno), tezina=p.tezina,
                        vazece=not noviji)
    db.add(m)
    if vrijeme < _utc(t.pocetak):
        t.pocetak = vrijeme
    if vrijeme > _utc(t.kraj):
        t.kraj = vrijeme
    db.flush()
    db.refresh(t)
    _ocijeni(db, t, novi_test)
    db.commit()
    # Pitanje mehaničaru „koje vozilo?" — Toni 17.11.2026.: rješava se drukčije, kasnije.
    # Zasad nerazvrstan test samo čeka na popisu „Testovi kočnica" (bez obavijesti).
    return {"ok": True, "test_id": t.id, "status": t.status, "nalog_id": t.nalog_id, "gb": t.gb}


def _lokalno(d: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        return _utc(d).astimezone(ZoneInfo("Europe/Zagreb")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return _utc(d).strftime("%H:%M")


def _obavijesti_nerazvrstan(db: Session, t: TestKocnica) -> None:
    try:
        from ..push import obavijesti_ulogu
        tekst = f"Test kočnica u {_lokalno(t.pocetak)} — koje vozilo?"
        for uloga in (Uloga.voditelj, Uloga.poslovodja):
            obavijesti_ulogu(db, uloga, "Test kočnica", tekst, url="/testovi-kocnica")
    except Exception:  # noqa: BLE001 — obavijest nije bitna za spremanje mjerenja
        pass


# --- pregled i vezanje (portal) ---------------------------------------------
def _test_out(db: Session, t: TestKocnica, nalozi: dict[int, Nalog] | None = None) -> dict:
    def nalog_mini(n: Nalog | None):
        if not n:
            return None
        return {"id": n.id, "broj": n.broj, "naslov": n.naslov,
                "gb": n.vozilo.gb if n.vozilo else None, "status": n.status.value}

    kand_ids = [int(x) for x in (t.kandidati or "").split(",") if x.strip().isdigit()]
    kand = []
    for i in kand_ids:
        n = (nalozi or {}).get(i) or db.get(Nalog, i)
        if n and n.status in OTVORENI:
            kand.append(nalog_mini(n))
    vazeca = [m for m in t.mjerenja if m.vazece]
    return {
        "id": t.id, "status": t.status, "napomena": t.napomena,
        "pocetak": _utc(t.pocetak).isoformat(), "kraj": _utc(t.kraj).isoformat(),
        "gb": t.gb, "nalog": nalog_mini(db.get(Nalog, t.nalog_id) if t.nalog_id else None),
        "kandidati": kand,
        "osovina": len({m.osovina for m in vazeca if m.vrsta == "radna"}),
        "mjerenja": [{
            "id": m.id, "osovina": m.osovina, "vrsta": m.vrsta, "vrijeme": _utc(m.vrijeme).isoformat(),
            "sila_lijevo": m.sila_lijevo, "sila_desno": m.sila_desno, "razlika_pct": m.razlika_pct,
            "tezina": m.tezina, "vazece": m.vazece,
        } for m in sorted(t.mjerenja, key=lambda m: (m.vrsta != "radna", m.osovina, m.vrijeme))],
    }


def _smije_vidjeti(k: Korisnik) -> None:
    if k.uloga == Uloga.vozac:
        raise HTTPException(status_code=403, detail="Nemate ovlasti")


@router.get("/testovi")
def testovi(status: str | None = Query(default=None, pattern="^(vezan|nerazvrstan|ceka_potvrdu|otvoreni)$"),
            nalog_id: int | None = None, gb: str | None = None,
            limit: int = Query(default=50, ge=1, le=500),
            db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    _smije_vidjeti(k)
    q = db.query(TestKocnica)
    if status == "otvoreni":
        q = q.filter(TestKocnica.status.in_(("nerazvrstan", "ceka_potvrdu")))
    elif status:
        q = q.filter(TestKocnica.status == status)
    if nalog_id:
        q = q.filter(TestKocnica.nalog_id == nalog_id)
    if gb:
        q = q.filter(TestKocnica.gb == gb.strip())
    return [_test_out(db, t) for t in q.order_by(TestKocnica.pocetak.desc()).limit(limit).all()]


@router.get("/otvoreni-nalozi")
def otvoreni_nalozi_za_gb(gb: str = Query(min_length=1, max_length=40),
                          db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    """Otvoreni nalozi vozila po GB-u — za ručni odabir kad pravog vozila nema među gumbima."""
    _smije_vidjeti(k)
    from ..models import Vozilo
    red = (db.query(Nalog).join(Vozilo, Vozilo.id == Nalog.vozilo_id)
           .filter(Vozilo.gb == gb.strip(), Nalog.status.in_(OTVORENI))
           .order_by(Nalog.kreiran.desc()).all())
    return [{"id": n.id, "broj": n.broj, "naslov": n.naslov, "gb": gb.strip()} for n in red]


class VeziIn(BaseModel):
    nalog_id: int


@router.post("/testovi/{test_id}/vezi")
def vezi_test(test_id: int, p: VeziIn, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    """Čovjek odabere nalog (= vozilo po GB-u) za test. Ručni izbor je konačan."""
    _smije_vidjeti(k)
    t = db.get(TestKocnica, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test ne postoji")
    n = db.get(Nalog, p.nalog_id)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    t.nalog_id = n.id
    t.gb = n.vozilo.gb if n.vozilo else None
    t.status = "vezan"
    t.napomena = None
    t.vezao_id = k.id
    db.commit()
    return _test_out(db, t)


def blokira_zatvaranje(db: Session, nalog_id: int) -> TestKocnica | None:
    """Nerazvrstan / nepotvrđen test koji bi mogao pripadati ovom nalogu."""
    for t in db.query(TestKocnica).filter(TestKocnica.status.in_(("nerazvrstan", "ceka_potvrdu"))).all():
        ids = {x for x in (t.kandidati or "").split(",") if x}
        if t.nalog_id == nalog_id or str(nalog_id) in ids:
            return t
    return None


# --- uređaji (vlasnik, Šifrarnik → Integracije) -----------------------------
@router.get("/uredjaji")
def uredjaji(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    out = []
    for u in db.query(CartecUredjaj).order_by(CartecUredjaj.kreiran.desc()).all():
        out.append({"id": u.id, "naziv": u.naziv, "odobren": u.odobren,
                    "kreiran": _utc(u.kreiran).isoformat(),
                    "zadnji_kontakt": _utc(u.zadnji_kontakt).isoformat() if u.zadnji_kontakt else None,
                    "verzija": u.verzija, "stanje": u.stanje,
                    "stanje_vrijeme": _utc(u.stanje_vrijeme).isoformat() if u.stanje_vrijeme else None})
    return out


class OdobriIn(BaseModel):
    odobren: bool


@router.post("/uredjaji/{uid}")
def odobri_uredjaj(uid: int, p: OdobriIn, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    u = db.get(CartecUredjaj, uid)
    if not u:
        raise HTTPException(status_code=404, detail="Uređaj ne postoji")
    u.odobren = p.odobren
    db.commit()
    return {"id": u.id, "odobren": u.odobren}


@router.delete("/uredjaji/{uid}")
def obrisi_uredjaj(uid: int, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    u = db.get(CartecUredjaj, uid)
    if not u:
        raise HTTPException(status_code=404, detail="Uređaj ne postoji")
    if db.query(TestKocnica).filter(TestKocnica.uredjaj_id == uid).first():
        u.odobren = False   # ima testove — samo ga isključi (povijest ostaje)
    else:
        db.delete(u)
    db.commit()
    return {"ok": True}
