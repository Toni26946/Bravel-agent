"""Faza 2 — učinak servisera: ljestvica (score) i osobni red poslova.

Cijena posla = norma(kategorija operacije) × (€/norma-sat)/60. Kad je zadatak
označen gotovim, njegov dio cijene (cijena operacije / broj zadataka u operaciji,
podijeljeno na radnike koji su radili zadatak) pribraja se učinku tih radnika.
Tako „stisni gotovo" odmah donosi zaradu i motivira samostalnost.

Shadow mode i dalje vrijedi za stvarnu plaću — ovo je prikaz učinka.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_ai_poslovodja, zahtijevaj_plan_pristup, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    KlikPoslano,
    KlikRucno,
    Korisnik,
    NormaPosla,
    Uloga,
    Zadatak,
    zadatak_radnici,
)
from ..norme import KLJUC_EUR, get_postavka, norm_kat, set_postavka

router = APIRouter(prefix="/ucinak", tags=["ucinak"])

voditelj_ili_poslovodja = zahtijevaj_ai_poslovodja()  # ljestvica je dio AI Poslovođe → samo vlasnik
_plan_pristup = zahtijevaj_plan_pristup()             # Klik-bonus: svi s pristupom Planu (voditelji/poslovođe)


def _eur(db: Session) -> float:
    try:
        return float(get_postavka(db, KLJUC_EUR, "0") or 0)
    except (TypeError, ValueError):
        return 0.0


def _norme_map(db: Session) -> dict[str, int]:
    return {n.kategorija: n.norma_min for n in db.execute(select(NormaPosla)).scalars().all()}


def _cijena_op(norma_min: int | None, eur: float) -> float:
    return round((norma_min or 0) * eur / 60.0, 2)


def _radnici_zadatka(z: Zadatak) -> list[Korisnik]:
    r = list(z.radnici)
    if not r and z.zaduzeni is not None:
        r = [z.zaduzeni]
    return r


def _skor(db: Session, od: datetime, do: datetime) -> tuple[dict[int, float], dict[int, int]]:
    """Vrati (zarada_po_radniku, broj_poslova_po_radniku) za gotove zadatke u razdoblju."""
    eur = _eur(db)
    norme = _norme_map(db)
    zadaci = db.execute(
        select(Zadatak).where(
            Zadatak.zavrseno.isnot(None),
            Zadatak.zavrseno >= od,
            Zadatak.zavrseno <= do,
        )
    ).scalars().all()
    op_broj_zad: dict[int, int] = {}
    zarada: dict[int, float] = defaultdict(float)
    broj: dict[int, int] = defaultdict(int)
    for z in zadaci:
        op = z.operacija
        if op is None:
            continue
        if op.id not in op_broj_zad:
            op_broj_zad[op.id] = db.scalar(
                select(func.count()).select_from(Zadatak).where(Zadatak.operacija_id == op.id)
            ) or 1
        norma = norme.get(norm_kat(op.kategorija))
        if not norma:
            continue
        cij = _cijena_op(norma, eur) / max(1, op_broj_zad[op.id])
        rad = _radnici_zadatka(z)
        if not rad:
            continue
        dio = cij / len(rad)
        for r in rad:
            zarada[r.id] += dio
            broj[r.id] += 1
    return zarada, broj


def _raspon(dana: int) -> tuple[datetime, datetime]:
    do = datetime.now(timezone.utc)
    od = do - timedelta(days=dana)
    return od, do


@router.get("/ljestvica")
def ljestvica(dana: int = Query(default=7, ge=1, le=365),
              db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    od, do = _raspon(dana)
    zarada, broj = _skor(db, od, do)
    imena = {k.id: k.ime for k in db.execute(
        select(Korisnik).where(Korisnik.id.in_(list(zarada.keys()) or [0]))
    ).scalars().all()}
    redovi = [
        {
            "radnik_id": rid,
            "ime": imena.get(rid, "—"),
            "zarada_eur": round(z, 2),
            "broj_poslova": broj.get(rid, 0),
        }
        for rid, z in zarada.items()
    ]
    redovi.sort(key=lambda r: r["zarada_eur"], reverse=True)
    for i, r in enumerate(redovi):
        r["mjesto"] = i + 1
    ukupno = round(sum(r["zarada_eur"] for r in redovi), 2)
    return {"dana": dana, "eur_po_normi": _eur(db), "ukupno_eur": ukupno, "redovi": redovi}


@router.get("/moj")
def moj_ucinak(dana: int = Query(default=7, ge=1, le=365),
               db: Session = Depends(get_db), ja: Korisnik = Depends(trenutni_korisnik)):
    od, do = _raspon(dana)
    zarada, broj = _skor(db, od, do)
    poredak = sorted(zarada.items(), key=lambda kv: kv[1], reverse=True)
    mjesto = next((i + 1 for i, (rid, _z) in enumerate(poredak) if rid == ja.id), None)
    eur = _eur(db)
    norme = _norme_map(db)

    # Otvoreni red poslova dodijeljenih meni (nezavršeni zadaci).
    red = db.execute(
        select(Zadatak)
        .join(zadatak_radnici, zadatak_radnici.c.zadatak_id == Zadatak.id)
        .where(zadatak_radnici.c.radnik_id == ja.id, Zadatak.gotovo.is_(False))
        .order_by(Zadatak.zapoceto.isnot(None).desc(), Zadatak.redoslijed, Zadatak.id)
    ).scalars().all()
    poslovi = []
    for z in red:
        op = z.operacija
        if op is None:
            continue
        nalog = op.nalog
        vozilo = nalog.vozilo if nalog else None
        norma = norme.get(norm_kat(op.kategorija))
        poslovi.append({
            "zadatak_id": z.id,
            "nalog_id": nalog.id if nalog else None,
            "nalog_broj": nalog.broj if nalog else None,
            "vozilo": (vozilo.gb if vozilo else None),
            "registracija": (vozilo.registracija if vozilo else None),
            "operacija": op.kategorija,
            "opis": z.opis,
            "cijena_eur": _cijena_op(norma, eur),
            "mjeri": z.zapoceto is not None,
        })
    return {
        "dana": dana,
        "zarada_eur": round(zarada.get(ja.id, 0.0), 2),
        "broj_poslova": broj.get(ja.id, 0),
        "mjesto": mjesto,
        "ukupno_servisera": len(poredak),
        "red": poslovi,
    }


# --- Klik-bonus: jutarnja disciplina klikanja --------------------------------
# Pravilo (shadow, samo mjerenje): ako je mehaničaru poruka poslana do `cutoff`
# (zadano 07:00), mora stisnuti (Počinjem/Gotovo) do `deadline` (zadano 07:10).
# Zakašnjenje/propust tog dana = 1 prekršaj. Bonus-pool se dijeli razmjerno
# disciplini; izgubljeni dio ide onima bez prekršaja.
KLJUC_KLIK_CUTOFF = "klik_cutoff"       # "HH:MM" — do kad poruka vrijedi kao jutarnja
KLJUC_KLIK_DEADLINE = "klik_deadline"   # "HH:MM" — do kad mora kliknuti
KLJUC_KLIK_POOL = "klik_pool"           # € mjesečni pool
KLJUC_KLIK_JUTRA = "klik_jutra"         # ISO datumi (CSV) kad je jutarnji plan poslan


def zabiljezi_jutro(db: Session, d) -> None:
    """Zabilježi da je JUTRO odrađeno (jutarnji plan poslan) — taj dan se očekuje klik
    od SVIH prisutnih mehaničara. Čuva zadnjih ~90 datuma u postavci."""
    ds = d.isoformat() if hasattr(d, "isoformat") else str(d)
    stari = [x.strip() for x in (get_postavka(db, KLJUC_KLIK_JUTRA, "") or "").split(",") if x.strip()]
    if ds in stari:
        return
    stari.append(ds)
    set_postavka(db, KLJUC_KLIK_JUTRA, ",".join(stari[-90:]))
    db.commit()


def _hr_offset(now_utc: datetime) -> timedelta:
    """HR pomak (CET/CEST) za dani UTC trenutak — bez vanjskih ovisnosti."""
    y = now_utc.year

    def _zadnja_ned(mj):
        d = 31
        while datetime(y, mj, d).weekday() != 6:
            d -= 1
        return datetime(y, mj, d, 1, 0, tzinfo=timezone.utc)

    ljeto = _zadnja_ned(3) <= now_utc < _zadnja_ned(10)
    return timedelta(hours=2 if ljeto else 1)


def _u_hr(dt: datetime) -> datetime:
    """UTC timestamp → hrvatsko lokalno (wall-clock) vrijeme."""
    u = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return u + _hr_offset(u)


def _hhmm(s: str | None, default: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in (s or default).split(":"))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    hh, mm = (int(x) for x in default.split(":"))
    return hh, mm


def _klik_bonus(db: Session, dana: int, pool: float) -> dict:
    ch, cm = _hhmm(get_postavka(db, KLJUC_KLIK_CUTOFF, "07:00"), "07:00")
    dh, dm = _hhmm(get_postavka(db, KLJUC_KLIK_DEADLINE, "07:10"), "07:10")
    od = datetime.now(timezone.utc) - timedelta(days=dana)

    danas = _u_hr(datetime.now(timezone.utc)).date()
    od_date = od.date()

    # 1) JUTRA kad je plan poslan (= očekivani dani za SVE prisutne): dani iz KlikPoslano
    #    (poruka ≤ cutoff) + ručno zabilježeni marker (da se broji i jutro bez novih poruka).
    jutra: set = set()
    for (ts,) in db.execute(select(KlikPoslano.poslano).where(KlikPoslano.poslano >= od)).all():
        h = _u_hr(ts)
        if (h.hour, h.minute) <= (ch, cm):
            jutra.add(h.date())
    for ds in (get_postavka(db, KLJUC_KLIK_JUTRA, "") or "").split(","):
        ds = ds.strip()
        if not ds:
            continue
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if od_date <= d <= danas:
            jutra.add(d)

    # 2) Svi PRISUTNI mehaničari (prijavljuju se u sustav). Očekuju se svako jutro,
    #    osim dana kad su odsutni (godišnji/bolovanje/odsutan za to razdoblje). Teren ne ulazi.
    meh = db.execute(select(Korisnik).where(
        Korisnik.uloga == Uloga.radnik, Korisnik.aktivan.is_(True),
        Korisnik.prijavljuje_se.is_(True))).scalars().all()

    def _odsutan_na(m, d) -> bool:
        if not m.odsutnost_vrsta:
            return False
        if m.odsutnost_od and d < m.odsutnost_od:
            return False
        if m.odsutnost_do and d > m.odsutnost_do:
            return False
        return True   # pokriva taj dan (ili bez datuma = trajno)

    # 3) Prvi klik (Počinjem/Gotovo) po danu, po radniku.
    rids = [m.id for m in meh]
    prvi: dict[int, dict] = defaultdict(dict)
    if rids and jutra:
        rows = db.execute(
            select(zadatak_radnici.c.radnik_id, Zadatak.zapoceto, Zadatak.zavrseno)
            .join(Zadatak, Zadatak.id == zadatak_radnici.c.zadatak_id)
            .where(zadatak_radnici.c.radnik_id.in_(rids),
                   (Zadatak.zapoceto.isnot(None)) | (Zadatak.zavrseno.isnot(None)))
        ).all()
        for rid, zap, zav in rows:
            for ts in (zap, zav):
                if ts is None:
                    continue
                h = _u_hr(ts)
                cur = prvi[rid].get(h.date())
                if cur is None or h < cur:
                    prvi[rid][h.date()] = h

    # Dani kad je mehaničar RUČNO prijavljen (dispečer umjesto njega) → prekršaj, ne broji na vrijeme.
    rucno: dict[int, set] = defaultdict(set)
    for rid, ts in db.execute(
        select(KlikRucno.radnik_id, KlikRucno.kreiran).where(KlikRucno.kreiran >= od)
    ).all():
        rucno[rid].add(_u_hr(ts).date())

    # 4) Po radniku: očekivani dani (jutra kad je prisutan) / na vrijeme / prekršaji. Teren van.
    po: dict[int, dict] = {}
    imena: dict[int, str] = {}
    for m in meh:
        imena[m.id] = m.ime
        if m.odsutnost_vrsta == "teren":
            continue
        dani = [d for d in jutra if not _odsutan_na(m, d)]
        if not dani:
            continue
        nav = 0
        detalji: list[dict] = []
        for d in sorted(dani, reverse=True):   # najnoviji prekršaj gore
            if d in rucno.get(m.id, ()):
                detalji.append({"datum": d.strftime("%d.%m.%Y"),
                                "razlog": "ručno prijavljen (dispečer umjesto njega)"})
                continue   # ručno prijavljen tog dana → prekršaj (nije sam kliknuo)
            k = prvi.get(m.id, {}).get(d)
            if k is not None and (k.hour, k.minute) <= (dh, dm):
                nav += 1
            elif k is not None:
                detalji.append({"datum": d.strftime("%d.%m.%Y"),
                                "razlog": f"kliknuo u {k.hour:02d}:{k.minute:02d} — nakon {dh:02d}:{dm:02d}"})
            else:
                detalji.append({"datum": d.strftime("%d.%m.%Y"), "razlog": "nije kliknuo"})
        po[m.id] = {"ocekivano": len(dani), "na_vrijeme": nav,
                    "prekrsaji": len(dani) - nav, "detalji": detalji}

    # 5) Podjela poola: razmjerno disciplini; izgubljeni dio onima bez prekršaja.
    n = len(po)
    base = (pool / n) if n else 0.0
    sirovi = {rid: base * (d["na_vrijeme"] / d["ocekivano"] if d["ocekivano"] else 0.0)
              for rid, d in po.items()}
    ostatak = base * n - sum(sirovi.values())
    cisti = [rid for rid, d in po.items() if d["prekrsaji"] == 0 and d["ocekivano"] > 0]
    extra = (ostatak / len(cisti)) if cisti else 0.0

    redovi = []
    for rid, d in po.items():
        bonus = sirovi[rid] + (extra if rid in cisti else 0.0)
        redovi.append({
            "radnik_id": rid, "ime": imena.get(rid, "—"),
            "ocekivano": d["ocekivano"], "na_vrijeme": d["na_vrijeme"],
            "prekrsaji": d["prekrsaji"],
            "prekrsaji_detalji": d["detalji"],
            "postotak": round(100 * d["na_vrijeme"] / d["ocekivano"]) if d["ocekivano"] else 0,
            "bonus_eur": round(bonus, 2),
        })
    redovi.sort(key=lambda r: (-r["bonus_eur"], r["prekrsaji"], r["ime"]))
    for i, r in enumerate(redovi):
        r["mjesto"] = i + 1
    return {"dana": dana, "pool_eur": round(pool, 2),
            "cutoff": f"{ch:02d}:{cm:02d}", "deadline": f"{dh:02d}:{dm:02d}",
            "redovi": redovi}


@router.get("/klik-bonus")
def klik_bonus(dana: int = Query(default=30, ge=1, le=365),
               pool: float | None = Query(default=None, ge=0),
               db: Session = Depends(get_db), _: Korisnik = Depends(_plan_pristup)):
    """Klik-bonus ljestvica (shadow): tko kliká ujutro na vrijeme i koliki mu je dio
    poola. Vide je svi s pristupom Planu (vlasnik + voditelji/poslovođe s modulom /plan);
    postavljanje poola (/klik-postavke) ostaje samo vlasniku. `pool` iz upita gazi spremljeni."""
    if pool is None:
        try:
            pool = float(get_postavka(db, KLJUC_KLIK_POOL, "0") or 0)
        except (TypeError, ValueError):
            pool = 0.0
    return _klik_bonus(db, dana, pool)


class KlikPostavkeIn(BaseModel):
    pool: float | None = None
    cutoff: str | None = None
    deadline: str | None = None


@router.post("/klik-postavke")
def klik_postavke(p: KlikPostavkeIn, db: Session = Depends(get_db),
                  _: Korisnik = Depends(voditelj_ili_poslovodja)):
    """Spremi pool (€) i pragove vremena za klik-bonus."""
    if p.pool is not None:
        set_postavka(db, KLJUC_KLIK_POOL, str(max(0.0, p.pool)))
    if p.cutoff:
        hh, mm = _hhmm(p.cutoff, "07:00")
        set_postavka(db, KLJUC_KLIK_CUTOFF, f"{hh:02d}:{mm:02d}")
    if p.deadline:
        hh, mm = _hhmm(p.deadline, "07:10")
        set_postavka(db, KLJUC_KLIK_DEADLINE, f"{hh:02d}:{mm:02d}")
    db.commit()
    return {"ok": True, "pool_eur": float(get_postavka(db, KLJUC_KLIK_POOL, "0") or 0),
            "cutoff": get_postavka(db, KLJUC_KLIK_CUTOFF, "07:00"),
            "deadline": get_postavka(db, KLJUC_KLIK_DEADLINE, "07:10")}


@router.get("/sumnjivo-brzi")
def sumnjivo_brzi(
    dana: int = Query(default=1, ge=1, le=90),
    prag_sek: int = Query(default=120, ge=1, le=3600),
    db: Session = Depends(get_db),
    _: Korisnik = Depends(voditelj_ili_poslovodja),
):
    """Zadaci koje je mehaničar označio gotovima a da je na njima proveo manje od
    `prag_sek` sekundi (zadano 120 s) u zadnjih `dana` dana. Za svaki: trajanje,
    je li uopće pokrenuo mjerač, norma (očekivano) i tko je bio na zadatku."""
    od, do = _raspon(dana)
    norme = _norme_map(db)
    zadaci = db.execute(
        select(Zadatak).where(
            Zadatak.zavrseno.isnot(None),
            Zadatak.zavrseno >= od,
            Zadatak.zavrseno <= do,
        )
    ).scalars().all()
    redovi = []
    for z in zadaci:
        op = z.operacija
        if op is None or (op.kategorija or "").upper() == "TEST":
            continue
        rad = _radnici_zadatka(z)
        if not rad:                      # samo zadaci koje je zatvorio mehaničar (ima radnika)
            continue
        trajanje = int(z.utroseno_sek or 0)
        if trajanje <= 0 and z.zapoceto and z.zavrseno:
            trajanje = max(0, int((z.zavrseno - z.zapoceto).total_seconds()))
        if trajanje >= prag_sek:
            continue
        n = op.nalog
        voz = n.vozilo if n else None
        redovi.append({
            "zadatak_id": z.id,
            "gb": (voz.gb if voz else (n.broj if n else None)),
            "registracija": (voz.registracija if voz else None),
            "kategorija": op.kategorija,
            "opis": z.opis,
            "trajanje_sek": trajanje,
            "pokrenuo": z.zapoceto is not None,
            "norma_min": norme.get(norm_kat(op.kategorija)),
            "kraj": z.zavrseno.isoformat() if z.zavrseno else None,
            "mehanicari": [r.ime for r in rad],
        })
    redovi.sort(key=lambda r: r["trajanje_sek"])
    return {"dana": dana, "prag_sek": prag_sek, "redovi": redovi}
