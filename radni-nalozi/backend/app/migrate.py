"""Jednostavne idempotentne migracije — dodaje stupce koji nedostaju.

create_all() stvara nove tablice, ali ne mijenja postojeće. Ovdje dodajemo
nove stupce na tablicu `nalozi` ako još ne postoje (radi na SQLite i Postgresu).
"""
import logging

from sqlalchemy import Engine, text

log = logging.getLogger("migrate")

# (tablica, stupac, SQL tip)
_STUPCI = [
    ("nalozi", "vozac_id", "INTEGER"),
    ("nalozi", "voditelj_id", "INTEGER"),
    ("zadaci", "zaduzeni_id", "INTEGER"),
    ("zadaci", "zapoceto", "TIMESTAMP"),
    ("zadaci", "zavrseno", "TIMESTAMP"),
    ("zadaci", "zavrsio_id", "INTEGER"),
    ("zadaci", "utroseno_sek", "INTEGER DEFAULT 0"),
    ("povijest_rada", "nalog_id", "INTEGER"),
    ("vozila", "slika", "VARCHAR(300)"),
    ("nalozi", "izvan_radione_javljeno", "BOOLEAN DEFAULT FALSE"),
    ("korisnici", "prijavljuje_se", "BOOLEAN DEFAULT TRUE"),
    ("korisnici", "radi_na_nalozima", "BOOLEAN DEFAULT FALSE"),
    ("korisnici", "skupine_poslova", "TEXT"),
    ("korisnici", "odsutnost_vrsta", "VARCHAR(20)"),
    ("korisnici", "odsutnost_od", "DATE"),
    ("korisnici", "odsutnost_do", "DATE"),
    ("nalozi", "parking_obavijest_poslano", "TIMESTAMP"),
    ("nalozi", "parking_zadnji_podsjetnik", "DATE"),
    ("nalozi", "parking_otvoreno", "TIMESTAMP"),
    ("nalozi", "parking_rijeseno", "TIMESTAMP"),
    ("nalozi", "parking_lokacija", "VARCHAR(300)"),
    ("registar_vozila", "rucno", "BOOLEAN DEFAULT FALSE"),
    ("registar_vozila", "mobilisis_status", "VARCHAR(60)"),
    ("registar_vozila", "lokacija", "VARCHAR(300)"),
    ("registar_vozila", "spreman_od", "DATE"),
    ("registar_vozila", "flota_ceka", "BOOLEAN DEFAULT FALSE"),
    ("registar_vozila", "podsjetnik_zadnji", "DATE"),
    ("registar_vozila", "servis_zadnji", "DATE"),
    ("registar_vozila", "servis_prag_km", "INTEGER"),
    ("zaduzenja", "vozac", "VARCHAR(120)"),
    ("registar_vozila", "servis_km", "INTEGER"),
    ("registar_vozila", "km_trenutni", "INTEGER"),
    ("registar_vozila", "km_azuriran", "DATE"),
    ("registar_vozila", "periodicki_datum", "DATE"),
    ("registar_vozila", "periodicki_int", "INTEGER"),
    ("registar_vozila", "taho_datum", "DATE"),
    ("registar_vozila", "taho_int", "INTEGER"),
    ("registar_vozila", "pp_datum", "DATE"),
    ("registar_vozila", "pp_int", "INTEGER"),
    ("registar_vozila", "registracija_istek", "DATE"),
    ("registar_vozila", "periodicki_do", "DATE"),
    ("registar_vozila", "taho_do", "DATE"),
    ("registar_vozila", "pp_do", "DATE"),
    ("zadaci", "prijedlog_radnik_id", "INTEGER"),
    ("zadaci", "prijedlog_odbijeni", "VARCHAR(200)"),
    ("registar_vozila", "vozac", "VARCHAR(120)"),
    ("primke", "fotografije", "JSON"),
    ("primke", "apross_broj", "INTEGER"),
    ("klik_rucno", "voditelj_id", "INTEGER"),
    ("klik_rucno", "opravdano", "BOOLEAN DEFAULT FALSE"),
    ("zadatak_radnik_vrijeme", "gotovo", "BOOLEAN DEFAULT FALSE"),
    ("fotografije", "steta_id", "INTEGER"),
    ("korisnici", "narucitelj", "BOOLEAN DEFAULT FALSE"),
    ("korisnici", "funkcija", "VARCHAR(60)"),
    ("korisnici", "moduli", "JSON"),
    # Matični podaci o vozilu (ručni unos / uvoz iz "GARAŽNI BROJEVI")
    ("registar_vozila", "vrsta", "VARCHAR(40)"),
    ("registar_vozila", "vozilo", "VARCHAR(80)"),
    ("registar_vozila", "prva_registracija", "VARCHAR(10)"),
    ("registar_vozila", "firma", "VARCHAR(60)"),
    ("registar_vozila", "iznos_registracije", "VARCHAR(20)"),
    ("registar_vozila", "norma", "VARCHAR(20)"),
    ("registar_vozila", "broj_sasije", "VARCHAR(40)"),
    ("registar_vozila", "opis", "TEXT"),
    # Plan radione
    ("nalozi", "plan_rang", "INTEGER"),
    ("nalozi", "plan_hitno", "BOOLEAN DEFAULT FALSE"),
    ("nalozi", "prioritet_rang", "INTEGER"),
    ("zadaci", "ceka_potvrdu", "BOOLEAN DEFAULT FALSE"),
    ("zadaci", "razlog_prekida", "VARCHAR(12)"),
    ("zadaci", "prekid_vrijeme", "TIMESTAMP"),
    ("zadaci", "red_ruc", "INTEGER"),
    ("zadaci", "dijelovi_foto", "JSON"),
    # Kraj smjene (pitanje "gotov za danas / ostaješ dulje")
    ("mehanicar_linkovi", "smjena_pitano", "TIMESTAMP"),
    ("mehanicar_linkovi", "smjena_odgovor", "VARCHAR(10)"),
    # Cartec skripta javlja svoju verziju i stanje (dnevnik) — dijagnoza bez AnyDeska
    ("cartec_uredjaji", "verzija", "VARCHAR(20)"),
    ("cartec_uredjaji", "stanje", "TEXT"),
    ("cartec_uredjaji", "stanje_vrijeme", "TIMESTAMP"),
    ("testovi_kocnica", "poveznica", "VARCHAR(40)"),
    ("testovi_kocnica", "rucno_poveznicom", "BOOLEAN DEFAULT FALSE"),
    ("testovi_kocnica", "obavijesteno", "TIMESTAMP"),
    ("cartec_uredjaji", "uzivo", "TEXT"),
    ("nalozi", "valjci", "TIMESTAMP"),
    ("cartec_uredjaji", "uzivo_vrijeme", "TIMESTAMP"),
    # Razduženje kamiona/prikolice (povratni obrazac uz zaduženje)
    ("zaduzenja", "vrsta", "VARCHAR(20) DEFAULT 'zaduzenje'"),
    ("zaduzenja", "zaduzenje_id", "INTEGER"),
]


# Jednokratno, samo u trenutku dodavanja stupca.
_NAKON_DODAVANJA = {
    # Testovi prije obavijesti „kraj testa" su već javljeni — da ne odu ponovno.
    ("testovi_kocnica", "obavijesteno"): "UPDATE testovi_kocnica SET obavijesteno = kreiran",
    # Nalozi koji već imaju izmjeren test s valjaka dobiju oznaku odmah.
    ("nalozi", "valjci"): ("UPDATE nalozi SET valjci = (SELECT MAX(t.kraj) FROM testovi_kocnica t "
                           "WHERE t.nalog_id = nalozi.id AND EXISTS (SELECT 1 FROM mjerenja_osovina m "
                           "WHERE m.test_id = t.id))"),
}


def _postojeci_stupci(conn, tablica: str, dialect: str) -> set[str]:
    if dialect == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info({tablica})").fetchall()
        return {r[1] for r in rows}
    rows = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": tablica},
    ).fetchall()
    return {r[0] for r in rows}


def migrate(engine: Engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for tablica, stupac, tip in _STUPCI:
            postojeci = _postojeci_stupci(conn, tablica, dialect)
            if not postojeci:
                # Tablica ne postoji (npr. create_all je nije stigao stvoriti) — preskoči.
                continue
            if stupac not in postojeci:
                conn.exec_driver_sql(f"ALTER TABLE {tablica} ADD COLUMN {stupac} {tip}")
                log.info("Migracija: dodan stupac %s.%s", tablica, stupac)
                if (tablica, stupac) in _NAKON_DODAVANJA:
                    conn.exec_driver_sql(_NAKON_DODAVANJA[(tablica, stupac)])
    if dialect == "postgresql":
        _dodaj_enum_vrijednosti(engine)


def _dodaj_enum_vrijednosti(engine: Engine) -> None:
    """Postgres: nove vrijednosti enuma (npr. status vozila „u_najmu", #432) moraju se
    dodati i u tip u bazi — create_all postojeći tip ne mijenja. Idempotentno
    (ADD VALUE IF NOT EXISTS), izvan transakcije (AUTOCOMMIT). SQLAlchemy sprema IME člana."""
    from .models import StatusVozila

    tipovi = {"statusvozila": [s.name for s in StatusVozila]}
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for tip, vrijednosti in tipovi.items():
            postoji = conn.execute(
                text("SELECT 1 FROM pg_type WHERE typname = :t"), {"t": tip}
            ).first()
            if not postoji:
                continue
            for v in vrijednosti:
                conn.exec_driver_sql(f"ALTER TYPE {tip} ADD VALUE IF NOT EXISTS '{v}'")
