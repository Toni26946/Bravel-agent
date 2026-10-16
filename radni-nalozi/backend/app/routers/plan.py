"""Plan radione — pregled za vlasnika (ai_poslovodja).

Jutarnji plan (prioriteti + hitno), dodjela i slanje operacije mehaničaru na
potvrdu (push), mehaničareva potvrda početka (starta mjerač), prekid s razlogom
(gotovo / nije gotovo / nema dijelova) i dnevnik promjena plana (churn).

Sve je vidljivo/dostupno SAMO vlasniku; mehaničarske akcije (potvrdi/prekini)
smije i dodijeljeni mehaničar.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_ai_poslovodja
from ..database import get_db
from ..models import (
    Korisnik, Nalog, Operacija, PlanDogadaj, StatusNaloga, Zadatak,
    ZadatakRadnikVrijeme,
)
from ..push import obavijesti_korisnika
from .nalozi import _aware, _pokreni_mjerac, _zaustavi_mjerac, _SERVISERI

router = APIRouter(prefix="/plan", tags=["plan"])
_samo_vlasnik = zahtijevaj_ai_poslovodja()

_AKTIVNI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)
PROZOR_MIN = 5
KRAJ_H, KRAJ_M = 14, 45
MAX_HITNO = 3
# Interni/pomoćni nalozi koji se NE prikazuju u planu (npr. "RADIONA").
_SKRIVENI_GB = {"400"}


# --- pomoćno ---------------------------------------------------------------
def _ms(dt):
    return int(_aware(dt).timestamp() * 1000) if dt else None


def _mehanicar(z: Zadatak):
    return z.radnici[0] if z.radnici else None


def _plan_status(z: Zadatak) -> str:
    if z.gotovo:
        return "gotovo"
    if z.razlog_prekida == "dijelovi":
        return "dijelovi"
    if not z.radnici:
        return "plan"              # nema radnika → natrag u plan
    if z.zapoceto:
        return "radu"
    if z.ceka_potvrdu:
        return "ceka"              # poslano, čeka potvrdu (i nova i nastavak)
    if (z.utroseno_sek or 0) > 0:
        return "pauza"             # rađeno prije, nije poslano → treba poslati nastavak
    return "plan"                  # dodijeljen ali nije poslan


def _hr_now() -> datetime:
    """Hrvatsko lokalno vrijeme bez vanjskih ovisnosti (CET/CEST po DST pravilu)."""
    now = datetime.now(timezone.utc)
    y = now.year

    def _zadnja_ned(mj):
        d = 31
        while datetime(y, mj, d).weekday() != 6:
            d -= 1
        return datetime(y, mj, d, 1, 0, tzinfo=timezone.utc)  # prebacivanje u 01:00 UTC

    ljeto = _zadnja_ned(3) <= now < _zadnja_ned(10)
    return now + timedelta(hours=2 if ljeto else 1)


def _poslije_smjene() -> bool:
    n = _hr_now()
    return n.hour > KRAJ_H or (n.hour == KRAJ_H and n.minute >= KRAJ_M)


def _gb(n: Nalog) -> str:
    return (n.vozilo.gb if n and n.vozilo else "") or ""


def _set_radnici(db: Session, z: Zadatak, ids: list[int]) -> None:
    """Postavi radnike na zadatak BEZ pokretanja mjerača i bez odjave s drugih
    (planiranje unaprijed). Mjerač kreće tek na mehaničarevu potvrdu."""
    valjani: list[Korisnik] = []
    for rid in dict.fromkeys(ids):
        r = db.get(Korisnik, rid)
        if not r or r.uloga not in _SERVISERI:
            raise HTTPException(status_code=400, detail=f"Korisnik {rid} nije mehaničar")
        valjani.append(r)
    z.radnici = valjani


def _log(db, korisnik, tip, opis, nalog_id=None, zadatak_id=None, radnik_id=None):
    db.add(PlanDogadaj(
        tip=tip, opis=opis, nalog_id=nalog_id, zadatak_id=zadatak_id,
        radnik_id=radnik_id, kreirao_id=(korisnik.id if korisnik else None),
    ))


def _zad(db: Session, zid: int) -> Zadatak:
    z = db.get(Zadatak, zid)
    if not z:
        raise HTTPException(status_code=404, detail="Zadatak ne postoji")
    return z


# Tokeni koji opisuju POLOŽAJ, ne vrstu posla — izbacuju se pri grupiranju
# kategorija (da "KOČNICE 3. OSOVINA" i "KOČNICE 1. OSOVINA" budu isto: "KOČNICE").
_KAT_POLOZAJ = {
    "OSOVINA", "OSOVINE", "OSOVINI", "LIJEVA", "DESNA", "LIJEVO", "DESNO",
    "LIJEVE", "DESNE", "STRANA", "STRANE", "STRANI", "PREDNJA", "ZADNJA",
    "PREDNJE", "ZADNJE", "PREDNJI", "ZADNJI", "GORE", "DOLJE", "GORNJA",
    "DONJA", "UNUTARNJA", "VANJSKA", "PRVA", "DRUGA", "TRECA", "TREĆA",
    "I", "II", "III", "IV", "V",
}


def _norm_kat(kat: str | None) -> str:
    """Normalizira kategoriju za grupiranje po vrsti posla: velika slova,
    bez brojeva i oznaka položaja (osovina/strana/lijeva…)."""
    if not kat:
        return ""
    toks = re.split(r"[\s,./\-]+", kat.upper())
    keep = [t for t in toks if t and not t.replace(".", "").isdigit() and t not in _KAT_POLOZAJ]
    return " ".join(keep) or kat.upper().strip()


def _preporuke_po_kategoriji(db: Session, aktivni_ids: list[int]) -> dict[str, int]:
    """Za svaku (normaliziranu) kategoriju posla vrati mehaničara među aktivnima
    koji je dosad najviše puta ZAVRŠIO operaciju te vrste — prijedlog po iskustvu."""
    if not aktivni_ids:
        return {}
    rows = (
        db.query(Operacija.kategorija, Korisnik.id, func.count(Zadatak.id).label("c"))
        .join(Zadatak, Zadatak.operacija_id == Operacija.id)
        .join(Zadatak.radnici)
        .filter(Zadatak.gotovo.is_(True), Korisnik.id.in_(aktivni_ids))
        .group_by(Operacija.kategorija, Korisnik.id)
        .all()
    )
    agg: dict[str, dict[int, int]] = {}   # norm-kategorija -> {radnik_id: broj}
    for kat, rid, c in rows:
        nk = _norm_kat(kat)
        if not nk:
            continue
        d = agg.setdefault(nk, {})
        d[rid] = d.get(rid, 0) + c
    return {nk: max(d, key=d.get) for nk, d in agg.items() if d}


def _radio_po_zadatku(db: Session, zad_ids: list[int]) -> dict[int, str]:
    """Za svaki zadatak vrati IME radnika koji je na njemu nakupio najviše
    vremena (iz ZadatakRadnikVrijeme) — tko je radio, i kad više nije dodijeljen."""
    if not zad_ids:
        return {}
    rows = (
        db.query(ZadatakRadnikVrijeme.zadatak_id, Korisnik.ime, ZadatakRadnikVrijeme.utroseno_sek)
        .join(Korisnik, Korisnik.id == ZadatakRadnikVrijeme.radnik_id)
        .filter(ZadatakRadnikVrijeme.zadatak_id.in_(zad_ids), ZadatakRadnikVrijeme.utroseno_sek > 0)
        .all()
    )
    best: dict[int, tuple[str, int]] = {}   # zadatak_id -> (ime, sek)
    for zid, ime, sek in rows:
        cur = best.get(zid)
        if cur is None or (sek or 0) > cur[1]:
            best[zid] = (ime, sek or 0)
    return {zid: v[0] for zid, v in best.items()}


# --- GET /plan -------------------------------------------------------------
@router.get("")
def plan(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    nalozi = db.query(Nalog).filter(Nalog.status.in_(_AKTIVNI)).all()
    nalozi = [n for n in nalozi if _gb(n) not in _SKRIVENI_GB]   # bez internih (RADIONA)
    nalozi.sort(key=lambda n: (
        0 if n.plan_hitno else 1,
        n.plan_rang if n.plan_rang is not None else 10 ** 9,
        n.id,
    ))
    meh = (
        db.query(Korisnik)
        .filter(Korisnik.uloga.in_(_SERVISERI), Korisnik.aktivan.is_(True))
        .order_by(Korisnik.ime).all()
    )
    preporuke = _preporuke_po_kategoriji(db, [m.id for m in meh])
    zad_ids = [z.id for n in nalozi for op in n.operacije for z in op.zadaci]
    radili = _radio_po_zadatku(db, zad_ids)   # tko je nakupio vrijeme na zadatku
    out_nal = []
    for i, n in enumerate(nalozi):
        ops = []
        for op in n.operacije:
            for z in op.zadaci:
                m = _mehanicar(z)
                ops.append({
                    "id": z.id, "naziv": z.opis, "kat": op.kategorija,
                    "mehId": m.id if m else None,
                    "preporukaId": preporuke.get(_norm_kat(op.kategorija)),
                    "radioIme": radili.get(z.id),
                    "status": _plan_status(z),
                    "akumSek": int(z.utroseno_sek or 0),
                    "startTs": _ms(z.zapoceto),
                })
        voz = n.vozilo
        naziv = " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x)
        out_nal.append({
            "id": n.id, "gb": _gb(n),
            "vozilo": naziv or (n.naslov or ""),
            "reg": (voz.registracija if voz else "") or "",
            "rang": n.plan_rang,
            "hitno": bool(n.plan_hitno),
            "cekaDijelove": n.status == StatusNaloga.ceka_dijelove,
            "usaoTs": _ms(n.kreiran),
            "ops": ops,
        })
    danas = datetime.now(timezone.utc).date()
    promjene = (
        db.query(PlanDogadaj).filter(PlanDogadaj.datum == danas)
        .order_by(PlanDogadaj.vrijeme.desc()).all()
    )
    return {
        "mehanicari": [{"id": m.id, "ime": m.ime} for m in meh],
        "nalozi": out_nal,
        "promjene": [{"t": _ms(p.vrijeme), "tekst": p.opis} for p in promjene],
    }


# --- write: vlasnik --------------------------------------------------------
class RedoslijedIn(BaseModel):
    redoslijed: list[int]


class HitnoIn(BaseModel):
    hitno: bool


class DodijeliIn(BaseModel):
    radnici_ids: list[int] = []


class PrekiniIn(BaseModel):
    razlog: str  # 'gotovo' | 'nije' | 'dijelovi'


@router.put("/redoslijed")
def redoslijed(p: RedoslijedIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    for i, nid in enumerate(p.redoslijed):
        n = db.get(Nalog, nid)
        if n:
            n.plan_rang = i
    db.commit()
    return {"ok": True}


class DodajIn(BaseModel):
    gb: str


@router.post("/dodaj")
def dodaj_u_plan(p: DodajIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Dodaj kamion (po garažnom broju) na KRAJ plana — za brzo slaganje plana
    tipkanjem GB-ova. Vraća na koju je poziciju došao."""
    gb = (p.gb or "").strip()
    if not gb:
        raise HTTPException(status_code=400, detail="Upiši garažni broj")
    g = gb.lstrip("0") or gb
    nalog = None
    for n in db.query(Nalog).filter(Nalog.status.in_(_AKTIVNI)).all():
        ng = _gb(n)
        if ng == gb or (ng.lstrip("0") or ng) == g:
            nalog = n
            break
    if not nalog:
        raise HTTPException(status_code=404, detail=f"Nema aktivnog naloga za GB {gb}")
    maxr = db.query(func.max(Nalog.plan_rang)).filter(Nalog.status.in_(_AKTIVNI)).scalar()
    nalog.plan_rang = (maxr if maxr is not None else -1) + 1
    db.commit()
    return {"ok": True, "gb": _gb(nalog), "rang": nalog.plan_rang}


@router.post("/ocisti")
def ocisti_plan(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Obriši ručni redoslijed (plan_rang) sa svih naloga — kreni novi plan."""
    for n in db.query(Nalog).filter(Nalog.plan_rang.isnot(None)).all():
        n.plan_rang = None
    db.commit()
    return {"ok": True}


@router.patch("/nalog/{nid}/hitno")
def hitno(nid: int, p: HitnoIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    n = db.get(Nalog, nid)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    if p.hitno and not n.plan_hitno:
        br = db.query(Nalog).filter(Nalog.plan_hitno.is_(True), Nalog.status.in_(_AKTIVNI)).count()
        if br >= MAX_HITNO:
            raise HTTPException(status_code=409, detail=f"Najviše {MAX_HITNO} hitna vozila")
    n.plan_hitno = bool(p.hitno)
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/dodijeli")
def dodijeli(zid: int, p: DodijeliIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    _set_radnici(db, z, p.radnici_ids or [])
    z.ceka_potvrdu = False
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/posalji")
def posalji(zid: int, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    m = _mehanicar(z)
    if not m:
        raise HTTPException(status_code=400, detail="Nema dodijeljenog mehaničara")
    n = z.operacija.nalog
    # WIP churn: mehaničar ima nezavršenu operaciju drugdje?
    zauzet = (
        db.query(Zadatak).join(Zadatak.radnici)
        .filter(Korisnik.id == m.id, Zadatak.id != z.id, Zadatak.gotovo.is_(False))
        .filter((Zadatak.zapoceto.isnot(None)) | (Zadatak.utroseno_sek > 0) | (Zadatak.ceka_potvrdu.is_(True)))
        .first()
    )
    if zauzet:
        _log(db, korisnik, "wip", f"{m.ime} dobio novu dok prethodna nije gotova (GB {_gb(n)})",
             nalog_id=n.id, zadatak_id=z.id, radnik_id=m.id)
    z.ceka_potvrdu = True
    z.razlog_prekida = None
    obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{z.opis} · GB {_gb(n)}", "/plan")
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/makni-radnika")
def makni_radnika(zid: int, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    m = _mehanicar(z)
    n = z.operacija.nalog
    _zaustavi_mjerac(z)
    _set_radnici(db, z, [])
    z.ceka_potvrdu = False
    if m:
        _log(db, korisnik, "makni", f"Radnik maknut — {m.ime} (GB {_gb(n)})",
             nalog_id=n.id, zadatak_id=z.id, radnik_id=m.id)
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/dio-stigao")
def dio_stigao(zid: int, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    if z.razlog_prekida == "dijelovi":
        z.razlog_prekida = None
        z.ceka_potvrdu = True
    db.commit()
    return {"ok": True}


# --- write: mehaničar (ili vlasnik) ---------------------------------------
def _smije_meh(korisnik: Korisnik, z: Zadatak) -> bool:
    return bool(korisnik.ai_poslovodja or any(r.id == korisnik.id for r in z.radnici))


@router.post("/zadatak/{zid}/potvrdi")
def potvrdi(zid: int, korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    if not _smije_meh(korisnik, z):
        raise HTTPException(status_code=403, detail="Nije tvoja operacija")
    m = _mehanicar(z)
    if m:
        # churn: ovaj radnik je nedavno pauzirao DRUGU operaciju → prešao na drugu
        n = z.operacija.nalog
        gran = datetime.now(timezone.utc).timestamp() - PROZOR_MIN * 60
        drugi = (
            db.query(Zadatak).join(Zadatak.radnici)
            .filter(Korisnik.id == m.id, Zadatak.id != z.id, Zadatak.prekid_vrijeme.isnot(None)).all()
        )
        for d in drugi:
            if d.prekid_vrijeme and _aware(d.prekid_vrijeme).timestamp() >= gran and not _poslije_smjene():
                _log(db, korisnik, "churn",
                     f"{m.ime} prešao na drugu bez završetka prethodne (GB {_gb(n)})",
                     nalog_id=n.id, zadatak_id=z.id, radnik_id=m.id)
            d.prekid_vrijeme = None
    z.ceka_potvrdu = False
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    _pokreni_mjerac(db, z)
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/prekini")
def prekini(zid: int, p: PrekiniIn, korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    if not _smije_meh(korisnik, z):
        raise HTTPException(status_code=403, detail="Nije tvoja operacija")
    _zaustavi_mjerac(z)
    z.ceka_potvrdu = False
    if p.razlog == "gotovo":
        z.gotovo = True
        z.zavrseno = datetime.now(timezone.utc)
        z.razlog_prekida = None
        z.prekid_vrijeme = None
    elif p.razlog == "dijelovi":
        z.razlog_prekida = "dijelovi"
        z.prekid_vrijeme = None
    else:  # 'nije' = pauza; pokreni prozor za churn (osim nakon kraja smjene)
        z.razlog_prekida = None
        z.prekid_vrijeme = None if _poslije_smjene() else datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
