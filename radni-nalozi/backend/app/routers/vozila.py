"""Vozila (kamioni). Svi prijavljeni mogu vidjeti; uređuje samo voditelj."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import re

from ..storage import obrisi_sliku, spremi_sliku

from .. import flota
from ..config import settings
from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    DnevnikPrikapcanja,
    Korisnik,
    Nalog,
    Parking,
    PovijestRada,
    RegistarVozila,
    StatusNaloga,
    StatusVozila,
    Uloga,
    Vozilo,
    VrstaDogadaja,
    ZamjenaDijela,
)
from ..schemas import (
    DogadajCreate,
    DogadajOut,
    ParkingCreate,
    ParkingOut,
    PovijestRadaOut,
    RegistarStatusUpdate,
    RegistarVozilaOut,
    ServisKmUvozStavka,
    ServisUpdate,
    ServisUvozStavka,
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


def _prikolice_na_kamionu(db: Session, kamion_gb: str) -> list[str]:
    """GB-ovi prikolica čiji je ZADNJI događaj 'prikaceno' na dani kamion.

    Kamion normalno vuče jednu prikolicu; ovo služi da pri novom prikačivanju
    automatski otkačimo prethodnu prikolicu tog kamiona."""
    svi = (
        db.query(DnevnikPrikapcanja)
        .order_by(
            DnevnikPrikapcanja.prikolica_gb,
            DnevnikPrikapcanja.vrijeme.desc(),
            DnevnikPrikapcanja.id.desc(),
        )
        .all()
    )
    zadnji: dict = {}
    for e in svi:
        zadnji.setdefault(e.prikolica_gb, e)
    return [
        p for p, e in zadnji.items()
        if e.vrsta == VrstaDogadaja.prikaceno and (e.kamion_gb or "") == kamion_gb
    ]


@router.post("/prikapcanje", response_model=DogadajOut, status_code=201)
def dodaj_dogadaj(
    podaci: DogadajCreate,
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db),
):
    """Zabilježi događaj prikačenja/otkačenja prikolice (naš dnevnik = evidencija).

    Kad se prikolica PRIKAČI na kamion, automatski se otkači prethodna prikolica
    tog kamiona (kamion vuče samo jednu)."""
    gb = (podaci.prikolica_gb or "").strip()
    if not gb:
        raise HTTPException(status_code=400, detail="Garažni broj prikolice je obavezan")
    try:
        vrsta = VrstaDogadaja(podaci.vrsta)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nepoznata vrsta događaja")
    kamion = (podaci.kamion_gb or "").strip() or None

    # Auto-otkači prethodnu prikolicu tog kamiona (osim ako je to baš ova).
    if vrsta == VrstaDogadaja.prikaceno and kamion:
        for stara in _prikolice_na_kamionu(db, kamion):
            if stara != gb:
                db.add(DnevnikPrikapcanja(
                    prikolica_gb=stara,
                    kamion_gb=kamion,
                    vrsta=VrstaDogadaja.otkaceno,
                    kreirao_id=korisnik.id,
                    napomena=f"Automatski otkačeno — kamion {kamion} preuzeo prikolicu {gb}",
                ))

    d = DnevnikPrikapcanja(
        prikolica_gb=gb,
        kamion_gb=kamion,
        vozac=(podaci.vozac or "").strip() or None,
        vrsta=vrsta,
        lokacija=(podaci.lokacija or "").strip() or None,
        napomena=(podaci.napomena or "").strip() or None,
        kreirao_id=korisnik.id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@router.get("/prikapcanje", response_model=list[DogadajOut])
def dnevnik(
    gb: str | None = None, vrsta: str | None = None, dana: int = 90, limit: int = 500,
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db),
):
    """Dnevnik prikapčanja/otkapčanja (evidencija) — najnoviji prvi. Filtri gb/vrsta/dana."""
    q = db.query(DnevnikPrikapcanja)
    if gb:
        g = gb.strip()
        q = q.filter((DnevnikPrikapcanja.prikolica_gb == g) | (DnevnikPrikapcanja.kamion_gb == g))
    if vrsta:
        try:
            q = q.filter(DnevnikPrikapcanja.vrsta == VrstaDogadaja(vrsta))
        except ValueError:
            raise HTTPException(status_code=400, detail="Nepoznata vrsta")
    if dana and dana > 0:
        granica = datetime.now(timezone.utc) - timedelta(days=dana)
        q = q.filter(DnevnikPrikapcanja.vrijeme >= granica)
    return q.order_by(DnevnikPrikapcanja.vrijeme.desc(), DnevnikPrikapcanja.id.desc()).limit(min(limit, 2000)).all()


@router.get("/prikapcanje/trenutno")
def prikapcanje_trenutno(
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db),
):
    """Trenutno stanje — tko vozi koju prikolicu.

    Za svaku prikolicu gleda ZADNJI događaj; vraća samo one čiji je zadnji
    događaj `prikaceno` (dakle još prikačene). Obogaćeno reg/tip iz matičnog popisa."""
    svi = (
        db.query(DnevnikPrikapcanja)
        .order_by(
            DnevnikPrikapcanja.prikolica_gb,
            DnevnikPrikapcanja.vrijeme.desc(),
            DnevnikPrikapcanja.id.desc(),
        )
        .all()
    )
    zadnji: dict = {}
    for d in svi:
        zadnji.setdefault(d.prikolica_gb, d)  # prvi viđeni = najnoviji (zbog poretka)
    aktivni = [d for d in zadnji.values() if d.vrsta == VrstaDogadaja.prikaceno]
    regmap = {r.gb: r for r in db.query(RegistarVozila).all()}
    out = []
    for d in aktivni:
        r = regmap.get(d.prikolica_gb)
        rk = regmap.get(d.kamion_gb) if d.kamion_gb else None
        out.append({
            "prikolica_gb": d.prikolica_gb,
            "reg": r.registracija if r else None,
            "tip": r.tip if r else None,
            "kamion_gb": d.kamion_gb,
            "kamion_reg": rk.registracija if rk else None,
            "vozac": d.vozac,
            "vrijeme": d.vrijeme,
        })
    def _num(g):
        try:
            return (0, int(g))
        except (TypeError, ValueError):
            return (1, 0)
    # Poredaj po kamionu (koji vuče) pa po prikolici.
    out.sort(key=lambda x: (_num(x["kamion_gb"]), _num(x["prikolica_gb"])))
    return out


# --- Servisi (rok idućeg servisa: vrijeme sad, km u Fazi 2) -------------------
def _servis_prag(tip: str | None) -> int:
    """Pretpostavljeni prag km do servisa po tipu vozila."""
    t = (tip or "").lower()
    if "dizal" in t or "šumar" in t or "sumar" in t:
        return 40000  # šumari / dizaličari
    return 45000      # tegljači (serija 75k = ručna iznimka)


def _plus_12m(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29.2.
        return d.replace(year=d.year + 1, day=28)


_KM_USKORO = 3000  # km: koliko prije praga se pali "uskoro"
_RANG = {"dospjelo": 0, "nepoznato": 1, "uskoro": 2, "ok": 3}


def _status_vrijeme(preostalo: int | None, ima_datum: bool) -> str:
    if not ima_datum:
        return "nepoznato"
    if preostalo is not None and preostalo <= 0:
        return "dospjelo"
    if preostalo is not None and preostalo <= 30:
        return "uskoro"
    return "ok"


def _status_km(km_preostalo: int | None) -> str:
    if km_preostalo is None:
        return "nepoznato"
    if km_preostalo <= 0:
        return "dospjelo"
    if km_preostalo <= _KM_USKORO:
        return "uskoro"
    return "ok"


@router.get("/servisi")
def servisi(korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db)):
    """Pregled servisa po kamionu: zadnji servis, idući rok po vremenu (12 mj) I po km.

    Uvjeti (servis kad istekne PRVI): vrijeme = zadnji + 12 mj; km = prag − (km_sad − km_na_servisu).
    Ukupni status je najhitniji od poznatih (vrijeme/km); 'nepoznato' ako nijedan nije poznat."""
    danas = date.today()
    redovi = (
        db.query(RegistarVozila)
        .filter(RegistarVozila.kategorija == "kamion")
        .all()
    )
    out = []
    for r in redovi:
        prag = r.servis_prag_km or _servis_prag(r.tip)
        zadnji = r.servis_zadnji
        iduci = _plus_12m(zadnji) if zadnji else None
        preostalo = (iduci - danas).days if iduci else None
        st_vrijeme = _status_vrijeme(preostalo, zadnji is not None)

        # Km uvjet (Faza 2)
        km_proslo = None
        km_preostalo = None
        if r.servis_km is not None and r.km_trenutni is not None:
            km_proslo = max(0, r.km_trenutni - r.servis_km)
            km_preostalo = prag - km_proslo
        st_km = _status_km(km_preostalo)

        # Ukupni status = najhitniji od poznatih uvjeta
        poznati = [s for s in (st_vrijeme, st_km) if s != "nepoznato"]
        status = min(poznati, key=lambda s: _RANG[s]) if poznati else "nepoznato"

        out.append({
            "gb": r.gb, "reg": r.registracija, "tip": r.tip,
            "servis_zadnji": zadnji.isoformat() if zadnji else None,
            "prag_km": prag,
            "iduci_datum": iduci.isoformat() if iduci else None,
            "preostalo_dana": preostalo,
            "status_vrijeme": st_vrijeme,
            "servis_km": r.servis_km,
            "km_trenutni": r.km_trenutni,
            "km_azuriran": r.km_azuriran.isoformat() if r.km_azuriran else None,
            "km_proslo": km_proslo,
            "km_preostalo": km_preostalo,
            "status_km": st_km,
            "status": status,
        })
    # Poredak: dospjelo prvo, pa nepoznato, uskoro, ok; sekundarno po preostalo (vrijeme/km).
    def _sec(x):
        kandidati = [v for v in (x["preostalo_dana"], x["km_preostalo"]) if v is not None]
        return min(kandidati) if kandidati else 10**9
    out.sort(key=lambda x: (_RANG.get(x["status"], 9), _sec(x)))
    return out


@router.post("/servisi/uvoz")
def servisi_uvoz(
    stavke: list[ServisUvozStavka],
    _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db),
):
    """Uvezi datume zadnjeg servisa (iz razduženja dijelova). Postavlja i prag po tipu ako fali."""
    n = 0
    for s in stavke:
        gb = (s.gb or "").strip()
        if not gb:
            continue
        r = db.get(RegistarVozila, gb)
        if r is None:
            r = RegistarVozila(gb=gb)
            db.add(r)
        r.servis_zadnji = s.datum
        if not r.servis_prag_km:
            r.servis_prag_km = _servis_prag(r.tip)
        n += 1
    db.commit()
    return {"uvezeno": n}


@router.post("/servisi/km-uvoz")
def servisi_km_uvoz(
    stavke: list[ServisKmUvozStavka],
    _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db),
):
    """Uvezi km podatke iz Mobilisisa (Popis vožnji): trenutni brojčanik i,
    ako je poznato, brojčanik na datum zadnjeg servisa."""
    n = 0
    for s in stavke:
        gb = (s.gb or "").strip()
        if not gb:
            continue
        r = db.get(RegistarVozila, gb)
        if r is None:
            r = RegistarVozila(gb=gb)
            db.add(r)
        if s.km_trenutni is not None:
            r.km_trenutni = s.km_trenutni
        if s.km_azuriran is not None:
            r.km_azuriran = s.km_azuriran
        if s.servis_km is not None:
            r.servis_km = s.servis_km
        if not r.servis_prag_km:
            r.servis_prag_km = _servis_prag(r.tip)
        n += 1
    db.commit()
    return {"uvezeno": n}


@router.patch("/servisi/{gb}")
def servisi_uredi(
    gb: str, podaci: ServisUpdate,
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db),
):
    """Ručno postavi datum zadnjeg servisa (i/ili prag km) za kamion."""
    r = db.get(RegistarVozila, gb)
    if r is None:
        r = RegistarVozila(gb=gb)
        db.add(r)
    if podaci.servis_zadnji is not None:
        r.servis_zadnji = podaci.servis_zadnji
    if podaci.servis_prag_km is not None:
        r.servis_prag_km = podaci.servis_prag_km
    if not r.servis_prag_km:
        r.servis_prag_km = _servis_prag(r.tip)
    r.azurirao_id = korisnik.id
    db.commit()
    return {"ok": True}


@router.get("/parkinzi", response_model=list[ParkingOut])
def parkinzi(korisnik: Korisnik = Depends(voditelj_ili_poslovodja), db: Session = Depends(get_db)):
    """Fiksni popis parkinga (aktivni) — za odabir lokacije spremne šlepe."""
    return db.query(Parking).filter(Parking.aktivan.is_(True)).order_by(Parking.naziv).all()


@router.post("/parkinzi", response_model=ParkingOut, status_code=201)
def dodaj_parking(podaci: ParkingCreate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    naziv = (podaci.naziv or "").strip()
    if not naziv:
        raise HTTPException(status_code=400, detail="Naziv parkinga je obavezan")
    p = db.query(Parking).filter(Parking.naziv == naziv).first()
    if p:
        if not p.aktivan:
            p.aktivan = True
            db.commit(); db.refresh(p)
        return p
    p = Parking(naziv=naziv)
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.delete("/parkinzi/{parking_id}", status_code=204)
def obrisi_parking(parking_id: int, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    p = db.get(Parking, parking_id)
    if p:
        p.aktivan = False  # deaktiviraj (ne briši — povijest lokacija ostaje smislena)
        db.commit()


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
            # Spremna (popravljena, na parkingu) = otkačena/slobodna → zabilježi u dnevnik.
            db.add(DnevnikPrikapcanja(
                prikolica_gb=r.gb, vrsta=VrstaDogadaja.otkaceno,
                lokacija=lok_nova.strip() or None, kreirao_id=korisnik.id,
                napomena="Spremno (radionica)",
            ))
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
