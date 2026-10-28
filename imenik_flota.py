# ============================================================
#  imenik_flota.py — brojevi mehaničara iz IMENIKA (Flota OS)
#
#  Flota OS je izvor istine za službene brojeve radnika. Ovdje dohvaćamo SKUP
#  normaliziranih brojeva AKTIVNIH mehaničara (odjel RADIONA) da dispečerski
#  linkovi smiju ići svakom tko je u Imeniku — bez ručnog popisa brojeva.
#
#  Brojevi se NE spremaju lokalno: povlače se s `GET {FLOTA}/api/imenik`
#  (zaglavlje X-Imenik-Kljuc = fly secret IMENIK_KLJUC, isti kao na radni-nalozi)
#  uz kratku predmemoriju (5 min). Ako Flota ne odgovara → zadnji poznati skup
#  (ili prazan). NIKAD ne baca prema pozivatelju.
#
#  Tajne (fly secrets, SAMO nazivi — vrijednosti nikad u repo/chat/log):
#    IMENIK_KLJUC     — isti ključ kao na radni-nalozi (X-Imenik-Kljuc)
#    FLOTA_OS_API_URL — opcionalno, default https://bravel-flota-os-api.fly.dev
#
#  VAŽNO: telefonski brojevi NIKAD ne idu u log.
# ============================================================

import os
import threading
import time

import requests

import monitoring

_TTL = 300.0          # predmemorija 5 min
_TIMEOUT = 15         # sekundi
_ODJEL_MEHANICARI = "RADIONA"

_lock = threading.RLock()
_cache_brojevi = None   # frozenset normaliziranih brojeva ili None (još nedohvaćeno)
_cache_ts = 0.0


def _flota_base():
    # Isti app i default kao servisni pristup u main.py (FLOTA_OS_API_URL).
    return os.getenv("FLOTA_OS_API_URL", "https://bravel-flota-os-api.fly.dev").strip().rstrip("/")


def _norm_broj(s):
    """Kanoniziraj broj na 385… oblik — ISTO kao whatsapp_racuni._norm_broj:
    samo znamenke; 00385→385; vodeća 0 (nacionalni)→385. Tako se poklapa bez
    obzira je li broj upisan s razmakom, +, 00 ili 0."""
    b = "".join(ch for ch in str(s) if ch.isdigit())
    if b.startswith("00"):
        b = b[2:]
    elif b.startswith("0"):
        b = "385" + b[1:]
    return b


def _dohvati_zapise():
    """Jedan poziv Imenika Flote. Vrati listu zapisa; baca na grešci (hvata
    pozivatelj). Odgovor NE logiramo (sadrži brojeve)."""
    kljuc = os.getenv("IMENIK_KLJUC", "").strip()
    if not kljuc:
        raise RuntimeError("IMENIK_KLJUC nije postavljen")
    r = requests.get(f"{_flota_base()}/api/imenik",
                     headers={"X-Imenik-Kljuc": kljuc}, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Flota OS HTTP {r.status_code}")
    d = r.json()
    zapisi = d.get("zapisi") if isinstance(d, dict) else None
    if not isinstance(zapisi, list):
        raise RuntimeError("Flota OS: neočekivan odgovor")
    return zapisi


def _izracunaj_brojeve():
    """Normalizirani brojevi AKTIVNIH mehaničara (odjel RADIONA) iz Imenika."""
    brojevi = set()
    for z in _dohvati_zapise():
        if not isinstance(z, dict):
            continue
        if not z.get("aktivan", True):
            continue
        if str(z.get("odjel") or "").strip().upper() != _ODJEL_MEHANICARI:
            continue
        b = _norm_broj(z.get("broj"))
        if b:
            brojevi.add(b)
    return frozenset(brojevi)


def brojevi_mehanicara():
    """Skup (frozenset) normaliziranih brojeva aktivnih mehaničara (RADIONA) iz
    Imenika. Keširano ~5 min. NIKAD ne baca: na grešci vrati zadnji poznati skup
    (ili prazan ako ga još nema). Brojevi se ne logiraju."""
    global _cache_brojevi, _cache_ts
    with _lock:
        if _cache_brojevi is not None and (time.time() - _cache_ts) < _TTL:
            return _cache_brojevi
    try:
        brojevi = _izracunaj_brojeve()
    except Exception as e:  # noqa: BLE001
        # Tip greške u log (bez brojeva); padni natrag na zadnji poznati skup.
        monitoring.warning(f"Imenik dohvat nije uspio: {type(e).__name__}",
                           source="imenik_flota")
        with _lock:
            return _cache_brojevi if _cache_brojevi is not None else frozenset()
    with _lock:
        _cache_brojevi = brojevi
        _cache_ts = time.time()
    return brojevi
