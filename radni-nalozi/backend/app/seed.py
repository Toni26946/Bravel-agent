"""Početni podaci — kreira prvog voditelja ako u bazi nema nijednog korisnika."""
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from datetime import datetime, timezone

from .auth import hash_lozinka
from .config import settings
from .models import (
    EvidencijaRV, Korisnik, Nalog, PovijestRada, RegistarVozila, StatusNaloga,
    StatusVozila, Uloga, Vozilo, Zadatak,
)

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
    zastavica = Path(settings.upload_dir).parent / ".povijest_rada_v3"
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
    # Zamijeni raniji uvoz (evidencija) punim podacima, ALI zadrži povijest koju
    # je generirala sama aplikacija iz naloga (izvor="nalog") — nju ne diramo.
    db.query(PovijestRada).filter(
        (PovijestRada.izvor != "nalog") | (PovijestRada.izvor.is_(None))
    ).delete(synchronize_session=False)
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


# Radnici koji se ne prijavljuju na operacije (skladište/uprava) — po tokenima imena.
_NEPRIJAVLJENI_TOKENI = [
    {"marina", "pejkovic"},   # Habijanec Pejković Marina — skladištarka
]


def oznaci_neprijavljene_radnike(db: Session) -> None:
    """Jednokratno označi poznate ne-servisere (npr. skladištar) da se ne prijavljuju."""
    zastavica = Path(settings.upload_dir).parent / ".neprijavljeni_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    promijenjeno = 0
    for k in db.query(Korisnik).filter(Korisnik.uloga == Uloga.radnik).all():
        tok = _tokeni(k.ime)
        if any(trazeni <= tok for trazeni in _NEPRIJAVLJENI_TOKENI) and k.prijavljuje_se:
            k.prijavljuje_se = False
            promijenjeno += 1
    if promijenjeno:
        db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    if promijenjeno:
        log.info("Označeno %d radnika kao 'ne prijavljuje se'.", promijenjeno)


# (ime za prikaz/kreiranje, tokeni za pronalazak postojećeg, korisničko ime, lozinka, uloga)
_BATCH_KORISNICI = [
    ("Mario Azinović", {"mario", "azinovic"}, "mario.azinovic", "Mario7391", Uloga.voditelj),
    ("Davor Kobeščak", {"davor", "kobescak"}, "davor.kobescak", "Davor2648", Uloga.voditelj),
    ("Dominik Bahal", {"dominik", "bahal"}, "dominik.bahal", "Dominik4157", Uloga.voditelj),
    ("Akshay", {"akshay"}, "akshay", "Akshay8264", Uloga.radnik),
]


def osiguraj_vlasnika(db: Session) -> None:
    """Osiguraj voditeljski račun vlasnika AI Poslovođe (settings.ai_poslovodja_user).

    Postojeći račun (npr. 'toni') se NE dira osim što se osigura da je aktivan
    voditelj (lozinku ne mijenjamo). Samo ako račun uopće ne postoji — kreira se
    (lozinka iz fly secreta VLASNIK_LOZINKA; ako prazno, privremena)."""
    uname = (settings.ai_poslovodja_user or "").strip()
    if not uname:
        return
    post = db.query(Korisnik).filter(Korisnik.korisnicko_ime == uname).first()
    if post:
        promjena = False
        if post.uloga != Uloga.voditelj:
            post.uloga = Uloga.voditelj
            promjena = True
        if not post.aktivan:
            post.aktivan = True
            promjena = True
        if promjena:
            db.commit()
        return
    lozinka = settings.vlasnik_lozinka or "bravel123"
    db.add(Korisnik(
        ime=settings.vlasnik_ime or uname, korisnicko_ime=uname,
        lozinka_hash=hash_lozinka(lozinka), uloga=Uloga.voditelj, aktivan=True,
    ))
    db.commit()


def uvezi_vozila_matica(db: Session) -> None:
    """Jednokratni uvoz matičnih podataka o vozilima iz app/data/vozila_matica.tsv
    (izvor: tablica "GARAŽNI BROJEVI"). Stupci po redoslijedu: GB, VOZILO, REG
    OZNAKA, VRSTA, PRVA REGISTRACIJA, TIP, FIRMA, IZNOS REGISTRACIJE, NORMA, BROJ
    ŠASIJE. Upsert po garažnom broju; PUNI SAMO PRAZNA polja (ne gazi postojeće /
    Flotine / ručne izmjene). Idempotentno preko zastavice na trajnom volumenu."""
    zastavica = Path(settings.upload_dir).parent / ".vozila_matica_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    put = _DATA_DIR / "vozila_matica.tsv"
    if not put.exists():
        return
    try:
        redci = [r for r in put.read_text(encoding="utf-8").splitlines() if r.strip()]
    except OSError as e:  # noqa: BLE001
        log.warning("Ne mogu učitati vozila_matica.tsv: %s", e)
        return

    def _v(x: str | None) -> str | None:
        x = (x or "").strip()
        return None if x in ("", "0") else x

    def _kat(tip: str | None) -> str | None:
        t = (tip or "").strip().lower()
        if "kamion" in t:
            return "kamion"
        if any(k in t for k in ("priklj", "prikolic", "slep", "šlep", "poluprik")):
            return "prikolica"
        return None

    dodano = azurirano = 0
    for redak in redci:
        c = redak.split("\t")
        c += [""] * (10 - len(c))
        gb = (c[0] or "").strip()
        if not gb or gb == "0":
            continue
        vrij = {
            "vozilo": _v(c[1]), "registracija": _v(c[2]), "vrsta": _v(c[3]),
            "prva_registracija": _v(c[4]), "tip": _v(c[5]), "firma": _v(c[6]),
            "iznos_registracije": _v(c[7]), "norma": _v(c[8]), "broj_sasije": _v(c[9]),
        }
        r = db.get(RegistarVozila, gb)
        nov = r is None
        if nov:
            r = RegistarVozila(gb=gb, status=StatusVozila.aktivno)
            db.add(r)
        for polje, val in vrij.items():
            if val and not getattr(r, polje, None):   # puni samo prazno
                setattr(r, polje, val)
        if not r.kategorija:
            kat = _kat(vrij.get("tip"))
            if kat:
                r.kategorija = kat
        dodano += 1 if nov else 0
        azurirano += 0 if nov else 1
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Uvoz matičnih podataka vozila: dodano %d, ažurirano %d.", dodano, azurirano)


def osiguraj_dodatne_korisnike(db: Session) -> None:
    """Jednokratno kreira/ažurira ručno zadane račune (korisničko ime + lozinka).

    Ako osoba već postoji (podudaranje po tokenima imena) — postavi joj čisto
    korisničko ime i novu lozinku te je aktivira; inače kreira novi račun.
    Guardano zastavicom na trajnom volumenu.
    """
    zastavica = Path(settings.upload_dir).parent / ".korisnici_batch_v2"
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
            postoji.uloga = uloga
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


def osiguraj_poslovodju(db: Session) -> None:
    """Jednokratno: Gmitrović Miloš → uloga 'poslovodja' (ograničeni voditelj)
    s čistim korisničkim imenom i lozinkom. Guardano zastavicom."""
    zastavica = Path(settings.upload_dir).parent / ".poslovodja_milos_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    ime, tset, kor, lozinka = "Gmitrović Miloš", {"milos", "gmitrovic"}, "milos.gmitrovic", "Milos4826"
    svi = db.query(Korisnik).all()
    zauzeta = {k.korisnicko_ime for k in svi}
    postoji = next((k for k in svi if tset <= _tokeni(k.ime)), None)
    h = hash_lozinka(lozinka)
    if postoji:
        if kor == postoji.korisnicko_ime or kor not in zauzeta:
            postoji.korisnicko_ime = kor
        postoji.lozinka_hash = h
        postoji.uloga = Uloga.poslovodja
        postoji.aktivan = True
    else:
        ime_kor, i = kor, 1
        while ime_kor in zauzeta:
            i += 1
            ime_kor = f"{kor}{i}"
        db.add(Korisnik(ime=ime, korisnicko_ime=ime_kor, lozinka_hash=h,
                        uloga=Uloga.poslovodja, aktivan=True))
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Poslovođa (Gmitrović Miloš) osiguran.")


def osiguraj_kovacevica(db: Session) -> None:
    """Jednokratno: osiguraj da 'Dario Kovačević' postoji kao aktivan serviser.

    Ako postoji (po tokenima imena) — aktivira ga, postavi ulogu radnik i da se
    prijavljuje; ako ne postoji — kreira ga (login: dario.kovacevic / radnik123).
    """
    zastavica = Path(settings.upload_dir).parent / ".kovacevic_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    tset, kor, lozinka = {"dario", "kovacevic"}, "dario.kovacevic", "radnik123"
    svi = db.query(Korisnik).all()
    zauzeta = {k.korisnicko_ime for k in svi}
    postoji = next((k for k in svi if tset <= _tokeni(k.ime)), None)
    if postoji:
        postoji.aktivan = True
        postoji.uloga = Uloga.radnik
        postoji.prijavljuje_se = True
    else:
        ime_kor, i = kor, 1
        while ime_kor in zauzeta:
            i += 1
            ime_kor = f"{kor}{i}"
        db.add(Korisnik(ime="Dario Kovačević", korisnicko_ime=ime_kor,
                        lozinka_hash=hash_lozinka(lozinka), uloga=Uloga.radnik, aktivan=True))
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Dario Kovačević osiguran kao aktivan serviser.")


def obavijesti_osvjezi(db: Session) -> None:
    """Jednokratno: pošalji svim korisnicima push da osvježe aplikaciju (nova verzija).

    Bump zastavice (.osvjezi_vN) kad treba ponovno poslati."""
    zastavica = Path(settings.upload_dir).parent / ".osvjezi_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    try:
        from .push import _posalji, push_omogucen
        if push_omogucen():
            poslano = 0
            for k in db.query(Korisnik).filter(Korisnik.aktivan.is_(True)).all():
                if k.push_subscription:
                    if _posalji(k.push_subscription, "Nova verzija aplikacije",
                                "Osvježite aplikaciju: zatvorite je i ponovno otvorite (ili povucite prema dolje).",
                                url="/"):
                        poslano += 1
            log.info("Poslana obavijest o osvježavanju: %d korisnika.", poslano)
    except Exception as e:  # noqa: BLE001
        log.warning("Obavijest o osvježavanju nije poslana: %s", e)
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


def osiguraj_vozilo_483(db: Session) -> None:
    """Jednokratno: ručno dodaj vozilo GB 483 u matični popis (nije u Flota OS-u).

    Registracija i napomena postavljene na „Volvo šumar" (uredit će se kasnije).
    rucno=True da sinkronizacija ne dira. Ako red već postoji, ne pregazi ga."""
    zastavica = Path(settings.upload_dir).parent / ".vozilo_483_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    if not db.get(RegistarVozila, "483"):
        db.add(RegistarVozila(
            gb="483", registracija="Volvo šumar", tip="Volvo šumar",
            kategorija="kamion", napomena="Volvo šumar",
            status=StatusVozila.aktivno, rucno=True,
        ))
        db.commit()
        log.info("Vozilo GB 483 (Volvo šumar) dodano u matični popis.")
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


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


def spoji_azinovica(db: Session) -> None:
    """Jednokratno: dani evidencije s viška-računa „Mario Azinović" (ručno napravljen
    03.09.2026., nikad korišten — dobio je samo 16 dana GO pri uvozu šifri iz GS)
    prebace se na pravi račun `mario.azinovic`; višak-račun se deaktivira ako
    nema drugih podataka. Guardano zastavicom."""
    zastavica = Path(settings.upload_dir).parent / ".spoji_azinovica_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    pravi = db.query(Korisnik).filter(Korisnik.korisnicko_ime == "mario.azinovic").first()
    visak = db.query(Korisnik).filter(Korisnik.korisnicko_ime == "Mario Azinović").first()
    if pravi and visak and pravi.id != visak.id:
        postoje = {d for (d,) in db.query(EvidencijaRV.datum).filter(EvidencijaRV.korisnik_id == pravi.id)}
        preb = 0
        for z in db.query(EvidencijaRV).filter(EvidencijaRV.korisnik_id == visak.id).all():
            if z.datum in postoje:
                db.delete(z)          # pravi račun već ima taj dan — ne dupliraj
            else:
                z.korisnik_id = pravi.id
                preb += 1
        visak.aktivan = False
        db.commit()
        log.info("Azinović: prebačeno %d dana evidencije na pravi račun, višak deaktiviran.", preb)
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


def uvezi_sifre_iz_gs(db: Session) -> None:
    """Jednokratno upiše šifre izostanaka (GO/BO/PD) iz Google tablice evidencije
    (app/data/evidencija_sifre_gs.json: {"2026-7": {"radnici": {"PREZIME IME": {"dan": "GO"}}}}).

    Prvi uvoz iz GS prenio je samo sate, pa su godišnji/bolovanja ispadali kao redovni
    rad (krivo za obračun plaća). Šifra iz tablice je mjerodavna: dan postaje odsutnost
    (od/do i sati se brišu, kao kod ručnog upisa šifre); dan kojeg nema se doda.
    Radnik se traži po imenu (isti skup riječi bez dijakritika). Guardano zastavicom."""
    # v2: kod istog imena prednost ima AKTIVNI korisnik (v1 je dio šifri upisao neaktivnim
    # duplikatima, npr. stari radnički račun uz novi voditeljski).
    zastavica = Path(settings.upload_dir).parent / ".evidencija_sifre_gs_v2"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    put = _DATA_DIR / "evidencija_sifre_gs.json"
    if not put.exists():
        return
    try:
        podaci = json.loads(put.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Ne mogu učitati evidencija_sifre_gs.json: %s", e)
        return

    def kljuc(ime: str) -> frozenset:
        return frozenset((ime or "").translate(_ASCII).upper().split())

    po_imenu = {}
    for k in sorted(db.query(Korisnik).all(), key=lambda k: bool(k.aktivan)):   # aktivni zadnji = pobjeđuju
        if k.ime:
            po_imenu[kljuc(k.ime)] = k.id
    upisano, nepoznati = 0, set()
    for mj, blok in podaci.items():
        try:
            g, m = (int(x) for x in mj.split("-"))
        except ValueError:
            continue
        for ime, dani in (blok.get("radnici") or {}).items():
            kid = po_imenu.get(kljuc(ime))
            if not kid:
                nepoznati.add(ime)
                continue
            for d, sifra in dani.items():
                sifra = str(sifra).strip().upper()
                if sifra not in ("GO", "BO", "PD"):
                    continue
                try:
                    dat = date(g, m, int(d))
                except ValueError:
                    continue
                z = db.query(EvidencijaRV).filter(EvidencijaRV.korisnik_id == kid,
                                                  EvidencijaRV.datum == dat).first()
                if not z:
                    z = EvidencijaRV(korisnik_id=kid, datum=dat)
                    db.add(z)
                z.kod, z.od, z.do = sifra, None, None
                z.redovni, z.prekovremeni, z.teren = 0.0, 0.0, 0.0
                upisano += 1
    db.commit()
    log.info("Šifre izostanaka iz GS: upisano %d dana; bez korisnika: %d", upisano, len(nepoznati))
    neaktivni = [k.ime for k in db.query(Korisnik).filter(Korisnik.aktivan.is_(False)).all()
                 if k.ime and kljuc(k.ime) in {kljuc(i) for b in podaci.values() for i in (b.get("radnici") or {})}
                 and po_imenu.get(kljuc(k.ime)) == k.id]
    if neaktivni:
        log.warning("Šifre izostanaka upisane NEAKTIVNIM korisnicima (ne idu u obračun): %d", len(neaktivni))
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


def uvezi_evidenciju_iz_gs(db: Session) -> None:
    """Jednokratni uvoz povijesnih unosa evidencije radnog vremena iz
    app/data/evidencija_gs.json (izvezeno iz Google tablice, srpanj–listopad 2026).

    v3: dani s odrađenim od/do broje se u redovno (i kad su označeni GO/BO).
    Teren se vodi neprekidno — svi sati od odlaska do povratka (puni dan = 24 h);
    jednodnevni teren bez spavanja (≤24 h, do<24) ide u redovno, višednevni
    (sa spavanjem) ostaje teren. Prije uvoza briše prethodni automatski uvoz
    (kreirao_id IS NULL) za srpanj–listopad 2026, a ručne unose ostavlja.
    Guardano zastavicom na trajnom volumenu.
    """
    zastavica = Path(settings.upload_dir).parent / ".evidencija_gs_v3"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    put = _DATA_DIR / "evidencija_gs.json"
    if not put.exists():
        return
    try:
        unosi = json.loads(put.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Ne mogu učitati evidencija_gs.json: %s", e)
        return
    # Ukloni prethodni automatski uvoz (bez autora) za uvozno razdoblje.
    (
        db.query(EvidencijaRV)
        .filter(
            EvidencijaRV.kreirao_id.is_(None),
            EvidencijaRV.datum >= date(2026, 7, 1),
            EvidencijaRV.datum <= date(2026, 10, 31),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    postoje = {(kid, dat) for kid, dat in db.query(EvidencijaRV.korisnik_id, EvidencijaRV.datum).all()}
    valjani = {kid for (kid,) in db.query(Korisnik.id).all()}
    dodano = 0
    for e in unosi:
        kid = e.get("kid")
        if kid not in valjani:
            continue
        try:
            dat = date(e["g"], e["m"], e["d"])
        except (KeyError, ValueError, TypeError):
            continue
        if (kid, dat) in postoje:
            continue
        db.add(EvidencijaRV(
            korisnik_id=kid, datum=dat,
            od=e.get("od"), do=e.get("do"),
            redovni=float(e.get("red", 0) or 0),
            prekovremeni=float(e.get("pre", 0) or 0),
            teren=float(e.get("ter", 0) or 0),
            kod=e.get("kod"),
        ))
        postoje.add((kid, dat))
        dodano += 1
    if dodano:
        db.commit()
        log.info("Uvezeno %d unosa evidencije iz GS.", dodano)
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass


# Bivši zaposlenici / računi koje više ne vodimo kao radnike (deaktiviraj, ne briši).
_BIVSI_TOKENI = [
    {"roko", "jendris"},      # Roko Jendriš
    {"velimir", "jendris"},   # Velimir Jendriš
]


def jednokratno_deaktiviraj_bivse(db: Session) -> None:
    """Jednokratno deaktivira račune bivših zaposlenika (po tokenima imena/korisničkog).

    Deaktivacija (aktivan=False) ih miče iz evidencije i ostalih popisa, ali račun
    ostaje (reverzibilno — može se ručno reaktivirati). Guardano zastavicom da ne
    poništi kasniju namjernu reaktivaciju.
    """
    zastavica = Path(settings.upload_dir).parent / ".deaktiviraj_bivse_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    deaktivirano = 0
    for k in db.query(Korisnik).filter(Korisnik.aktivan.is_(True)).all():
        tok = _tokeni(f"{k.ime} {k.korisnicko_ime}")
        if any(trazeni <= tok for trazeni in _BIVSI_TOKENI):
            k.aktivan = False
            deaktivirano += 1
    if deaktivirano:
        db.commit()
        log.info("Deaktivirano %d bivših računa (Roko/Velimir).", deaktivirano)
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


def ocisti_mjerace_bez_radnika(db: Session) -> None:
    """Zaustavi mjerenje na zadacima koji nemaju dodijeljenog radnika.

    Vrijeme smije teći samo dok je radnik prijavljen; ovo čisti eventualne
    mjerače pokrenute ručno (stari gumbi) bez radnika. Sigurno se pokreće pri
    svakom startu — ne dira zadatke koji imaju radnika."""
    n = 0
    for z in db.query(Zadatak).filter(Zadatak.zapoceto.isnot(None)).all():
        if not z.radnici:
            zp = z.zapoceto if z.zapoceto.tzinfo else z.zapoceto.replace(tzinfo=timezone.utc)
            proteklo = (datetime.now(timezone.utc) - zp).total_seconds()
            z.utroseno_sek = int(z.utroseno_sek or 0) + max(0, int(proteklo))
            z.zapoceto = None
            n += 1
    if n:
        db.commit()
        log.info("Zaustavljeno %d mjerača bez dodijeljenog radnika.", n)


def preimenuj_naslove_naloga(db: Session) -> None:
    """Jednokratno: naslov 'Servis <GB>' → samo '<GB>'."""
    zastavica = Path(settings.upload_dir).parent / ".naslov_gb_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    promijenjeno = 0
    for nalog in db.query(Nalog).join(Vozilo, Nalog.vozilo_id == Vozilo.id).all():
        gb = nalog.vozilo.gb if nalog.vozilo else None
        if gb and nalog.naslov in (f"Servis {gb}", f"Servis  {gb}"):
            nalog.naslov = gb
            promijenjeno += 1
    if promijenjeno:
        db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    if promijenjeno:
        log.info("Preimenovano %d naslova naloga u garažni broj.", promijenjeno)


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


def backfill_povijest_gotovih(db: Session) -> None:
    """Jednokratno: upiši SVE dosad gotove operacije u servisnu povijest vozila.

    Ranije se rad evidentirao samo kad cijeli nalog postane 'gotov'; gotove
    operacije na nalozima koji nikad ne dođu do 'gotov' (npr. radnik samo
    odjavljen) ostale su nezabilježene. Ovo rekonstruira povijest iz trenutnog
    stanja zadataka. Idempotentno po nalogu (obriši pa upiši), pa je sigurno.
    """
    zastavica = Path(settings.upload_dir).parent / ".povijest_backfill_v1"
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    sada = datetime.now(timezone.utc)
    upisano = 0
    for nalog in db.query(Nalog).all():
        sve = nalog.status in (StatusNaloga.gotov, StatusNaloga.zatvoren)
        # očisti postojeće zapise ovog naloga (ne dira uvezenu povijest bez nalog_id)
        db.query(PovijestRada).filter(PovijestRada.nalog_id == nalog.id).delete()
        for op in nalog.operacije:
            for z in op.zadaci:
                if not sve and not z.gotovo:
                    continue
                opis = (z.opis or "").strip()
                if not opis:
                    continue
                dat = z.zavrseno or nalog.zatvoren or sada
                if dat.tzinfo is None:
                    dat = dat.replace(tzinfo=timezone.utc)
                imena = ", ".join(r.ime for r in z.radnici) or (z.zaduzeni.ime if z.zaduzeni else None)
                db.add(PovijestRada(
                    vozilo_id=nalog.vozilo_id,
                    nalog_id=nalog.id,
                    datum=dat.date(),
                    radnik=(imena or None),
                    operacija=op.kategorija or None,
                    opis=opis,
                    minute=(int((z.utroseno_sek or 0) / 60) or None),
                    izvor="nalog",
                ))
                upisano += 1
    db.commit()
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
    log.info("Backfill servisne povijesti: upisano %d gotovih operacija.", upisano)


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
