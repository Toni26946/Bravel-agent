"""Vozila (kamioni). Svi prijavljeni mogu vidjeti; uređuje samo voditelj."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import re

from ..storage import obrisi_sliku, spremi_sliku

from .. import flota
from ..config import settings
from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    Korisnik,
    Nalog,
    PovijestRada,
    RegistarVozila,
    StatusNaloga,
    StatusVozila,
    Uloga,
    Vozilo,
    ZamjenaDijela,
)
from ..schemas import (
    PovijestRadaOut,
    RegistarStatusUpdate,
    RegistarVozilaOut,
    VoziloCreate,
    VoziloOut,
    VoziloUpdate,
    VoziloUvoz,
    VoziloUvozRezultat,
    ZamjenaDijelaCreate,
    ZamjenaDijelaOut,
)

router = APIRouter(prefix="/vozila", tags=["vozila"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)
voditelj_ili_radnik = zahtijevaj_uloge(Uloga.voditelj, Uloga.radnik)
voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)

# Nalozi koji drže vozilo "u radionici" (za poveznicu na aktivan nalog).
_AKTIVNI_STATUSI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)


def _status_iz_mobilisisa(sirovi: str | None) -> StatusVozila | None:
    """Mapiraj sirovi Mobilisis status (Status_vozila.xlsx) u naš operativni status.
    Vrati None ako nema podatka (tada ne diramo status)."""
    s = (sirovi or "").strip().lower()
    if not s:
        return None
    # Izašlo iz flote (prodano/odjava/rashod/razbijeno/neaktivno/pasivno…)
    if any(k in s for k in ("prodan", "prodaj", "odjav", "rashod", "razbij",
                            "neaktiv", "pasiv", "ne koristi")):
        return StatusVozila.prodano
    if any(k in s for k in ("radioni", "servis", "popravak", "popravk")):
        return StatusVozila.u_radionici
    if any(k in s for k in ("neisprav", "pokvar", "kvar")):
        return StatusVozila.pokvareno
    return StatusVozila.aktivno


async def _sync_registar(db: Session) -> bool:
    """Osvježi popisna polja (gb/reg/tip/kategorija) iz Flota OS-a i predloži status
    iz Mobilisisa. RUČNO postavljen status (rucno=True) se NE dira. Best-effort;
    vraća True ako je Flota odgovorila."""
    vozila = await flota.vozila_flota()
    if vozila is None:
        return False
    postojeci = {r.gb: r for r in db.query(RegistarVozila).all()}
    sad = datetime.now(timezone.utc)
    for v in vozila:
        gb = str(v.get("gb") or "").strip()
        if not gb:
            continue
        mob = _status_iz_mobilisisa(v.get("status"))
        r = postojeci.get(gb)
        if r is None:
            r = RegistarVozila(gb=gb, status=(mob or StatusVozila.aktivno))
            db.add(r)
            postojeci[gb] = r
        r.registracija = v.get("reg")
        r.tip = v.get("tip")
        r.kategorija = v.get("kategorija")
        r.mobilisis_status = v.get("status")
        # Prijedlog iz Mobilisisa vrijedi dok ga netko ručno ne promijeni.
        if not r.rucno and mob is not None:
            r.status = mob
        r.sinkroniziran = sad
    db.commit()
    return True


def _nalog_po_gb(db: Session) -> dict:
    """{gb: Nalog} za vozila trenutno u radu (za poveznicu s registra)."""
    aktivni = (
        db.query(Nalog).filter(Nalog.status.in_(_AKTIVNI_STATUSI))
        .order_by(Nalog.azuriran.desc()).all()
    )
    mapa: dict = {}
    for n in aktivni:
        gb = n.vozilo.gb if n.vozilo else None
        if gb:
            mapa.setdefault(str(gb), n)
            mapa.setdefault(str(gb).lstrip("0") or str(gb), n)
    return mapa


@router.get("/registar", response_model=list[RegistarVozilaOut])
async def registar(
    kategorija: str | None = None,
    status: str | None = None,
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja),
    db: Session = Depends(get_db),
):
    """Matični popis svih vozila sa statusom (mjerodavno). Popis se osvježava iz
    Flota OS-a (best-effort), a status je ručni. Opcijski filtri kategorija/status."""
    await _sync_registar(db)
    q = db.query(RegistarVozila)
    if kategorija:
        q = q.filter(RegistarVozila.kategorija == kategorija)
    if status:
        try:
            q = q.filter(RegistarVozila.status == StatusVozila(status))
        except ValueError:
            raise HTTPException(status_code=400, detail="Nepoznat status")
    redovi = q.all()
    # stabilan poredak: po duljini GB pa GB (kao u Floti)
    redovi.sort(key=lambda r: (len(r.gb), r.gb))
    nalozi = _nalog_po_gb(db)
    out = []
    for r in redovi:
        n = nalozi.get(r.gb) or nalozi.get(r.gb.lstrip("0") or r.gb)
        stavka = RegistarVozilaOut.model_validate(r)
        stavka.nalog_id = n.id if n else None
        stavka.broj = n.broj if n else None
        out.append(stavka)
    return out


@router.patch("/registar/{gb}", response_model=RegistarVozilaOut)
def registar_status(
    gb: str,
    podaci: RegistarStatusUpdate,
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja),
    db: Session = Depends(get_db),
):
    """Postavi ručni status (i napomenu) vozila — mjerodavno („sveto pismo").

    `rucno=False` (bez statusa) = poništi ručno i vrati na Mobilisis prijedlog."""
    r = db.get(RegistarVozila, gb)
    if r is None:
        # vozilo možda još nije sinkronizirano — kreiraj minimalni zapis
        r = RegistarVozila(gb=gb)
        db.add(r)
    if podaci.rucno is False and not podaci.status:
        # Vrati na Mobilisis: makni ručnu zastavicu i primijeni prijedlog.
        r.rucno = False
        mob = _status_iz_mobilisisa(r.mobilisis_status)
        if mob is not None:
            r.status = mob
    else:
        try:
            novi = StatusVozila(podaci.status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Nepoznat status")
        # „Spremno" (šlepa spremna za kamion) ne može bez lokacije parkinga —
        # baš to ih tjeramo da upišu da se zna GDJE je spremna šlepa.
        lok_nova = (podaci.lokacija if podaci.lokacija is not None else r.lokacija) or ""
        if novi == StatusVozila.spremno and not lok_nova.strip():
            raise HTTPException(
                status_code=400,
                detail="Za status Spremno upišite gdje je šlepa parkirana (lokacija).",
            )
        if novi == StatusVozila.spremno and r.status != StatusVozila.spremno:
            r.spreman_od = date.today()
        r.status = novi
        r.rucno = True  # od sada ručno pobjeđuje nad Mobilisis prijedlogom
    if podaci.lokacija is not None:
        r.lokacija = podaci.lokacija.strip() or None
    if podaci.napomena is not None:
        r.napomena = podaci.napomena.strip() or None
    r.podsjetnik_zadnji = None  # upisali su nešto → prekini eskalaciju podsjetnika
    r.azurirao_id = korisnik.id
    db.commit()
    db.refresh(r)
    return RegistarVozilaOut.model_validate(r)


def _prikolice_za_upisati(db: Session) -> list[RegistarVozila]:
    """Šlepe (prikolice) čiji je nalog nedavno završen, a još nisu dobile ishod:
    nisu označene Spremno(+lokacija) ni Pokvareno. Njih moramo natjerati na upis."""
    zavrseni = (StatusNaloga.gotov, StatusNaloga.zatvoren)
    nalozi = (
        db.query(Nalog).filter(Nalog.status.in_(zavrseni))
        .order_by(Nalog.azuriran.desc()).all()
    )
    gbs: list[str] = []
    vidjeno: set = set()
    for n in nalozi:
        gb = str(n.vozilo.gb) if n.vozilo else None
        if gb and gb not in vidjeno:
            vidjeno.add(gb)
            gbs.append(gb)
    out = []
    for gb in gbs:
        r = db.get(RegistarVozila, gb) or db.query(RegistarVozila).filter(
            RegistarVozila.gb == (gb.lstrip("0") or gb)).first()
        if not r or r.kategorija != "prikolica":
            continue
        rijeseno = (r.status == StatusVozila.spremno and (r.lokacija or "").strip()) \
            or r.status in (StatusVozila.pokvareno, StatusVozila.prodano)
        if not rijeseno:
            out.append(r)
    return out


def _gotovi_kamioni(db: Session, pozicije: dict) -> list[dict]:
    """Kamioni čiji je nalog gotov/zatvoren, a JOŠ su u krugu radione (nisu otišli).

    Kamioni imaju GPS (Flota OS), pa izlaze s popisa kad napuste krug od
    `spremni_radius_m` (default 5 km). Bez upisanih koordinata radione ili bez
    GPS-a → prikaži ih (pretpostavi da su tu)."""
    zavrseni = (StatusNaloga.gotov, StatusNaloga.zatvoren)
    nalozi = (
        db.query(Nalog).filter(Nalog.status.in_(zavrseni))
        .order_by(Nalog.azuriran.desc()).all()
    )
    ima_radionu = bool(settings.radiona_lat) and bool(settings.radiona_lon)
    radius = settings.spremni_radius_m
    out = []
    vidjeno: set = set()
    for n in nalozi:
        gb = str(n.vozilo.gb) if n.vozilo else None
        if not gb or gb in vidjeno:
            continue
        vidjeno.add(gb)
        r = db.get(RegistarVozila, gb) or db.query(RegistarVozila).filter(
            RegistarVozila.gb == (gb.lstrip("0") or gb)).first()
        if not r or r.kategorija != "kamion" or r.status == StatusVozila.prodano:
            continue
        p = pozicije.get(gb) or pozicije.get(gb.lstrip("0") or gb)
        udalj = None
        if ima_radionu and p and p.get("lat") is not None and p.get("lon") is not None:
            udalj = int(flota.udaljenost_m(p["lat"], p["lon"],
                                           settings.radiona_lat, settings.radiona_lon))
            if udalj > radius:
                continue  # napustio krug radione → više nije „spreman u radioni"
        out.append({
            "gb": gb, "reg": r.registracija, "tip": r.tip,
            "nalog_id": n.id, "broj": n.broj,
            "udaljenost_m": udalj, "ima_gps": bool(p),
            "lat": (p.get("lat") if p else None),
            "lon": (p.get("lon") if p else None),
            "vrijeme": (p.get("vrijeme") if p else None),
        })
    return out


@router.get("/spremne")
async def spremne_slepe(
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db)
):
    """Ploča spremnih šlepa: što imamo i gdje.

    - `spremne`: šlepe sa statusom „Spremno", grupirane po parkingu (lokaciji).
    - `za_upisati`: šlepe s nedavno završenim nalogom koje čekaju upis spremnosti+lokacije.
    - `lokacije`: nedavno korišteni parkinzi (za prijedloge pri upisu).
    """
    await _sync_registar(db)
    nalozi = _nalog_po_gb(db)

    def _stavka(r: RegistarVozila) -> dict:
        n = nalozi.get(r.gb) or nalozi.get(r.gb.lstrip("0") or r.gb)
        return {
            "gb": r.gb, "reg": r.registracija, "tip": r.tip,
            "lokacija": r.lokacija, "napomena": r.napomena,
            "spreman_od": r.spreman_od.isoformat() if r.spreman_od else None,
            "nalog_id": n.id if n else None, "broj": n.broj if n else None,
        }

    spremne = (
        db.query(RegistarVozila).filter(RegistarVozila.status == StatusVozila.spremno).all()
    )
    spremne.sort(key=lambda r: ((r.lokacija or "~"), len(r.gb), r.gb))
    grupe: dict = {}
    for r in spremne:
        grupe.setdefault(r.lokacija or "—", []).append(_stavka(r))

    za_upisati = [_stavka(r) for r in _prikolice_za_upisati(db)]

    lokacije = sorted({
        (r.lokacija or "").strip()
        for r in db.query(RegistarVozila).filter(RegistarVozila.lokacija.isnot(None)).all()
        if (r.lokacija or "").strip()
    })

    # Gotovi kamioni — u krugu radione (GPS). Best-effort dohvat pozicija.
    try:
        pozicije = await flota.dohvati_pozicije()
    except Exception:
        pozicije = None
    if not pozicije:
        pozicije = flota.zadnje_pozicije()
    kamioni = _gotovi_kamioni(db, pozicije or {})

    return {
        "broj_spremnih": len(spremne),
        "grupe": [{"lokacija": k, "slepe": v} for k, v in grupe.items()],
        "za_upisati": za_upisati,
        "lokacije": lokacije,
        "kamioni": kamioni,
        "kamion_radius_km": round(settings.spremni_radius_m / 1000, 1),
    }


@router.get("", response_model=list[VoziloOut])
def popis(_: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    return db.query(Vozilo).filter(Vozilo.aktivan.is_(True)).order_by(Vozilo.gb).all()


@router.post("", response_model=VoziloOut, status_code=201)
def kreiraj(podaci: VoziloCreate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    if db.query(Vozilo).filter(Vozilo.gb == podaci.gb).first():
        raise HTTPException(status_code=409, detail="Vozilo s tim GB već postoji")
    v = Vozilo(**podaci.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _je_registracija(t: str) -> bool:
    """Grubo prepoznavanje registarske oznake (npr. ZG3495FR, DQB2425):
    bez razmaka/točke, kratka, ima i slova i brojke."""
    return (
        " " not in t and "." not in t
        and 4 <= len(t) <= 9
        and any(c.isdigit() for c in t)
        and any(c.isalpha() for c in t)
    )


@router.post("/uvoz", response_model=VoziloUvozRezultat)
def uvoz(podaci: VoziloUvoz, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    """Skupni uvoz kamiona iz zalijepljenog popisa.

    Svaki redak počinje garažnim brojem (GB). Ostali stupci (razdvojeni tabom,
    zarezom ili točka-zarezom) prepoznaju se automatski: registracija po obliku
    (npr. ZG1234AB), a ostalo je naziv vozila (marka). Redoslijed stupaca nije
    bitan — može se lijepiti direktno iz Excela (GB, VOZILO, REG OZNAKA).
    Postojeći GB i redak zaglavlja se preskaču.
    """
    postojeci = {v.gb.lower() for v in db.query(Vozilo).all()}
    dodano = 0
    ukupno = 0
    for redak in podaci.tekst.splitlines():
        redak = redak.strip()
        if not redak:
            continue
        dijelovi = [d.strip() for d in re.split(r"[\t,;]", redak)]
        gb = dijelovi[0] if dijelovi else ""
        if not gb:
            continue
        # Preskoči vjerojatni redak zaglavlja ("GB", "Garažni broj"…)
        if gb.lower() in ("gb", "garažni broj", "garazni broj", "gb kamiona", "gb vozila"):
            continue
        ukupno += 1
        if gb.lower() in postojeci:
            continue
        ostali = [d for d in dijelovi[1:] if d and d != "0"]
        reg = next((d for d in ostali if _je_registracija(d)), None)
        marka = next((d for d in ostali if d != reg and not _je_registracija(d)), None)
        db.add(Vozilo(gb=gb, registracija=reg, marka=marka))
        postojeci.add(gb.lower())
        dodano += 1
    db.commit()
    return VoziloUvozRezultat(dodano=dodano, preskoceno=ukupno - dodano, ukupno=ukupno)


@router.get("/{vozilo_id}", response_model=VoziloOut)
def detalj(vozilo_id: int, _: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    v = db.get(Vozilo, vozilo_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    return v


@router.post("/{vozilo_id}/slika", response_model=VoziloOut)
def postavi_sliku(
    vozilo_id: int,
    slika: UploadFile = File(...),
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    v = db.get(Vozilo, vozilo_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    nova = spremi_sliku(slika)
    if v.slika:
        obrisi_sliku(v.slika)  # ukloni staru datoteku
    v.slika = nova
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{vozilo_id}/slika", response_model=VoziloOut)
def obrisi_sliku_vozila(
    vozilo_id: int, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)
):
    v = db.get(Vozilo, vozilo_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    if v.slika:
        obrisi_sliku(v.slika)
        v.slika = None
        db.commit()
        db.refresh(v)
    return v


@router.patch("/{vozilo_id}", response_model=VoziloOut)
def azuriraj(
    vozilo_id: int,
    podaci: VoziloUpdate,
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    v = db.get(Vozilo, vozilo_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    for polje, vrijednost in podaci.model_dump(exclude_unset=True).items():
        setattr(v, polje, vrijednost)
    db.commit()
    db.refresh(v)
    return v


# --- Servisna povijest (uvezena evidencija; voditelj + radnik) ---------------
@router.get("/{vozilo_id}/povijest-rada", response_model=list[PovijestRadaOut])
def povijest_rada(
    vozilo_id: int, _: Korisnik = Depends(voditelj_ili_radnik), db: Session = Depends(get_db)
):
    if not db.get(Vozilo, vozilo_id):
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    return (
        db.query(PovijestRada)
        .filter(PovijestRada.vozilo_id == vozilo_id)
        .order_by(PovijestRada.datum.desc(), PovijestRada.id.desc())
        .all()
    )


# --- Povijest zamjene dijelova (voditelj + radnik) ---------------------------
@router.get("/{vozilo_id}/dijelovi", response_model=list[ZamjenaDijelaOut])
def povijest_dijelova(
    vozilo_id: int, _: Korisnik = Depends(voditelj_ili_radnik), db: Session = Depends(get_db)
):
    if not db.get(Vozilo, vozilo_id):
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    return (
        db.query(ZamjenaDijela)
        .filter(ZamjenaDijela.vozilo_id == vozilo_id)
        .order_by(ZamjenaDijela.datum.desc(), ZamjenaDijela.id.desc())
        .all()
    )


@router.post("/{vozilo_id}/dijelovi", response_model=ZamjenaDijelaOut, status_code=201)
def dodaj_zamjenu(
    vozilo_id: int, podaci: ZamjenaDijelaCreate,
    korisnik: Korisnik = Depends(voditelj_ili_radnik), db: Session = Depends(get_db),
):
    if not db.get(Vozilo, vozilo_id):
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    if not podaci.naziv.strip():
        raise HTTPException(status_code=400, detail="Upišite naziv dijela.")
    if podaci.nalog_id is not None and not db.get(Nalog, podaci.nalog_id):
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    z = ZamjenaDijela(
        vozilo_id=vozilo_id,
        nalog_id=podaci.nalog_id,
        naziv=podaci.naziv.strip(),
        razlog=(podaci.razlog or "").strip() or None,
        datum=podaci.datum or date.today(),
        kilometraza=podaci.kilometraza,
        promijenio_id=korisnik.id,
    )
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@router.delete("/{vozilo_id}/dijelovi/{zamjena_id}", status_code=204)
def obrisi_zamjenu(
    vozilo_id: int, zamjena_id: int,
    korisnik: Korisnik = Depends(voditelj_ili_radnik), db: Session = Depends(get_db),
):
    z = db.get(ZamjenaDijela, zamjena_id)
    if not z or z.vozilo_id != vozilo_id:
        raise HTTPException(status_code=404, detail="Zapis ne postoji")
    if korisnik.uloga == Uloga.radnik and z.promijenio_id != korisnik.id:
        raise HTTPException(status_code=403, detail="Možete brisati samo svoje unose")
    db.delete(z)
    db.commit()
