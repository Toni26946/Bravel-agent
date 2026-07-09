# ============================================================
#  RACUNI - obrada fotografija racuna s Telegrama i upis u
#  Excel na SharePointu (preko graph_client / Microsoft Graph).
#
#  Tok:
#   1. vozac posalje fotku racuna (photo ili slika-kao-dokument)
#   2. Claude vision (claude-sonnet-4-6 SAMO ovdje) izvuce podatke -> JSON
#   3. mapiramo vozaca (SQLite) ili pitamo GB ako je nepoznat
#   4. pokazemo sazetak + gumbi ✅ Upiši / ✏️ Ispravi / ❌ Odbaci
#   5. tek nakon ✅ upisujemo redak u Racuni_terena.xlsx (folder BRAVEL)
#
#  Integracija: main.py poziva setup(), init_db(), register(),
#  a na vrhu svog catch-all text handlera poziva handle_text(message)
#  koji vraca True ako je poruku "pojeo" (pending stanje ili /vozac_*).
# ============================================================

import base64
import io
import json
import re
import threading
import time
from datetime import datetime

import telebot

import graph_client
import monitoring

# ---- Postavke ----
VISION_MODEL = "claude-sonnet-4-6"  # samo za citanje racuna; razgovor ostaje na Haiku
EXCEL_FILE = "Racuni_terena.xlsx"
TABLE_NAME = "Racuni"

# Kolone Excel tablice (redoslijed je bitan za upis retka)
COLUMNS = [
    "Datum", "Vrijeme", "Izdavatelj", "OIB", "BrojRacuna", "Opis",
    "UkupnoEUR", "PDV", "NacinPlacanja", "Vozac", "GB", "JIR",
    "UnioTelegramID", "VrijemeUnosa",
]

# ---- Ovisnosti koje ubrizgava main.py preko setup() ----
_bot = None
_client = None            # anthropic klijent
_db = None                # tvornica konekcija (main.db)
_allowed_users = ()
_tz = None
_log_note = None          # main.log_note (opcionalno biljezenje u dnevni log)

# ---- Stanje razgovora po chatu (jedan aktivan racun po vozacu) ----
_sessions = {}
_sessions_lock = threading.Lock()
_token_counter = [0]  # rastuci token za callback_data (kratak, <64 B)


def setup(bot, client, db, allowed_users, tz, log_note=None):
    global _bot, _client, _db, _allowed_users, _tz, _log_note
    _bot = bot
    _client = client
    _db = db
    _allowed_users = tuple(allowed_users)
    _tz = tz
    _log_note = log_note


def _now():
    return datetime.now(_tz)


# ==================== BAZA: mapiranje vozaca ====================

def init_db():
    """Kreira tablicu vozaca u glavnoj bazi (bot.db)."""
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vozaci (
                telegram_user_id INTEGER PRIMARY KEY,
                ime_vozaca       TEXT NOT NULL,
                gb_vozila        TEXT
            )
        """)
    print("Tablica vozaca spremna.")


def get_driver(user_id):
    """Vraca (ime, gb) ili None ako korisnik nije mapiran."""
    with _db() as conn:
        row = conn.execute(
            "SELECT ime_vozaca, gb_vozila FROM vozaci WHERE telegram_user_id = ?",
            (user_id,)
        ).fetchone()
    if row:
        return row["ime_vozaca"], row["gb_vozila"]
    return None


def upsert_driver(user_id, ime, gb):
    with _db() as conn:
        conn.execute(
            "INSERT INTO vozaci (telegram_user_id, ime_vozaca, gb_vozila) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET "
            "ime_vozaca = excluded.ime_vozaca, gb_vozila = excluded.gb_vozila",
            (user_id, ime, gb)
        )


def list_drivers():
    with _db() as conn:
        return conn.execute(
            "SELECT telegram_user_id, ime_vozaca, gb_vozila FROM vozaci "
            "ORDER BY ime_vozaca"
        ).fetchall()


# ==================== POMOCNE ====================

def _allowed(message_or_user_id):
    uid = (message_or_user_id.from_user.id
           if hasattr(message_or_user_id, "from_user") else message_or_user_id)
    return uid in _allowed_users


def _parse_num(val):
    """Pretvori '1.234,56' / '1234.56' / broj u float, ili None ako ne ide."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    # Ako ima i tocku i zarez -> zarez je decimalni (hr format): makni tocke
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_num(x):
    """Broj za prikaz (2 decimale) ili '⚠️' ako fali."""
    if x is None:
        return "⚠️"
    return f"{x:.2f}"


def _stavke_to_opis(stavke):
    """Spoji listu stavki u jedan string za kolonu Opis."""
    if not stavke:
        return ""
    dijelovi = []
    for s in stavke:
        if not isinstance(s, dict):
            dijelovi.append(str(s))
            continue
        naziv = (s.get("naziv") or "").strip()
        kol = s.get("kolicina")
        iznos = s.get("iznos")
        dio = naziv or "stavka"
        if kol not in (None, ""):
            dio += f" x{kol}"
        if iznos not in (None, ""):
            dio += f" = {iznos}"
        dijelovi.append(dio)
    return "; ".join(dijelovi)


# ==================== CLAUDE VISION ====================

_VISION_SYSTEM = (
    "Ti si precizan sustav za citanje hrvatskih fiskalnih racuna sa slike. "
    "Odgovaraj ISKLJUCIVO validnim JSON-om, bez ikakvog teksta prije ili poslije."
)

_VISION_PROMPT = (
    "Izvuci podatke s ovog racuna i vrati STROGO JSON s tocno ovim poljima:\n"
    '{\n'
    '  "datum": "DD.MM.YYYY ili null",\n'
    '  "vrijeme": "HH:MM ili null",\n'
    '  "izdavatelj": "naziv tvrtke ili null",\n'
    '  "oib": "OIB izdavatelja (11 znamenki) ili null",\n'
    '  "broj_racuna": "broj racuna ili null",\n'
    '  "stavke": [ {"naziv": "...", "kolicina": broj_ili_null, '
    '"cijena": broj_ili_null, "iznos": broj_ili_null} ],\n'
    '  "ukupno_eur": broj_ili_null,\n'
    '  "pdv_iznos": broj_ili_null,\n'
    '  "nacin_placanja": "gotovina/kartica/transakcija ili null",\n'
    '  "jir": "JIR oznaka ili null"\n'
    '}\n'
    "Pravila: sve novcane iznose vrati kao brojeve u eurima (npr. 12.50). "
    "Ako je neko polje necitljivo ili ga nema, stavi null (nemoj izmisljati). "
    "Interno provjeri da se zbroj stavki i PDV slazu s ukupnim iznosom; "
    "ako se ne slazu, ipak vrati najbolju procjenu procitanog. "
    "Vrati SAMO JSON."
)


def _extract_json(text):
    """Izvuci JSON objekt iz Claudeova odgovora (skini ograde, nadji {...})."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    return json.loads(t)


def _read_receipt(image_bytes, media_type):
    """Posalji sliku Claudeu i vrati parsirani dict s podacima racuna."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    resp = _client.messages.create(
        model=VISION_MODEL,
        max_tokens=1500,
        system=_VISION_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
        temperature=0,
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _extract_json(text)


# ==================== SAZETAK I GUMBI ====================

# (labela, kljuc u data, je_broj)
_DISPLAY = [
    ("Datum", "datum", False),
    ("Vrijeme", "vrijeme", False),
    ("Izdavatelj", "izdavatelj", False),
    ("OIB", "oib", False),
    ("Broj računa", "broj_racuna", False),
    ("Ukupno (EUR)", "ukupno_eur", True),
    ("PDV", "pdv_iznos", True),
    ("Način plaćanja", "nacin_placanja", False),
    ("JIR", "jir", False),
]

# Aliasi za odabir polja kod ispravka -> kljuc u sesiji
_EDIT_ALIASES = {
    "datum": ("data", "datum"),
    "vrijeme": ("data", "vrijeme"),
    "izdavatelj": ("data", "izdavatelj"),
    "oib": ("data", "oib"),
    "broj racuna": ("data", "broj_racuna"),
    "broj_racuna": ("data", "broj_racuna"),
    "broj": ("data", "broj_racuna"),
    "ukupno": ("data", "ukupno_eur"),
    "ukupno_eur": ("data", "ukupno_eur"),
    "iznos": ("data", "ukupno_eur"),
    "pdv": ("data", "pdv_iznos"),
    "nacin placanja": ("data", "nacin_placanja"),
    "nacin_placanja": ("data", "nacin_placanja"),
    "placanje": ("data", "nacin_placanja"),
    "jir": ("data", "jir"),
    "opis": ("data", "_opis_override"),
    "vozac": ("sess", "vozac"),
    "gb": ("sess", "gb"),
    "vozilo": ("sess", "gb"),
}

_NUM_FIELDS = {"ukupno_eur", "pdv_iznos"}


def _summary_text(sess):
    data = sess["data"]
    lines = ["🧾 Provjeri izvučene podatke:", ""]
    for label, key, is_num in _DISPLAY:
        val = data.get(key)
        if is_num:
            shown = _fmt_num(_parse_num(val))
        else:
            shown = (str(val).strip() if val not in (None, "") else "⚠️")
        lines.append(f"• {label}: {shown}")

    opis = data.get("_opis_override")
    if opis is None:
        opis = _stavke_to_opis(data.get("stavke"))
    lines.append(f"• Opis: {opis if opis else '⚠️'}")

    lines.append("")
    lines.append(f"• Vozač: {sess.get('vozac') or '⚠️'}")
    lines.append(f"• GB (vozilo): {sess.get('gb') or '⚠️'}")
    lines.append("")
    lines.append("⚠️ = nečitljivo / prazno. Ispravi po potrebi.")
    return "\n".join(lines)


def _confirm_markup(token):
    mk = telebot.types.InlineKeyboardMarkup()
    mk.row(
        telebot.types.InlineKeyboardButton("✅ Upiši", callback_data=f"rc_ok_{token}"),
        telebot.types.InlineKeyboardButton("✏️ Ispravi", callback_data=f"rc_ed_{token}"),
        telebot.types.InlineKeyboardButton("❌ Odbaci", callback_data=f"rc_no_{token}"),
    )
    return mk


def _send_confirm(sess):
    _bot.send_message(sess["chat_id"], _summary_text(sess),
                      reply_markup=_confirm_markup(sess["token"]))


# ==================== EXCEL: kreiranje i redak ====================

def _build_row(sess):
    """Sastavi listu vrijednosti za jedan redak tablice (redoslijed COLUMNS)."""
    data = sess["data"]
    opis = data.get("_opis_override")
    if opis is None:
        opis = _stavke_to_opis(data.get("stavke"))

    def txt(k):
        v = data.get(k)
        return str(v).strip() if v not in (None, "") else ""

    ukupno = _parse_num(data.get("ukupno_eur"))
    pdv = _parse_num(data.get("pdv_iznos"))

    return [
        txt("datum"),
        txt("vrijeme"),
        txt("izdavatelj"),
        txt("oib"),
        txt("broj_racuna"),
        opis,
        ukupno if ukupno is not None else "",   # broj ili prazno
        pdv if pdv is not None else "",
        txt("nacin_placanja"),
        sess.get("vozac") or "",
        sess.get("gb") or "",
        txt("jir"),
        int(sess["user_id"]),
        _now().strftime("%Y-%m-%d %H:%M:%S"),
    ]


def _create_workbook_bytes(initial_row=None):
    """Kreiraj novi xlsx s Excel TABLICOM (ListObject) 'Racuni'.

    Ako je zadan initial_row, upisujemo ga odmah (tablica ima zaglavlje +
    prvi redak). Tako prvi upis NE ovisi o workbook API-ju na tek
    nastalom fajlu (gdje Excel sesija zna kasniti/visjeti)."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = "Racuni"
    ws.append(COLUMNS)
    if initial_row is not None:
        ws.append(initial_row)

    last_col = _col_letter(len(COLUMNS))
    last_row = ws.max_row  # 1 (samo zaglavlje) ili 2 (zaglavlje + redak)
    tab = Table(displayName=TABLE_NAME, ref=f"A1:{last_col}{last_row}")
    tab.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tab)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _col_letter(n):
    """1 -> A, 14 -> N."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _fallback_append(row_values):
    """Rezerva ako workbook API zapne: download -> append openpyxl -> upload."""
    from openpyxl import load_workbook

    content = graph_client.download_file(EXCEL_FILE)
    wb = load_workbook(io.BytesIO(content))
    ws = wb["Racuni"] if "Racuni" in wb.sheetnames else wb.active
    ws.append(row_values)

    # Prosiri raspon tablice da ukljuci novi redak (ako tablica postoji)
    tab = ws.tables.get(TABLE_NAME) if hasattr(ws, "tables") else None
    if tab is not None:
        last_col = _col_letter(len(COLUMNS))
        tab.ref = f"A1:{last_col}{ws.max_row}"

    buf = io.BytesIO()
    wb.save(buf)
    graph_client.upload_file(EXCEL_FILE, buf.getvalue())


# HTTP kodovi na kojima workbook API vrijedi ponoviti (Excel sesija se jos
# budi na tek uploadanom fajlu, ili prolazni serverski problem).
_RETRYABLE = {404, 423, 500, 502, 503, 504}


def _append_via_workbook(row):
    """Dodaj redak preko workbook API-ja s kratkim backoff retryjem.
    Dize GraphError ako ni nakon retryja ne uspije (pozivatelj ide na fallback)."""
    delays = [2, 4]  # nakon 1. i 2. neuspjeha; 3. pokusaj je zadnji
    for attempt in range(3):
        try:
            graph_client.append_table_row(EXCEL_FILE, TABLE_NAME, row)
            return
        except graph_client.GraphError as e:
            if e.status_code in _RETRYABLE and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise


def _write_receipt(sess):
    """Upisi redak na SharePoint. UVIJEK vraca (bool ok, poruka) — nikad ne
    baca (pozivatelj se oslanja na to da poruka nikad ne ostane 'Upisujem...')."""
    if not graph_client.is_configured():
        return False, ("SharePoint nije konfiguriran (nedostaju Graph "
                       "kredencijali). Redak nije upisan.")

    try:
        row = _build_row(sess)

        # PRVI upis: fajl ne postoji -> kreiraj ga s retkom vec unutra i
        # uploadaj. Bez workbook API-ja na svjezem fajlu (izbjegava vis/greske
        # dok se Excel sesija ne probudi).
        if not graph_client.file_exists(EXCEL_FILE):
            graph_client.upload_file(
                EXCEL_FILE, _create_workbook_bytes(initial_row=row))
            return True, "✅ Račun upisan (kreiran novi Racuni_terena.xlsx)."

        # Fajl postoji: workbook API (s retryjem), pa fallback download/upload.
        try:
            _append_via_workbook(row)
            return True, "✅ Račun upisan u Racuni_terena.xlsx na SharePointu."
        except graph_client.GraphError as e:
            monitoring.warning(
                f"Workbook API zapeo ({e}); prelazim na fallback download/upload.",
                source="racuni")
            _fallback_append(row)
            return True, ("✅ Račun upisan (preko rezervne metode "
                          "download→upload).")

    except graph_client.GraphError as e:
        if e.status_code == 403:
            monitoring.error("Graph 403 pri upisu racuna", source="racuni", exc=e)
            return False, ("❌ Nedostaje ovlast — provjeri admin consent za "
                           "Sites.ReadWrite.All.")
        monitoring.error("Graph greska pri upisu racuna", source="racuni", exc=e)
        return False, f"❌ Greška pri upisu na SharePoint (kod {e.status_code})."
    except Exception as e:
        monitoring.error("Neocekivana greska pri upisu racuna",
                         source="racuni", exc=e)
        return False, "❌ Neočekivana greška pri upisu računa."


# ==================== TELEGRAM HANDLERI ====================

def _download_telegram_file(file_id):
    info = _bot.get_file(file_id)
    return _bot.download_file(info.file_path)


def _handle_image_message(message, image_bytes, media_type):
    chat_id = message.chat.id
    _bot.send_message(chat_id, "🔎 Čitam račun, trenutak...")

    # 1. Claude vision
    try:
        data = _read_receipt(image_bytes, media_type)
    except json.JSONDecodeError as e:
        monitoring.warning(f"Racun: neispravan JSON od modela: {e}", source="racuni")
        _bot.send_message(chat_id, "❌ Nisam uspio pročitati račun (neispravan "
                                   "format). Pokušaj s jasnijom fotografijom.")
        return
    except Exception as e:
        monitoring.error("Racun: greska pri Claude vision pozivu",
                         source="racuni", exc=e)
        _bot.send_message(chat_id, "❌ Greška pri čitanju računa. Pokušaj ponovno.")
        return

    # 2. mapiranje vozaca
    driver = None
    try:
        driver = get_driver(message.from_user.id)
    except Exception as e:
        monitoring.warning(f"Racun: dohvat vozaca nije uspio: {e}", source="racuni")

    if driver:
        vozac, gb = driver
    else:
        # nepoznat posiljatelj: ime iz Telegrama, GB cemo pitati
        vozac = (message.from_user.full_name or message.from_user.username
                 or str(message.from_user.id))
        gb = None

    with _sessions_lock:
        _token_counter[0] += 1
        token = _token_counter[0]
        sess = {
            "token": token,
            "chat_id": chat_id,
            "user_id": message.from_user.id,
            "data": data,
            "vozac": vozac,
            "gb": gb,
            "stage": None,
            "edit_key": None,
        }
        _sessions[chat_id] = sess

    # 3. ako GB nepoznat -> pitaj prije potvrde
    if not gb:
        sess["stage"] = "need_gb"
        _bot.send_message(chat_id, "Koje vozilo (GB)? Napiši oznaku, npr. GB123-AB.")
        return

    # 4. sazetak + gumbi
    sess["stage"] = "confirm"
    _send_confirm(sess)


def _on_photo(message):
    if not _allowed(message):
        return
    try:
        file_id = message.photo[-1].file_id  # najveca rezolucija
        img = _download_telegram_file(file_id)
    except Exception as e:
        monitoring.error("Racun: skidanje fotke nije uspjelo",
                         source="racuni", exc=e)
        _bot.send_message(message.chat.id, "❌ Nisam mogao preuzeti fotografiju.")
        return
    _handle_image_message(message, img, "image/jpeg")


def _on_document(message):
    if not _allowed(message):
        return
    doc = message.document
    mime = (doc.mime_type or "").lower()
    if not mime.startswith("image/"):
        return  # nije slika-kao-dokument; pusti druge handlere/ignore
    try:
        img = _download_telegram_file(doc.file_id)
    except Exception as e:
        monitoring.error("Racun: skidanje dokumenta nije uspjelo",
                         source="racuni", exc=e)
        _bot.send_message(message.chat.id, "❌ Nisam mogao preuzeti sliku.")
        return
    _handle_image_message(message, img, mime)


def _on_callback(c):
    if c.from_user.id not in _allowed_users:
        _bot.answer_callback_query(c.id)
        return
    try:
        _bot.answer_callback_query(c.id)
    except Exception:
        pass

    try:
        _, action, tok = c.data.split("_")
        token = int(tok)
    except ValueError:
        return

    chat_id = c.message.chat.id
    with _sessions_lock:
        sess = _sessions.get(chat_id)
        if not sess or sess["token"] != token:
            sess = None

    if not sess:
        try:
            _bot.edit_message_text("Ovaj račun više nije aktivan.",
                                   chat_id, c.message.message_id)
        except Exception:
            pass
        return

    if action == "no":
        with _sessions_lock:
            _sessions.pop(chat_id, None)
        try:
            _bot.edit_message_text("❌ Račun odbačen.", chat_id, c.message.message_id)
        except Exception:
            pass
        return

    if action == "ed":
        sess["stage"] = "edit_which"
        polja = ", ".join(sorted({
            "datum", "vrijeme", "izdavatelj", "oib", "broj racuna",
            "ukupno", "pdv", "nacin placanja", "jir", "opis", "vozac", "gb",
        }))
        _bot.send_message(chat_id,
                          "Koje polje želiš ispraviti? Napiši naziv, npr. 'oib'.\n\n"
                          f"Moguća polja: {polja}")
        return

    if action == "ok":
        msg_id = c.message.message_id
        # onemoguci ponovni klik
        try:
            _bot.edit_message_text("⏳ Upisujem račun...", chat_id, msg_id)
        except Exception:
            pass
        # _write_receipt je vec potpuno guardan, ali dodatno hvatamo sve da
        # poruka NIKAD ne ostane na "Upisujem račun...".
        try:
            ok, msg = _write_receipt(sess)
        except Exception as e:
            monitoring.error("Racun: neuhvacena greska pri upisu",
                             source="racuni", exc=e)
            ok, msg = False, "❌ Neočekivana greška pri upisu računa."
        with _sessions_lock:
            _sessions.pop(chat_id, None)
        # Uredi ISTU poruku u konacni status; ako edit ne uspije, posalji novu.
        try:
            _bot.edit_message_text(msg, chat_id, msg_id)
        except Exception:
            try:
                _bot.send_message(chat_id, msg)
            except Exception:
                pass
        if ok and _log_note:
            try:
                _log_note(chat_id,
                          f"Račun upisan: {sess['data'].get('izdavatelj') or ''} "
                          f"{_fmt_num(_parse_num(sess['data'].get('ukupno_eur')))} EUR")
            except Exception:
                pass
        return


# ==================== PENDING TEXT (zove main.handle) ====================

def handle_text(message):
    """Vraca True ako je poruka obradjena ovdje (pending stanje ili /vozac_*),
    inace False (main nastavlja svoju obradu)."""
    if not _allowed(message):
        return False

    text = (message.text or "").strip()
    low = text.lower()

    # --- admin komande za vozace ---
    if low.startswith("/vozac_dodaj"):
        _cmd_vozac_dodaj(message)
        return True
    if low.startswith("/vozac_lista"):
        _cmd_vozac_lista(message)
        return True

    # --- pending stanja aktivne sesije ---
    with _sessions_lock:
        sess = _sessions.get(message.chat.id)
    if not sess:
        return False

    stage = sess.get("stage")
    if stage == "need_gb":
        sess["gb"] = text
        sess["stage"] = "confirm"
        _send_confirm(sess)
        return True

    if stage == "edit_which":
        key = _EDIT_ALIASES.get(low)
        if not key:
            _bot.send_message(message.chat.id,
                              "Ne prepoznajem to polje. Pokušaj npr. 'oib' ili 'ukupno'.")
            return True
        sess["edit_key"] = key
        sess["stage"] = "edit_value"
        _bot.send_message(message.chat.id, f"Nova vrijednost za '{low}':")
        return True

    if stage == "edit_value":
        target, field = sess["edit_key"]
        if target == "sess":
            sess[field] = text
        else:  # data
            if field in _NUM_FIELDS:
                num = _parse_num(text)
                sess["data"][field] = num if num is not None else text
            else:
                sess["data"][field] = text
        sess["edit_key"] = None
        sess["stage"] = "confirm"
        _bot.send_message(message.chat.id, "✅ Ažurirano.")
        _send_confirm(sess)
        return True

    return False


def _cmd_vozac_dodaj(message):
    # /vozac_dodaj <telegram_id> <GB> <ime i prezime>
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        _bot.reply_to(message,
                      "Format: /vozac_dodaj <telegram_id> <GB> <ime i prezime>\n"
                      "Npr: /vozac_dodaj 5191857104 GB123-AB Ivan Horvat")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        _bot.reply_to(message, "Telegram ID mora biti broj.")
        return
    gb = parts[2]
    ime = parts[3].strip()
    try:
        upsert_driver(uid, ime, gb)
    except Exception as e:
        monitoring.error("Racun: upsert vozaca nije uspio", source="racuni", exc=e)
        _bot.reply_to(message, "❌ Greška pri spremanju vozača.")
        return
    _bot.reply_to(message, f"✅ Vozač spremljen:\n{ime} — {gb} (ID {uid})")


def _cmd_vozac_lista(message):
    try:
        rows = list_drivers()
    except Exception as e:
        monitoring.error("Racun: lista vozaca nije uspjela", source="racuni", exc=e)
        _bot.reply_to(message, "❌ Greška pri dohvatu vozača.")
        return
    if not rows:
        _bot.reply_to(message, "Nema spremljenih vozača. Dodaj s /vozac_dodaj.")
        return
    lines = ["🚚 Vozači:"]
    for r in rows:
        lines.append(f"• {r['ime_vozaca']} — {r['gb_vozila'] or '?'} "
                     f"(ID {r['telegram_user_id']})")
    _bot.reply_to(message, "\n".join(lines))


# ==================== REGISTRACIJA HANDLERA ====================

def register(bot):
    """Registrira photo/document/callback handlere. Text (pending stanja i
    /vozac_* komande) ide preko main.handle -> handle_text()."""
    bot.message_handler(content_types=["photo"])(_on_photo)
    bot.message_handler(content_types=["document"])(_on_document)
    bot.callback_query_handler(func=lambda c: c.data.startswith("rc_"))(_on_callback)
