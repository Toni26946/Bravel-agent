"""Plan radione — pregled za vlasnika (ai_poslovodja).

Jutarnji plan (prioriteti + hitno), dodjela i slanje operacije mehaničaru na
potvrdu (push), mehaničareva potvrda početka (starta mjerač), prekid s razlogom
(gotovo / nije gotovo / nema dijelova) i dnevnik promjena plana (churn).

Sve je vidljivo/dostupno SAMO vlasniku; mehaničarske akcije (potvrdi/prekini)
smije i dodijeljeni mehaničar.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_plan_pristup
from ..database import get_db
from ..models import (
    Korisnik, Nalog, Operacija, PlanDogadaj, PlanStanje, StatusNaloga, Zadatak,
    ZadatakRadnikVrijeme,
)
from ..push import obavijesti_korisnika
from .nalozi import _aware, _pokreni_mjerac, _zaustavi_mjerac, _SERVISERI, _auto_status_naloga, nalog_eager

router = APIRouter(prefix="/plan", tags=["plan"])
_samo_vlasnik = zahtijevaj_plan_pristup()   # vlasnik ILI tko ima modul '/plan'

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


def _je_odsutan(m) -> bool:
    """Je li mehaničar danas odsutan (godišnji/bolovanje) — ista logika kao /api/plan."""
    if not m.odsutnost_vrsta:
        return False
    danas = _hr_now().date().isoformat()
    if m.odsutnost_do and danas > m.odsutnost_do.isoformat():
        return False   # odsutnost istekla
    return True


# Auto-slanje jutarnjeg plana (Postavka ključevi; vrijeme je HR lokalno, datum je dan okidanja — jednokratno).
KLJUC_AUTO_HHMM = "plan_auto_hhmm"
KLJUC_AUTO_DATUM = "plan_auto_datum"


def _auto_slanje_stanje(db: Session) -> dict:
    from .. import norme
    hhmm = norme.get_postavka(db, KLJUC_AUTO_HHMM)
    datum = norme.get_postavka(db, KLJUC_AUTO_DATUM)
    return {"ukljuceno": bool(hhmm and datum), "ura": hhmm or "06:45", "datum": datum}


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


# --- zaključavanje plana ---------------------------------------------------
def _plan_stanje(db: Session) -> PlanStanje:
    """Dohvati (ili stvori) jedini redak stanja plana."""
    st = db.get(PlanStanje, 1)
    if not st:
        st = PlanStanje(id=1, zakljucan=False)
        db.add(st)
        db.flush()
    return st


def _zakljucan(db: Session) -> bool:
    """Je li plan zaključan ZA DANAS (HR datum)."""
    st = db.get(PlanStanje, 1)
    return bool(st and st.zakljucan and st.datum == _hr_now().date())


def _provjeri_otkljucan(db: Session) -> None:
    """Odbij promjenu sastava/redoslijeda plana dok je zaključan."""
    if _zakljucan(db):
        raise HTTPException(status_code=409, detail="🔒 Plan je zaključan — prvo ga otključaj")


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


def _radio_po_zadatku(db: Session, zad_ids: list[int]) -> dict[int, tuple[str, int]]:
    """Za svaki zadatak vrati (IME, ID) radnika koji je na njemu nakupio najviše
    vremena (iz ZadatakRadnikVrijeme) — tko je radio, i kad više nije dodijeljen."""
    if not zad_ids:
        return {}
    rows = (
        db.query(ZadatakRadnikVrijeme.zadatak_id, Korisnik.ime, Korisnik.id, ZadatakRadnikVrijeme.utroseno_sek)
        .join(Korisnik, Korisnik.id == ZadatakRadnikVrijeme.radnik_id)
        .filter(ZadatakRadnikVrijeme.zadatak_id.in_(zad_ids), ZadatakRadnikVrijeme.utroseno_sek > 0)
        .all()
    )
    best: dict[int, tuple[str, int, int]] = {}   # zadatak_id -> (ime, radnik_id, sek)
    for zid, ime, rid, sek in rows:
        cur = best.get(zid)
        if cur is None or (sek or 0) > cur[2]:
            best[zid] = (ime, rid, sek or 0)
    return {zid: (v[0], v[1]) for zid, v in best.items()}   # zadatak_id -> (ime, radnik_id)


# --- GET /plan -------------------------------------------------------------
@router.get("")
def plan(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    nalozi = db.query(Nalog).options(*nalog_eager()).filter(Nalog.status.in_(_AKTIVNI)).all()
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
                    "mehovi": [{"id": r.id, "ime": r.ime} for r in z.radnici],
                    "mehIds": [r.id for r in z.radnici],
                    "preporukaId": preporuke.get(_norm_kat(op.kategorija)),
                    "radioIme": (radili.get(z.id) or (None, None))[0],
                    "radioId": (radili.get(z.id) or (None, None))[1],
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
    st = db.get(PlanStanje, 1)
    zakljucan = bool(st and st.zakljucan and st.datum == _hr_now().date())
    zak = db.get(Korisnik, st.zakljucao_id) if (zakljucan and st.zakljucao_id) else None
    _danas_iso = _hr_now().date().isoformat()

    def _odsutan(m) -> bool:
        if not m.odsutnost_vrsta:
            return False
        if m.odsutnost_do and _danas_iso > m.odsutnost_do.isoformat():
            return False   # odsutnost istekla
        return True

    return {
        "mehanicari": [{"id": m.id, "ime": m.ime, "odsutan": _odsutan(m)} for m in meh],
        "nalozi": out_nal,
        "promjene": [{"t": _ms(p.vrijeme), "tekst": p.opis} for p in promjene],
        "zakljucan": zakljucan,
        "zakljucaoIme": (zak.ime if zak else None),
        "zakljucanoTs": (_ms(st.zakljucano) if zakljucan else None),
        "autoSlanje": _auto_slanje_stanje(db),
    }


# --- GET /plan/moje (radnik vidi SAMO svoje operacije) ---------------------
@router.get("/moje")
def moje(korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    """Operacije dodijeljene PRIJAVLJENOM radniku — njegova radiona."""
    nalozi = db.query(Nalog).filter(Nalog.status.in_(_AKTIVNI)).all()
    out = []
    for n in nalozi:
        if _gb(n) in _SKRIVENI_GB:
            continue
        voz = n.vozilo
        vn = " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x)
        for op in n.operacije:
            for z in op.zadaci:
                if not any(r.id == korisnik.id for r in z.radnici):
                    continue
                out.append({
                    "id": z.id, "nalogId": n.id, "gb": _gb(n),
                    "vozilo": vn or (n.naslov or ""),
                    "reg": (voz.registracija if voz else "") or "",
                    "naziv": z.opis, "kat": op.kategorija,
                    "status": _plan_status(z),
                    "akumSek": int(z.utroseno_sek or 0),
                    "startTs": _ms(z.zapoceto),
                    "hitno": bool(n.plan_hitno),
                })
    return {"ops": out, "ime": korisnik.ime}


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
    _provjeri_otkljucan(db)
    for i, nid in enumerate(p.redoslijed):
        n = db.get(Nalog, nid)
        if n:
            n.plan_rang = i
    db.commit()
    return {"ok": True}


@router.get("/zastoji")
def zastoji(dana: int = 14, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Nalozi 'u radu' bez aktivnosti dulje od `dana` dana — za čišćenje podataka.

    SAMO vlasnik. READ-ONLY: ništa se NE zatvara; vraća prijedlog
    (zatvoriti / u_radu / nejasno) uz obrazloženje, da voditelj odluči.
    'Zadnja aktivnost' = najnoviji od: start/kraj/pauza zadataka, azuriranje naloga.
    """
    sada = datetime.now(timezone.utc)
    prag = sada - timedelta(days=max(0, dana))
    out = []
    for n in db.query(Nalog).filter(Nalog.status == StatusNaloga.u_radu).all():
        if _gb(n) in _SKRIVENI_GB:
            continue
        zadaci = [z for op in n.operacije for z in op.zadaci]
        # 'Zadnja aktivnost' = stvarni rad (start/kraj/pauza zadataka) + datum kreiranja.
        # NE koristimo n.azuriran — sinkronizacije ga bumpaju pa bi sakrile zastoje.
        vremena = [n.kreiran]
        for z in zadaci:
            vremena += [z.zavrseno, z.zapoceto, z.prekid_vrijeme]
        vremena = [_aware(t) for t in vremena if t]
        zadnja = max(vremena) if vremena else _aware(n.kreiran)
        if zadnja > prag:
            continue  # bilo aktivnosti unutar praga — ne stoji
        dana_od = int((sada - zadnja).total_seconds() // 86400)
        ukupno = len(zadaci)
        gotovih = sum(1 for z in zadaci if z.gotovo)
        tece = any(z.zapoceto for z in zadaci)
        if ukupno and gotovih == ukupno:
            prijedlog, razlog = "zatvoriti", "svi zadaci gotovi, a nalog je još 'u radu'"
        elif tece:
            prijedlog, razlog = "u_radu", "mjerač trenutno radi"
        elif gotovih > 0:
            prijedlog, razlog = "nejasno", f"{gotovih}/{ukupno} zadataka gotovo, bez aktivnosti {dana_od} d"
        else:
            prijedlog, razlog = "nejasno", f"ništa započeto, bez aktivnosti {dana_od} d"
        out.append({
            "nalog_id": n.id, "broj": n.broj, "gb": _gb(n),
            "vozilo": ((f"{n.vozilo.marka or ''} {n.vozilo.model or ''}".strip() or None) if n.vozilo else None),
            "zadnja_aktivnost": zadnja.date().isoformat(),
            "dana": dana_od, "zadaci": f"{gotovih}/{ukupno}",
            "prijedlog": prijedlog, "razlog": razlog,
        })
    out.sort(key=lambda r: r["dana"], reverse=True)
    return {"prag_dana": dana, "broj": len(out), "nalozi": out}


class DodajIn(BaseModel):
    gb: str


@router.post("/dodaj")
def dodaj_u_plan(p: DodajIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Dodaj kamion (po garažnom broju) na VRH plana (prvo mjesto) — da novi odmah
    bude na vrhu bez skrolanja. Vraća na koju je poziciju došao (0)."""
    _provjeri_otkljucan(db)
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
    # Novi na VRH plana (prvo mjesto) — ostale u planu pomakni za 1 niže.
    for n in db.query(Nalog).filter(
        Nalog.status.in_(_AKTIVNI), Nalog.plan_rang.isnot(None), Nalog.id != nalog.id
    ).all():
        n.plan_rang = (n.plan_rang or 0) + 1
    nalog.plan_rang = 0
    db.commit()
    return {"ok": True, "gb": _gb(nalog), "rang": nalog.plan_rang}


@router.post("/ocisti")
def ocisti_plan(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Obriši ručni redoslijed (plan_rang) sa svih naloga — kreni novi plan."""
    _provjeri_otkljucan(db)
    for n in db.query(Nalog).filter(Nalog.plan_rang.isnot(None)).all():
        n.plan_rang = None
    db.commit()
    return {"ok": True}


@router.post("/nalog/{nid}/izbaci")
def izbaci_iz_plana(nid: int, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Izbaci jedan nalog iz plana (makni mu plan_rang i oznaku hitno). Nalog i
    njegovi zadaci OSTAJU — samo više nije u planu za danas."""
    _provjeri_otkljucan(db)
    n = db.get(Nalog, nid)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    n.plan_rang = None
    n.plan_hitno = False
    db.commit()
    return {"ok": True, "gb": _gb(n)}


@router.patch("/nalog/{nid}/hitno")
def hitno(nid: int, p: HitnoIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    _provjeri_otkljucan(db)
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


class ZakljucajIn(BaseModel):
    zakljucan: bool


@router.post("/zakljucaj")
def zakljucaj(p: ZakljucajIn, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Zaključaj/otključaj plan za danas. Dok je zaključan, backend odbija
    promjene sastava/redoslijeda; dnevni rad (dodjela/slanje/štoperica) teče."""
    st = _plan_stanje(db)
    st.zakljucan = bool(p.zakljucan)
    if st.zakljucan:
        st.datum = _hr_now().date()
        st.zakljucao_id = korisnik.id
        st.zakljucano = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "zakljucan": st.zakljucan}


@router.post("/zadatak/{zid}/dodijeli")
def dodijeli(zid: int, p: DodijeliIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    z = _zad(db, zid)
    _set_radnici(db, z, p.radnici_ids or [])
    z.ceka_potvrdu = False
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/posalji")
def posalji(zid: int, request: Request, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
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
    obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{z.opis} · GB {_gb(n)}", "/moja-radiona")
    # Dispečer: pošalji login-less poveznicu mehaničaru na WhatsApp (GATED — ništa se
    # ne šalje dok se izričito ne upali i samo odobrenim brojevima). Ne ruši dodjelu.
    from .dispecer import posalji_poveznicu
    wa = posalji_poveznicu(db, m, _gb(n), z.opis or "", str(request.base_url))
    db.commit()
    return {"ok": True, "wa": wa}


@router.post("/nalog/{nalog_id}/isplaniraj")
def isplaniraj(nalog_id: int, request: Request,
               korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """„Nalog isplaniran" — jedan gumb umjesto slanja po operaciji.
    Za svakog mehaničara dodijeljenog na ovom nalogu pošalje JEDNU poveznicu
    (njegov trenutni, prvi zadatak u redu), a ostale zadatke ostavi u redu
    čekanja. Napredovanje kroz red ide preko mehaničareve stranice (Gotovo /
    Nemam dijelova) — ista login-less poveznica se sama pomakne na sljedeći."""
    n = db.get(Nalog, nalog_id)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    from .dispecer import _red, posalji_poveznicu
    # Mehaničari dodijeljeni na nezavršenim operacijama ovog naloga (bez onih koji čekaju dijelove).
    mehanicari: dict[int, Korisnik] = {}
    for op in n.operacije:
        for z in op.zadaci:
            if z.gotovo or z.razlog_prekida == "dijelovi":
                continue
            for r in z.radnici:
                mehanicari.setdefault(r.id, r)
    poslano = 0
    preskoceno_rade = 0
    vec_poslano = 0
    for m in mehanicari.values():
        red = _red(db, m)
        if not red:
            continue
        z = red[0][2]                 # trenutni (prvi) zadatak u redu
        if z.zapoceto:                # već radi — ne diraj; red mu ide sam preko stranice
            preskoceno_rade += 1
            continue
        if z.ceka_potvrdu:            # već mu je poslano → ne dupliciraj poruku
            vec_poslano += 1
            continue
        z.ceka_potvrdu = True         # prvi ide na potvrdu/slanje, ostali ostaju u redu
        z.razlog_prekida = None
        z.prekid_vrijeme = None
        nt = z.operacija.nalog
        obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{z.opis} · GB {_gb(nt)}", "/moja-radiona")
        wa = posalji_poveznicu(db, m, _gb(nt), z.opis or "", str(request.base_url))
        if wa.get("poslano"):
            poslano += 1
    db.commit()
    return {"ok": True, "mehanicara": len(mehanicari), "poslano": poslano,
            "vec_rade": preskoceno_rade, "vec_poslano": vec_poslano}


def posalji_sve_plan(db: Session, base_url: str) -> dict:
    """Jezgra 'Pošalji sve naloge': svakom DODIJELJENOM i PRISUTNOM mehaničaru pošalji
    poveznicu na njegov prvi zadatak u redu. Preskače: odsutne (godišnji/bolovanje),
    one koji već rade (mjerač teče) i one kojima je već poslano (ceka_potvrdu). Koristi
    je i ručni gumb i jutarnje auto-slanje (zato prima base_url umjesto Requesta)."""
    from .dispecer import _red, posalji_poveznicu
    nalozi = (db.query(Nalog)
              .filter(Nalog.status.in_(_AKTIVNI), Nalog.plan_rang.isnot(None)).all())
    mehanicari: dict[int, Korisnik] = {}
    for n in nalozi:
        if _gb(n) in _SKRIVENI_GB:
            continue
        for op in n.operacije:
            for z in op.zadaci:
                if z.gotovo or z.razlog_prekida == "dijelovi":
                    continue
                for r in z.radnici:
                    mehanicari.setdefault(r.id, r)
    poslano = 0
    preskoceno_rade = 0
    vec_poslano = 0
    odsutni = 0
    for m in mehanicari.values():
        if _je_odsutan(m):
            odsutni += 1
            continue
        red = _red(db, m)
        if not red:
            continue
        z = red[0][2]
        if z.zapoceto:
            preskoceno_rade += 1
            continue
        if z.ceka_potvrdu:            # već mu je poslano (pojedinačno ili ranijim klikom) → ne dupliciraj
            vec_poslano += 1
            continue
        z.ceka_potvrdu = True
        z.razlog_prekida = None
        z.prekid_vrijeme = None
        nt = z.operacija.nalog
        obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{z.opis} · GB {_gb(nt)}", "/moja-radiona")
        wa = posalji_poveznicu(db, m, _gb(nt), z.opis or "", base_url)
        if wa.get("poslano"):
            poslano += 1
    db.commit()
    return {"ok": True, "mehanicara": len(mehanicari), "poslano": poslano,
            "vec_rade": preskoceno_rade, "vec_poslano": vec_poslano, "odsutni": odsutni}


@router.post("/isplaniraj-sve")
def isplaniraj_sve(request: Request, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Pošalji SVE naloge iz plana odjednom — jedan gumb umjesto po nalogu."""
    return posalji_sve_plan(db, str(request.base_url))


class AutoSlanjeIn(BaseModel):
    ukljuceno: bool
    ura: str | None = None   # "HH:MM" (HR lokalno); prazno = 06:45


@router.post("/auto-slanje")
def auto_slanje(p: AutoSlanjeIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Zakaži (ili otkaži) jutarnje auto-slanje plana. Jednokratno: okine se jednom na
    sljedeći termin pa se sam ugasi. Vrijeme je HR lokalno; ako je danas već prošlo → sutra."""
    from .. import norme
    if not p.ukljuceno:
        norme.set_postavka(db, KLJUC_AUTO_HHMM, None)
        norme.set_postavka(db, KLJUC_AUTO_DATUM, None)
        db.commit()
        return {"ok": True, "ukljuceno": False}
    dijelovi = (p.ura or "06:45").strip().split(":")
    try:
        hh, mm = int(dijelovi[0]), int(dijelovi[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Neispravno vrijeme (HH:MM)")
    hhmm = f"{hh:02d}:{mm:02d}"
    now = _hr_now()
    datum = now.date() if (now.hour, now.minute) < (hh, mm) else now.date() + timedelta(days=1)
    norme.set_postavka(db, KLJUC_AUTO_HHMM, hhmm)
    norme.set_postavka(db, KLJUC_AUTO_DATUM, datum.isoformat())
    db.commit()
    return {"ok": True, "ukljuceno": True, "ura": hhmm, "datum": datum.isoformat()}


class OcistiVrijemeIn(BaseModel):
    zadaci: list[int]


@router.post("/ocisti-vrijeme")
def ocisti_vrijeme(p: OcistiVrijemeIn, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Vlasnik: poništi izmjereno vrijeme na navedenim zadacima (čišćenje testnih
    tragova). Nulira utroseno_sek, makne per-radnik vremena (ZadatakRadnikVrijeme),
    vrati zadatak u 'nije započeto / nije gotovo' i uskladi servisnu povijest.
    Ne dira dodijeljene radnike ni druge zadatke."""
    from ..models import ZadatakRadnikVrijeme
    from .nalozi import _sync_povijest
    nalozi_ids: set[int] = set()
    ocisceno: list[int] = []
    for zid in (p.zadaci or []):
        z = db.get(Zadatak, zid)
        if not z:
            continue
        z.utroseno_sek = 0
        z.gotovo = False
        z.zavrseno = None
        z.zapoceto = None
        z.prekid_vrijeme = None
        z.ceka_potvrdu = False
        db.query(ZadatakRadnikVrijeme).filter(
            ZadatakRadnikVrijeme.zadatak_id == zid
        ).delete(synchronize_session=False)
        nalozi_ids.add(z.operacija.nalog_id)
        ocisceno.append(zid)
    db.flush()
    for nid in nalozi_ids:
        n = db.get(Nalog, nid)
        if n:
            _sync_povijest(db, n)
    db.commit()
    return {"ok": True, "ocisceno": ocisceno}


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
    _pokreni_mjerac(db, z, odjavi_druge=False)   # zadrži ostale zadatke u redu čekanja
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, korisnik)  # nalog → u_radu + sync povijesti
    if m:
        from .dispecer import provjeri_zalihu
        provjeri_zalihu(db, m)   # krenuo iz pripreme → javi poslovođi ako je zaliha niska
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
    db.flush()
    # Uskladi status naloga i servisnu povijest (gotov zadatak → odmah u povijest_rada,
    # da AI Poslovođa računa iz svježih podataka). Isti put kao regularni task-endpointi.
    _auto_status_naloga(db, z.operacija.nalog, korisnik)
    db.commit()
    return {"ok": True}
