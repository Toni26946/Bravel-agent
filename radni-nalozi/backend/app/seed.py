"""Početni podaci — kreira prvog voditelja ako u bazi nema nijednog korisnika."""
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from .auth import hash_lozinka
from .config import settings
from .models import Korisnik, PovijestRada, Uloga, Vozilo, Zadatak

log = logging.getLogger("seed")

_DATA_DIR = Path(__file__).resolve().parent / "data"


def seed(db: Session) -> None:
    if db.query(Korisnik).count() > 0:
        return
    voditelj = Korisnik(
        ime=settings.seed_admin_ime,
        korisnicko_ime=settings.seed_admin_username,
        lozinka_hash=hash_lozinka(settings.seed_admin_password),
        uloga=Uloga.voditelj,
    )
    db.add(voditelj)
    db.commit()
    log.info(
        "Kreiran početni voditelj '%s' (promijenite lozinku nakon prve prijave).",
        settings.seed_admin_username,
    )


# --- Jednokratni uvoz radnika radione (popis iz kolovoza 2026.) --------------
_ASCII = str.maketrans({
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d",
    "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d",
})

RADNICI_POCETNI = [
    "Kobeščak Davor", "Habijanec Pejković Marina", "Azinović Mario", "Karthik Raju",
    "Svečnjak Alen", "Kahlina Igor", "Baček Matija", "Poslon Božidar", "Kuzmić Zlatko",
    "Hasan Matija", "Pavliukh Vasyl", "Baranov Gennadiy", "Borovyk Yevhen",
    "Liushnenko Miykhailo", "Serniak Ivan", "Elson Jacob", "Konathukatiil Akshay",
    "Ankudy Midhun Hari", "Antony Jeffin", "Gmitrović Miloš", "Balaško Florijan",
    "Jambrač Brigita", "Ronquillo Rickey", "Kovačević Dario", "Dominik Bahal", "Sergej Haver",
]


def _slug(ime: str) -> str:
    baza = ime.translate(_ASCII).lower()
    rijeci = ["".join(c for c in r if c.isalnum()) for r in baza.split()]
    return ".".join(r for r in rijeci if r) or "radnik"


def uvezi_povijest_rada(db: Session) -> None:
    """Jednokratni uvoz servisne povijesti iz app/data/povijest_rada.json.

    Za svaki zapis nađe (ili kreira) vozilo po garažnom broju i doda stavku
    povijesti. Idempotentno preko zastavice na trajnom volumenu — ako se popis
    kasnije nadopuni (npr. i opisima), povećaj verziju zastavice.
    """
    zastavica = Path(settings.upload_dir).parent / ".povijest_rada_v2"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    put = _DATA_DIR / "povijest_rada.json"
    if not put.exists():
        return
    try:
        zapisi = json.loads(put.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # noqa: BLE001
        log.warning("Ne mogu učitati povijest_rada.json: %s", e)
        return
    # Zamijeni eventualni raniji (v1) uvoz punim podacima.
    db.query(PovijestRada).delete()
    db.flush()
    # keš vozila po GB-u (kreiraj koji nedostaju)
    vozila = {v.gb: v for v in db.query(Vozilo).all()}
    dodano = 0
    for z in zapisi:
        gb = str(z.get("gb", "")).strip()
        if not gb:
            continue
        voz = vozila.get(gb)
        if voz is None:
            voz = Vozilo(gb=gb)
            db.add(voz)
            db.flush()
            vozila[gb] = voz
        try:
            g, m, d = z["datum"].split("-")
            dat = date(int(g), int(m), int(d))
        except (KeyError, ValueError):
            continue
        db.add(PovijestRada(
            vozilo_id=voz.id, datum=dat,
            radnik=(z.get("radnik") or None),
            operacija=(z.get("operacija") or None),
            opis=(z.get("opis") or None),
            minute=z.get("minute"),
            izvor="evidencija",
        ))
        dodano += 1
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Uvezeno %d zapisa servisne povijesti (%d vozila).", dodano, len(vozila))


def _tokeni(ime: str) -> set[str]:
    return {t for t in ime.translate(_ASCII).lower().replace(".", " ").split() if t}


# (ime za prikaz/kreiranje, tokeni za pronalazak postojećeg, korisničko ime, lozinka, uloga)
_BATCH_KORISNICI = [
    ("Mario Azinović", {"mario", "azinovic"}, "mario.azinovic", "Mario7391", Uloga.radnik),
    ("Davor Kobeščak", {"davor", "kobescak"}, "davor.kobescak", "Davor2648", Uloga.radnik),
    ("Velimir Jendriš", {"velimir", "jendris"}, "velimir.jendris", "Velimir5093", Uloga.voditelj),
    ("Dominik Bahal", {"dominik", "bahal"}, "dominik.bahal", "Dominik4157", Uloga.radnik),
    ("Akshay", {"akshay"}, "akshay", "Akshay8264", Uloga.radnik),
]


def osiguraj_dodatne_korisnike(db: Session) -> None:
    """Jednokratno kreira/ažurira ručno zadane račune (korisničko ime + lozinka).

    Ako osoba već postoji (podudaranje po tokenima imena) — postavi joj čisto
    korisničko ime i novu lozinku te je aktivira; inače kreira novi račun.
    Guardano zastavicom na trajnom volumenu.
    """
    zastavica = Path(settings.upload_dir).parent / ".korisnici_batch_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    svi = db.query(Korisnik).all()
    zauzeta = {k.korisnicko_ime for k in svi}
    for ime, tset, kor, lozinka, uloga in _BATCH_KORISNICI:
        postoji = next((k for k in svi if tset and tset <= _tokeni(k.ime)), None)
        h = hash_lozinka(lozinka)
        if postoji:
            # postavi čisto korisničko ime ako je slobodno (ili već njegovo)
            if kor == postoji.korisnicko_ime or kor not in zauzeta:
                zauzeta.discard(postoji.korisnicko_ime)
                postoji.korisnicko_ime = kor
                zauzeta.add(kor)
            postoji.lozinka_hash = h
            postoji.aktivan = True
        else:
            ime_kor = kor
            i = 1
            while ime_kor in zauzeta:
                i += 1
                ime_kor = f"{kor}{i}"
            zauzeta.add(ime_kor)
            novi = Korisnik(ime=ime, korisnicko_ime=ime_kor, lozinka_hash=h, uloga=uloga, aktivan=True)
            db.add(novi)
            svi.append(novi)
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Batch korisnika obrađen (%d).", len(_BATCH_KORISNICI))


def jednokratna_reaktivacija_roka(db: Session) -> None:
    """Jednokratno ponovno aktivira račun 'Roko Jendriš' (slučajno deaktiviran).

    Traži po imenu/korisničkom imenu koje sadrži 'roko' i 'jendris' (bez kvačica).
    Guardano zastavicom na trajnom volumenu da se izvrši samo jednom.
    """
    zastavica = Path(settings.upload_dir).parent / ".reaktivacija_roko_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    reaktivirano = 0
    for k in db.query(Korisnik).all():
        tekst = f"{k.ime} {k.korisnicko_ime}".translate(_ASCII).lower()
        if "roko" in tekst and "jendris" in tekst and not k.aktivan:
            k.aktivan = True
            reaktivirano += 1
    if reaktivirano:
        db.commit()
        log.warning("Jednokratno reaktiviran račun Roko Jendriš (%d).", reaktivirano)
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


def osiguraj_aktivnog_voditelja(db: Session) -> None:
    """Sigurnosna mreža protiv zaključavanja portala.

    Ako nijedan voditelj nije aktivan (npr. slučajno deaktiviran zadnji), ponovno
    aktivira sve voditelje kako bi se barem netko mogao prijaviti. Ne dira ništa
    dok postoji barem jedan aktivan voditelj, pa ne smeta namjernim deaktivacijama.
    """
    ima_aktivnog = (
        db.query(Korisnik)
        .filter(Korisnik.uloga == Uloga.voditelj, Korisnik.aktivan.is_(True))
        .count()
        > 0
    )
    if ima_aktivnog:
        return
    voditelji = db.query(Korisnik).filter(Korisnik.uloga == Uloga.voditelj).all()
    for v in voditelji:
        v.aktivan = True
    if voditelji:
        db.commit()
        log.warning(
            "Nije bilo nijednog aktivnog voditelja — reaktivirano %d (%s).",
            len(voditelji), ", ".join(v.korisnicko_ime for v in voditelji),
        )


def migriraj_zaduzene_u_radnike(db: Session) -> None:
    """Prebaci postojeće pojedinačne zaduženike (zaduzeni_id) u novi popis radnika.

    Jednokratno preko zastavice na trajnom volumenu.
    """
    zastavica = Path(settings.upload_dir).parent / ".zadatak_radnici_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    preneseno = 0
    for z in db.query(Zadatak).filter(Zadatak.zaduzeni_id.isnot(None)).all():
        if z.zaduzeni and z.zaduzeni not in z.radnici:
            z.radnici.append(z.zaduzeni)
            preneseno += 1
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    if preneseno:
        log.info("Preneseno %d zaduženja u popis radnika zadataka.", preneseno)


def seed_radnici(db: Session, lozinka: str = "radnik123") -> None:
    """Kreira početni popis radnika — samo ako u bazi još nema nijednog radnika
    (idempotentno; ne uskrsava pojedinačno obrisane radnike kasnije)."""
    if db.query(Korisnik).filter(Korisnik.uloga == Uloga.radnik).count() > 0:
        return
    zauzeti = {k.korisnicko_ime for k in db.query(Korisnik).all()}
    dodano = 0
    for ime in RADNICI_POCETNI:
        baza = _slug(ime)
        kor, i = baza, 1
        while kor in zauzeti:
            i += 1
            kor = f"{baza}{i}"
        zauzeti.add(kor)
        db.add(Korisnik(
            ime=ime, korisnicko_ime=kor,
            lozinka_hash=hash_lozinka(lozinka), uloga=Uloga.radnik,
        ))
        dodano += 1
    db.commit()
    log.info("Uvezeno %d radnika (početna lozinka '%s').", dodano, lozinka)
