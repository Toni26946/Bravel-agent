"""Integracija s APROSS ERP-om (Zagreb Data) — API za skladišne dokumente.

Dvostruka autentifikacija:
  1) API-KEY je sastavni dio URL-a:  {base}/{API-KEY}/{endpoint}
  2) HTTP Basic (korisnik/lozinka) na razini zahtjeva.

GET  — šifrarnici (skladišta, artikli, poslovni partneri, mjesta troška = vozila)
       i trenutno stanje zalihe po skladištima.
POST — kreiranje artikla i primke u ERP-u (JSON tijelo, Content-Type application/json).

Sve tajne dolaze iz env/fly secreta (vidi config.py: AROSS_*). Dok API-KEY nije
postavljen, `konfigurirano()` je False i pozivi dižu `ArossNijePovezan` (endpointi
to prevode u uredan 503), pa app radi normalno i bez integracije.
"""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger("aross")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ArossGreska(RuntimeError):
    """Općenita greška u komunikaciji s APROSS API-jem."""


class ArossNijePovezan(ArossGreska):
    """API-KEY / Basic Auth nisu postavljeni — integracija isključena."""


def konfigurirano() -> bool:
    return bool(settings.aross_api_key and settings.aross_user and settings.aross_pass)


def _baza() -> str:
    """Puni prefiks s ključem: https://.../api5/{API-KEY}  (bez završnog /)."""
    return f"{settings.aross_base.rstrip('/')}/{settings.aross_api_key.strip()}"


def _client() -> httpx.Client:
    if not konfigurirano():
        raise ArossNijePovezan("APROSS API nije povezan (nedostaje AROSS_API_KEY/USER/PASS).")
    return httpx.Client(
        base_url=_baza(),
        auth=(settings.aross_user, settings.aross_pass),
        timeout=_TIMEOUT,
        headers={"Accept": "application/json"},
    )


def _json(r: httpx.Response):
    if r.status_code == 401:
        raise ArossGreska("APROSS: neispravna autentifikacija (401) — provjeri API-KEY i korisnika/lozinku.")
    if r.status_code >= 400:
        raise ArossGreska(f"APROSS HTTP {r.status_code}: {(r.text or '')[:300]}")
    try:
        return r.json()
    except ValueError as e:
        raise ArossGreska(f"APROSS: odgovor nije JSON: {e}") from e


# --- GET: šifrarnici i stanje -------------------------------------------------
def _get(putanja: str, params: dict | None = None):
    with _client() as c:
        return _json(c.get(putanja, params=params))


def skladista() -> list[dict]:
    """[{sifra, naziv}] — šifrarnik skladišta."""
    return _get("/skladista/get")


def artikli() -> list[dict]:
    """[{sifra, naziv, kataloskiBroj, jmj}] — šifrarnik artikala."""
    return _get("/artikli/get")


def artikli_stanje() -> list[dict]:
    """Stanje zalihe grupirano po skladištima:
    [{sifraSkladista, nazivSkladista, artikli:[{sifraArtikla, stanje}]}]."""
    return _get("/artikliStanje/get", params={"type": "nested"})


def poslovni_partneri() -> list[dict]:
    """[{sifra, naziv, adresa, mjesto, zip, drzava, oib}] — kupci i dobavljači."""
    return _get("/poslovniPartneri/get")


def mjesta_troska() -> list[dict]:
    """[{sifra, naziv, sektor}] — mjesta troška = vozila/priključna vozila (naziv = reg. oznaka)."""
    return _get("/mjestoTroska/get")


# --- POST: kreiranje u ERP-u --------------------------------------------------
def _post(putanja: str, tijelo: dict):
    with _client() as c:
        return _json(c.post(putanja, json=tijelo))


def kreiraj_artikl(id_artikla: int, naziv: str, jmj: str,
                   kat_broj: str | None = None, barkod: str | None = None) -> list[dict]:
    """Kreira artikl u ERP-u pod šifrom `id_artikla`. Vraća [{webBrojArtikla, erpBrojPrimke}]."""
    tijelo = {"idArtikla": int(id_artikla), "naziv": naziv, "jmj": jmj}
    if kat_broj:
        tijelo["katBroj"] = kat_broj
    if barkod:
        tijelo["barkod"] = barkod
    return _post("/artikli/kreiraj", tijelo)


def kreiraj_primku(broj_primke: str, sifra_dobavljaca: int, datum_dokumenta: str,
                   sifra_skladista: int, stavke: list[dict], napomena: str | None = None) -> list[dict]:
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
    return _post("/primka/kreiraj", tijelo)
