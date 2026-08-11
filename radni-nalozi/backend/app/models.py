"""ORM modeli — korisnici, vozila, prijave kvarova, radni nalozi i prateće tablice."""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumeracije
# ---------------------------------------------------------------------------
class Uloga(str, enum.Enum):
    vozac = "vozac"
    voditelj = "voditelj"
    radnik = "radnik"


class Hitnost(str, enum.Enum):
    niska = "niska"
    srednja = "srednja"
    visoka = "visoka"


class StatusPrijave(str, enum.Enum):
    nova = "nova"              # čeka voditelja
    u_obradi = "u_obradi"      # voditelj otvorio nalog iz nje
    zatvorena = "zatvorena"    # odbijena / riješena bez naloga


class Prioritet(str, enum.Enum):
    nizak = "nizak"
    srednji = "srednji"
    visok = "visok"
    hitan = "hitan"


class StatusNaloga(str, enum.Enum):
    otvoren = "otvoren"
    u_radu = "u_radu"
    ceka_dijelove = "ceka_dijelove"
    gotov = "gotov"
    zatvoren = "zatvoren"


class TipFotografije(str, enum.Enum):
    prije = "prije"
    poslije = "poslije"
    ostalo = "ostalo"


# ---------------------------------------------------------------------------
# Poveznica nalog <-> radnik (dodjele)
# ---------------------------------------------------------------------------
class Dodjela(Base):
    __tablename__ = "dodjele"
    __table_args__ = (UniqueConstraint("nalog_id", "radnik_id", name="uq_dodjela"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), index=True)
    radnik_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"), index=True)
    dodijeljeno: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog"] = relationship(back_populates="dodjele")
    radnik: Mapped["Korisnik"] = relationship()


# ---------------------------------------------------------------------------
# Korisnik
# ---------------------------------------------------------------------------
class Korisnik(Base):
    __tablename__ = "korisnici"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ime: Mapped[str] = mapped_column(String(120))
    korisnicko_ime: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    lozinka_hash: Mapped[str] = mapped_column(String(255))
    uloga: Mapped[Uloga] = mapped_column(Enum(Uloga), index=True)
    telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aktivan: Mapped[bool] = mapped_column(Boolean, default=True)
    push_subscription: Mapped[str | None] = mapped_column(Text, nullable=True)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Vozilo (kamion)
# ---------------------------------------------------------------------------
class Vozilo(Base):
    __tablename__ = "vozila"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gb: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # garažni broj
    registracija: Mapped[str | None] = mapped_column(String(40), nullable=True)
    marka: Mapped[str | None] = mapped_column(String(60), nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    aktivan: Mapped[bool] = mapped_column(Boolean, default=True)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Prijava kvara (vozač)
# ---------------------------------------------------------------------------
class Prijava(Base):
    __tablename__ = "prijave"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vozilo_id: Mapped[int] = mapped_column(ForeignKey("vozila.id"), index=True)
    prijavio_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"), index=True)
    opis: Mapped[str] = mapped_column(Text)
    hitnost: Mapped[Hitnost] = mapped_column(Enum(Hitnost), default=Hitnost.srednja)
    status: Mapped[StatusPrijave] = mapped_column(Enum(StatusPrijave), default=StatusPrijave.nova, index=True)
    nalog_id: Mapped[int | None] = mapped_column(ForeignKey("nalozi.id"), nullable=True)
    kreirana: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    vozilo: Mapped["Vozilo"] = relationship()
    prijavio: Mapped["Korisnik"] = relationship()
    fotografije: Mapped[list["Fotografija"]] = relationship(
        back_populates="prijava", cascade="all, delete-orphan",
        primaryjoin="Prijava.id==Fotografija.prijava_id",
    )


# ---------------------------------------------------------------------------
# Radni nalog
# ---------------------------------------------------------------------------
class Nalog(Base):
    __tablename__ = "nalozi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broj: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    vozilo_id: Mapped[int] = mapped_column(ForeignKey("vozila.id"), index=True)
    prijava_id: Mapped[int | None] = mapped_column(ForeignKey("prijave.id"), nullable=True)
    naslov: Mapped[str] = mapped_column(String(200))
    opis: Mapped[str | None] = mapped_column(Text, nullable=True)
    prioritet: Mapped[Prioritet] = mapped_column(Enum(Prioritet), default=Prioritet.srednji, index=True)
    status: Mapped[StatusNaloga] = mapped_column(Enum(StatusNaloga), default=StatusNaloga.otvoren, index=True)
    kreirao_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"))
    vozac_id: Mapped[int | None] = mapped_column(ForeignKey("korisnici.id"), nullable=True)
    voditelj_id: Mapped[int | None] = mapped_column(ForeignKey("korisnici.id"), nullable=True)
    rok: Mapped[date | None] = mapped_column(Date, nullable=True)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    azuriran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    zatvoren: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vozilo: Mapped["Vozilo"] = relationship()
    kreirao: Mapped["Korisnik"] = relationship(foreign_keys=[kreirao_id])
    vozac: Mapped["Korisnik | None"] = relationship(foreign_keys=[vozac_id])
    voditelj: Mapped["Korisnik | None"] = relationship(foreign_keys=[voditelj_id])
    operacije: Mapped[list["Operacija"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan",
        order_by="Operacija.redoslijed",
    )
    dodjele: Mapped[list["Dodjela"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan"
    )
    radni_sati: Mapped[list["RadniSat"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan"
    )
    dijelovi: Mapped[list["Dio"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan"
    )
    fotografije: Mapped[list["Fotografija"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan",
        primaryjoin="Nalog.id==Fotografija.nalog_id",
    )
    povijest: Mapped[list["PovijestStatusa"]] = relationship(
        back_populates="nalog", cascade="all, delete-orphan"
    )

    @property
    def dodijeljeni(self) -> list["Korisnik"]:
        return [d.radnik for d in self.dodjele]


# ---------------------------------------------------------------------------
# Radni sati (mehaničar upisuje utrošeno vrijeme)
# ---------------------------------------------------------------------------
class RadniSat(Base):
    __tablename__ = "radni_sati"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), index=True)
    radnik_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"))
    opis: Mapped[str | None] = mapped_column(Text, nullable=True)
    sati: Mapped[float] = mapped_column(Float)
    datum: Mapped[date] = mapped_column(Date, default=date.today)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog"] = relationship(back_populates="radni_sati")
    radnik: Mapped["Korisnik"] = relationship()


# ---------------------------------------------------------------------------
# Dijelovi (ugrađeni)
# ---------------------------------------------------------------------------
class Dio(Base):
    __tablename__ = "dijelovi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), index=True)
    naziv: Mapped[str] = mapped_column(String(200))
    kolicina: Mapped[float] = mapped_column(Float, default=1)
    jedinica: Mapped[str] = mapped_column(String(20), default="kom")
    cijena: Mapped[float | None] = mapped_column(Float, nullable=True)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog"] = relationship(back_populates="dijelovi")


# ---------------------------------------------------------------------------
# Fotografija (uz prijavu ili nalog)
# ---------------------------------------------------------------------------
class Fotografija(Base):
    __tablename__ = "fotografije"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int | None] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), nullable=True, index=True)
    prijava_id: Mapped[int | None] = mapped_column(ForeignKey("prijave.id", ondelete="CASCADE"), nullable=True, index=True)
    putanja: Mapped[str] = mapped_column(String(300))
    tip: Mapped[TipFotografije] = mapped_column(Enum(TipFotografije), default=TipFotografije.ostalo)
    postavio_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"))
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog | None"] = relationship(
        back_populates="fotografije", primaryjoin="Nalog.id==Fotografija.nalog_id",
    )
    prijava: Mapped["Prijava | None"] = relationship(
        back_populates="fotografije", primaryjoin="Prijava.id==Fotografija.prijava_id",
    )


# ---------------------------------------------------------------------------
# Povijest promjena statusa naloga (audit)
# ---------------------------------------------------------------------------
class PovijestStatusa(Base):
    __tablename__ = "povijest_statusa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), index=True)
    stari_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    novi_status: Mapped[str] = mapped_column(String(30))
    napomena: Mapped[str | None] = mapped_column(Text, nullable=True)
    promijenio_id: Mapped[int] = mapped_column(ForeignKey("korisnici.id"))
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog"] = relationship(back_populates="povijest")
    promijenio: Mapped["Korisnik"] = relationship()


# ---------------------------------------------------------------------------
# Operacija (kategorija posla na nalogu: motor, pneumatika, bojanje…)
# ---------------------------------------------------------------------------
class Operacija(Base):
    __tablename__ = "operacije"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nalog_id: Mapped[int] = mapped_column(ForeignKey("nalozi.id", ondelete="CASCADE"), index=True)
    kategorija: Mapped[str] = mapped_column(String(80))
    redoslijed: Mapped[int] = mapped_column(Integer, default=0)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    nalog: Mapped["Nalog"] = relationship(back_populates="operacije")
    zadaci: Mapped[list["Zadatak"]] = relationship(
        back_populates="operacija", cascade="all, delete-orphan",
        order_by="Zadatak.redoslijed",
    )


# ---------------------------------------------------------------------------
# Zadatak (stavka unutar operacije, s oznakom gotovo)
# ---------------------------------------------------------------------------
class Zadatak(Base):
    __tablename__ = "zadaci"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operacija_id: Mapped[int] = mapped_column(ForeignKey("operacije.id", ondelete="CASCADE"), index=True)
    opis: Mapped[str] = mapped_column(Text)
    gotovo: Mapped[bool] = mapped_column(Boolean, default=False)
    zaduzeni_id: Mapped[int | None] = mapped_column(ForeignKey("korisnici.id"), nullable=True)
    redoslijed: Mapped[int] = mapped_column(Integer, default=0)
    kreiran: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    operacija: Mapped["Operacija"] = relationship(back_populates="zadaci")
    zaduzeni: Mapped["Korisnik | None"] = relationship()
