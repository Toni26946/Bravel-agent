"""Valjci — mjerenje kočnica preko aplikacije (Toni 19.11.2026.).

Tok:
1. Upišu se vozila na valjcima: GB kamiona i (ako ima) GB prikolice.
2. App iz vrste vozila (registar) nacrta osovine: tegljač 2, šumar 3, prikolica 2,
   poluprikolica 3. Nepoznata vrsta → app pita broj osovina.
3. Osoba u kamionu stisne osovinu koju mjeri (i „Ručna" ako mjeri ručnu). Svako
   mjerenje s valjaka ide na tu osovinu dok se ne stisne druga (ponovljeno = prepiše).
   Cartecov broj osovine se ne gleda (Cartec je namješten na jedne postavke).
4. Sila se vidi uživo (skripta šalje /cartec/uzivo ~1x u sekundi).
5. Rezultati su test kočnica vezan uz nalog vozila (otvoreni, ili se otvori novi).
   Na završetku: operacija „KOČNICE N. OSOVINA" SAMO za osovine koje nisu dobre.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik
from ..database import get_db
from ..models import (
    CartecUredjaj,
    Korisnik,
    Nalog,
    Operacija,
    RegistarVozila,
    StatusNaloga,
    TestKocnica,
    Uloga,
    ValjciSesija,
    Vozilo,
    Zadatak,
)

MODUL = "/valjci"


def ima_pristup(k: Korisnik) -> bool:
    """Voditelj/poslovođa ili korisnik kojem je dodijeljen modul /valjci (Toni bira tko)."""
    mod = k.moduli if isinstance(k.moduli, (list, tuple)) else []
    return k.uloga in (Uloga.voditelj, Uloga.poslovodja) or MODUL in mod


def _korisnik_valjaka(k: Korisnik = Depends(trenutni_korisnik)) -> Korisnik:
    if not ima_pristup(k):
        raise HTTPException(status_code=403, detail="Nemaš pristup aplikaciji Valjci.")
    return k


router = APIRouter(prefix="/valjci", tags=["valjci"], dependencies=[Depends(_korisnik_valjaka)])

LOSA_RAZLIKA_PCT = 25          # razlika L/D iznad ovoga = osovina nije dobra (isto kao crveno na crtežu)
SESIJA_TRAJE_H = 4             # zaboravljena sesija se sama zatvori
AKTIVNI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)

# Vrsta iz registra vozila → (naziv, broj osovina)
_VRSTE = [
    (("ŠLEP", "POLUPRIK"), "poluprikolica", 3),
    (("PRIKOL",), "prikolica", 2),
    (("TEGLJ",), "tegljač", 2),
    (("DIZAL", "ŠUMAR"), "šumar", 3),
]


def _sad() -> datetime:
    return datetime.now(timezone.utc)


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _norm_gb(gb: str) -> str:
    return "".join(str(gb or "").split())


def _registar(db: Session, gb: str) -> RegistarVozila | None:
    return db.get(RegistarVozila, gb) or db.get(RegistarVozila, gb.lstrip("0") or gb)


def vrsta_vozila(db: Session, gb: str) -> tuple[str | None, int | None]:
    """(naziv vrste, broj osovina) po GB-u iz registra; (None, None) ako vrsta nije poznata."""
    r = _registar(db, gb)
    tekst = " ".join(x for x in ((r.vrsta if r else None), (r.tip if r else None)) if x).upper()
    for kljucevi, naziv, osovina in _VRSTE:
        if any(k in tekst for k in kljucevi):
            return naziv, osovina
    return None, None


def _postoji(db: Session, gb: str) -> bool:
    return bool(_registar(db, gb)) or db.query(Vozilo.id).filter(Vozilo.gb == gb).first() is not None


def _vozila(s: ValjciSesija) -> list[dict]:
    try:
        return json.loads(s.vozila or "[]")
    except ValueError:
        return []


def _uredjaj_valjaka(db: Session) -> CartecUredjaj | None:
    return (db.query(CartecUredjaj).filter(CartecUredjaj.odobren.is_(True))
            .order_by(CartecUredjaj.zadnji_kontakt.desc().nullslast(), CartecUredjaj.id.desc()).first())


# --- za cartec.py (mjerenja sa skripte) --------------------------------------
def aktivna_sesija(db: Session, u: CartecUredjaj) -> ValjciSesija | None:
    s = (db.query(ValjciSesija)
         .filter(ValjciSesija.uredjaj_id == u.id, ValjciSesija.zavrsena.is_(None))
         .order_by(ValjciSesija.id.desc()).first())
    if s is not None and _sad() - _utc(s.pocetak) > timedelta(hours=SESIJA_TRAJE_H):
        zavrsi(db, s)
        return None
    return s


def usmjeri(db: Session, s: ValjciSesija) -> tuple[TestKocnica, int, str]:
    """Kamo ide mjerenje: test odabranog vozila, odabrana osovina, radna/ručna po tipki."""
    vozila = _vozila(s)
    v = vozila[min(max(s.odabrano_vozilo, 0), len(vozila) - 1)]
    t = db.get(TestKocnica, v["test_id"])
    return t, s.odabrana_osovina, ("parkirna" if s.rucna else "radna")


def _vazeca(t: TestKocnica | None, osovina: int, vrsta: str):
    if t is None:
        return None
    ms = [m for m in t.mjerenja if m.osovina == osovina and m.vrsta == vrsta and m.vazece]
    return ms[-1] if ms else None


def zavrsi_ako_sve_izmjereno(db: Session, s: ValjciSesija) -> bool:
    """Vozilo sišlo s valjaka: ako je radna izmjerena na svim osovinama — završi test."""
    for v in _vozila(s):
        t = db.get(TestKocnica, v["test_id"])
        if any(_vazeca(t, br, "radna") is None for br in range(1, v["osovina"] + 1)):
            return False
    zavrsi(db, s)
    return True


def _kn(n: int) -> str:
    return f"{n / 1000:.1f}".replace(".", ",")


def zavrsi(db: Session, s: ValjciSesija) -> list[str]:
    """Zatvori mjerenje i u nalog upiši operacije SAMO za osovine koje nisu dobre."""
    if s.zavrsena is not None:
        return []
    from ..pregledi_auto import _aktivni_nalog, _vozilo_za_gb
    dodano: list[str] = []
    korisnik = db.get(Korisnik, s.korisnik_id)
    for v in _vozila(s):
        t = db.get(TestKocnica, v["test_id"])
        if t is None:
            continue
        lose = []
        for br in range(1, v["osovina"] + 1):
            for vrsta, naziv in (("radna", "Radna"), ("parkirna", "Ručna")):
                m = _vazeca(t, br, vrsta)
                if m is not None and (m.razlika_pct or 0) > LOSA_RAZLIKA_PCT:
                    lose.append((br, f"{naziv} kočnica: razlika {round(m.razlika_pct)} % "
                                     f"(L {_kn(m.sila_lijevo)} kN / D {_kn(m.sila_desno)} kN) — valjci "
                                     f"{_utc(m.vrijeme).astimezone(_zg()).strftime('%d.%m.%Y.')}"))
        if not lose:
            continue
        n = db.get(Nalog, t.nalog_id) if t.nalog_id else None
        if n is None or n.status not in AKTIVNI:
            n = _aktivni_nalog(db, _vozilo_za_gb(db, v["gb"]), korisnik)
            t.nalog_id = n.id
        for br, opis in lose:
            kat = f"KOČNICE {br}. OSOVINA"
            op = next((o for o in n.operacije if (o.kategorija or "").upper() == kat), None)
            if op is None:
                op = Operacija(kategorija=kat, redoslijed=len(n.operacije))
                n.operacije.append(op)
            op.zadaci.append(Zadatak(opis=opis, redoslijed=len(op.zadaci)))
            dodano.append(f"GB {v['gb']} · {kat}: {opis}")
        if n.plan_rang is None:   # da se popravak vidi u planu radione
            mx = db.query(func.max(Nalog.plan_rang)).filter(Nalog.status.in_(AKTIVNI)).scalar()
            n.plan_rang = (mx if mx is not None else -1) + 1
    s.zavrsena = _sad()
    db.commit()
    return dodano


def _zg():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Zagreb")
    except Exception:  # noqa: BLE001
        return timezone.utc


# --- ekran /valjci ------------------------------------------------------------
def _mjerenje_out(m) -> dict | None:
    if m is None:
        return None
    return {"l": m.sila_lijevo, "d": m.sila_desno, "razlika": m.razlika_pct,
            "losa": (m.razlika_pct or 0) > LOSA_RAZLIKA_PCT, "vrijeme": _utc(m.vrijeme).isoformat()}


def _out(db: Session, s: ValjciSesija) -> dict:
    u = db.get(CartecUredjaj, s.uredjaj_id)
    vozila = []
    for v in _vozila(s):
        t = db.get(TestKocnica, v["test_id"])
        n = db.get(Nalog, t.nalog_id) if t and t.nalog_id else None
        vozila.append({
            "gb": v["gb"], "vrsta": v.get("vrsta"), "test_id": v["test_id"],
            "nalog": {"id": n.id, "broj": n.broj, "novi": v.get("novi_nalog", False)} if n else None,
            "osovine": [{"br": br, "radna": _mjerenje_out(_vazeca(t, br, "radna")),
                         "rucna": _mjerenje_out(_vazeca(t, br, "parkirna"))}
                        for br in range(1, v["osovina"] + 1)],
        })
    uzivo = None
    if u and u.uzivo and u.uzivo_vrijeme and _sad() - _utc(u.uzivo_vrijeme) <= timedelta(seconds=4):
        try:
            uzivo = json.loads(u.uzivo)
        except ValueError:
            uzivo = None
    spojeno = bool(u and u.zadnji_kontakt and _sad() - _utc(u.zadnji_kontakt) <= timedelta(minutes=3))
    return {"id": s.id, "vozila": vozila, "odabrano_vozilo": s.odabrano_vozilo,
            "odabrana_osovina": s.odabrana_osovina, "rucna": s.rucna,
            "zavrsena": _utc(s.zavrsena).isoformat() if s.zavrsena else None,
            "pocetak": _utc(s.pocetak).isoformat(), "uzivo": uzivo, "spojeno": spojeno,
            "losa_razlika": LOSA_RAZLIKA_PCT}


class SesijaIn(BaseModel):
    kamion_gb: str = Field(min_length=1, max_length=40)
    prikolica_gb: str | None = Field(default=None, max_length=40)
    osovine: dict[str, int] | None = None     # za vozila nepoznate vrste: {gb: broj osovina}


@router.post("/sesija")
def nova_sesija(p: SesijaIn, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    u = _uredjaj_valjaka(db)
    if u is None:
        raise HTTPException(status_code=409, detail="Računalo s valjcima nije spojeno.")
    gbs = [g for g in (_norm_gb(p.kamion_gb), _norm_gb(p.prikolica_gb or "")) if g]
    if len(gbs) == 2 and gbs[0] == gbs[1]:
        raise HTTPException(status_code=400, detail="Kamion i prikolica ne mogu imati isti GB.")
    vozila, treba = [], []
    for gb in gbs:
        if not _postoji(db, gb):
            raise HTTPException(status_code=404, detail=f"GB {gb} ne postoji u popisu vozila.")
        naziv, osovina = vrsta_vozila(db, gb)
        rucno = (p.osovine or {}).get(gb)
        if rucno:
            osovina = max(1, min(int(rucno), 8))
        if not osovina:
            treba.append(gb)
        vozila.append({"gb": gb, "vrsta": naziv, "osovina": osovina})
    if treba:
        return {"treba_osovine": treba}
    # Prethodno mjerenje na istim valjcima je gotovo.
    for stara in (db.query(ValjciSesija)
                  .filter(ValjciSesija.uredjaj_id == u.id, ValjciSesija.zavrsena.is_(None)).all()):
        zavrsi(db, stara)
    from ..pregledi_auto import _vozilo_za_gb
    sad = _sad()
    s = ValjciSesija(uredjaj_id=u.id, korisnik_id=k.id, pocetak=sad, vozila="[]",
                     odabrano_vozilo=0, odabrana_osovina=1, rucna=False)
    db.add(s)
    db.flush()
    for i, v in enumerate(vozila):
        voz = _vozilo_za_gb(db, v["gb"])
        n = (db.query(Nalog).filter(Nalog.vozilo_id == voz.id, Nalog.status.in_(AKTIVNI))
             .order_by(Nalog.kreiran.desc()).first())
        v["novi_nalog"] = n is None
        if n is None:   # Toni: „nek se otvori novi, ako nema otvorenog"
            from .nalozi import _sljedeci_broj
            n = Nalog(broj=_sljedeci_broj(db), vozilo_id=voz.id, naslov=f"{v['gb']} — test kočnica",
                      kreirao_id=k.id, voditelj_id=k.id, status=StatusNaloga.otvoren)
            db.add(n)
            db.flush()
        t = TestKocnica(uredjaj_id=u.id, sesija=f"valjci-{s.id}-{i}", pocetak=sad, kraj=sad,
                        status="vezan", nalog_id=n.id, gb=v["gb"], vezao_id=k.id,
                        poveznica=secrets.token_urlsafe(18), obavijesteno=sad,
                        napomena="Mjereno preko aplikacije Valjci")
        db.add(t)
        db.flush()
        v["test_id"] = t.id
    s.vozila = json.dumps(vozila, ensure_ascii=False)
    db.commit()
    return _out(db, s)


@router.get("/aktivna")
def aktivna(db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    u = _uredjaj_valjaka(db)
    s = aktivna_sesija(db, u) if u else None
    db.commit()
    return _out(db, s) if s else None


@router.get("/sesija/{sid}")
def sesija(sid: int, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    s = db.get(ValjciSesija, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Nema tog mjerenja.")
    return _out(db, s)


class OdabirIn(BaseModel):
    vozilo: int = Field(ge=0, le=1)
    osovina: int = Field(ge=1, le=8)
    rucna: bool = False


@router.post("/sesija/{sid}/odabir")
def odabir(sid: int, p: OdabirIn, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    s = db.get(ValjciSesija, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Nema tog mjerenja.")
    if s.zavrsena is not None:
        raise HTTPException(status_code=409, detail="Mjerenje je završeno.")
    vozila = _vozila(s)
    if p.vozilo >= len(vozila) or p.osovina > vozila[p.vozilo]["osovina"]:
        raise HTTPException(status_code=400, detail="Nema te osovine.")
    s.odabrano_vozilo, s.odabrana_osovina, s.rucna = p.vozilo, p.osovina, p.rucna
    db.commit()
    return _out(db, s)


@router.post("/sesija/{sid}/zavrsi")
def zavrsi_sesiju(sid: int, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    s = db.get(ValjciSesija, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Nema tog mjerenja.")
    dodano = zavrsi(db, s)
    return {**_out(db, s), "operacije": dodano}
