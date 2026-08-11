"""Pydantic sheme za zahtjeve i odgovore API-ja."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    Hitnost,
    Prioritet,
    StatusNaloga,
    StatusPrijave,
    TipFotografije,
    Uloga,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth --------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    korisnik: "KorisnikOut"


class PromjenaLozinke(BaseModel):
    stara_lozinka: str
    nova_lozinka: str = Field(min_length=4)


# --- Korisnik ----------------------------------------------------------------
class KorisnikBase(BaseModel):
    ime: str
    korisnicko_ime: str
    uloga: Uloga
    telefon: str | None = None


class KorisnikCreate(KorisnikBase):
    lozinka: str = Field(min_length=4)


class KorisnikUpdate(BaseModel):
    ime: str | None = None
    uloga: Uloga | None = None
    telefon: str | None = None
    aktivan: bool | None = None
    lozinka: str | None = Field(default=None, min_length=4)


class KorisnikOut(ORM):
    id: int
    ime: str
    korisnicko_ime: str
    uloga: Uloga
    telefon: str | None = None
    aktivan: bool


# --- Vozilo ------------------------------------------------------------------
class VoziloBase(BaseModel):
    gb: str
    registracija: str | None = None
    marka: str | None = None
    model: str | None = None


class VoziloCreate(VoziloBase):
    pass


class VoziloUpdate(BaseModel):
    gb: str | None = None
    registracija: str | None = None
    marka: str | None = None
    model: str | None = None
    aktivan: bool | None = None


class VoziloOut(ORM):
    id: int
    gb: str
    registracija: str | None = None
    marka: str | None = None
    model: str | None = None
    aktivan: bool


# --- Fotografija -------------------------------------------------------------
class FotografijaOut(ORM):
    id: int
    putanja: str
    tip: TipFotografije
    kreiran: datetime


# --- Prijava -----------------------------------------------------------------
class PrijavaCreate(BaseModel):
    vozilo_id: int
    opis: str
    hitnost: Hitnost = Hitnost.srednja


class PrijavaStatusUpdate(BaseModel):
    status: StatusPrijave


class PrijavaOut(ORM):
    id: int
    vozilo: VoziloOut
    prijavio: KorisnikOut
    opis: str
    hitnost: Hitnost
    status: StatusPrijave
    nalog_id: int | None = None
    kreirana: datetime
    fotografije: list[FotografijaOut] = []


# --- Radni sati / dijelovi ---------------------------------------------------
class RadniSatCreate(BaseModel):
    opis: str | None = None
    sati: float = Field(gt=0)
    datum: date | None = None


class RadniSatOut(ORM):
    id: int
    radnik: KorisnikOut
    opis: str | None = None
    sati: float
    datum: date


class DioCreate(BaseModel):
    naziv: str
    kolicina: float = 1
    jedinica: str = "kom"
    cijena: float | None = None


class DioOut(ORM):
    id: int
    naziv: str
    kolicina: float
    jedinica: str
    cijena: float | None = None


class PovijestOut(ORM):
    id: int
    stari_status: str | None = None
    novi_status: str
    napomena: str | None = None
    promijenio: KorisnikOut
    kreiran: datetime


# --- Nalog -------------------------------------------------------------------
class NalogCreate(BaseModel):
    vozilo_id: int
    naslov: str
    opis: str | None = None
    prioritet: Prioritet = Prioritet.srednji
    rok: date | None = None
    prijava_id: int | None = None
    radnici_ids: list[int] = []


class NalogUpdate(BaseModel):
    naslov: str | None = None
    opis: str | None = None
    prioritet: Prioritet | None = None
    rok: date | None = None


class NalogStatusUpdate(BaseModel):
    status: StatusNaloga
    napomena: str | None = None


class DodjelaUpdate(BaseModel):
    radnici_ids: list[int]


class NalogListItem(ORM):
    id: int
    broj: str
    naslov: str
    prioritet: Prioritet
    status: StatusNaloga
    rok: date | None = None
    vozilo: VoziloOut
    dodijeljeni: list[KorisnikOut] = []
    kreiran: datetime


class NalogOut(ORM):
    id: int
    broj: str
    naslov: str
    opis: str | None = None
    prioritet: Prioritet
    status: StatusNaloga
    rok: date | None = None
    vozilo: VoziloOut
    kreirao: KorisnikOut
    prijava_id: int | None = None
    dodijeljeni: list[KorisnikOut] = []
    radni_sati: list[RadniSatOut] = []
    dijelovi: list[DioOut] = []
    fotografije: list[FotografijaOut] = []
    povijest: list[PovijestOut] = []
    kreiran: datetime
    azuriran: datetime
    zatvoren: datetime | None = None


# --- Push --------------------------------------------------------------------
class PushSubscription(BaseModel):
    subscription: dict


Token.model_rebuild()
