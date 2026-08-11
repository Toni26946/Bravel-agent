"""Radni nalozi — kreiranje (voditelj), dodjele, statusi, sati, dijelovi, fotografije."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    Dio,
    Dodjela,
    Fotografija,
    Korisnik,
    Nalog,
    Operacija,
    PovijestStatusa,
    Prijava,
    Prioritet,
    RadniSat,
    StatusNaloga,
    StatusPrijave,
    TipFotografije,
    Uloga,
    Vozilo,
    Zadatak,
)
from ..ai import ai_dostupan, parsiraj
from ..push import obavijesti_korisnika, obavijesti_ulogu
from ..schemas import (
    DioCreate,
    DioOut,
    DodjelaUpdate,
    FotografijaOut,
    GlasovniOdgovor,
    GlasovniZahtjev,
    NalogCreate,
    NalogListItem,
    NalogOut,
    NalogStatusUpdate,
    NalogUpdate,
    OperacijaCreate,
    OperacijaOut,
    RadniSatCreate,
    RadniSatOut,
    ZadatakDodaj,
    ZadatakOut,
    ZadatakUpdate,
)
from ..storage import spremi_sliku

router = APIRouter(prefix="/nalozi", tags=["nalozi"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


# --- pomoćne funkcije --------------------------------------------------------
def _sljedeci_broj(db: Session) -> str:
    godina = datetime.now(timezone.utc).year
    prefiks = f"RN-{godina}-"
    n = db.query(Nalog).filter(Nalog.broj.like(f"{prefiks}%")).count()
    return f"{prefiks}{n + 1:04d}"


def _je_dodijeljen(db: Session, nalog_id: int, radnik_id: int) -> bool:
    return (
        db.query(Dodjela)
        .filter(Dodjela.nalog_id == nalog_id, Dodjela.radnik_id == radnik_id)
        .first()
        is not None
    )


def _dohvati_ovlasten(db: Session, nalog_id: int, korisnik: Korisnik) -> Nalog:
    nalog = db.get(Nalog, nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    # Voditelj i radnik (mehaničar) rade na svim nalozima; vozač nema pristup.
    if korisnik.uloga in (Uloga.voditelj, Uloga.radnik):
        return nalog
    raise HTTPException(status_code=403, detail="Nemate ovlasti za ovaj nalog")


def _postavi_dodjele(db: Session, nalog: Nalog, radnici_ids: list[int]) -> None:
    trazeni = set(radnici_ids)
    for rid in trazeni:
        r = db.get(Korisnik, rid)
        if not r or r.uloga != Uloga.radnik:
            raise HTTPException(status_code=400, detail=f"Korisnik {rid} nije radnik")
    postojeci = {d.radnik_id: d for d in nalog.dodjele}
    # dodaj nove
    for rid in trazeni - set(postojeci):
        db.add(Dodjela(nalog_id=nalog.id, radnik_id=rid))
    # ukloni maknute
    for rid, d in postojeci.items():
        if rid not in trazeni:
            db.delete(d)


# --- AI glasovni unos --------------------------------------------------------
@router.post("/glasovni-parse", response_model=GlasovniOdgovor)
def glasovni_parse(z: GlasovniZahtjev, _: Korisnik = Depends(samo_voditelj)):
    if not ai_dostupan():
        raise HTTPException(status_code=503, detail="Glasovni unos nije konfiguriran (nedostaje ANTHROPIC_API_KEY).")
    if not z.tekst.strip():
        raise HTTPException(status_code=400, detail="Nema izgovorenog teksta.")
    try:
        podaci = parsiraj(z.tekst, z.kategorije, z.voditelji, z.vozaci)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI nije uspio obraditi govor: {e}")
    operacije = [
        {"kategorija": (o.get("kategorija") or "").strip(),
         "zadaci": [t.strip() for t in (o.get("zadaci") or []) if t and t.strip()]}
        for o in (podaci.get("operacije") or [])
        if (o.get("kategorija") or "").strip()
    ]
    return GlasovniOdgovor(
        vozilo_gb=podaci.get("vozilo_gb") or None,
        voditelj=podaci.get("voditelj") or None,
        vozac=podaci.get("vozac") or None,
        operacije=operacije,
    )


# --- popis / detalj ----------------------------------------------------------
@router.get("", response_model=list[NalogListItem])
def popis(
    status: StatusNaloga | None = Query(default=None),
    korisnik: Korisnik = Depends(trenutni_korisnik),
    db: Session = Depends(get_db),
):
    if korisnik.uloga == Uloga.vozac:
        raise HTTPException(status_code=403, detail="Vozači nemaju pristup nalozima")
    q = db.query(Nalog)  # voditelj i radnik vide sve naloge
    if status:
        q = q.filter(Nalog.status == status)
    return q.order_by(Nalog.kreiran.desc()).all()


@router.get("/{nalog_id}", response_model=NalogOut)
def detalj(nalog_id: int, korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    return _dohvati_ovlasten(db, nalog_id, korisnik)


# --- kreiranje (voditelj) ----------------------------------------------------
@router.post("", response_model=NalogOut, status_code=201)
def kreiraj(podaci: NalogCreate, voditelj: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    vozilo = db.get(Vozilo, podaci.vozilo_id)
    if not vozilo:
        raise HTTPException(status_code=404, detail="Vozilo (kamion) ne postoji")

    odabrani_voditelj = db.get(Korisnik, podaci.voditelj_id)
    if not odabrani_voditelj or odabrani_voditelj.uloga != Uloga.voditelj:
        raise HTTPException(status_code=400, detail="Odabrani voditelj nije valjan")

    if podaci.vozac_id is not None:
        vozac = db.get(Korisnik, podaci.vozac_id)
        if not vozac or vozac.uloga != Uloga.vozac:
            raise HTTPException(status_code=400, detail="Odabrani vozač nije valjan")

    prijava = None
    if podaci.prijava_id:
        prijava = db.get(Prijava, podaci.prijava_id)
        if not prijava:
            raise HTTPException(status_code=404, detail="Prijava ne postoji")

    nalog = Nalog(
        broj=_sljedeci_broj(db),
        vozilo_id=podaci.vozilo_id,
        prijava_id=podaci.prijava_id,
        naslov=(podaci.naslov or "").strip() or f"Servis {vozilo.gb}",
        opis=podaci.opis,
        prioritet=podaci.prioritet,
        rok=podaci.rok,
        kreirao_id=voditelj.id,
        voditelj_id=podaci.voditelj_id,
        vozac_id=podaci.vozac_id,
    )
    db.add(nalog)
    db.flush()
    _postavi_dodjele(db, nalog, podaci.radnici_ids)
    # Operacije (kategorije) i zadaci
    for i, op in enumerate(podaci.operacije):
        operacija = Operacija(nalog_id=nalog.id, kategorija=op.kategorija.strip(), redoslijed=i)
        db.add(operacija)
        db.flush()
        for j, opis in enumerate(op.zadaci):
            if opis.strip():
                db.add(Zadatak(operacija_id=operacija.id, opis=opis.strip(), redoslijed=j))
    db.add(PovijestStatusa(
        nalog_id=nalog.id, stari_status=None, novi_status=StatusNaloga.otvoren.value,
        napomena="Nalog kreiran", promijenio_id=voditelj.id,
    ))
    if prijava:
        prijava.status = StatusPrijave.u_obradi
        prijava.nalog_id = nalog.id
    db.commit()
    db.refresh(nalog)
    obavijesti_ulogu(
        db, Uloga.radnik, "Novi radni nalog",
        f"{nalog.broj}: {vozilo.gb} — {nalog.naslov}", url=f"/nalozi/{nalog.id}",
    )
    return nalog


# --- uređivanje osnovnih polja (voditelj) ------------------------------------
@router.patch("/{nalog_id}", response_model=NalogOut)
def azuriraj(
    nalog_id: int, podaci: NalogUpdate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)
):
    nalog = db.get(Nalog, nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    for polje, vrijednost in podaci.model_dump(exclude_unset=True).items():
        setattr(nalog, polje, vrijednost)
    db.commit()
    db.refresh(nalog)
    return nalog


@router.delete("/{nalog_id}", status_code=204)
def obrisi_nalog(nalog_id: int, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    nalog = db.get(Nalog, nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    # Ako je nalog nastao iz prijave kvara, odveži je i vrati na "nova"
    if nalog.prijava_id:
        prijava = db.get(Prijava, nalog.prijava_id)
        if prijava and prijava.nalog_id == nalog.id:
            prijava.nalog_id = None
            prijava.status = StatusPrijave.nova
    db.delete(nalog)  # kaskadno briše operacije, zadatke, sate, dijelove, povijest, dodjele
    db.commit()


# --- dodjele (voditelj) ------------------------------------------------------
@router.put("/{nalog_id}/dodjele", response_model=NalogOut)
def azuriraj_dodjele(
    nalog_id: int, podaci: DodjelaUpdate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)
):
    nalog = db.get(Nalog, nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    stari = {d.radnik_id for d in nalog.dodjele}
    _postavi_dodjele(db, nalog, podaci.radnici_ids)
    db.commit()
    db.refresh(nalog)
    for rid in set(podaci.radnici_ids) - stari:
        obavijesti_korisnika(
            db, rid, "Dodijeljen vam je nalog",
            f"{nalog.broj}: {nalog.naslov}", url=f"/nalozi/{nalog.id}",
        )
    return nalog


# --- promjena statusa (voditelj ili dodijeljeni radnik) ----------------------
@router.patch("/{nalog_id}/status", response_model=NalogOut)
def promijeni_status(
    nalog_id: int, podaci: NalogStatusUpdate,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    nalog = _dohvati_ovlasten(db, nalog_id, korisnik)
    stari = nalog.status
    if stari == podaci.status:
        return nalog
    nalog.status = podaci.status
    if podaci.status in (StatusNaloga.gotov, StatusNaloga.zatvoren):
        nalog.zatvoren = datetime.now(timezone.utc)
    else:
        nalog.zatvoren = None
    db.add(PovijestStatusa(
        nalog_id=nalog.id, stari_status=stari.value, novi_status=podaci.status.value,
        napomena=podaci.napomena, promijenio_id=korisnik.id,
    ))
    db.commit()
    db.refresh(nalog)
    # Obavijesti voditelje kad radnik završi
    if korisnik.uloga == Uloga.radnik and podaci.status == StatusNaloga.gotov:
        obavijesti_ulogu(
            db, Uloga.voditelj, "Nalog završen",
            f"{nalog.broj} — {korisnik.ime} označio gotovo", url=f"/nalozi/{nalog.id}",
        )
    return nalog


# --- radni sati --------------------------------------------------------------
@router.post("/{nalog_id}/sati", response_model=RadniSatOut, status_code=201)
def dodaj_sate(
    nalog_id: int, podaci: RadniSatCreate,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    rs = RadniSat(
        nalog_id=nalog_id, radnik_id=korisnik.id, opis=podaci.opis,
        sati=podaci.sati, datum=podaci.datum or date.today(),
    )
    db.add(rs)
    db.commit()
    db.refresh(rs)
    return rs


@router.delete("/{nalog_id}/sati/{sat_id}", status_code=204)
def obrisi_sat(
    nalog_id: int, sat_id: int,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    rs = db.get(RadniSat, sat_id)
    if not rs or rs.nalog_id != nalog_id:
        raise HTTPException(status_code=404, detail="Zapis ne postoji")
    if korisnik.uloga == Uloga.radnik and rs.radnik_id != korisnik.id:
        raise HTTPException(status_code=403, detail="Možete brisati samo svoje unose")
    db.delete(rs)
    db.commit()


# --- dijelovi ----------------------------------------------------------------
@router.post("/{nalog_id}/dijelovi", response_model=DioOut, status_code=201)
def dodaj_dio(
    nalog_id: int, podaci: DioCreate,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    d = Dio(nalog_id=nalog_id, **podaci.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@router.delete("/{nalog_id}/dijelovi/{dio_id}", status_code=204)
def obrisi_dio(
    nalog_id: int, dio_id: int,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    d = db.get(Dio, dio_id)
    if not d or d.nalog_id != nalog_id:
        raise HTTPException(status_code=404, detail="Dio ne postoji")
    db.delete(d)
    db.commit()


# --- fotografije -------------------------------------------------------------
@router.post("/{nalog_id}/fotografije", response_model=FotografijaOut, status_code=201)
def dodaj_foto(
    nalog_id: int,
    tip: TipFotografije = Form(TipFotografije.ostalo),
    slika: UploadFile = File(...),
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    putanja = spremi_sliku(slika)
    f = Fotografija(nalog_id=nalog_id, putanja=putanja, tip=tip, postavio_id=korisnik.id)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


# --- operacije (kategorije) --------------------------------------------------
@router.post("/{nalog_id}/operacije", response_model=OperacijaOut, status_code=201)
def dodaj_operaciju(
    nalog_id: int, podaci: OperacijaCreate,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    nalog = _dohvati_ovlasten(db, nalog_id, korisnik)
    redoslijed = len(nalog.operacije)
    op = Operacija(nalog_id=nalog_id, kategorija=podaci.kategorija.strip(), redoslijed=redoslijed)
    db.add(op)
    db.flush()
    for j, opis in enumerate(podaci.zadaci):
        if opis.strip():
            db.add(Zadatak(operacija_id=op.id, opis=opis.strip(), redoslijed=j))
    db.commit()
    db.refresh(op)
    return op


@router.delete("/{nalog_id}/operacije/{op_id}", status_code=204)
def obrisi_operaciju(
    nalog_id: int, op_id: int,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    op = db.get(Operacija, op_id)
    if not op or op.nalog_id != nalog_id:
        raise HTTPException(status_code=404, detail="Operacija ne postoji")
    db.delete(op)
    db.commit()


# --- zadaci ------------------------------------------------------------------
def _dohvati_zadatak(db: Session, nalog_id: int, zadatak_id: int) -> Zadatak:
    z = db.get(Zadatak, zadatak_id)
    if not z or z.operacija.nalog_id != nalog_id:
        raise HTTPException(status_code=404, detail="Zadatak ne postoji")
    return z


def _provjeri_radnik(db: Session, rid: int) -> None:
    r = db.get(Korisnik, rid)
    if not r or r.uloga != Uloga.radnik:
        raise HTTPException(status_code=400, detail="Zaduženi nije valjan mehaničar")


@router.post("/{nalog_id}/operacije/{op_id}/zadaci", response_model=ZadatakOut, status_code=201)
def dodaj_zadatak(
    nalog_id: int, op_id: int, podaci: ZadatakDodaj,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    op = db.get(Operacija, op_id)
    if not op or op.nalog_id != nalog_id:
        raise HTTPException(status_code=404, detail="Operacija ne postoji")
    if podaci.zaduzeni_id is not None:
        _provjeri_radnik(db, podaci.zaduzeni_id)
    z = Zadatak(
        operacija_id=op_id, opis=podaci.opis.strip(),
        zaduzeni_id=podaci.zaduzeni_id, redoslijed=len(op.zadaci),
    )
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@router.patch("/{nalog_id}/zadaci/{zadatak_id}", response_model=ZadatakOut)
def azuriraj_zadatak(
    nalog_id: int, zadatak_id: int, podaci: ZadatakUpdate,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    z = _dohvati_zadatak(db, nalog_id, zadatak_id)
    if podaci.opis is not None:
        z.opis = podaci.opis.strip()
    if podaci.gotovo is not None:
        z.gotovo = podaci.gotovo
    if "zaduzeni_id" in podaci.model_fields_set:
        if podaci.zaduzeni_id is not None:
            _provjeri_radnik(db, podaci.zaduzeni_id)
        z.zaduzeni_id = podaci.zaduzeni_id
    db.commit()
    db.refresh(z)
    return z


@router.delete("/{nalog_id}/zadaci/{zadatak_id}", status_code=204)
def obrisi_zadatak(
    nalog_id: int, zadatak_id: int,
    korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db),
):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    z = _dohvati_zadatak(db, nalog_id, zadatak_id)
    db.delete(z)
    db.commit()
