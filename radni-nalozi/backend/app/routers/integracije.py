"""Integracije (vlasnik) — pristupni podaci za vanjske sustave spremaju se u bazu,
pa ih Toni zalijepi izravno u portal (Šifrarnik → Integracije), bez terminala.

Zasad: APROSS (Zagreb Data) — API-KEY (+ opcionalni Basic Auth). Ključ se NIKAD
ne vraća natrag klijentu; vraća se samo je li postavljen i zadnje 4 znaka.
"""
from __future__ import annotations

import io
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import aross
from ..auth import zahtijevaj_ai_poslovodja, zahtijevaj_uloge
from ..database import get_db
from ..models import ArtiklCijena, Korisnik, Uloga
from ..norme import get_postavka, set_postavka

router = APIRouter(prefix="/integracije", tags=["integracije"])

samo_vlasnik = zahtijevaj_ai_poslovodja()
skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)


def _zadnje4(s: str) -> str:
    s = (s or "").strip()
    return ("…" + s[-4:]) if len(s) >= 4 else ("•" * len(s))


class ArossIn(BaseModel):
    api_key: str | None = None   # None/izostavljeno = ne diraj; "" = obriši
    user: str | None = None
    lozinka: str | None = None
    adresa: str | None = None    # npr. https://bravel-api-test.zgdata.hr/api5 (bez ključa)


@router.get("/aross")
def aross_stanje(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Stanje APROSS integracije — bez otkrivanja ključa."""
    key = (get_postavka(db, aross.P_KEY, "") or "").strip()
    user = (get_postavka(db, aross.P_USER, "") or "").strip()
    return {
        "povezano": aross.konfigurirano(db),
        "ima_kljuc": bool(key),
        "kljuc_kraj": _zadnje4(key) if key else "",
        "ima_basic": aross.ima_basic(db),
        "korisnik": user,                 # korisničko ime nije tajna; lozinka se ne vraća
        "baza": aross._baza(db) if key else "",
        "adresa": aross.adresa(db),       # bez ključa
        "testna": aross.je_testna(db),    # True = testna baza (ništa ne ide u pravi Apross)
    }


@router.post("/aross")
def aross_spremi(p: ArossIn, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Spremi API-KEY i (opcionalno) Basic Auth. Prazan string briše vrijednost;
    izostavljeno polje se ne dira."""
    if p.api_key is not None:
        set_postavka(db, aross.P_KEY, p.api_key.strip())
    if p.user is not None:
        set_postavka(db, aross.P_USER, p.user.strip())
    if p.lozinka is not None:
        set_postavka(db, aross.P_PASS, p.lozinka)
    if p.adresa is not None:
        a = p.adresa.strip().rstrip("/")
        if a and not re.match(r"^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._/-]*)?$", a):
            raise HTTPException(status_code=400, detail="Adresa mora biti https://… (bez API ključa na kraju).")
        set_postavka(db, aross.P_BASE, a)
    db.commit()
    # Druga baza/ključ → šifrarnici iz keša više ne vrijede (artikli, partneri, mjesta troška).
    for kes in (_ART_KES, _PART_KES, _MT_KES):
        kes["ts"] = 0.0
    _ART_KES["map"] = {}
    _PART_KES["lista"] = []
    _MT_KES["lista"] = []
    return aross_stanje(db, _)


@router.post("/aross/test")
def aross_test(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Pokušaj dohvat skladišta — potvrda da ključ i mreža rade."""
    if not aross.konfigurirano(db):
        return {"ok": False, "poruka": "Nema API-KEY-a. Zalijepi ključ pa spremi."}
    try:
        skl = aross.skladista(db)
    except aross.ArossGreska as e:
        return {"ok": False, "poruka": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "poruka": f"Greška u spoju: {e}"}
    n = len(skl) if isinstance(skl, list) else 0
    return {"ok": True, "poruka": f"Spoj radi — dohvaćeno skladišta: {n}.", "skladista": n}


def _na_broj(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# --- Cjenik (nabavna cijena) iz APROSS izvoza „Kocka stanja" -----------------
_SIFRA_RE = re.compile(r"\((\d+)\)\s*$")   # šifra je zadnja (broj) u nazivu artikla


def _broj_hr(x) -> float:
    """Broj iz ćelije (xls daje float; .xlsx isto). Podnosi i hrvatski zapis
    '12.345,67' ili '12,5' ako se pojavi kao tekst."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_kocka(ime: str, data: bytes) -> list[dict]:
    """Pročitaj izvoz „Kocka stanja" (.xls ili .xlsx). Stupci: Artikl, JM,
    Stanje robno, Stanje NC. Jedinična nabavna = |Stanje NC| ÷ |Stanje robno|.
    Vrati [{sifra, naziv, jmj, cijena}]."""
    low = (ime or "").lower()
    rows: list[list] = []
    if low.endswith(".xlsx") or low.endswith(".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
        wb.close()
    else:
        import xlrd  # čita stari .xls (BIFF)
        wb = xlrd.open_workbook(file_contents=data)
        ws = wb.sheet_by_index(0)
        rows = [ws.row_values(i) for i in range(ws.nrows)]

    # Nađi redak zaglavlja (sadrži „Artikl" i „Stanje NC").
    hi = None
    for i, r in enumerate(rows[:30]):
        txt = [str(c or "").strip().lower() for c in r]
        if any(c == "artikl" for c in txt) and any("stanje nc" in c for c in txt):
            hi = i
            break
    if hi is None:
        raise ValueError("ne prepoznajem stupce (treba 'Artikl' i 'Stanje NC')")
    zagl = [str(c or "").strip().lower() for c in rows[hi]]

    def idx(*kand):
        for k in kand:
            for j, c in enumerate(zagl):
                if c == k or k in c:
                    return j
        return None

    i_art, i_jm = idx("artikl"), idx("jm")
    i_rob, i_nc = idx("stanje robno"), idx("stanje nc")
    if i_art is None or i_rob is None or i_nc is None:
        raise ValueError("nedostaje stupac Artikl / Stanje robno / Stanje NC")

    out: list[dict] = []
    for r in rows[hi + 1:]:
        art = str(r[i_art] or "").strip() if i_art < len(r) else ""
        if not art or art.lower().startswith("ukupno"):
            continue
        m = _SIFRA_RE.search(art)
        if not m:
            continue
        sifra = int(m.group(1))
        naziv = _SIFRA_RE.sub("", art).strip()
        jmj = (str(r[i_jm] or "").strip() if i_jm is not None and i_jm < len(r) else "")
        robno = _broj_hr(r[i_rob]) if i_rob < len(r) else 0.0
        nc = _broj_hr(r[i_nc]) if i_nc < len(r) else 0.0
        if robno == 0:
            continue
        out.append({"sifra": sifra, "naziv": naziv[:200], "jmj": jmj[:20],
                    "cijena": round(abs(nc) / abs(robno), 4)})
    return out


def _cjenik_mapa(db) -> dict:
    """{str(sifra): jedinicna_nabavna} iz baze (cijeli cjenik, ~3k redaka).
    Ključ je tekst jer APROSS šifre znaju doći i kao broj i kao string."""
    return {str(s): c for s, c in db.query(ArtiklCijena.sifra, ArtiklCijena.cijena).all()}


@router.get("/cjenik")
def cjenik_stanje(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Status uvezenog cjenika nabavnih cijena."""
    n = db.query(ArtiklCijena).count()
    zadnje = (db.query(ArtiklCijena.azurirano)
              .order_by(ArtiklCijena.azurirano.desc()).first())
    return {"artikala": n, "azurirano": zadnje[0].isoformat() if zadnje and zadnje[0] else None}


@router.post("/cjenik/uvoz")
async def cjenik_uvoz(datoteka: UploadFile = File(...),
                      db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Uvezi „Kocka stanja" (.xls/.xlsx) → jedinične nabavne cijene po šifri.
    Postojeće šifre se ažuriraju, nove dodaju (snimka cjenika)."""
    data = await datoteka.read()
    try:
        redovi = _parse_kocka(datoteka.filename or "", data)
    except ImportError:
        raise HTTPException(status_code=500, detail="Čitač .xls nije dostupan — spremi datoteku kao .xlsx.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Ne mogu pročitati datoteku: {e}")
    if not redovi:
        raise HTTPException(status_code=400, detail="Nijedan artikl s cijenom nije prepoznat.")
    postoji = {c.sifra: c for c in db.query(ArtiklCijena).all()}
    for r in redovi:
        c = postoji.get(r["sifra"])
        if c is None:
            c = ArtiklCijena(sifra=r["sifra"])
            db.add(c)
            postoji[r["sifra"]] = c
        c.naziv, c.jmj, c.cijena = r["naziv"], r["jmj"], r["cijena"]
    db.commit()
    return {"ok": True, "uneseno": len(redovi), "ukupno_u_cjeniku": len(postoji)}


# Šifrarnik artikala je velik (~27k) i rijetko se mijenja → keširaj kratko da
# svaki dohvat zaliha ne vuče cijeli popis (bez keša ~3 s po pozivu).
_ART_KES: dict = {"ts": 0.0, "map": {}}
_ART_TTL = 600  # 10 minuta


def _artikli_mapa(db, osvjezi: bool = False) -> dict:
    sad = time.time()
    if not osvjezi and _ART_KES["map"] and (sad - _ART_KES["ts"]) < _ART_TTL:
        return _ART_KES["map"]
    art = aross.artikli(db)
    _ART_KES["map"] = {a.get("sifra"): a for a in (art or [])}
    _ART_KES["ts"] = sad
    return _ART_KES["map"]


@router.get("/aross/zalihe")
def aross_zalihe(nule: int = Query(default=0, ge=0, le=1),
                 osvjezi: int = Query(default=0, ge=0, le=1),
                 db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Stanje zalihe po skladištima (uživo iz APROSS-a), s imenima artikala.
    `nule=0` (zadano) prikazuje samo artikle sa stanjem ≠ 0; `nule=1` i nule.
    `osvjezi=1` zaobiđe keš šifrarnika artikala.
    Vraća {povezano, skladista:[{sifra, naziv, ukupno, artikli:[…]}], osvjezeno}."""
    if not aross.konfigurirano(db):
        return {"povezano": False, "skladista": [], "osvjezeno": None}
    try:
        imena = _artikli_mapa(db, osvjezi=bool(osvjezi))
        stanje = aross.artikli_stanje(db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))

    cjenik = _cjenik_mapa(db)   # {sifra: jedinicna_nabavna}; prazno dok se ne uveze
    skladista = []
    vrijednost_svih = 0.0
    for s in (stanje or []):
        redovi = []
        broj_artikala = 0     # koliko RAZLIČITIH artikala ima stanje ≠ 0
        zbroj_kolicina = 0.0  # ZBROJ svih količina na stanju (komadi/jmj) — pravo "na stanju"
        vrijednost = 0.0      # vrijednost stanja po nabavnoj cijeni (EUR)
        bez_cijene = 0        # artikli sa stanjem ≠ 0 kojima nemamo cijenu
        for a in (s.get("artikli") or []):
            st = _na_broj(a.get("stanje"))
            sa = a.get("sifraArtikla")
            cij = cjenik.get(str(sa)) if sa is not None else None
            vr = round(st * cij, 2) if cij is not None else None
            if st != 0:
                broj_artikala += 1
                zbroj_kolicina += st
                if cij is not None:
                    vrijednost += st * cij
                else:
                    bez_cijene += 1
            if not nule and st == 0:
                continue
            meta = imena.get(sa, {})
            redovi.append({
                "sifra": sa,
                "naziv": meta.get("naziv") or f"Artikl {sa}",
                "kataloskiBroj": meta.get("kataloskiBroj"),
                "jmj": meta.get("jmj"),
                "stanje": st,
                "cijena": cij,         # jedinična nabavna ili None
                "vrijednost": vr,      # stanje × cijena ili None
            })
        redovi.sort(key=lambda r: (r["naziv"] or "").lower())
        # Cijeli broj ako je zbroj cijeli (npr. 3044.0 → 3044); inače 1 decimala.
        kol = int(zbroj_kolicina) if float(zbroj_kolicina).is_integer() else round(zbroj_kolicina, 1)
        vrijednost_svih += vrijednost
        skladista.append({
            "sifra": s.get("sifraSkladista"),
            "naziv": s.get("nazivSkladista") or f"Skladište {s.get('sifraSkladista')}",
            "kolicina": kol,               # ZBROJ količina na stanju (pravo "na stanju")
            "artikala": broj_artikala,     # koliko različitih artikala (stanje ≠ 0)
            "ukupno": broj_artikala,       # kompatibilnost sa starim frontendom
            "vrijednost": round(vrijednost, 2),   # vrijednost zaliha po nabavnoj (EUR)
            "bez_cijene": bez_cijene,      # koliko artikala nema cijenu u cjeniku
            "artikli": redovi,
        })
    skladista.sort(key=lambda s: (s["naziv"] or "").lower())
    return {"povezano": True, "skladista": skladista,
            "ima_cjenik": bool(cjenik),
            "vrijednost_ukupno": round(vrijednost_svih, 2),
            "osvjezeno": datetime.now(timezone.utc).isoformat()}


# --- Šifrarnici za odabir pri slanju primke ----------------------------------
_PART_KES: dict = {"ts": 0.0, "lista": []}


def _partneri(db, osvjezi: bool = False) -> list[dict]:
    sad = time.time()
    if not osvjezi and _PART_KES["lista"] and (sad - _PART_KES["ts"]) < _ART_TTL:
        return _PART_KES["lista"]
    _PART_KES["lista"] = aross.poslovni_partneri(db) or []
    _PART_KES["ts"] = sad
    return _PART_KES["lista"]


@router.get("/aross/skladista")
def aross_skladista(db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Popis skladišta (za odabir odredišta primke)."""
    if not aross.konfigurirano(db):
        return []
    try:
        return aross.skladista(db) or []
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/aross/partneri")
def aross_partneri(q: str = Query(default="", max_length=100),
                   limit: int = Query(default=30, ge=1, le=200),
                   db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Pretraga poslovnih partnera (dobavljača) po nazivu/OIB-u."""
    if not aross.konfigurirano(db):
        return []
    try:
        svi = _partneri(db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    s = q.strip().lower()
    if s:
        svi = [p for p in svi if s in (p.get("naziv") or "").lower()
               or s in str(p.get("oib") or "").lower() or s in (p.get("mjesto") or "").lower()]
    svi = sorted(svi, key=lambda p: (p.get("naziv") or "").lower())[:limit]
    return svi


@router.get("/aross/artikli")
def aross_artikli(q: str = Query(default="", max_length=100),
                  limit: int = Query(default=30, ge=1, le=100),
                  db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Pretraga artikala po nazivu/kataloškom broju/šifri (za odabir stavke primke)."""
    if not aross.konfigurirano(db):
        return []
    try:
        mapa = _artikli_mapa(db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    s = q.strip().lower()
    # Unos po ŠIFRI: točna šifra uvijek prva, pa šifre koje počinju s upisanim, pa ostalo.
    tocna = mapa.get(int(s)) if s.isdigit() else None
    if tocna is None and s.isdigit():
        tocna = next((a for a in mapa.values() if str(a.get("sifra")) == s), None)
    out = []
    for a in mapa.values():
        if a is tocna:
            continue
        sif = str(a.get("sifra"))
        if s and not (s in (a.get("naziv") or "").lower()
                      or s in (a.get("kataloskiBroj") or "").lower()
                      or (s.isdigit() and sif.startswith(s))):
            continue
        out.append(a)
        if len(out) >= limit * 3:
            break
    out.sort(key=lambda a: (not (s.isdigit() and str(a.get("sifra")).startswith(s)),
                            (a.get("naziv") or "").lower()))
    if tocna is not None:
        out.insert(0, tocna)
    return out[:limit]


# --- Prijedlog Apross artikla po KATALOŠKOM BROJU (za stavke primke) ----------
def _kat_norm(s) -> str:
    """Kataloški broj bez razmaka/crtica/točaka/kosih crta, velikim slovima:
    '13.0460-2796.2' → '1304602796 2'→'13046027962'."""
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def _kandidati_kat(tekst: str) -> list[str]:
    """Mogući kataloški brojevi iz teksta stavke s otpremnice. AI ih stavlja u zagradu
    („Disk pločice (13.0460-2796.2)"), a znaju biti i u samom nazivu. Uzimamo sadržaj
    zagrada pa riječi koje imaju barem 4 znamenke/znaka i bar jednu znamenku."""
    t = str(tekst or "")
    out: list[str] = []
    for z in re.findall(r"\(([^()]+)\)", t):
        n = _kat_norm(z)
        if _dobar_kat(n) and n not in out:
            out.append(n)
    # Broj u zagradi JE kataloški broj → riječi iz naziva se tada ne gledaju
    # („10W40 Total Quartz 7000 (TOTAL711)" ne smije se spojiti po „7000" ili „10W40").
    if out:
        return out
    for rijec in re.split(r"[\s,;()]+", t):
        n = _kat_norm(rijec)
        if _dobar_kat(n) and re.search(r"\d", n) and n not in out:
            out.append(n)
    return out


_VISKOZNOST = re.compile(r"^\d{1,2}W\d{2}$")          # 5W30, 10W40, 75W90 — vrsta ulja, ne artikl
_PAKIRANJE = re.compile(r"^\d+(ML|L|KG|G|KOM|M)$")    # 200ML, 1L, 5KG — pakiranje


def _dobar_kat(n: str) -> bool:
    """Normalizirani kataloški broj koji smije služiti za spajanje (ne kratki broj,
    ne viskoznost ulja, ne pakiranje)."""
    return len(n) >= 5 and not _VISKOZNOST.match(n) and not _PAKIRANJE.match(n)


def _kat_indeks(mapa: dict) -> dict[str, list[dict]]:
    """normalizirani kataloški broj → [artikli] (isti kat. broj zna imati više artikala)."""
    idx: dict[str, list[dict]] = {}
    for a in mapa.values():
        n = _kat_norm(a.get("kataloskiBroj"))
        if _dobar_kat(n):
            idx.setdefault(n, []).append(a)
    return idx


def predlozi_artikl(tekst: str, idx: dict[str, list[dict]]) -> dict | None:
    """Jedan Apross artikl čiji kataloški broj TOČNO odgovara kandidatu iz teksta.
    Ako isti broj ima više artikala ili ničega nema → None (korisnik bira ručno)."""
    for k in _kandidati_kat(tekst):
        pogodci = idx.get(k) or []
        if len(pogodci) == 1:
            return pogodci[0]
    return None


class PrijedloziIn(BaseModel):
    stavke: list[str]


@router.post("/aross/predlozi-artikle")
def aross_predlozi_artikle(p: PrijedloziIn, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Za svaku stavku primke predloži Apross artikl po kataloškom broju (ili null)."""
    if not aross.konfigurirano(db):
        return {"prijedlozi": [None] * len(p.stavke)}
    try:
        idx = _kat_indeks(_artikli_mapa(db))
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"prijedlozi": [predlozi_artikl(s, idx) for s in p.stavke[:500]]}


# Šifre od 100000 naviše u Aprossu su posebni knjigovodstveni artikli („Predujam primljen
# od kupca" 200000–200003), ne dijelovi — nova šifra dijela ide iza najveće ispod toga.
_SIFRA_POSEBNI_OD = 100000


def sljedeca_sifra(mapa: dict) -> int:
    brojevi = [int(s) for s in mapa.keys() if (isinstance(s, int) or str(s).isdigit()) and int(s) < _SIFRA_POSEBNI_OD]
    return (max(brojevi) + 1) if brojevi else 1


class ArtiklIn(BaseModel):
    naziv: str
    jmj: str = "kom"
    kat_broj: str | None = None
    barkod: str | None = None
    id_artikla: int | None = None   # ako je prazno → dodijeli sljedeću slobodnu šifru


@router.post("/aross/artikl")
def aross_kreiraj_artikl(p: ArtiklIn, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Kreiraj novi artikl u Aprossu (kad dio s otpremnice još ne postoji).
    Šifru dodjeljujemo sami (zadnja + 1) ako nije poslana. Vraća kreirani artikl."""
    if not aross.konfigurirano(db):
        raise HTTPException(status_code=503, detail="APROSS nije povezan.")
    if not (p.naziv or "").strip():
        raise HTTPException(status_code=400, detail="Naziv artikla je obavezan.")
    try:
        mapa = _artikli_mapa(db, osvjezi=True)   # svjež popis da izračunamo sljedeću šifru
        id_art = p.id_artikla
        if not id_art:
            id_art = sljedeca_sifra(mapa)
        if id_art in mapa:
            raise HTTPException(status_code=409, detail=f"Šifra {id_art} već postoji.")
        aross.kreiraj_artikl(id_art, p.naziv.strip(), p.jmj or "kom", p.kat_broj, p.barkod, db=db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    _ART_KES["ts"] = 0.0   # poništi keš da se novi artikl odmah vidi u pretrazi
    return {"ok": True, "artikl": {"sifra": id_art, "naziv": p.naziv.strip(),
                                   "kataloskiBroj": p.kat_broj, "jmj": p.jmj or "kom"}}


def razdvoji_naziv_kat(tekst: str) -> tuple[str, str | None]:
    """Stavka s otpremnice → (naziv za Apross, kataloški broj).
    „Filter goriva (190199)" → („FILTER GORIVA", „190199"). Naziv velikim slovima
    kao postojeći Apross artikli, najviše 60 znakova."""
    t = " ".join(str(tekst or "").split())
    zagrade = re.findall(r"\(([^()]+)\)", t)
    kat = zagrade[-1].strip() if zagrade else None
    naziv = " ".join(re.sub(r"\([^()]*\)", " ", t).split()).strip(" -·,") or t
    return naziv.upper()[:60], (kat[:40] if kat else None)


class NoviArtikliIn(BaseModel):
    stavke: list[str]          # tekstovi stavki s otpremnice
    jmj: list[str] = []        # jedinica po stavci (isti redoslijed), zadano „kom"


@router.post("/aross/artikli/novi")
def aross_novi_artikli(p: NoviArtikliIn, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Opcija 2 (Toni 17.11.2026.): stavke s otpremnice kojih nema u Aprossu otvori
    kao nove artikle — naziv + kataloški broj s otpremnice, šifre redom (zadnja + 1).
    Prije otvaranja još jednom provjeri točan kataloški broj (da ne nastane duplikat).
    Vraća {artikli: [artikl|None, …]} istim redoslijedom kao stavke."""
    if not aross.konfigurirano(db):
        raise HTTPException(status_code=503, detail="APROSS nije povezan.")
    try:
        mapa = dict(_artikli_mapa(db, osvjezi=True))
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    idx = _kat_indeks(mapa)
    sljedeca = sljedeca_sifra(mapa)
    out: list[dict | None] = []
    for i, tekst in enumerate(p.stavke):
        postoji = predlozi_artikl(tekst, idx)
        if postoji:
            out.append(postoji)
            continue
        naziv, kat = razdvoji_naziv_kat(tekst)
        if not naziv:
            out.append(None)
            continue
        jmj = ((p.jmj[i] if i < len(p.jmj) else "") or "kom").strip()[:10] or "kom"
        try:
            aross.kreiraj_artikl(sljedeca, naziv, jmj, kat, None, db=db)
        except aross.ArossGreska as e:
            raise HTTPException(status_code=502, detail=f"Artikl „{naziv}”: {e}")
        novi = {"sifra": sljedeca, "naziv": naziv, "kataloskiBroj": kat, "jmj": jmj}
        mapa[sljedeca] = novi
        if kat and _dobar_kat(_kat_norm(kat)):
            idx.setdefault(_kat_norm(kat), []).append(novi)   # isti kat. broj dvaput → jedan artikl
        out.append(novi)
        sljedeca += 1
    _ART_KES["ts"] = 0.0
    return {"artikli": out}


class PrimkaStavkaIn(BaseModel):
    sifraArtikla: int
    kolicina: float
    cijena: float


class PrimkaIn(BaseModel):
    broj_primke: str
    sifra_dobavljaca: int
    datum: str                    # yyyy-MM-dd
    sifra_skladista: int
    stavke: list[PrimkaStavkaIn]
    napomena: str | None = None
    primka_id: int | None = None  # lokalna primka (da zapišemo ERP broj natrag)


@router.post("/aross/primka")
def aross_posalji_primku(p: PrimkaIn, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Pošalji (kreiraj) primku u Apross. Vraća ERP broj primke i zapiše ga na lokalnu primku."""
    if not aross.konfigurirano(db):
        raise HTTPException(status_code=503, detail="APROSS nije povezan.")
    if not p.stavke:
        raise HTTPException(status_code=400, detail="Primka nema stavki.")
    from ..models import Primka
    lokalna = db.get(Primka, p.primka_id) if p.primka_id else None
    if lokalna is not None and lokalna.apross_broj:
        raise HTTPException(status_code=409, detail=f"Primka je već poslana u Apross (#{lokalna.apross_broj}).")
    stavke = [{"sifraArtikla": s.sifraArtikla, "kolicina": s.kolicina, "cijena": s.cijena}
              for s in p.stavke]
    try:
        rez = aross.kreiraj_primku(p.broj_primke, p.sifra_dobavljaca, p.datum,
                                   p.sifra_skladista, stavke, p.napomena, db=db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    erp = None
    if isinstance(rez, list) and rez and isinstance(rez[0], dict):
        erp = rez[0].get("erpBrojPrimke")
    if erp is None:
        raise HTTPException(status_code=502, detail=f"APROSS nije vratio broj primke: {str(rez)[:200]}")
    if lokalna is not None:
        lokalna.apross_broj = int(erp)
        db.commit()
    return {"ok": True, "erp_broj_primke": erp, "rezultat": rez}


# --- Izdatnice (utrošeni dijelovi na nalogu → Apross, na teret vozila) --------
_MT_KES: dict = {"ts": 0.0, "lista": []}


def _mjesta_troska(db, osvjezi: bool = False) -> list[dict]:
    sad = time.time()
    if not osvjezi and _MT_KES["lista"] and (sad - _MT_KES["ts"]) < _ART_TTL:
        return _MT_KES["lista"]
    _MT_KES["lista"] = aross.mjesta_troska(db) or []
    _MT_KES["ts"] = sad
    return _MT_KES["lista"]


def _reg_norm(s: str | None) -> str:
    """Registracija bez crtica/razmaka, velikim slovima: 'ZG-3495-FR' → 'ZG3495FR'."""
    return re.sub(r"[^A-Z0-9ČĆŠŽĐ]", "", (s or "").upper())


# Registracija u slobodnom tekstu: 2 slova, 3–4 znamenke, 1–2 slova, s crticama/razmacima ili bez
# (ZG-7234-FE, ZG7234HF, DA-920 CZ). Nazivi u Aprossu su neuredni: „ Prikolica   ZG1239HJ (stara
# ZG-8284-FC)", „ZG5182HC( prijeDA-264-DB)", „ZG-3208-FF * PRODAN".
_REG_RE = re.compile(r"([A-ZČĆŠŽĐ]{2})[\s-]*(\d{3,4})[\s-]*([A-ZČĆŠŽĐ]{1,2})(?![A-Z0-9ČĆŠŽĐ])")


def _mt_registracije_lista(naziv: str) -> list[str]:
    """Registracije iz naziva redom pojavljivanja (prva = trenutna, ostale = stare)."""
    out: list[str] = []
    for a, b, c in _REG_RE.findall((naziv or "").upper()):
        r = a + b + c
        if r not in out:
            out.append(r)
    return out


def _mt_registracije(naziv: str) -> set[str]:
    """Sve registracije iz naziva mjesta troška, npr. 'ZG-4732-HC (prije DA681EC)'
    → {'ZG4732HC', 'DA681EC'}."""
    return set(_mt_registracije_lista(naziv))


def _registracije_naloga(db, nalog) -> set[str]:
    """Registracije vozila naloga: iz naloga i iz matičnog popisa (po GB-u)."""
    from ..models import RegistarVozila
    regs = set()
    v = nalog.vozilo
    if v is not None:
        if _reg_norm(v.registracija):
            regs.add(_reg_norm(v.registracija))
        rv = db.get(RegistarVozila, v.gb) if v.gb else None
        if rv is not None and _reg_norm(rv.registracija):
            regs.add(_reg_norm(rv.registracija))
    return regs


def _nadji_mjesto_troska(db, nalog) -> dict | None:
    """Mjesto troška vozila naloga — po GARAŽNOM BROJU: šifra mjesta troška u Aprossu
    JE garažni broj (GB 79 → šifra 79). Registracija se NE koristi (u Aprossu zna biti
    novija/starija nego kod nas). Nema pogotka → korisnik bira ručno."""
    gb = (nalog.vozilo.gb if nalog.vozilo else "") or ""
    return _mjesto_po_gb(gb, _mjesta_troska(db))


def _mjesto_po_gb(gb: str, mjesta: list[dict]) -> dict | None:
    gb = (gb or "").strip()
    if not gb.isdigit():
        return None
    for mt in mjesta:
        if str(mt.get("sifra")).strip() == str(int(gb)):
            return mt
    return None


def _odaberi_mjesto_troska(regs: set[str], mjesta: list[dict]) -> dict | None:
    """Najbolje mjesto troška za registracije vozila: prednost ima ono kojem je to
    TRENUTNA (prva) registracija i koje nije prodano/rashodovano; stara reg. je rezerva."""
    if not regs:
        return None
    najbolje, bod = None, -1
    for mt in mjesta:
        naziv = str(mt.get("naziv") or "")
        lista = _mt_registracije_lista(naziv)
        if not regs.intersection(lista):
            continue
        b = 2 if lista and lista[0] in regs else 1
        if not re.search(r"PRODAN|RASHOD", naziv.upper()):
            b += 2
        if b > bod:
            najbolje, bod = mt, b
    return najbolje


@router.get("/aross/mjesta-troska")
def aross_mjesta_troska(q: str = Query(default="", max_length=100),
                        limit: int = Query(default=30, ge=1, le=200),
                        db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Pretraga mjesta troška (vozila) po registraciji/nazivu/sektoru — za ručni odabir."""
    if not aross.konfigurirano(db):
        return []
    try:
        svi = _mjesta_troska(db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    s = q.strip().lower()
    sn = _reg_norm(q)
    if s:
        svi = [m for m in svi if s in (m.get("naziv") or "").lower() or s in (m.get("sektor") or "").lower()
               or (sn and sn in _reg_norm(m.get("naziv"))) or s == str(m.get("sifra"))]
    # Točan GB (šifra) uvijek prvi.
    return sorted(svi, key=lambda m: (str(m.get("sifra")) != s, (m.get("naziv") or "").lower()))[:limit]


@router.get("/aross/izdatnica/{nalog_id}")
def aross_izdatnica_priprema(nalog_id: int, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Što bi se poslalo: mjesto troška pronađeno po registraciji vozila + broj neposlanih stavki."""
    from ..models import Izdatnica, Nalog
    nalog = db.get(Nalog, nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    red = db.query(Izdatnica).filter(Izdatnica.nalog_id == nalog_id, Izdatnica.apross_broj.is_(None)).all()
    out = {"povezano": aross.konfigurirano(db), "neposlane": sum(1 for i in red if i.artikl_sifra),
           "bez_sifre": sum(1 for i in red if not i.artikl_sifra), "mjesto_troska": None,
           "registracija": (nalog.vozilo.registracija if nalog.vozilo else None),
           "gb": (nalog.vozilo.gb if nalog.vozilo else None)}
    if out["povezano"]:
        try:
            out["mjesto_troska"] = _nadji_mjesto_troska(db, nalog)
        except aross.ArossGreska as e:
            out["greska"] = str(e)
    return out


class IzdatnicaSlanjeIn(BaseModel):
    nalog_id: int
    sifra_skladista: int
    sifra_mjesta_troska: int
    datum: str                    # yyyy-MM-dd
    napomena: str | None = None


@router.post("/aross/izdatnica")
def aross_posalji_izdatnicu(p: IzdatnicaSlanjeIn, db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Pošalji sve NEPOSLANE utrošene dijelove naloga (koji imaju Apross šifru) kao jednu
    izdatnicu na teret mjesta troška. ERP broj se zapiše na svaku poslanu stavku."""
    from ..models import Izdatnica, Nalog
    if not aross.konfigurirano(db):
        raise HTTPException(status_code=503, detail="APROSS nije povezan.")
    nalog = db.get(Nalog, p.nalog_id)
    if not nalog:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    red = (db.query(Izdatnica)
           .filter(Izdatnica.nalog_id == p.nalog_id, Izdatnica.apross_broj.is_(None),
                   Izdatnica.artikl_sifra.isnot(None))
           .order_by(Izdatnica.id).all())
    if not red:
        raise HTTPException(status_code=400, detail="Nema neposlanih dijelova s Apross šifrom.")
    gb = (nalog.vozilo.gb if nalog.vozilo else "") or ""
    broj = f"N{nalog.id}-{red[0].id}"   # jedinstven web broj (nalog + prva stavka)
    napomena = p.napomena or (f"Radni nalog #{nalog.id}" + (f", GB {gb}" if gb else ""))
    try:
        rez = aross.kreiraj_izdatnicu(broj, p.datum, p.sifra_skladista, p.sifra_mjesta_troska,
                                      [{"sifraArtikla": i.artikl_sifra, "kolicina": i.kolicina} for i in red],
                                      napomena, db=db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))
    erp = mt = None
    if isinstance(rez, list) and rez and isinstance(rez[0], dict):
        erp = rez[0].get("erpBrojIzdatnice")
        mt = rez[0].get("erpMjestoTroska")
    if erp is None:
        raise HTTPException(status_code=502, detail=f"APROSS nije vratio broj izdatnice: {str(rez)[:200]}")
    for i in red:
        i.apross_broj = int(erp)
    db.commit()
    return {"ok": True, "erp_broj_izdatnice": erp, "erp_mjesto_troska": mt, "stavki": len(red)}


# ================= GPS uređaji → GB (bravel-agent) =================
# Lokacija vozila se veže SAMO po GB-u: bravel-agent pamti koji Mobilisis GPS
# uređaj pripada kojem GB-u (preregistracija to ne mijenja). Ovdje se novi /
# nepovezani uređaj jednom poveže s GB-om.

def _agent(metoda: str, putanja: str, json: dict | None = None):
    from ..config import settings
    if not (settings.bravel_agent_url and settings.bravel_agent_kljuc):
        raise HTTPException(status_code=503, detail="bravel-agent nije konfiguriran")
    import httpx
    try:
        r = httpx.request(metoda, f"{settings.bravel_agent_url.rstrip('/')}{putanja}", json=json,
                          headers={"X-Api-Key": settings.bravel_agent_kljuc}, timeout=30)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"bravel-agent ne odgovara: {e}")
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=data.get("error") or f"bravel-agent HTTP {r.status_code}")
    return data


@router.get("/gps-uredaji")
def gps_uredaji(_: Korisnik = Depends(samo_vlasnik)):
    return _agent("GET", "/api/gps-uredaji")


class GpsVezaIn(BaseModel):
    id: str
    gb: str = ""
    naziv: str = ""


@router.post("/gps-uredaji")
def gps_uredaj_veza(p: GpsVezaIn, _: Korisnik = Depends(samo_vlasnik)):
    gb = (p.gb or "").strip()
    if gb and not gb.isdigit():
        raise HTTPException(status_code=400, detail="GB mora biti broj")
    return _agent("POST", "/api/gps-uredaji", {"id": p.id, "gb": gb, "naziv": p.naziv})
