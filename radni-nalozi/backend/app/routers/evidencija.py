"""Evidencija radnog vremena — mjesečna, po radniku i danu.

Skladištar vodi za cijelu ekipu: upiše dolazak (OD) i odlazak (DO), a aplikacija
izračuna redovne i prekovremene sate (standardni dan = 8 h, iznad = prekovremeni).
Umjesto sati dan se može označiti kodom: GO (godišnji), BO (bolovanje),
PD (plaćeni dopust), OD (odjava). Teren se upisuje zasebno (sati na terenu).
"""
import calendar
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import EvidencijaRV, Korisnik, Uloga
from ..schemas import EvidencijaDan, EvidencijaMjesec, EvidencijaRadnik, EvidencijaUnos

router = APIRouter(prefix="/evidencija", tags=["evidencija"])

# Evidenciju vode skladištari; voditelj/poslovođa je također vide i uređuju.
evidencija_pristup = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)

KODOVI = {"GO", "BO", "PD", "OD"}
STANDARDNI_DAN = 8.0  # sati nakon kojih počinju prekovremeni
PRAG_2H = 2.0         # dan se broji u "2h+" ako je prekovremenih ≥ ovoliko sati


def _radnici(db: Session) -> list[Korisnik]:
    """Ekipa radione + skladišta (svi aktivni osim vozača), po imenu."""
    return (
        db.query(Korisnik)
        .filter(Korisnik.aktivan.is_(True), Korisnik.uloga != Uloga.vozac)
        .order_by(Korisnik.ime)
        .all()
    )


def _minute(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _sati(od: str | None, do: str | None) -> float:
    """Neto sati između OD i DO (ako DO < OD pretpostavi prelazak ponoći)."""
    a, b = _minute(od), _minute(do)
    if a is None or b is None:
        return 0.0
    if b < a:
        b += 24 * 60
    return round(max(0, b - a) / 60.0, 2)


def _preracun(od: str | None, do: str | None, kod: str | None) -> tuple[float, float]:
    """Vrati (redovni, prekovremeni) sate; kod (odsutnost) poništava sate."""
    if kod:
        return 0.0, 0.0
    uk = _sati(od, do)
    redovni = min(uk, STANDARDNI_DAN)
    prekovremeni = round(max(0.0, uk - STANDARDNI_DAN), 2)
    return round(redovni, 2), prekovremeni


def _prazno(u: EvidencijaUnos) -> bool:
    return not (u.od or u.do or (u.teren or 0) or (u.kod or "").strip() or (u.napomena or "").strip())


@router.get("", response_model=EvidencijaMjesec)
def dohvati_mjesec(
    godina: int = Query(..., ge=2000, le=2100),
    mjesec: int = Query(..., ge=1, le=12),
    _: Korisnik = Depends(evidencija_pristup),
    db: Session = Depends(get_db),
):
    dana = calendar.monthrange(godina, mjesec)[1]
    prvi = date(godina, mjesec, 1)
    zadnji = date(godina, mjesec, dana)

    zapisi = (
        db.query(EvidencijaRV)
        .filter(EvidencijaRV.datum >= prvi, EvidencijaRV.datum <= zadnji)
        .all()
    )
    po_radniku: dict[int, list[EvidencijaRV]] = {}
    for z in zapisi:
        po_radniku.setdefault(z.korisnik_id, []).append(z)

    radnici_out: list[EvidencijaRadnik] = []
    for k in _radnici(db):
        r = EvidencijaRadnik(korisnik_id=k.id, ime=k.ime, uloga=k.uloga.value)
        for z in po_radniku.get(k.id, []):
            kljuc = z.datum.isoformat()
            r.dani[kljuc] = EvidencijaDan(
                datum=z.datum, od=z.od, do=z.do,
                redovni=z.redovni or 0, prekovremeni=z.prekovremeni or 0,
                teren=z.teren or 0, kod=z.kod, napomena=z.napomena,
            )
            r.redovno += z.redovni or 0
            r.prekovremeni += z.prekovremeni or 0
            r.teren += z.teren or 0
            if (z.redovni or 0) > 0 or (z.prekovremeni or 0) > 0:
                r.radni_dani += 1
            if (z.prekovremeni or 0) >= PRAG_2H:
                r.prekovremeni_2h += 1
            if z.kod == "GO":
                r.go += 1
            elif z.kod == "BO":
                r.bo += 1
            elif z.kod == "PD":
                r.pd += 1
        r.redovno = round(r.redovno, 2)
        r.prekovremeni = round(r.prekovremeni, 2)
        r.teren = round(r.teren, 2)
        r.ukupno_redovnih = r.redovno
        radnici_out.append(r)

    return EvidencijaMjesec(godina=godina, mjesec=mjesec, dana_u_mjesecu=dana, radnici=radnici_out)


@router.put("", response_model=EvidencijaDan)
def upsert(podaci: EvidencijaUnos, korisnik: Korisnik = Depends(evidencija_pristup), db: Session = Depends(get_db)):
    if not db.get(Korisnik, podaci.korisnik_id):
        raise HTTPException(status_code=404, detail="Radnik ne postoji")
    kod = (podaci.kod or "").strip().upper() or None
    if kod and kod not in KODOVI:
        raise HTTPException(status_code=400, detail="Nepoznat kod (GO/BO/PD/OD)")

    z = (
        db.query(EvidencijaRV)
        .filter(EvidencijaRV.korisnik_id == podaci.korisnik_id, EvidencijaRV.datum == podaci.datum)
        .first()
    )
    # Prazan unos → obriši postojeći redak (ako ga ima).
    if _prazno(podaci):
        if z:
            db.delete(z)
            db.commit()
        return EvidencijaDan(datum=podaci.datum)

    od = (podaci.od or "").strip() or None
    do = (podaci.do or "").strip() or None
    teren = round(float(podaci.teren or 0), 2)
    redovni, prekovremeni = _preracun(od, do, kod)

    if not z:
        z = EvidencijaRV(korisnik_id=podaci.korisnik_id, datum=podaci.datum, kreirao_id=korisnik.id)
        db.add(z)
    z.od, z.do, z.teren, z.kod = od, do, teren, kod
    z.redovni, z.prekovremeni = redovni, prekovremeni
    z.napomena = (podaci.napomena or "").strip() or None
    db.commit()
    db.refresh(z)
    return EvidencijaDan(
        datum=z.datum, od=z.od, do=z.do, redovni=z.redovni, prekovremeni=z.prekovremeni,
        teren=z.teren, kod=z.kod, napomena=z.napomena,
    )


@router.get("/izvoz.xlsx")
def izvoz(
    godina: int = Query(..., ge=2000, le=2100),
    mjesec: int = Query(..., ge=1, le=12),
    _: Korisnik = Depends(evidencija_pristup),
    db: Session = Depends(get_db),
):
    """Mjesečni Excel: redak po radniku, zbirni stupci + po danu OD/DO/redovni/prekovremeni/teren."""
    from openpyxl import Workbook

    podaci = dohvati_mjesec(godina, mjesec, _, db)  # ponovno iskoristi logiku dohvata
    dana = podaci.dana_u_mjesecu

    wb = Workbook()
    ws = wb.active
    ws.title = f"{godina}-{mjesec:02d}"

    zbirni = ["RB", "Radnik", "Redovno", "Prekovremeni", "2h+", "Teren", "Radni dani", "GO", "BO", "PD", "Ukupno redovnih"]
    po_danu = ["OD", "DO", "Redovni", "Prekovremeni", "Teren"]
    zaglavlje1 = list(zbirni) + []
    zaglavlje2 = [""] * len(zbirni)
    for d in range(1, dana + 1):
        zaglavlje1 += [str(d)] + [""] * (len(po_danu) - 1)
        zaglavlje2 += po_danu
    ws.append(zaglavlje1)
    ws.append(zaglavlje2)
    for red in (ws[1], ws[2]):
        for c in red:
            c.font = c.font.copy(bold=True)

    for i, r in enumerate(podaci.radnici, start=1):
        red = [i, r.ime, r.redovno, r.prekovremeni, r.prekovremeni_2h, r.teren, r.radni_dani, r.go, r.bo, r.pd, r.ukupno_redovnih]
        for d in range(1, dana + 1):
            kljuc = date(godina, mjesec, d).isoformat()
            dan = r.dani.get(kljuc)
            if dan is None:
                red += ["", "", "", "", ""]
            elif dan.kod:
                red += [dan.kod, "", "", "", dan.teren or ""]
            else:
                red += [dan.od or "", dan.do or "", dan.redovni or "", dan.prekovremeni or "", dan.teren or ""]
        ws.append(red)

    ws.column_dimensions["B"].width = 28
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="evidencija-{godina}-{mjesec:02d}.xlsx"'},
    )
