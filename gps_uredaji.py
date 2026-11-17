# ============================================================
#  GPS UREĐAJI → GB  (trajna veza, Toni 17.11.2026.: „fiksno gledaj samo gb")
#
#  Mobilisis za svaki GPS uređaj daje samo stalni broj (Id) i ime (= registracija).
#  Ovdje se pamti koji uređaj pripada kojem GB-u. Kad se kamion preregistrira,
#  uređaj (Id) ostaje isti → GB ostaje isti. Novi uređaj se poveže JEDNOM
#  (automatski ako mu se ime poklopi s registracijom iz GARAŽNI BROJEVI, inače
#  ručno na ekranu „📡 GPS uređaji" u radnim nalozima).
#
#  Datoteka: /data/gps_uredaji.json  {"<id>": {"gb", "izvor", "naziv", "ts"}}
# ============================================================

import json
import os
import threading
from datetime import datetime, timezone

_DATOTEKA = "/data/gps_uredaji.json" if os.path.isdir("/data") else "gps_uredaji.json"
_lock = threading.Lock()
_veze = None   # keš u memoriji


def _ucitaj():
    global _veze
    if _veze is None:
        try:
            with open(_DATOTEKA, encoding="utf-8") as f:
                _veze = json.load(f) or {}
        except FileNotFoundError:
            _veze = {}
        except Exception as e:  # noqa: BLE001 — oštećena datoteka ne smije srušiti GPS
            print(f"[gps_uredaji] ne mogu pročitati {_DATOTEKA}: {e}", flush=True)
            _veze = {}
    return _veze


def _spremi():
    tmp = _DATOTEKA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_veze, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _DATOTEKA)


def gb_za(uredaj_id):
    with _lock:
        v = _ucitaj().get(str(uredaj_id))
    return (v or {}).get("gb") or None


def zapamti(uredaj_id, gb, izvor, naziv=""):
    """Postavi vezu uređaj → GB. gb prazan = odspoji. Vraća novu vezu ili None."""
    kljuc = str(uredaj_id)
    gb = (str(gb or "").strip().lstrip("0") or "") if gb else ""
    with _lock:
        veze = _ucitaj()
        if not gb:
            veze.pop(kljuc, None)
            _spremi()
            return None
        veze[kljuc] = {"gb": gb, "izvor": izvor, "naziv": naziv or "",
                       "ts": datetime.now(timezone.utc).isoformat()}
        _spremi()
        return veze[kljuc]


def zapamti_ako_nema(uredaj_id, gb, izvor, naziv=""):
    """Automatsko učenje: upiše SAMO ako uređaj još nema GB (ručna veza se nikad ne gazi)."""
    if not gb:
        return False
    with _lock:
        if str(uredaj_id) in _ucitaj():
            return False
    zapamti(uredaj_id, gb, izvor, naziv)
    return True


def sve():
    with _lock:
        return dict(_ucitaj())
