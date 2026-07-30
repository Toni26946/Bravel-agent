"""Obavijest kad kamion STIGNE na odredište (istovar) — „kraj check-callova".

Scheduler prati GPS pozicije (Mobilisis) i tekuće ture (Flota OS /api/flota/ture,
gdje je odredište = geokodirani istovar zadnjeg naloga). Kad kamion uđe u krug oko
odredišta I stane, obavijest ide u chat PODRŠKA (Flota OS):

    🚚 Dolazak: 📍 GB363 STIGAO na istovar
    Graz · Müller GmbH
    Vozač: Ivan Horvat
    (≈1.2 km od odredišta)

Svaki dolazak se TRAJNO sprema (tablica dolazak_log). Ako u trenutku dolaska nitko
nije spojen na Podršku (Flota OS ugašen/zatvoren), obavijest ostaje „nevidjena" i
šalje se čim se netko sljedeći put spoji (podrska.set_on_open → posalji_backlog) —
tako se nijedan dolazak ne izgubi.

Fire-once po turi: dok je isti istovar+datum, javlja se SAMO prvi dolazak. Nova
tura (drugi istovar/datum) ponovno naoruža. Ako je kamion VEĆ u krugu kad se tura
(ili feature) prvi put vidi, tiho se upamti „stigao" — ne witnessamo putovanje pa
ne spamamo stare parkinge.

Odredište je geokodirano na razini mjesta (baza geofenceova + overlay), pa je prag
namjerno velik (default 3 km). „Stao" filtrira prolaske kroz grad (kamion koji
samo prolazi je blizu ali se giba).

Postavke (env):
  DOLASCI_ON           "1" = uključeno (default off)
  DOLASCI_POLL_SEC     razmak provjere pozicija/tura (default 180 s)
  DOLASCI_PRAG_KM      radijus oko odredišta za „stigao" (default 3.0 km)
  DOLASCI_MAX_BRZINA   najveća brzina da se broji kao „stao" (default 8 km/h)
  DOLASCI_SAMO_GB      (test) samo ovi GB-ovi, zarezom; prazno = svi
"""

import math
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import mobilisis
import monitoring
import podrska

TZ = ZoneInfo("Europe/Zagreb")


def _log(msg):
    print(f"[dolasci] {msg}", flush=True)


# ---- injektirane ovisnosti iz main.py (izbjegavamo kružni import) ----
_db = None                 # tvornica konekcija (main.db)
_flota_get = None          # main._flota_os_get(path, params) -> dict


def konfiguriraj(db_factory, flota_get):
    """Pozvati JEDNOM iz main.py nakon inicijalizacije baze i Flota OS helpera.
    Obavijesti idu u Podršku (podrska.posalji_svima); backlog na otvaranje sesije
    registrira main preko podrska.set_on_open(dolasci.posalji_backlog)."""
    global _db, _flota_get
    _db = db_factory
    _flota_get = flota_get
    _init_tablice()


# ==================== POSTAVKE ====================

def _ukljuceno():
    return os.getenv("DOLASCI_ON", "").strip() == "1"


def _poll_sec():
    try:
        return max(60, int(os.getenv("DOLASCI_POLL_SEC", "180")))
    except ValueError:
        return 180


def _prag_km():
    try:
        return max(0.2, float(os.getenv("DOLASCI_PRAG_KM", "3")))
    except ValueError:
        return 3.0


def _max_brzina():
    try:
        return max(0.0, float(os.getenv("DOLASCI_MAX_BRZINA", "8")))
    except ValueError:
        return 8.0


def _samo_gb():
    """Skup GB-ova za nadzor (test); prazno = svi kamioni."""
    raw = os.getenv("DOLASCI_SAMO_GB", "")
    return {g.strip().lstrip("0") or g.strip()
            for g in raw.replace(";", ",").split(",") if g.strip()}


# ==================== BAZA ====================

def _init_tablice():
    with _db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS dolazak_stanje (
                gb          TEXT PRIMARY KEY,
                tura_kljuc  TEXT,   -- 'istovar_ime|datum' (naoružanje po turi)
                stanje      TEXT,   -- 'putuje' | 'stigao'
                ts          REAL    -- kad je stanje zadnji put dirano
            )
        """)
        # Trajni dnevnik dolazaka — da se obavijest ne izgubi ako u tom trenu nitko
        # nije spojen na Podršku (vidjeno=0 → pošalje se na sljedeće otvaranje sesije).
        c.execute("""
            CREATE TABLE IF NOT EXISTS dolazak_log (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                gb       TEXT,
                mjesto   TEXT,
                nalog    TEXT,
                vozac    TEXT,
                dist_km  REAL,
                ts       REAL,      -- vrijeme dolaska (epoch)
                poruka   TEXT,      -- gotov tekst obavijesti
                vidjeno  INTEGER DEFAULT 0   -- 1 = predano bar jednoj Podrška sesiji
            )
        """)


def _stanje(gb):
    with _db() as c:
        return c.execute(
            "SELECT gb, tura_kljuc, stanje, ts FROM dolazak_stanje WHERE gb=?",
            (gb,)).fetchone()


def _spremi(gb, tura_kljuc, stanje):
    with _db() as c:
        c.execute(
            "INSERT INTO dolazak_stanje (gb, tura_kljuc, stanje, ts) "
            "VALUES (?,?,?,?) ON CONFLICT(gb) DO UPDATE SET "
            "tura_kljuc=excluded.tura_kljuc, stanje=excluded.stanje, ts=excluded.ts",
            (gb, tura_kljuc, stanje, time.time()))


# ==================== POMOĆNO ====================

def _ngb(g):
    d = "".join(ch for ch in str(g or "") if ch.isdigit())
    return d.lstrip("0") or d


def _km(la1, lo1, la2, lo2):
    """Haversine udaljenost u kilometrima."""
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _poz_po_gb(pozicije):
    out = {}
    for p in pozicije:
        g = _ngb(p.get("gb"))
        if g and p.get("lat") is not None and p.get("lon") is not None:
            out[g] = p
    return out


def _tura_kljuc(t, ist):
    return f"{ist.get('ime', '')}|{t.get('datum', '')}"


# ==================== SCHEDULER ====================

_zadnji_poll = 0.0


def tick():
    """Pozvati često (iz check_reminders svakih 10 s). Sam throttla; radi samo ako
    je DOLASCI_ON=1. Mrežni dio ide u nit — ne blokira."""
    global _zadnji_poll
    if not _ukljuceno():
        return
    now = time.time()
    if now - _zadnji_poll < _poll_sec():
        return
    _zadnji_poll = now
    import threading
    threading.Thread(target=obradi_ciklus, daemon=True).start()


def obradi_ciklus():
    """Jedan prolaz: pozicije + tekuće ture → detekcija dolaska na istovar. Fire-once
    po turi. Best-effort; nikad ne baca."""
    if not _ukljuceno():
        return
    try:
        pozicije = mobilisis.all_positions()
    except Exception as e:
        monitoring.warning(f"Dolasci: pozicije nedostupne: {e}", source="dolasci")
        return
    try:
        odg = _flota_get("/api/flota/ture") or {}
    except Exception as e:
        monitoring.warning(f"Dolasci: ture nedostupne: {e}", source="dolasci")
        return
    ture = (odg or {}).get("ture") or {}
    if not ture:
        return

    # Počisti stare VIDJENE zapise (nevidjene NE diramo — čekaju Podršku).
    try:
        with _db() as c:
            c.execute("DELETE FROM dolazak_log WHERE vidjeno=1 AND ts < ?",
                      (time.time() - 30 * 86400,))
    except Exception:
        pass

    poz = _poz_po_gb(pozicije)
    samo = _samo_gb()
    prag = _prag_km()
    maxb = _max_brzina()

    for gb_raw, t in ture.items():
        gb = _ngb(gb_raw)
        if not gb or (samo and gb not in samo):
            continue
        ist = (t or {}).get("istovar") or {}
        la, lo = ist.get("lat"), ist.get("lon")
        if la is None or lo is None:
            continue                              # odredište nije geokodirano
        p = poz.get(gb)
        if not p:
            continue                              # nemamo GPS za taj kamion
        dist = _km(float(p["lat"]), float(p["lon"]), float(la), float(lo))
        brzina = p.get("brzina")
        stao = (brzina is None) or (float(brzina) <= maxb)
        blizu = dist <= prag
        kljuc = _tura_kljuc(t, ist)

        st = _stanje(gb)
        if st is None or st["tura_kljuc"] != kljuc:
            # Nova / prvi put viđena tura → upamti baseline BEZ javljanja. Ako je
            # kamion već tu i stao, tiho ga označi „stigao" (nismo vidjeli dolazak).
            _spremi(gb, kljuc, "stigao" if (blizu and stao) else "putuje")
            continue

        if st["stanje"] != "stigao" and blizu and stao:
            _javi_dolazak(gb, t, dist)
            _spremi(gb, kljuc, "stigao")
        elif st["stanje"] == "stigao" and not blizu:
            _spremi(gb, kljuc, "putuje")          # otišao → naoružaj za novi dolazak


def _javi_dolazak(gb, t, dist):
    ist = (t or {}).get("istovar") or {}
    mjesto = ist.get("ime") or "odredište"
    nalog = t.get("nalogodavac")
    vozac = t.get("vozac")
    vrijeme = datetime.now(TZ).strftime("%H:%M")
    reci = [f"📍 GB{gb} STIGAO na istovar u {vrijeme}",
            mjesto + (f" · {nalog}" if nalog else "")]
    if vozac:
        reci.append(f"Vozač: {vozac}")
    reci.append(f"(≈{dist:.1f} km od odredišta)")
    poruka = "\n".join(reci)

    # 1) TRAJNO spremi (nevidjeno) — da se ne izgubi ako nitko nije spojen na Podršku.
    rid = None
    try:
        with _db() as c:
            cur = c.execute(
                "INSERT INTO dolazak_log (gb, mjesto, nalog, vozac, dist_km, ts, poruka, vidjeno) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (gb, mjesto, nalog, vozac, round(dist, 2), time.time(), poruka))
            rid = cur.lastrowid
    except Exception as e:
        monitoring.warning(f"Dolasci GB{gb}: spremanje: {e}", source="dolasci")

    # 2) UŽIVO u Podršku (svima spojenima). Ako je bar jedan primio → označi vidjeno.
    try:
        n = podrska.posalji_svima(poruka, od="🚚 Dolazak")
    except Exception as e:
        n = 0
        monitoring.warning(f"Dolasci GB{gb}: Podrška broadcast: {e}", source="dolasci")
    if n > 0 and rid is not None:
        try:
            with _db() as c:
                c.execute("UPDATE dolazak_log SET vidjeno=1 WHERE id=?", (rid,))
        except Exception:
            pass
    _log(f"GB{gb} dolazak: {mjesto} ({dist:.1f} km) → Podrška sesija={n}.")


def posalji_backlog(session_id):
    """Kad se netko spoji na Podršku (podrska.set_on_open), pošalji mu propuštene
    (nevidjene) dolaske po redu i označi ih vidjenima — tako se nijedan ne izgubi."""
    if _db is None:
        return
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT id, poruka FROM dolazak_log WHERE vidjeno=0 ORDER BY ts LIMIT 50"
            ).fetchall()
        if not rows:
            return
        for r in rows:
            podrska.posalji_klijentu(session_id, r["poruka"], od="🚚 Dolazak (propušteno)")
        with _db() as c:
            c.executemany("UPDATE dolazak_log SET vidjeno=1 WHERE id=?",
                          [(r["id"],) for r in rows])
        _log(f"Backlog: {len(rows)} propuštenih dolazaka poslano sesiji #{session_id}.")
    except Exception as e:
        monitoring.warning(f"Dolasci backlog: {e}", source="dolasci")


# ==================== PREGLED (za /dolasci — owner test) ====================

def pregled():
    """Tekstualni pregled: za svaku tekuću turu udaljenost kamiona do odredišta i
    status. Za /dolasci naredbu — read-only, ništa ne šalje vlasnicima."""
    if _db is None:
        return "Dolasci nisu konfigurirani."
    try:
        pozicije = mobilisis.all_positions()
    except Exception as e:
        return f"⚠️ Pozicije nedostupne: {e}"
    try:
        odg = _flota_get("/api/flota/ture") or {}
    except Exception as e:
        return f"⚠️ Ture nedostupne: {e}"
    ture = (odg or {}).get("ture") or {}
    if not ture:
        return "Nema tekućih tura (Flota OS)."
    poz = _poz_po_gb(pozicije)
    prag = _prag_km()
    reci = []
    for gb_raw, t in sorted(ture.items(), key=lambda kv: int(_ngb(kv[0]) or 0)):
        gb = _ngb(gb_raw)
        ist = (t or {}).get("istovar") or {}
        if ist.get("lat") is None or ist.get("lon") is None:
            continue                              # bez koordinata → preskoči
        p = poz.get(gb)
        if not p:
            reci.append(f"• GB{gb} → {ist.get('ime', '?')}: nema GPS-a")
            continue
        d = _km(float(p["lat"]), float(p["lon"]), float(ist["lat"]), float(ist["lon"]))
        reci.append(f"{'✅' if d <= prag else '🚚'} GB{gb} → {ist.get('ime', '?')}: {d:.0f} km")
    if not reci:
        return "Nema tura s geokodiranim odredištem."
    stat = "UKLJUČENO" if _ukljuceno() else "ISKLJUČENO (DOLASCI_ON=1 za uključ.)"
    glava = f"📍 DOLASCI · prag {prag:.0f} km · {stat}\n\n"
    # Zadnji zabilježeni dolasci + koliko ih čeka (nevidjeno) na Podršci.
    rep = ""
    try:
        with _db() as c:
            nevid = c.execute("SELECT COUNT(*) n FROM dolazak_log WHERE vidjeno=0").fetchone()["n"]
            zadnji = c.execute(
                "SELECT gb, mjesto, ts FROM dolazak_log ORDER BY ts DESC LIMIT 5"
            ).fetchall()
        if zadnji:
            rep = "\n\n— zadnji dolasci —\n" + "\n".join(
                f"• GB{r['gb']} → {r['mjesto']}" for r in zadnji)
            if nevid:
                rep += f"\n({nevid} čeka na Podršci — nevidjeno)"
    except Exception:
        pass
    return glava + "\n".join(reci) + rep
