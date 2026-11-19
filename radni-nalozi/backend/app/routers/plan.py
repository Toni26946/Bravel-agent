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
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import flota
from ..auth import ima_plan_pristup, trenutni_korisnik, zahtijevaj_plan_pristup
from ..database import get_db
from ..models import (
    Dodjela, KlikPoslano, KlikRucno, Korisnik, Nalog, Operacija, PlanDogadaj, PlanStanje, PovijestStatusa,
    Prioritet, RegistarVozila, StatusNaloga, Uloga, Zadatak, ZadatakRadnikVrijeme,
)
from ..push import obavijesti_korisnika
from .nalozi import (
    _aware, _pokreni_mjerac, _zaustavi_mjerac, _SERVISERI, _UREDNICI, _auto_status_naloga,
    _sljedeci_broj, _sync_povijest, je_serviser, nalog_eager, servis_odradjen,
)

# Tko se smije dodijeliti na operaciju: mehaničari (rade rukama) + voditelji/poslovođe
# (npr. kamion ide u VANJSKI servis → voditelj „vodi" nalog). Voditelji ne primaju
# WhatsApp poveznicu, ne idu u klik-bonus i ne broje se kao mehaničari u planu.
_DODJELJIVI = tuple(set(_SERVISERI) | set(_UREDNICI))

router = APIRouter(prefix="/plan", tags=["plan"])
_samo_vlasnik = zahtijevaj_plan_pristup()   # vlasnik ILI tko ima modul '/plan'

_AKTIVNI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)
PROZOR_MIN = 5
KRAJ_H, KRAJ_M = 14, 45
MAX_HITNO = 3
# Interni/pomoćni nalozi koji se NE prikazuju u planu (npr. "RADIONA").
_SKRIVENI_GB = set()   # interni/skriveni GB-ovi (prazno = ništa skriveno; GB 400 otkriven)
# (Ranije MAX_PLAN = 50 — ograničenje broja vozila u planu maknuto na zahtjev.)
# Pregledar (radnik koji radi preglede/registracije) se nudi kao ⭐ prijedlog na ove kategorije.
_PREGLED_KAT = {"PERIODIČKI PREGLED", "BAŽDARENJE TAHOGRAFA", "PP APARATI", "REGISTRACIJA"}
_PREGLEDAR_KIME = "karthik.raju"


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
    if z.razlog_prekida == "nedostupan":
        return "nedostupan"            # vozilo nije dostupno (mehaničar označio) — ostaje u planu
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
# Ponavljajuće jutarnje slanje: svaki radni dan (pon–sub) u zadani sat, samostalno.
KLJUC_AUTO_PON_ON = "plan_auto_pon_on"        # "1" = uključeno
KLJUC_AUTO_PON_HHMM = "plan_auto_pon_hhmm"    # "HH:MM"
KLJUC_AUTO_PON_ZADNJE = "plan_auto_pon_zadnje"  # zadnji datum kad je poslano (anti-duplikat)


def _auto_slanje_stanje(db: Session) -> dict:
    from .. import norme
    hhmm = norme.get_postavka(db, KLJUC_AUTO_HHMM)
    datum = norme.get_postavka(db, KLJUC_AUTO_DATUM)
    return {
        "ukljuceno": bool(hhmm and datum), "ura": hhmm or "06:45", "datum": datum,
        "ponavlja": {
            "ukljuceno": norme.get_postavka(db, KLJUC_AUTO_PON_ON) == "1",
            "ura": norme.get_postavka(db, KLJUC_AUTO_PON_HHMM) or "07:00",
        },
    }


def _gb(n: Nalog) -> str:
    return (n.vozilo.gb if n and n.vozilo else "") or ""


def _set_radnici(db: Session, z: Zadatak, ids: list[int]) -> None:
    """Postavi radnike na zadatak BEZ pokretanja mjerača i bez odjave s drugih
    (planiranje unaprijed). Mjerač kreće tek na mehaničarevu potvrdu."""
    valjani: list[Korisnik] = []
    for rid in dict.fromkeys(ids):
        r = db.get(Korisnik, rid)
        if not r or not (r.uloga in _DODJELJIVI or je_serviser(r)):
            raise HTTPException(status_code=400, detail=f"Korisnik {rid} se ne može dodijeliti")
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
    agg = _iskustvo_po_kategoriji(db, aktivni_ids)
    return {nk: max(d, key=d.get) for nk, d in agg.items() if d}


def _iskustvo_po_kategoriji(db: Session, aktivni_ids: list[int]) -> dict[str, dict[int, int]]:
    """Koliko je puta koji mehaničar ZAVRŠIO operaciju pojedine (normalizirane) vrste:
    {kategorija: {radnik_id: broj}} — za prijedlog i automatsko popunjavanje reda."""
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
    return agg


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
    from .dispecer import radi_na as _radi_na
    nalozi = db.query(Nalog).options(*nalog_eager()).filter(Nalog.status.in_(_AKTIVNI)).all()
    nalozi = [n for n in nalozi if _gb(n) not in _SKRIVENI_GB]   # bez internih (RADIONA)
    nalozi.sort(key=lambda n: (
        0 if n.plan_hitno else 1,
        n.plan_rang if n.plan_rang is not None else 10 ** 9,
        n.id,
    ))
    meh = (
        db.query(Korisnik)
        .filter(or_(Korisnik.uloga.in_(_SERVISERI), Korisnik.radi_na_nalozima.is_(True)),
                Korisnik.uloga != Uloga.skladistar,   # skladištar (Akshay) nije u Radnicima i ne dobiva zadatke (Toni 19.11.2026.)
                Korisnik.aktivan.is_(True),
                Korisnik.prijavljuje_se.is_(True))   # mehaničari + označeni „radi na nalozima"
        .order_by(Korisnik.ime).all()
    )
    # Pregledar (Karthik) — vidljiv u Radnici/dropdownu da mu se vide dodijeljeni pregledi.
    # Dispatch (Pošalji sve / isplaniraj) ga svejedno preskače (prijavljuje_se=False).
    pregledar = db.query(Korisnik).filter(Korisnik.korisnicko_ime == _PREGLEDAR_KIME).first()
    if pregledar and pregledar not in meh:
        meh.append(pregledar)
    preporuke = _preporuke_po_kategoriji(db, [m.id for m in meh])
    zad_ids = [z.id for n in nalozi for op in n.operacije for z in op.zadaci]
    radili = _radio_po_zadatku(db, zad_ids)   # tko je nakupio vrijeme na zadatku
    # Naziv/registracija vozila: PRIMARNO iz matičnog popisa (RegistarVozila — ono što se
    # uređuje na stranici „Vozila"), fallback na Vozilo (marka/model). GB se podudara
    # izravno; probamo i bez vodećih nula (kao drugdje u kodu).
    _gbs = {_gb(n) for n in nalozi if _gb(n)}
    _gbs |= {g.lstrip("0") or g for g in list(_gbs)}
    reg_map = {}
    if _gbs:
        for rv in db.query(RegistarVozila).filter(RegistarVozila.gb.in_(_gbs)).all():
            reg_map[rv.gb] = rv
            reg_map.setdefault(rv.gb.lstrip("0") or rv.gb, rv)
    out_nal = []
    for i, n in enumerate(nalozi):
        ops = []
        for op in n.operacije:
            for z in op.zadaci:
                m = _mehanicar(z)
                vrem = {v.radnik_id: v for v in z.vremena}   # vrijeme po radniku
                prep_id = preporuke.get(_norm_kat(op.kategorija))
                prep_ime = None
                if prep_id is None and pregledar and op.kategorija in _PREGLED_KAT:
                    prep_id, prep_ime = pregledar.id, pregledar.ime   # prijedlog pregledara
                ops.append({
                    "id": z.id, "naziv": z.opis, "kat": op.kategorija,
                    "mehId": m.id if m else None,
                    "mehovi": [{"id": r.id, "ime": r.ime} for r in z.radnici],
                    "mehIds": [r.id for r in z.radnici],
                    # Vrijeme po svakom mehaničaru (akumulirano + startTs ako trenutno radi).
                    "mehVremena": [{
                        "id": r.id, "ime": r.ime,
                        "akumSek": int((vrem[r.id].utroseno_sek if r.id in vrem else 0) or 0),
                        "startTs": _ms(vrem[r.id].zapoceto) if (r.id in vrem and vrem[r.id].zapoceto) else None,
                    } for r in z.radnici],
                    "preporukaId": prep_id,
                    "preporukaIme": prep_ime,
                    "radioIme": (radili.get(z.id) or (None, None))[0],
                    "radioId": (radili.get(z.id) or (None, None))[1],
                    "status": _plan_status(z),
                    "red": z.red_ruc,                 # ručni ključ reda (strelica/povlačenje), None = po prioritetu
                    "radiIds": [r.id for r in z.radnici if _radi_na(z, r.id)],   # kome mjerač teče (isto kao dispečer)
                    "akumSek": int(z.utroseno_sek or 0),
                    "startTs": _ms(z.zapoceto),
                })
        voz = n.vozilo
        gb = _gb(n)
        rv = reg_map.get(gb) or reg_map.get(gb.lstrip("0") or gb)
        ime_rv = (rv.vozilo.strip() if (rv and rv.vozilo) else "")
        reg_rv = (rv.registracija.strip() if (rv and rv.registracija) else "")
        naziv = " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x)
        out_nal.append({
            "id": n.id, "gb": gb,
            "vozilo": ime_rv or naziv or (n.naslov or ""),
            "reg": reg_rv or (voz.registracija if voz else "") or "",
            "rang": n.plan_rang,
            "hitno": bool(n.plan_hitno),
            "prioritet": n.prioritet_rang,   # pozicija na listi prioriteta (0 = najhitniji); None = nije na listi
            "cekaDijelove": n.status == StatusNaloga.ceka_dijelove,
            "usaoTs": _ms(n.kreiran),
            "udaljenostM": flota.udaljenost_od_radione(_gb(n)),   # metri od radione (None ako nema GPS-a)
            "mjesto": flota.mjesto_vozila(_gb(n)),                 # naziv mjesta iz GPS-a (None ako nema)
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

    # Voditelji/poslovođe — za padajući izbornik dodjele (kad kamion ide u vanjski
    # servis, nalog „vodi" voditelj). NE ulaze u popis mehaničara ni u dispatch.
    voditelji = (
        db.query(Korisnik)
        .filter(Korisnik.uloga.in_(_UREDNICI), Korisnik.aktivan.is_(True))
        .order_by(Korisnik.ime).all()
    )
    return {
        "mehanicari": [{"id": m.id, "ime": m.ime, "odsutan": _odsutan(m),
                        "odsutnost": (m.odsutnost_vrsta if _odsutan(m) else None)} for m in meh],
        "voditelji": [{"id": v.id, "ime": v.ime} for v in voditelji],
        "nalozi": out_nal,
        "promjene": [{"t": _ms(p.vrijeme), "tekst": p.opis} for p in promjene],
        "zakljucan": zakljucan,
        "zakljucaoIme": (zak.ime if zak else None),
        "zakljucanoTs": (_ms(st.zakljucano) if zakljucan else None),
        "autoSlanje": _auto_slanje_stanje(db),
        "autoPopuni": _auto_popuni_ukljuceno(db),
    }


def _auto_popuni_ukljuceno(db: Session) -> bool:
    from ..auto_popuni import ukljuceno
    return ukljuceno(db)


class AutoPopuniIn(BaseModel):
    ukljuceno: bool


@router.post("/auto-popuni")
def auto_popuni_prekidac(p: AutoPopuniIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Upali/ugasi automatsko popunjavanje reda mehaničara (Radnici). Upaljeno → odmah popuni."""
    from .. import norme
    from ..auto_popuni import KLJUC, popuni
    norme.set_postavka(db, KLJUC, "1" if p.ukljuceno else "0")
    db.commit()
    dodano = popuni(db) if p.ukljuceno else []
    return {"ok": True, "ukljuceno": p.ukljuceno, "dodijeljeno": len(dodano)}


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


class PrioritetiIn(BaseModel):
    redoslijed: list[int]   # id-evi naloga po prioritetu; prvi = najhitniji (prioritet 1)


@router.put("/prioriteti")
def prioriteti(p: PrioritetiIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Popis prioriteta naloga — ZASEBNO od HITNO i od redoslijeda plana.
    `redoslijed` je lista nalog id-eva; prvi je najhitniji (prioritet 1). Nalozi koji
    nisu na listi gube prioritet_rang (više nisu označeni). Ne ovisi o zaključavanju plana."""
    nova = {nid: i for i, nid in enumerate(p.redoslijed)}
    # Makni s liste one koji su bili, a više nisu.
    for n in db.query(Nalog).filter(Nalog.prioritet_rang.isnot(None)).all():
        if n.id not in nova:
            n.prioritet_rang = None
    # Postavi/ažuriraj poziciju za one na listi.
    for nid, i in nova.items():
        n = db.get(Nalog, nid)
        if n:
            n.prioritet_rang = i
    db.commit()
    from ..auto_popuni import popuni_tiho
    popuni_tiho(db)   # novi prioriteti → odmah dopuni redove mehaničara
    return {"ok": True}


class MehRedoslijedIn(BaseModel):
    radnik_id: int
    zadaci: list[int] = []      # id-evi zadataka u novom redu tog mehaničara (kako je na ekranu)
    pomaknut: int | None = None  # koja je kartica pomaknuta (strelica / povlačenje)


@router.get("/napravljeno")
def napravljeno(od_ms: int = 0, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Tko je što napravio (gotovi zadaci) od `od_ms` (početak dana, lokalno vrijeme s klijenta).
    Vraća po mehaničaru listu GB-ova/operacija koje je danas završio."""
    od = (datetime.fromtimestamp(od_ms / 1000, tz=timezone.utc)
          if od_ms else datetime.now(timezone.utc) - timedelta(days=1))
    zadaci = (
        db.query(Zadatak)
        .options(
            joinedload(Zadatak.operacija).joinedload(Operacija.nalog).joinedload(Nalog.vozilo),
            selectinload(Zadatak.radnici),
        )
        .filter(Zadatak.zavrseno.isnot(None), Zadatak.zavrseno >= od)
        .all()
    )
    po: dict = {}
    for z in zadaci:
        op = z.operacija
        if op is None:
            continue
        gb = _gb(op.nalog) if op.nalog else "?"
        rad = list(z.radnici) or ([z.zaduzeni] if z.zaduzeni else [])
        for r in rad:
            d = po.setdefault(r.id, {"ime": r.ime, "zadaci": []})
            d["zadaci"].append({"zid": z.id, "gb": gb, "kat": op.kategorija, "opis": z.opis, "krajTs": _ms(z.zavrseno)})
    out = sorted(po.values(), key=lambda x: (-len(x["zadaci"]), x["ime"]))
    return {"mehanicari": out, "ukupno": sum(len(x["zadaci"]) for x in out)}


@router.post("/zadatak/{zid}/vrati")
def vrati_u_plan(zid: int, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """„Nije gotovo" iz pregleda Napravljeno: zadatak se ponovno otvara i vraća u plan
    ISTOM mehaničaru kao nedovršen (pauza, čuva dosadašnje vrijeme, mjerač NE kreće).
    Ako je nalog bio gotov/zatvoren, vraća se u rad da se opet vidi u planu."""
    z = _zad(db, zid)
    if not z.gotovo:
        raise HTTPException(status_code=400, detail="Zadatak nije označen gotovim")
    z.gotovo = False
    z.zavrseno = None
    z.zavrsio_id = None
    for zr in z.vremena:
        zr.gotovo = False
    z.ceka_potvrdu = False
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    n = z.operacija.nalog
    if n.status in (StatusNaloga.gotov, StatusNaloga.zatvoren):
        stari = n.status
        n.status = StatusNaloga.u_radu
        n.zatvoren = None
        db.add(PovijestStatusa(nalog_id=n.id, stari_status=stari.value, novi_status=n.status.value,
                               napomena="Zadatak vraćen u plan (nije gotovo)", promijenio_id=korisnik.id))
    db.flush()
    _auto_status_naloga(db, n, korisnik)
    m = _mehanicar(z)
    _log(db, korisnik, "vrati", f"GB {_gb(n)}: vraćeno u plan — nije gotovo ({z.opis or ''})"[:250],
         nalog_id=n.id, zadatak_id=z.id, radnik_id=(m.id if m else None))
    db.commit()
    return {"ok": True}


def _poslani_mu(db: Session, radnik: Korisnik) -> set[int]:
    """Zadaci ovog mehaničara koji su mu poslani i čekaju potvrdu (nezapočeti)."""
    from .dispecer import _red
    return {z.id for (_n, _op, z) in _red(db, radnik) if z.ceka_potvrdu and not z.zapoceto}


def _postavi_rucni_kljuc(db: Session, radnik: Korisnik, poredak: list[int], pomaknut: int) -> None:
    """Toni je pomaknuo JEDNU karticu (strelica / povlačenje): samo ona dobiva ručni
    ključ reda — između susjeda u novom poretku. Ostale kartice ostaju po prioritetu,
    pa jedan pomak ne „zaledi" cijeli redak (ni redak drugog mehaničara kod zajedničke
    operacije)."""
    from .dispecer import KORAK_REDA, _red, faza_zadatka, kljuc_reda
    red = _red(db, radnik)
    po_id = {z.id: (n, z) for (n, _op, z) in red}
    if pomaknut not in po_id:
        return
    n_x, z_x = po_id[pomaknut]
    f = faza_zadatka(n_x, z_x, radnik.id)
    if f not in (1, 2, 3):
        return   # u tijeku / odgođeni se ne slažu ručno
    # Zaključani (poslani, prvi) zadatak nije dio poretka po ključu — ne računa se.
    prvi = red[0][2]
    zakljucan = prvi.id if (prvi.ceka_potvrdu and not prvi.zapoceto
                            and faza_zadatka(red[0][0], prvi, radnik.id) == f) else None
    lista = [zid for zid in poredak if zid in po_id and zid != zakljucan
             and faza_zadatka(*po_id[zid], radnik.id) == f]
    if pomaknut not in lista:
        return
    # Prođi novi poredak: svaka kartica mora biti iza prethodne po (ključ, id). Pomaknuta
    # dobiva ključ između susjeda; ostale zadržavaju svoj ključ (prioritet) i dobivaju
    # ručni samo ako baš moraju (npr. više operacija istog naloga s istim ključem).
    zadnji = None   # (ključ, id) prethodne kartice
    for i, zid in enumerate(lista):
        n, z = po_id[zid]
        if zid == pomaknut:
            sljedeci = next((kljuc_reda(*po_id[y]) for y in lista[i + 1:]), None)
            if zadnji is None:
                k = (sljedeci - KORAK_REDA) if sljedeci is not None else 0
            elif sljedeci is not None and sljedeci - zadnji[0] >= 2:
                k = (zadnji[0] + sljedeci) // 2
            elif sljedeci is None:
                k = zadnji[0] + KORAK_REDA
            else:
                k = zadnji[0] + 1   # nema mjesta — sljedeće se pomaknu iza
            z.red_ruc = k
            zadnji = (k, z.id)
            continue
        cur = (kljuc_reda(n, z), z.id)
        if zadnji is None or cur > zadnji:
            zadnji = cur
        else:
            z.red_ruc = zadnji[0] + 1
            zadnji = (z.red_ruc, z.id)


def _novi_prvi_posalji(db: Session, radnik: Korisnik, prije: set[int], novi_prvi: int | None,
                       base_url: str, korisnik) -> bool:
    """Ako je na PRVO mjesto došao drugi zadatak, a mehaničar ne radi ništa i čeka
    potvrdu poslanog (Toni 19.11.2026.) → stari poslani se poništi, novi prvi ide na
    potvrdu i mehaničar dobiva NOVU poruku (push + WhatsApp)."""
    if not prije or not radnik or not radnik.prijavljuje_se or novi_prvi is None or novi_prvi in prije:
        return False
    from .dispecer import _red, opis_s_operacijom, posalji_poveznicu, radi_na
    red = _red(db, radnik)
    if any(radi_na(z, radnik.id) for (_n, _op, z) in red):
        return False   # radi nešto — novi prvi mu dolazi kad završi
    t = next(((n, op, z) for (n, op, z) in red if z.id == novi_prvi), None)
    if t is None:
        return False
    n, op, z = t
    for (_n, _op, x) in red:
        if x.id in prije and x.id != z.id and not x.zapoceto:
            x.ceka_potvrdu = False
    z.ceka_potvrdu = True
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    tekst = opis_s_operacijom(op.kategorija, z.opis)
    obavijesti_korisnika(db, radnik.id, "Potvrdi početak", f"{tekst} · GB {_gb(n)}", "/moja-radiona")
    try:
        posalji_poveznicu(db, radnik, _gb(n), tekst, base_url)
    except Exception:  # noqa: BLE001 — slanje ne smije srušiti presloživanje
        pass
    _log(db, korisnik, "novi-prvi", f"{radnik.ime}: novi prvi zadatak GB {_gb(n)} — poslana nova poruka"[:250],
         nalog_id=n.id, zadatak_id=z.id, radnik_id=radnik.id)
    return True


def _prvi_u_poretku(db: Session, radnik: Korisnik, poredak: list[int]) -> int | None:
    """Prvi zadatak u Tonijevom poretku koji mehaničar ne radi i nije odgođen."""
    from .dispecer import _red, faza_zadatka
    po_id = {z.id: (n, z) for (n, _op, z) in _red(db, radnik)}
    for zid in poredak:
        if zid in po_id and faza_zadatka(*po_id[zid], radnik.id) in (1, 2):
            return zid
    return None


def _pomaknut_iz_poretka(staro: list[int], novo: list[int]) -> int | None:
    """Koja je kartica pomaknuta (stari klijent bez polja `pomaknut`)."""
    for x in novo:
        if [y for y in staro if y != x] == [y for y in novo if y != x] and staro.index(x) != novo.index(x):
            return x
    return None


@router.post("/meh-redoslijed")
def meh_redoslijed(p: MehRedoslijedIn, request: Request, korisnik: Korisnik = Depends(_samo_vlasnik),
                   db: Session = Depends(get_db)):
    """Ručni pomak kartice u Radnicima (strelica / povlačenje). `zadaci` = novi poredak
    retka, `pomaknut` = koja je kartica pomaknuta. Samo ona dobiva ručno mjesto; ostale
    ostaju po prioritetu. Zadatak „u tijeku" ostaje prvi. Ako na prvo mjesto dođe drugi
    zadatak dok mehaničar čeka potvrdu → nova poruka."""
    _provjeri_otkljucan(db)
    radnik = db.get(Korisnik, p.radnik_id)
    if not radnik:
        raise HTTPException(status_code=404, detail="Mehaničar ne postoji")
    from .dispecer import _red
    prije = _poslani_mu(db, radnik)
    pomaknut = p.pomaknut
    if pomaknut is None:
        staro = [z.id for (_n, _op, z) in _red(db, radnik)]
        pomaknut = _pomaknut_iz_poretka([x for x in staro if x in p.zadaci],
                                        [x for x in p.zadaci if x in staro])
    if pomaknut is not None:
        _postavi_rucni_kljuc(db, radnik, p.zadaci, pomaknut)
    db.flush()
    poslano = _novi_prvi_posalji(db, radnik, prije, _prvi_u_poretku(db, radnik, p.zadaci),
                                 str(request.base_url), korisnik)
    db.commit()
    return {"ok": True, "poslano": poslano}


class PremjestiIn(BaseModel):
    zadatak_id: int
    s_radnika: int
    na_radnika: int
    redoslijed: list[int] = []   # novi red zadataka ciljnog mehaničara (dashboard drag)


@router.post("/premjesti")
def premjesti(p: PremjestiIn, request: Request, korisnik: Korisnik = Depends(_samo_vlasnik),
              db: Session = Depends(get_db)):
    """Dashboard drag između mehaničara: zadatak prelazi s jednog na drugog i dobiva
    mjesto u njegovom redu (samo ON dobiva ručno mjesto). Zadatak u tijeku se ne seli.
    Ako je bio poslan starom mehaničaru (čeka potvrdu), ta se oznaka skida; kome se
    zbog toga promijeni prvi zadatak dok čeka potvrdu, dobiva novu poruku."""
    _provjeri_otkljucan(db)
    stari = db.get(Korisnik, p.s_radnika)
    novi = db.get(Korisnik, p.na_radnika)
    prije_stari = _poslani_mu(db, stari) if stari else set()
    prije_novi = _poslani_mu(db, novi) if novi else set()
    z = _zad(db, p.zadatak_id)
    if z.gotovo:
        raise HTTPException(status_code=400, detail="Zadatak je već gotov")
    if z.zapoceto:
        raise HTTPException(status_code=400, detail="Zadatak je u tijeku — prvo ga zaustavi")
    if p.s_radnika != p.na_radnika:
        # novi mehaničar preuzima mjesto starog (ostali suradnici na zadatku ostaju)
        ids = [p.na_radnika if r.id == p.s_radnika else r.id for r in z.radnici]
        if p.na_radnika not in ids:
            ids.append(p.na_radnika)
        _set_radnici(db, z, ids)
        z.ceka_potvrdu = False
        _log(db, korisnik, "premjesti",
             f"GB {_gb(z.operacija.nalog)}: {stari.ime if stari else '?'} → {novi.ime if novi else '?'}",
             nalog_id=z.operacija.nalog_id, zadatak_id=z.id, radnik_id=p.na_radnika)
    db.flush()
    if novi:
        _postavi_rucni_kljuc(db, novi, p.redoslijed, z.id)
    db.flush()
    base = str(request.base_url)
    if novi:
        _novi_prvi_posalji(db, novi, prije_novi, _prvi_u_poretku(db, novi, p.redoslijed), base, korisnik)
    if stari and stari is not novi:
        from .dispecer import _red
        red_s = _red(db, stari)
        _novi_prvi_posalji(db, stari, prije_stari, red_s[0][2].id if red_s else None, base, korisnik)
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
    if _gb(nalog) in _SKRIVENI_GB:
        raise HTTPException(status_code=409, detail=f"GB {gb} je interni — ne prikazuje se u planu.")
    # Bez ograničenja na broj vozila u planu (ranije MAX_PLAN) — koliko god treba.
    # Novi na VRH plana (prvo mjesto) — ostale u planu pomakni za 1 niže.
    for n in db.query(Nalog).filter(
        Nalog.status.in_(_AKTIVNI), Nalog.plan_rang.isnot(None), Nalog.id != nalog.id
    ).all():
        n.plan_rang = (n.plan_rang or 0) + 1
    nalog.plan_rang = 0
    db.commit()
    from ..auto_popuni import popuni_tiho
    popuni_tiho(db)   # novi kamion u planu → odmah dopuni redove mehaničara
    return {"ok": True, "gb": _gb(nalog), "rang": 0}


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


@router.post("/nalog/{nid}/obnovi")
def obnovi_nalog(nid: int, korisnik: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Zatvori nalog i otvori NOVI pod istim GB, prenoseći samo NEDOVRŠENE operacije.

    Namijenjeno radioni (npr. GB 400) gdje se gomilaju operacije: jednim klikom
    „okreneš list" — gotove operacije ostaju na ZATVORENOM nalogu i odlaze u
    servisnu povijest vozila, a sve nedovršeno (zadatak nije gotov, uključujući
    ono što je trenutno u tijeku) seli se u svježi nalog SA SVIME: dodijeljeni
    radnici, pokrenuti mjerači, utrošeno vrijeme i ručni red ostaju netaknuti.
    Novi nalog preuzima mjesto starog u planu (rang + hitno)."""
    n = db.get(Nalog, nid)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    # Radimo po ZADATKU (ne cijeloj operaciji): jedna operacija radione zna sadržavati
    # i gotov i nedovršen zadatak — gotove treba arhivirati, nedovršene prenijeti.
    svi = [z for op in n.operacije for z in op.zadaci]
    gotovi = [z for z in svi if z.gotovo]
    nedovrseni = [z for z in svi if not z.gotovo]
    if not nedovrseni:
        raise HTTPException(status_code=409,
                            detail="Nema nedovršenih operacija — nema što prenijeti u novi nalog.")
    if not gotovi:
        raise HTTPException(status_code=409,
                            detail="Sve operacije su još u radu — nema gotovih za zatvoriti.")

    novi = Nalog(
        broj=_sljedeci_broj(db), vozilo_id=n.vozilo_id, naslov=n.naslov, opis=n.opis,
        prioritet=n.prioritet, kreirao_id=korisnik.id, voditelj_id=n.voditelj_id,
        vozac_id=n.vozac_id, status=StatusNaloga.u_radu,
        plan_rang=n.plan_rang, plan_hitno=bool(n.plan_hitno),
    )
    db.add(novi)
    db.flush()
    # Preseli NEDOVRŠENE zadatke u novi nalog, grupirane u operaciju iste kategorije
    # (radnici, mjerači, utrošeno vrijeme i red ostaju jer selimo isti objekt zadatka).
    nove_op: dict[str, Operacija] = {}
    for op in n.operacije:
        za_seliti = [z for z in op.zadaci if not z.gotovo]
        for z in za_seliti:
            cilj = nove_op.get(op.kategorija)
            if cilj is None:
                cilj = Operacija(kategorija=op.kategorija, redoslijed=len(nove_op))
                novi.operacije.append(cilj)
                nove_op[op.kategorija] = cilj
            op.zadaci.remove(z)
            cilj.zadaci.append(z)
    # Operacije kojima su svi zadaci preseljeni (ostale prazne) makni sa zatvorenog naloga.
    for op in list(n.operacije):
        if not op.zadaci:
            n.operacije.remove(op)
    # Prenesi dodjele (nalog↔radnik) za radnike koji su na prenesenim zadacima.
    preneseni_rad = {r.id for z in nedovrseni for r in z.radnici}
    for rid in preneseni_rad:
        db.add(Dodjela(nalog_id=novi.id, radnik_id=rid))

    # Stari nalog: izlazi iz plana i zatvara se; gotovi zadaci → servisna povijest.
    n.plan_rang = None
    n.plan_hitno = False
    stari_status = n.status
    n.status = StatusNaloga.zatvoren
    n.zatvoren = datetime.now(timezone.utc)
    db.flush()
    _sync_povijest(db, n)   # upiše gotove zadatke u povijest_rada vozila
    db.add(PovijestStatusa(
        nalog_id=n.id, stari_status=stari_status.value, novi_status=n.status.value,
        napomena=f"Zatvoren — {len(gotovi)} gotovih arhivirano, {len(nedovrseni)} nedovršenih preneseno u {novi.broj}",
        promijenio_id=korisnik.id,
    ))
    db.add(PovijestStatusa(
        nalog_id=novi.id, stari_status=None, novi_status=novi.status.value,
        napomena=f"Otvoren prijenosom nedovršenog iz {n.broj}", promijenio_id=korisnik.id,
    ))
    _log(db, korisnik, "obnovi",
         f"GB {_gb(n)}: zatvoren {n.broj}, nedovršeno ({len(nedovrseni)}) → {novi.broj}",
         nalog_id=novi.id)
    db.commit()
    return {"ok": True, "novi_id": novi.id, "novi_broj": novi.broj,
            "preneseno": len(nedovrseni), "arhivirano": len(gotovi), "gb": _gb(novi)}


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
    from .dispecer import opis_s_operacijom
    tekst = opis_s_operacijom(z.operacija.kategorija, z.opis)   # s nazivom operacije (#298)
    obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{tekst} · GB {_gb(n)}", "/moja-radiona")
    # Dispečer: pošalji login-less poveznicu mehaničaru na WhatsApp (GATED — ništa se
    # ne šalje dok se izričito ne upali i samo odobrenim brojevima). Ne ruši dodjelu.
    from .dispecer import posalji_poveznicu
    wa = posalji_poveznicu(db, m, _gb(n), tekst, str(request.base_url))
    db.commit()
    return {"ok": True, "wa": wa}


class PrijaviRucnoIn(BaseModel):
    radnik_id: int


@router.post("/zadatak/{zid}/prijavi-rucno")
def prijavi_rucno(zid: int, p: PrijaviRucnoIn, korisnik: Korisnik = Depends(_samo_vlasnik),
                  db: Session = Depends(get_db)):
    """Dispečer RUČNO prijavi mehaničara na zadatak (pokrene mu mjerač umjesto njega).
    Bilježi se kao ručna prijava → u klik-bonusu se taj dan broji kao prekršaj (nije sam
    kliknuo). Pokreće mjerač SAMO tom mehaničaru (ostali na operaciji i dalje čekaju svoj)."""
    z = _zad(db, zid)
    m = next((r for r in z.radnici if r.id == p.radnik_id), None)
    if m is None:
        raise HTTPException(status_code=404, detail="Mehaničar nije dodijeljen na ovom zadatku")
    n = z.operacija.nalog
    z.ceka_potvrdu = False
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    _pokreni_mjerac(db, z, odjavi_druge=False, radnik_id=m.id)
    db.add(KlikRucno(radnik_id=m.id, voditelj_id=korisnik.id))   # ručna prijava (tko ju je napravio) → prekršaj u klik-bonusu
    db.flush()
    _auto_status_naloga(db, n, korisnik)
    _log(db, korisnik, "rucna-prijava",
         f"{m.ime} ručno prijavljen na zadatak (GB {_gb(n)})",
         nalog_id=n.id, zadatak_id=z.id, radnik_id=m.id)
    db.commit()
    return {"ok": True}


@router.post("/zadatak/{zid}/ponisti-rucnu")
def ponisti_rucnu(zid: int, p: PrijaviRucnoIn, korisnik: Korisnik = Depends(_samo_vlasnik),
                  db: Session = Depends(get_db)):
    """Poništi ručnu prijavu (greška/demo): zaustavi mjerač tom radniku BEZ pribrajanja,
    vrati zadatak u 'čeka potvrdu' (ako nitko drugi ne radi) i obriši zadnji KlikRucno
    (da se ne broji kao prekršaj). Vraća stanje kakvo je bilo prije ručne prijave."""
    z = _zad(db, zid)
    m = next((r for r in z.radnici if r.id == p.radnik_id), None)
    if m is None:
        raise HTTPException(status_code=404, detail="Mehaničar nije dodijeljen na ovom zadatku")
    for zr in z.vremena:
        if zr.radnik_id == m.id:
            zr.zapoceto = None
            zr.utroseno_sek = 0
    drugi_radi = any(zr.zapoceto for zr in z.vremena if zr.radnik_id != m.id)
    if not drugi_radi:
        z.zapoceto = None            # izravno (bez pribrajanja u z.utroseno_sek)
        z.ceka_potvrdu = True
    zadnji = (db.query(KlikRucno)
              .filter(KlikRucno.radnik_id == m.id)
              .order_by(KlikRucno.id.desc()).first())
    if zadnji is not None:
        db.delete(zadnji)
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, korisnik)
    db.commit()
    return {"ok": True}


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
    from .dispecer import _red, opis_s_operacijom, posalji_poveznicu
    # Mehaničari dodijeljeni na nezavršenim operacijama ovog naloga (bez onih koji čekaju dijelove).
    mehanicari: dict[int, Korisnik] = {}
    for op in n.operacije:
        for z in op.zadaci:
            if z.gotovo or z.razlog_prekida == "dijelovi":
                continue
            for r in z.radnici:
                if not je_serviser(r) or not r.prijavljuje_se:
                    continue   # voditelj (vanjski servis) / pregledar (Karthik) — ne primaju poveznice
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
        tekst = opis_s_operacijom(z.operacija.kategorija, z.opis)   # s nazivom operacije (#298)
        obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{tekst} · GB {_gb(nt)}", "/moja-radiona")
        wa = posalji_poveznicu(db, m, _gb(nt), tekst, str(request.base_url))
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
    from .dispecer import _red, opis_s_operacijom, posalji_poveznicu
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
                    if not je_serviser(r) or not r.prijavljuje_se:
                        continue   # voditelj (vanjski servis) / pregledar (Karthik) — ne primaju poveznice
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
        tekst = opis_s_operacijom(z.operacija.kategorija, z.opis)   # s nazivom operacije (#298)
        obavijesti_korisnika(db, m.id, "Potvrdi početak", f"{tekst} · GB {_gb(nt)}", "/moja-radiona")
        wa = posalji_poveznicu(db, m, _gb(nt), tekst, base_url)
        if wa.get("poslano"):
            poslano += 1
            db.add(KlikPoslano(radnik_id=m.id))   # trag za klik-bonus (kad mu je poslano)
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


class AutoPonavljaIn(BaseModel):
    ukljuceno: bool
    ura: str | None = None   # "HH:MM"


@router.post("/auto-slanje-ponavlja")
def auto_slanje_ponavlja(p: AutoPonavljaIn, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Uključi/isključi ponavljajuće jutarnje slanje: svaki radni dan (pon–sub) u zadani
    sat, samostalno (ne treba paliti navečer). Nedjelja se preskače. Propušten termin
    (server bio dolje dulje od 2 h) se NE šalje naknadno (da ne ode stari plan)."""
    from .. import norme
    if not p.ukljuceno:
        norme.set_postavka(db, KLJUC_AUTO_PON_ON, None)
        db.commit()
        return {"ok": True, "ukljuceno": False}
    dijelovi = (p.ura or "07:00").strip().split(":")
    try:
        hh, mm = int(dijelovi[0]), int(dijelovi[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Neispravno vrijeme (HH:MM)")
    hhmm = f"{hh:02d}:{mm:02d}"
    norme.set_postavka(db, KLJUC_AUTO_PON_ON, "1")
    norme.set_postavka(db, KLJUC_AUTO_PON_HHMM, hhmm)
    db.commit()
    return {"ok": True, "ukljuceno": True, "ura": hhmm}


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
        z.zavrsio_id = None
        for zr in z.vremena:
            zr.gotovo = False
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


@router.post("/zadatak/{zid}/vozilo-doslo")
def vozilo_doslo(zid: int, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Vozilo opet dostupno — skini oznaku 'nedostupan' i vrati operaciju u plan
    (dispečer je onda može slati/raditi normalno)."""
    z = _zad(db, zid)
    if z.razlog_prekida == "nedostupan":
        z.razlog_prekida = None
        z.prekid_vrijeme = None
        z.ceka_potvrdu = False
    db.commit()
    return {"ok": True}


# --- write: mehaničar (ili vlasnik) ---------------------------------------
def _smije_meh(korisnik: Korisnik, z: Zadatak) -> bool:
    # Dispečer/voditelj (pristup Planu) smije kliknuti umjesto mehaničara, ILI sam mehaničar.
    # (Prije: korisnik.ai_poslovodja — to polje postoji samo na Pydantic shemi, ne na ORM-u → 500.)
    return bool(ima_plan_pristup(korisnik) or any(r.id == korisnik.id for r in z.radnici))


@router.post("/zadatak/{zid}/potvrdi")
def potvrdi(zid: int, korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    # Prijava (početak/nastavak rada) ide ISKLJUČIVO preko WhatsApp poveznice (dispečer,
    # z_pocinjem). Prijava preko naloga/portala je onemogućena — ni poslovođa ni radnik ne
    # mogu pokrenuti mehaničara ovim putem.
    raise HTTPException(status_code=403,
                        detail="Prijava (početak rada) ide isključivo preko WhatsApp poveznice.")
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
        z.zavrsio_id = korisnik.id   # tko je kliknuo gotovo (dispečer/voditelj u planu)
        for zr in z.vremena:          # dispečer zatvara cijelu operaciju → svi radnici gotovi
            zr.gotovo = True
        z.razlog_prekida = None
        z.prekid_vrijeme = None
        servis_odradjen(db, z)   # servis gotov → upiši zadnji servis vozila
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
