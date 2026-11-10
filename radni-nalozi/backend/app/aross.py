"""Integracija s APROSS ERP-om (Zagreb Data) — API za skladišne dokumente.

Dvostruka autentifikacija:
  1) API-KEY je sastavni dio URL-a:  {base}/{API-KEY}/{endpoint}
  2) HTTP Basic (korisnik/lozinka) na razini zahtjeva — OPCIONALNO (ZGData ga
     dodaje naknadno; testno okruženje radi i samo s ključem).

GET  — šifrarnici (skladišta, artikli, poslovni partneri, mjesta troška = vozila)
       i trenutno stanje zalihe po skladištima.
POST — kreiranje artikla i primke u ERP-u (JSON tijelo, Content-Type application/json).

Pristupni podaci se čitaju PRVO iz baze (postavke `aross_api_key/user/pass`), a
ako ih tamo nema — iz env/fly secreta (AROSS_*). Tako Toni ključ zalijepi izravno
u portal (Šifrarnik → Integracije), bez terminala. Dok ključa nema, `konfigurirano()`
je False i pozivi dižu `ArossNijePovezan` (endpointi to prevode u uredan 503).
"""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger("aross")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Ključevi u tablici postavki (imaju prednost pred env varijablama).
P_KEY = "aross_api_key"
P_USER = "aross_user"
P_PASS = "aross_pass"


class ArossGreska(RuntimeError):
    """Općenita greška u komunikaciji s APROSS API-jem."""


class ArossNijePovezan(ArossGreska):
    """API-KEY nije postavljen — integracija isključena."""


def _postavka(db, kljuc: str) -> str:
    if db is None:
        return ""
    try:
        from .norme import get_postavka
        return (get_postavka(db, kljuc, "") or "").strip()
    except Exception:  # noqa: BLE001 — postavke su opcionalne, padni na env
        return ""


def _konf(db=None) -> tuple[str, str, str]:
    """(api_key, user, pass) — prvo iz baze (postavke), pa iz env/secreta."""
    key = _postavka(db, P_KEY) or (settings.aross_api_key or "").strip()
    user = _postavka(db, P_USER) or (settings.aross_user or "")
    pw = _postavka(db, P_PASS) or (settings.aross_pass or "")
    return key, user, pw


def konfigurirano(db=None) -> bool:
    key, _u, _p = _konf(db)
    return bool(key)


def ima_basic(db=None) -> bool:
    _k, user, pw = _konf(db)
    return bool(user and pw)


def _baza(db=None) -> str:
    """Puni prefiks s ključem: https://.../api5/{API-KEY}  (bez završnog /)."""
    key, _u, _p = _konf(db)
    return f"{settings.aross_base.rstrip('/')}/{key}"


def _client(db=None) -> httpx.Client:
    key, user, pw = _konf(db)
    if not key:
        raise ArossNijePovezan("APROSS API nije povezan (nedostaje API-KEY).")
    auth = (user, pw) if (user and pw) else None
    return httpx.Client(
        base_url=f"{settings.aross_base.rstrip('/')}/{key}",
        auth=auth,
        timeout=_TIMEOUT,
        headers={"Accept": "application/json"},
    )


def _json(r: httpx.Response):
    if r.status_code == 401:
        raise ArossGreska("APROSS: neispravna autentifikacija (401) — provjeri API-KEY i korisnika/lozinku.")
    if r.status_code >= 400:
        raise ArossGreska(f"APROSS HTTP {r.status_code}: {(r.text or '')[:300]}")
    try:
        data = r.json()
    except ValueError as e:
        raise ArossGreska(f"APROSS: odgovor nije JSON: {e}") from e
    # APROSS vraća grešku kao HTTP 200 s tijelom [{"message": "..."}] (npr. "Unauthorized
    # access" kad nedostaje Basic Auth). Prepoznaj i digni jasnu grešku.
    el = data[0] if isinstance(data, list) and len(data) == 1 else (data if isinstance(data, dict) else None)
    if isinstance(el, dict) and set(el.keys()) == {"message"}:
        msg = str(el.get("message") or "").strip()
        if "unauthor" in msg.lower():
            raise ArossGreska(f"APROSS: {msg} — treba Basic Auth (korisnik i lozinka).")
        raise ArossGreska(f"APROSS: {msg}")
    return data


# --- GET: šifrarnici i stanje -------------------------------------------------
def _get(putanja: str, params: dict | None = None, db=None):
    with _client(db) as c:
        return _json(c.get(putanja, params=params))


def skladista(db=None) -> list[dict]:
    """[{sifra, naziv}] — šifrarnik skladišta."""
    return _get("/skladista/get", db=db)


def artikli(db=None) -> list[dict]:
    """[{sifra, naziv, kataloskiBroj, jmj}] — šifrarnik artikala."""
    return _get("/artikli/get", db=db)


def artikli_stanje(db=None) -> list[dict]:
    """Stanje zalihe grupirano po skladištima:
    [{sifraSkladista, nazivSkladista, artikli:[{sifraArtikla, stanje}]}]."""
    return _get("/artikliStanje/get", params={"type": "nested"}, db=db)


def poslovni_partneri(db=None) -> list[dict]:
    """[{sifra, naziv, adresa, mjesto, zip, drzava, oib}] — kupci i dobavljači."""
    return _get("/poslovniPartneri/get", db=db)


def mjesta_troska(db=None) -> list[dict]:
    """[{sifra, naziv, sektor}] — mjesta troška = vozila/priključna vozila (naziv = reg. oznaka)."""
    return _get("/mjestoTroska/get", db=db)


# --- POST: kreiranje u ERP-u --------------------------------------------------
def _post(putanja: str, tijelo: dict, db=None):
    with _client(db) as c:
        return _json(c.post(putanja, json=tijelo))


def kreiraj_artikl(id_artikla: int, naziv: str, jmj: str,
                   kat_broj: str | None = None, barkod: str | None = None, db=None) -> list[dict]:
    """Kreira artikl u ERP-u pod šifrom `id_artikla`. Vraća [{webBrojArtikla, erpBrojPrimke}]."""
    tijelo = {"idArtikla": int(id_artikla), "naziv": naziv, "jmj": jmj}
    if kat_broj:
        tijelo["katBroj"] = kat_broj
    if barkod:
        tijelo["barkod"] = barkod
    return _post("/artikli/kreiraj", tijelo, db=db)


def kreiraj_primku(broj_primke: str, sifra_dobavljaca: int, datum_dokumenta: str,
                   sifra_skladista: int, stavke: list[dict], napomena: str | None = None, db=None) -> list[dict]:
    """Kreira primku u ERP-u. `datum_dokumenta` u obliku 'yyyy-MM-dd'.

    `stavke` = [{sifraArtikla, kolicina, cijena, iznos}]. `ukupanIznos` se računa
    kao zbroj stavki. Vraća [{webBrojPrimke, erpBrojPrimke}]."""
    ciste: list[dict] = []
    ukupno = 0.0
    for s in stavke:
        kol = float(s["kolicina"])
        cij = float(s["cijena"])
        izn = float(s.get("iznos") if s.get("iznos") is not None else round(kol * cij, 2))
        ukupno += izn
        ciste.append({"sifraArtikla": int(s["sifraArtikla"]), "kolicina": kol, "cijena": cij, "iznos": izn})
    tijelo = {
        "brojPrimke": str(broj_primke),
        "sifraDobavljaca": int(sifra_dobavljaca),
        "datumDokumenta": datum_dokumenta,
        "sifraSkladista": int(sifra_skladista),
        "ukupanIznos": round(ukupno, 2),
        "stavke": ciste,
    }
    if napomena:
        tijelo["napomena"] = napomena
    return _post("/primka/kreiraj", tijelo, db=db)
