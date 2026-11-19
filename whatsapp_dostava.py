# ============================================================
#  WHATSAPP DOSTAVA — praćenje statusa poslanih poruka (Meta webhook „statuses")
#
#  Meta na slanje odgovori 200 + id poruke čim PRIMI zahtjev, a stvarnu
#  isporuku javi KASNIJE webhookom (sent → delivered → read, ili failed s
#  kodom greške). Dosad se taj dio webhooka ignorirao, pa je Flota OS
#  pokazivala „POSLAN" i kad vozač poruku nikad nije dobio (WhatsApp prijava
#  #304, Marko 17.11.2026.: „nitko od ovih vozača nije dobio nalog").
#
#  Ovdje: zapamti što je poslano (id → opis, npr. „nalog vozaču X"), iz
#  webhooka izvuci neuspjele isporuke i složi čitljivu poruku za vlasnike
#  (Telegram). Čisti stdlib — testira se bez mreže i bez aiohttp-a.
#  Brojevi se nikad ne zapisuju cijeli (samo maska).
# ============================================================

import threading
import time

_MAX = 2000             # najviše zapamćenih poslanih poruka
_TRAJANJE_S = 3 * 86400  # status stiže brzo, ali neuspjeh zna doći i nakon sati

_lock = threading.Lock()
_poslano = {}   # id poruke → {"opis", "maska", "ts", "status", "greska"}

# Najčešći kodovi neuspjele isporuke → objašnjenje na hrvatskom
_KODOVI = {
    131026: "poruka se ne može isporučiti — broj nema WhatsApp, krivo je upisan ili vozač ima staru verziju WhatsAppa",
    131049: "Meta ju je zadržala (ograničenje poruka po primatelju — predložak se tretira kao marketinški)",
    131050: "primatelj je isključio poslovne/marketinške poruke",
    131042: "problem s plaćanjem na WhatsApp Business računu (Meta Business → Plaćanja)",
    131047: "prošlo je više od 24 h od zadnje poruke vozača (treba predložak)",
    131051: "nepodržana vrsta poruke",
    131053: "privitak se ne može poslati",
    131000: "nepoznata greška na Meti",
    130472: "Meta eksperiment — broj je u testnoj skupini, poruka nije isporučena",
    132000: "broj parametara predloška ne odgovara",
    132001: "predložak ne postoji ili nije odobren",
    132015: "predložak je pauziran (loša kvaliteta)",
    132016: "predložak je isključen",
    368: "broj je privremeno blokiran zbog kršenja pravila",
}


def maska(broj):
    b = str(broj or "")
    return b[:5] + "…" + b[-3:] if len(b) > 8 else b


def zapamti(msg_id, opis, broj=None):
    """Zapamti poslanu poruku da se kasniji status (failed) može povezati s njom."""
    if not msg_id:
        return
    sad = time.time()
    with _lock:
        _poslano[str(msg_id)] = {"opis": str(opis or "")[:200], "maska": maska(broj),
                                 "ts": sad, "status": "poslan", "greska": None}
        if len(_poslano) > _MAX:
            # makni najstarije
            for k, _ in sorted(_poslano.items(), key=lambda kv: kv[1]["ts"])[:len(_poslano) - _MAX]:
                _poslano.pop(k, None)


def id_iz_odgovora(res):
    """Id poruke iz odgovora whatsapp.send_* ({ok,status,data}) ili None."""
    try:
        return (res.get("data") or {}).get("messages", [{}])[0].get("id")
    except Exception:
        return None


def stanje(msg_id):
    with _lock:
        z = _poslano.get(str(msg_id))
        return dict(z) if z else None


def opis_greske(err):
    """Jedna greška iz statuses[].errors → čitljiv tekst."""
    if not isinstance(err, dict):
        return "nepoznata greška"
    kod = err.get("code")
    try:
        kod_i = int(kod)
    except (TypeError, ValueError):
        kod_i = None
    tekst = _KODOVI.get(kod_i) or err.get("title") or err.get("message") or "nepoznata greška"
    detalji = (err.get("error_data") or {}).get("details") if isinstance(err.get("error_data"), dict) else None
    out = f"{tekst} (kod {kod})" if kod is not None else tekst
    if detalji and detalji not in out:
        out += f" — {detalji}"
    return out


def obradi_statuse(value):
    """Iz jednog `value` bloka Meta webhooka obradi `statuses`.
    Ažurira zapamćene poruke i vrati popis NEUSPJELIH isporuka:
    [{"id", "opis", "maska", "greska"}]. Ostali statusi (sent/delivered/read)
    samo se zapišu."""
    neuspjele = []
    if not isinstance(value, dict):
        return neuspjele
    sad = time.time()
    for s in value.get("statuses", []) or []:
        if not isinstance(s, dict):
            continue
        mid = str(s.get("id") or "")
        st = str(s.get("status") or "")
        with _lock:
            z = _poslano.get(mid)
            # ne vraćaj status unatrag (read pa zakašnjeli delivered)
            if z is not None and st in ("sent", "delivered", "read", "failed"):
                red = ["poslan", "sent", "delivered", "read"]
                if st == "failed" or z["status"] not in red or red.index(st) >= red.index(z["status"]):
                    z["status"] = st
            # stare zapise počisti usput
            for k in [k for k, v in _poslano.items() if sad - v["ts"] > _TRAJANJE_S]:
                _poslano.pop(k, None)
        if st != "failed":
            # trag u logu (fly logs) za naše poruke — da se vidi je li stvarno stiglo
            if z is not None and st in ("delivered", "read"):
                print(f"[dostava] {z['opis']} ({z['maska']}): {st}", flush=True)
            continue
        errs = s.get("errors") or [{}]
        greska = "; ".join(opis_greske(e) for e in errs)
        print(f"[dostava] NEUSPJELO {(z or {}).get('opis', 'poruka')} "
              f"({(z or {}).get('maska') or maska(s.get('recipient_id'))}): {greska}", flush=True)
        with _lock:
            z = _poslano.get(mid)
            if z is not None:
                z["greska"] = greska
            opis = z["opis"] if z else "poruka"
            msk = z["maska"] if z else maska(s.get("recipient_id"))
        neuspjele.append({"id": mid, "opis": opis, "maska": msk, "greska": greska})
    return neuspjele


def poruka_vlasnicima(neuspjele):
    """Složi Telegram poruku za vlasnike iz popisa neuspjelih isporuka."""
    if not neuspjele:
        return ""
    redovi = [f"⚠️ WhatsApp poruka NIJE isporučena ({len(neuspjele)}):"]
    for n in neuspjele[:15]:
        redovi.append(f"• {n['opis']} ({n['maska']}): {n['greska']}")
    if len(neuspjele) > 15:
        redovi.append(f"… i još {len(neuspjele) - 15}")
    redovi.append("U Floti OS stoji „POSLAN”, ali vozač poruku nije dobio — pošalji mu link ručno.")
    return "\n".join(redovi)


class Skupljac:
    """Skupi neuspjele isporuke par sekundi pa ih javi JEDNOM porukom
    (Flota šalje 6 naloga zaredom → ne 6 zasebnih upozorenja)."""

    def __init__(self, javi, odgoda_s=20.0):
        self._javi = javi
        self._odgoda = odgoda_s
        self._lock = threading.Lock()
        self._red = []
        self._timer = None

    def dodaj(self, neuspjele):
        if not neuspjele:
            return
        with self._lock:
            self._red.extend(neuspjele)
            if self._timer is None:
                self._timer = threading.Timer(self._odgoda, self.isprazni)
                self._timer.daemon = True
                self._timer.start()

    def isprazni(self):
        with self._lock:
            red, self._red, self._timer = self._red, [], None
        if red:
            try:
                self._javi(poruka_vlasnicima(red))
            except Exception:
                pass
