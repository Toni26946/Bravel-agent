"""IMENIK / TELEFONI — samo za ČITANJE, uživo iz Flota OS-a.

Flota OS je jedini izvor istine za službene brojeve radnika (tamo se uređuju). Ovdje se brojevi
NE spremaju u bazu: povlače se s `GET {flota_api_base}/api/imenik` (zaglavlje X-Imenik-Kljuc = fly
secret IMENIK_KLJUC, isti na obje aplikacije) uz kratku predmemoriju u memoriji (5 min), pa na oba
portala uvijek piše isto. Ako Flota ne odgovara, vraća se zadnji dobar odgovor (oznaka `zastarjelo`)
ili prazan popis s porukom — stranica se nikad ne ruši.

Telefonski brojevi NIKAD ne idu u log.
"""
import logging
import time
import unicodedata

import httpx

from .config import settings

log = logging.getLogger("imenik")

TTL_S = 300                                  # predmemorija 5 min
_kes: dict = {"ts": 0.0, "podaci": None}     # zadnji USPJEŠAN odgovor Flote


def konfigurirano() -> bool:
    return bool(settings.imenik_kljuc)


def _dohvati_flotu() -> dict:
    """Jedan poziv Flote. Baca iznimku na svaku grešku (poziva ga dohvati)."""
    base = settings.flota_api_base.rstrip("/")
    r = httpx.get(f"{base}/api/imenik", headers={"X-Imenik-Kljuc": settings.imenik_kljuc}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Flota OS HTTP {r.status_code}")
    d = r.json()
    if not isinstance(d, dict) or not isinstance(d.get("zapisi"), list):
        raise RuntimeError("Flota OS: neočekivan odgovor")
    return d


def dohvati(osvjezi: bool = False) -> dict:
    """{zapisi, broj, odjeli, azurirano, dohvaceno, zastarjelo, greska}. Nikad ne baca."""
    sad = time.time()
    if not osvjezi and _kes["podaci"] is not None and sad - _kes["ts"] < TTL_S:
        return {**_kes["podaci"], "dohvaceno": _kes["ts"], "zastarjelo": False, "greska": None}
    if not konfigurirano():
        greska = "Imenik nije povezan s Flota OS-om (nedostaje IMENIK_KLJUC)."
    else:
        try:
            d = _dohvati_flotu()
            podaci = {"zapisi": [z for z in d["zapisi"] if z.get("aktivan", True)],
                      "odjeli": d.get("odjeli") or [], "azurirano": d.get("azurirano")}
            podaci["broj"] = len(podaci["zapisi"])
            _kes["podaci"], _kes["ts"] = podaci, sad
            return {**podaci, "dohvaceno": sad, "zastarjelo": False, "greska": None}
        except Exception as e:  # noqa: BLE001
            log.warning("Imenik: Flota OS ne odgovara (%s)", type(e).__name__)
            greska = "Flota OS trenutno ne odgovara — imenik se ne može osvježiti."
    if _kes["podaci"] is not None:
        return {**_kes["podaci"], "dohvaceno": _kes["ts"], "zastarjelo": True, "greska": greska}
    return {"zapisi": [], "broj": 0, "odjeli": [], "azurirano": None, "dohvaceno": None,
            "zastarjelo": True, "greska": greska}


class GreskaUpisa(Exception):
    """Flota je odbila upis (status + poruka za korisnika)."""

    def __init__(self, status: int, poruka: str):
        super().__init__(poruka)
        self.status = status
        self.poruka = poruka


def _posalji_flotu(putanja: str, json: dict | None = None, params: dict | None = None) -> dict:
    """POST na Flotu ključem radione. Baca GreskaUpisa (nikad sirovu iznimku s podacima)."""
    if not settings.imenik_radiona_kljuc:
        raise GreskaUpisa(503, "Upis u imenik nije uključen (nedostaje IMENIK_RADIONA_KLJUC).")
    base = settings.flota_api_base.rstrip("/")
    try:
        r = httpx.post(f"{base}{putanja}", json=json, params=params, timeout=15,
                       headers={"X-Imenik-Radiona-Kljuc": settings.imenik_radiona_kljuc})
    except Exception as e:  # noqa: BLE001
        log.warning("Imenik upis: Flota OS ne odgovara (%s)", type(e).__name__)
        raise GreskaUpisa(502, "Flota OS trenutno ne odgovara — broj nije spremljen.")
    if r.status_code != 200:
        try:
            poruka = r.json().get("detail") or f"Flota OS HTTP {r.status_code}"
        except Exception:  # noqa: BLE001
            poruka = f"Flota OS HTTP {r.status_code}"
        raise GreskaUpisa(r.status_code if r.status_code in (400, 403, 404) else 502, str(poruka))
    return r.json()


def spremi_radiona(d: dict, korisnik_ime: str) -> dict:
    """Novi broj ili ispravak — SAMO odjel RADIONA (Flota to i sama prisiljava). Nakon upisa se
    predmemorija odmah osvježi, pa korisnik odmah vidi novo stanje. Vraća svježi imenik."""
    polja = ("id", "ime", "opis", "broj", "kratki", "tarifa", "napomena")
    _posalji_flotu("/api/imenik/radiona", json={**{k: d.get(k) for k in polja}, "korisnik": korisnik_ime})
    return dohvati(osvjezi=True)


def postavi_aktivan_radiona(rid: int, aktivan: bool, korisnik_ime: str) -> dict:
    _posalji_flotu(f"/api/imenik/radiona/{int(rid)}/aktivan",
                   params={"aktivan": "true" if aktivan else "false", "korisnik": korisnik_ime})
    return dohvati(osvjezi=True)


def kljuc_imena(ime: str | None) -> str:
    """„Kovač Marko" == „marko KOVAC": bez dijakritike, mala slova, riječi sortirane."""
    s = str(ime or "").replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(w for w in "".join(ch if ch.isalnum() else " " for ch in s).split() if w))


def brojevi_po_imenu(zapisi: list) -> dict:
    """{kljuc_imena: {broj, kratki}} SAMO za imena s jednim jedinim brojem (siguran spoj).
    Ime koje se pojavljuje s više različitih brojeva se izostavlja — radije ništa nego krivi broj."""
    po: dict = {}
    for z in zapisi:
        k = kljuc_imena(z.get("ime"))
        if k:
            po.setdefault(k, {})[z.get("broj")] = z.get("kratki")
    return {k: {"broj": b, "kratki": v[b]} for k, v in po.items() if len(v) == 1 for b in v}
