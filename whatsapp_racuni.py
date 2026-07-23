# ============================================================
#  whatsapp_racuni.py — obrada RAČUNA/PRIMKI na WhatsApp
#
#  Ovlašteni zaposlenik (broj u WHATSAPP_ALLOWED) pošalje FOTOGRAFIJU računa
#  ili primke na WhatsApp poslovni broj. Tok:
#    slika(e) → Claude vision (racuni._read_document) → pitaj GB → potvrda
#    (gumbi) → upis na SharePoint (racuni._write_once) → poruka natrag.
#
#  Ponovno koristi ČISTU jezgru iz racuni.py (vision + build_rows + upis +
#  upload slike + summary). Vlastito stanje sesije (po broju telefona) i
#  vlastiti WhatsApp I/O — Telegram tok ostaje netaknut.
#
#  v3:
#   - VIŠESTRANIČNI dokumenti: više fotografija poslanih uzastopno sakupe se
#     u jedan dokument (debounce prozor _PAGE_WINDOW; „gotovo” završava odmah).
#   - PROMIJENI VRSTU (račun↔primka): tijekom potvrde napiši „vrsta” →
#     ponovno čitanje istih slika kao druga vrsta (WhatsApp dopušta max 3
#     gumba, pa ide tekstom umjesto 4. gumba).
#   - IMENA VOZAČA po broju: WHATSAPP_DRIVERS mapira broj → ime (+ zadani GB),
#     pa u tablicu ide pravo ime umjesto WhatsApp profila/broja.
#
#  Ograničenje: sve poruke idu unutar 24 h prozora (zaposlenik piše prvi),
#  pa NE treba predložak.
# ============================================================

import os
import time
import threading

import racuni
import whatsapp
import monitoring

_sessions = {}          # broj → sess (racuni-kompatibilan dict)
_pending = {}           # broj → {"images":[(bytes,mime)], "ime":str, "timer":Timer}
_obrada = set()         # brojevi kojima upravo čitamo dokument (vision u tijeku)
_lock = threading.RLock()

# Koliko sekundi čekamo daljnje stranice prije obrade (album/više fotki zaredom).
_PAGE_WINDOW = float(os.getenv("WHATSAPP_PAGE_WINDOW", "8"))

# Potvrde: id gumba / prihvatljivi tekst
_DA = {"wa_ok", "upiši", "upisi", "da", "ok", "potvrdi", "✅"}
_NE = {"wa_no", "odbaci", "ne", "poništi", "ponisti", "❌"}
_ISPRAVI = {"wa_ed", "ispravi", "✏️"}
_VRSTA = {"vrsta", "promijeni", "promijeni vrstu", "druga vrsta", "preokreni", "🔄"}
_GOTOVO = {"gotovo", "gotov", "kraj", "to je to", "završi", "zavrsi", "dosta"}

_drivers_cache = None


def _log(msg):
    print(f"[wa_racuni] {msg}", flush=True)


def _norm_broj(s):
    """Kanoniziraj broj na oblik koji WhatsApp šalje (samo znamenke, 385…):
    makni sve osim znamenki; 00385→385; vodeća 0 (nacionalni)→385. Tako se
    poklapa bez obzira je li u secretu upisan s razmakom, +, 00 ili 0."""
    b = "".join(ch for ch in str(s) if ch.isdigit())
    if b.startswith("00"):
        b = b[2:]
    elif b.startswith("0"):
        b = "385" + b[1:]
    return b


def allowed_set():
    """Skup ovlaštenih brojeva iz WHATSAPP_ALLOWED (zarez/točka-zarez),
    normaliziranih na 385… oblik (otporno na format upisa)."""
    raw = os.getenv("WHATSAPP_ALLOWED", "")
    return {_norm_broj(b) for b in raw.replace(";", ",").split(",") if b.strip()}


def is_allowed(frm):
    return _norm_broj(frm) in allowed_set()


def zauzet(frm):
    """True ako je za taj broj aktivan tok računa/primke (sesija, sakupljanje
    stranica ili obrada) — izbornik tad ne preuzima poruku."""
    with _lock:
        return frm in _sessions or frm in _pending or frm in _obrada


def _drivers_map():
    """WHATSAPP_DRIVERS → {broj: (ime, zadani_gb ili None)}.
    Format (entry sep ';' ili novi red): '385994396448=Ivan Ivić:GB123-AB'
    (dio ':GB' je opcionalan). Keširano — fly restarta app na promjenu secreta."""
    global _drivers_cache
    if _drivers_cache is not None:
        return _drivers_cache
    raw = os.getenv("WHATSAPP_DRIVERS", "")
    m = {}
    for entry in raw.replace("\n", ";").split(";"):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        num, rest = entry.split("=", 1)
        num = num.strip()
        ime = rest.strip()
        gb = None
        if ":" in rest:
            ime_part, gb_part = rest.split(":", 1)
            ime = ime_part.strip()
            gb = gb_part.strip() or None
        if num:
            m[_norm_broj(num)] = (ime or None, gb)
    _drivers_cache = m
    return m


def driver_for(frm):
    """(ime, zadani_gb) za broj ili (None, None) ako nije mapiran."""
    return _drivers_map().get(_norm_broj(frm), (None, None))


# ==================== AKTIVNOST (za tjedne podsjetnike) ====================
# Bilježimo kad je koji broj zadnji put USPJEŠNO poslao dokument, da tjedni
# podsjetnik preskoči one koji su nedavno slali. Koristi glavnu bazu (racuni._db).

def _ensure_akt():
    with racuni._db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS wa_aktivnost "
                     "(broj TEXT PRIMARY KEY, zadnja_ts INTEGER)")


def zabiljezi_aktivnost(frm):
    """Upamti da je broj upravo poslao dokument (za preskakanje u podsjetniku)."""
    try:
        _ensure_akt()
        with racuni._db() as conn:
            conn.execute(
                "INSERT INTO wa_aktivnost (broj, zadnja_ts) VALUES (?, ?) "
                "ON CONFLICT(broj) DO UPDATE SET zadnja_ts = excluded.zadnja_ts",
                (str(frm), int(time.time())))
    except Exception as e:
        monitoring.warning(f"WhatsApp aktivnost upis nije uspio: {e}", source="wa_racuni")


def dani_od_zadnje(frm):
    """Broj dana (float) od zadnjeg uspješnog slanja tog broja; None ako nikad."""
    try:
        _ensure_akt()
        with racuni._db() as conn:
            row = conn.execute("SELECT zadnja_ts FROM wa_aktivnost WHERE broj = ?",
                               (str(frm),)).fetchone()
        if not row or row[0] is None:
            return None
        return (time.time() - row[0]) / 86400.0
    except Exception as e:
        monitoring.warning(f"WhatsApp aktivnost čitanje nije uspio: {e}", source="wa_racuni")
        return None


def handle(frm, ime, msg):
    """Ulazna WhatsApp poruka ovlaštenog zaposlenika (msg = raw message dict)."""
    try:
        _handle(frm, ime, msg)
    except Exception as e:
        _log(f"GREŠKA: {e}")
        monitoring.error("WhatsApp računi: greška u obradi", source="wa_racuni", exc=e)
        try:
            whatsapp.send_text(frm, "❌ Došlo je do greške pri obradi. Pošalji ponovno.")
        except Exception:
            pass


def _handle(frm, ime, msg):
    tip = msg.get("type")

    # 1) SLIKA / DOKUMENT → nova stranica (sakuplja se u dokument)
    media_id = None
    if tip == "image":
        media_id = (msg.get("image") or {}).get("id")
    elif tip == "document":
        media_id = (msg.get("document") or {}).get("id")
    if media_id:
        _primi_stranicu(frm, ime, media_id)
        return

    # 2) INTERAKTIVNI ODGOVOR (gumb)
    if tip == "interactive":
        inter = msg.get("interactive") or {}
        bid = ((inter.get("button_reply") or {}).get("id")
               or (inter.get("list_reply") or {}).get("id") or "")
        _odgovor(frm, bid)
        return

    # 3) TEKST
    if tip == "text":
        txt = (msg.get("text") or {}).get("body", "").strip()
        # Ako još skupljamo stranice, „gotovo” završava odmah; ostalo = podsjetnik.
        with _lock:
            skuplja = frm in _pending
        if skuplja:
            if txt.lower() in _GOTOVO:
                _zavrsi_prijem(frm, odmah=True)
            else:
                whatsapp.send_text(
                    frm, "📸 Još primam stranice. Napiši „gotovo” kad si poslao sve.")
            return
        _odgovor(frm, txt)
        return

    # ostali tipovi (audio, lokacija…) — kratka uputa
    whatsapp.send_text(frm, "Pošalji fotografiju računa ili primke pa te vodim dalje.")


# ==================== PRIJEM STRANICA (višestranično) ====================

def _primi_stranicu(frm, ime, media_id):
    """Preuzmi sliku i dodaj je u buffer stranica za taj broj; (ponovno) pokreni
    debounce timer. Kad _PAGE_WINDOW sekundi prođe bez nove stranice (ili stigne
    „gotovo”), sve se stranice obrađuju kao JEDAN dokument."""
    b, mime = whatsapp.download_media(media_id)
    with _lock:
        buf = _pending.get(frm)
        prva = buf is None
        if buf and buf.get("timer"):
            buf["timer"].cancel()
        if prva:
            buf = {"images": [], "ime": ime, "timer": None}
            _pending[frm] = buf
        buf["images"].append((b, mime))
        if ime and not buf.get("ime"):
            buf["ime"] = ime
        n = len(buf["images"])
        t = threading.Timer(_PAGE_WINDOW, _zavrsi_prijem, args=(frm,))
        t.daemon = True
        buf["timer"] = t
        t.start()
    if prva:
        whatsapp.send_text(
            frm, "📸 Primam… Pošalji još stranica istog dokumenta ili napiši "
                 "„gotovo”. Sam nastavljam za koju sekundu.")
    else:
        whatsapp.send_text(frm, f"➕ Stranica {n} dodana.")


def _zavrsi_prijem(frm, odmah=False):
    """Zatvori buffer stranica i pokreni obradu. odmah=True dolazi od „gotovo”
    (otkaži timer)."""
    with _lock:
        buf = _pending.get(frm)
        if buf and odmah and buf.get("timer"):
            buf["timer"].cancel()
        buf = _pending.pop(frm, None)
        if buf and buf["images"]:
            _obrada.add(frm)   # označi obradu (vision) → nema fallback poruke
    if not buf or not buf["images"]:
        return
    try:
        _pokreni_dokument(frm, buf["ime"], buf["images"])
    except Exception as e:
        _log(f"GREŠKA obrada: {e}")
        monitoring.error("WhatsApp računi: obrada stranica pala", source="wa_racuni", exc=e)
        try:
            whatsapp.send_text(frm, "❌ Greška pri obradi dokumenta. Pošalji ponovno.")
        except Exception:
            pass
    finally:
        with _lock:
            _obrada.discard(frm)


def _pokreni_dokument(frm, ime, images):
    """images = lista (bytes, mime). Vision pročita SVE stranice u jednom pozivu."""
    n = len(images)
    whatsapp.send_text(frm, "🔎 Čitam dokument…" + (f" ({n} str.)" if n > 1 else ""))
    data = racuni._read_document(images)
    spec = racuni._spec_for(data.get("vrsta"))
    voz_ime, def_gb = driver_for(frm)
    who = voz_ime or ime or frm
    sess = {
        "token": 0, "chat_id": frm, "user_id": frm, "who": who,
        # Kolona UnioTelegramID: označi da je WhatsApp broj, ne Telegram ID.
        "unio": f"WhatsApp {frm}",
        "data": data, "images": images, "spec": spec, "vrsta": spec.vrsta,
        "gb": None, "vozac": None, "zaprimio": None, "stage": "need_gb",
        "edit_key": None, "def_gb": def_gb,
    }
    _postavi_ime(sess, who)
    with _lock:
        _sessions[frm] = sess
    _pitaj_gb(frm, sess)


def _postavi_ime(sess, who):
    """Upiši ime u polje prema vrsti (Vozac za račun, Zaprimio za primku)."""
    if sess["vrsta"] == "primka":
        sess["zaprimio"] = who
        sess["vozac"] = None
    else:
        sess["vozac"] = who
        sess["zaprimio"] = None


def _pitaj_gb(frm, sess):
    spec = sess["spec"]
    if sess["vrsta"] == "primka":
        base = "Za koje vozilo (GB)? (napiši „-” ako nije za konkretno vozilo)"
    else:
        base = "Koje vozilo (GB)? Napiši oznaku, npr. GB123-AB."
    if sess.get("def_gb"):
        base += f"\n(napiši „.” za {sess['def_gb']})"
    whatsapp.send_text(frm, f"{spec.emoji} Prepoznato: {spec.naziv}.\n{base}")


def _posalji_potvrdu(frm, sess):
    """Sažetak + 3 gumba (Upiši / Ispravi / Odbaci) + uputa za promjenu vrste."""
    whatsapp.send_text(frm, racuni._summary_text(sess))
    druga = "primku" if sess["vrsta"] == "racun" else "račun"
    whatsapp.send_buttons(
        frm, f"Upisati u SharePoint?\n🔄 Napiši „vrsta” ako je zapravo {druga}.",
        [("wa_ok", "✅ Upiši"), ("wa_ed", "✏️ Ispravi"), ("wa_no", "❌ Odbaci")])


def _promijeni_vrstu(frm, sess):
    """🔄 Ponovno pročitaj iste slike kao DRUGA vrsta (račun↔primka)."""
    druga = "primka" if sess["vrsta"] == "racun" else "racun"
    naziv = "primku" if druga == "primka" else "račun"
    whatsapp.send_text(frm, f"🔄 Ponovno čitam kao {naziv}…")
    try:
        data = racuni._read_document(sess["images"], force_vrsta=druga)
    except Exception as e:
        monitoring.error("WhatsApp računi: promjena vrste pala", source="wa_racuni", exc=e)
        whatsapp.send_text(frm, "❌ Greška pri ponovnom čitanju. Pokušaj opet.")
        return
    sess["data"] = data
    sess["spec"] = racuni._spec_for(druga)
    sess["vrsta"] = druga
    _postavi_ime(sess, sess.get("who") or frm)
    sess["stage"] = "confirm"
    _posalji_potvrdu(frm, sess)


def _odgovor(frm, tekst):
    with _lock:
        sess = _sessions.get(frm)
        u_obradi = frm in _obrada or frm in _pending
    if not sess:
        # Ne dobacuj uputu ako smo usred sakupljanja/čitanja dokumenta —
        # sesija tad još ne postoji, a poruka bi zbunila (npr. „gotovo”).
        if u_obradi:
            whatsapp.send_text(frm, "⏳ Samo trenutak, još obrađujem dokument…")
        else:
            whatsapp.send_text(frm, "Pošalji fotografiju računa ili primke pa te vodim dalje.")
        return

    stage = sess.get("stage")
    low = (tekst or "").strip().lower()

    if stage == "need_gb":
        raw = (tekst or "").strip()
        if raw == "." and sess.get("def_gb"):
            sess["gb"] = sess["def_gb"]
        else:
            sess["gb"] = None if raw in ("-", "") else raw
        sess["stage"] = "confirm"
        _posalji_potvrdu(frm, sess)
        return

    if stage == "confirm":
        if low in _DA:
            whatsapp.send_text(frm, "💾 Upisujem…")
            poruka = _upisi(sess)
            with _lock:
                _sessions.pop(frm, None)
            whatsapp.send_text(frm, poruka)
            return
        if low in _NE:
            with _lock:
                _sessions.pop(frm, None)
            whatsapp.send_text(frm, "❌ Odbačeno. Pošalji novu fotografiju kad želiš.")
            return
        if low in _VRSTA:
            _promijeni_vrstu(frm, sess)
            return
        if low in _ISPRAVI:
            sess["stage"] = "edit_which"
            polja = ", ".join(racuni._edit_field_names(sess["vrsta"]))
            whatsapp.send_text(frm, f"Koje polje ispravljaš? Napiši ime, npr:\n{polja}")
            return
        _posalji_potvrdu(frm, sess)  # nejasno → ponovno sažetak + gumbi
        return

    if stage == "edit_which":
        key = racuni._edit_aliases(sess["vrsta"]).get(low)
        if not key:
            whatsapp.send_text(frm, "Ne prepoznajem to polje. Pokušaj npr. „oib” ili „ukupno”.")
            return
        sess["edit_key"] = key
        sess["stage"] = "edit_value"
        whatsapp.send_text(frm, f"Nova vrijednost za „{low}”:")
        return

    if stage == "edit_value":
        target, field = sess["edit_key"]
        if target == "sess":
            sess[field] = (tekst or "").strip()
        elif field in racuni._NUM_FIELDS:
            num = racuni._parse_num(tekst)
            sess["data"][field] = num if num is not None else (tekst or "").strip()
        else:
            sess["data"][field] = (tekst or "").strip()
        sess["edit_key"] = None
        sess["stage"] = "confirm"
        whatsapp.send_text(frm, "✅ Ažurirano.")
        _posalji_potvrdu(frm, sess)
        return


def _upisi(sess):
    """Upis uz par pokušaja ako je Excel zaključan (isti _Locked kao Telegram)."""
    # Provjera duplikata (isti OIB + broj dokumenta) — kao Telegram: duplikat se
    # NE upisuje, samo informativna poruka. Ako provjera padne → ne gubimo
    # dokument, nastavljamo s upisom.
    try:
        dup = racuni._find_duplicate(sess["spec"], sess["data"])
    except Exception as e:
        monitoring.warning(f"WhatsApp računi: dedupe nije uspio: {e}", source="wa_racuni")
        dup = None
    if dup:
        zabiljezi_aktivnost(sess["user_id"])  # ipak je poslao (samo je duplikat)
        return racuni._dup_text(sess["spec"], dup)

    # Slika se MORA uploadati PRIJE _write_once — ona postavlja sess['slika_url']
    # koju _build_rows/_slika_cell ugrađuju u redak (kolona 'Slika'). Bez ovog
    # koraka redak se upiše bez linka slike.
    try:
        racuni._prepare_image(sess)
    except Exception as e:
        monitoring.warning(f"WhatsApp računi: priprema slike pala: {e}", source="wa_racuni")

    for pokusaj in range(4):
        try:
            ok, poruka = racuni._write_once(sess)
            zabiljezi_aktivnost(sess["user_id"])
            return poruka + (sess.get("slika_note") or "")
        except racuni._Locked:
            time.sleep(2 * (pokusaj + 1))
        except Exception as e:
            monitoring.error("WhatsApp računi: upis pao", source="wa_racuni", exc=e)
            return "❌ Neočekivana greška pri upisu."
    return "⚠️ Datoteka je trenutno zauzeta (netko je uređuje). Pokušaj za koju minutu."
