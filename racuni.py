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

# Kolone Excel tablice (redoslijed je bitan za upis retka).
# NOVA STRUKTURA: jedan redak = JEDNA STAVKA racuna.
COLUMNS = [
    "Datum", "Vrijeme", "Izdavatelj", "OIB", "BrojRacuna",
    "Stavka", "Kolicina", "JedinicnaCijena", "IznosStavke",
    "PDV", "UkupnoEUR", "Lokacija", "Vozac", "GB",
    "VrijemeUnosa", "UnioTelegramID",
]

# Kljucne kolone po kojima prepoznajemo NOVU strukturu (za migraciju
# starog fajla): ako zaglavlje nema ove kolone, fajl je stara struktura.
_NEW_STRUCTURE_MARKERS = ("Stavka", "IznosStavke", "Lokacija")

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


def _log(msg):
    print(f"[racuni] {msg}", flush=True)


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
    '  "lokacija": "adresa/mjesto poslovnice iz zaglavlja racuna '
    '(npr. Zagrebačka 12, Vrbovec) ili null",\n'
    '  "stavke": [ {"naziv": "...", "kolicina": broj_ili_null, '
    '"cijena": broj_ili_null, "iznos": broj_ili_null} ],\n'
    '  "ukupno_eur": broj_ili_null,\n'
    '  "pdv_iznos": broj_ili_null\n'
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

# Aliasi za odabir polja kod ispravka -> kljuc u sesiji.
# (Pojedinacne stavke se ne uredjuju ovdje - kod krive stavke odbaci i
#  posalji jasniju fotku.)
_EDIT_ALIASES = {
    "datum": ("data", "datum"),
    "vrijeme": ("data", "vrijeme"),
    "izdavatelj": ("data", "izdavatelj"),
    "oib": ("data", "oib"),
    "broj racuna": ("data", "broj_racuna"),
    "broj_racuna": ("data", "broj_racuna"),
    "broj": ("data", "broj_racuna"),
    "lokacija": ("data", "lokacija"),
    "ukupno": ("data", "ukupno_eur"),
    "ukupno_eur": ("data", "ukupno_eur"),
    "iznos": ("data", "ukupno_eur"),
    "pdv": ("data", "pdv_iznos"),
    "vozac": ("sess", "vozac"),
    "gb": ("sess", "gb"),
    "vozilo": ("sess", "gb"),
}

# polja koja se nude u poruci "koje polje ispraviti?"
_EDIT_FIELD_NAMES = sorted({
    "datum", "vrijeme", "izdavatelj", "oib", "broj racuna", "lokacija",
    "ukupno", "pdv", "vozac", "gb",
})

_NUM_FIELDS = {"ukupno_eur", "pdv_iznos"}


def _stavka_usable(s):
    """True ako stavka ima barem naziv ili citljiv iznos."""
    if not isinstance(s, dict):
        return False
    naziv = (s.get("naziv") or "").strip()
    return bool(naziv) or _parse_num(s.get("iznos")) is not None


def _stavka_fields(s):
    """(naziv, kolicina, jed_cijena, iznos) — brojevi ili None gdje fali."""
    if not isinstance(s, dict):
        return ("(nespecificirano)", None, None, None)
    naziv = (s.get("naziv") or "").strip() or "(nespecificirano)"
    return (naziv, _parse_num(s.get("kolicina")),
            _parse_num(s.get("cijena")), _parse_num(s.get("iznos")))


def _usable_stavke(data):
    return [s for s in (data.get("stavke") or []) if _stavka_usable(s)]


def _stavka_line(s):
    naziv, kol, cij, izn = _stavka_fields(s)
    kol_s = f"{kol:g}" if kol is not None else "⚠️"
    cij_s = f"{cij:.2f}" if cij is not None else "⚠️"
    izn_s = f"{izn:.2f}" if izn is not None else "⚠️"
    return f"  • {naziv} — {kol_s} × {cij_s} = {izn_s}"


def _summary_text(sess):
    data = sess["data"]

    def show(k):
        v = data.get(k)
        return str(v).strip() if v not in (None, "") else "⚠️"

    lines = ["🧾 Provjeri izvučene podatke:", ""]
    lines.append(f"• Datum: {show('datum')}   Vrijeme: {show('vrijeme')}")
    lines.append(f"• Izdavatelj: {show('izdavatelj')}")
    lines.append(f"• OIB: {show('oib')}")
    lines.append(f"• Broj računa: {show('broj_racuna')}")
    lines.append(f"• Lokacija: {show('lokacija')}")
    lines.append("")

    lines.append("Stavke:")
    usable = _usable_stavke(data)
    if usable:
        for s in usable:
            lines.append(_stavka_line(s))
    else:
        lines.append("  ⚠️ nema čitljivih stavki — upisat će se 1 redak "
                     "„(nespecificirano)” s ukupnim iznosom")
    lines.append("")

    lines.append(f"• PDV: {_fmt_num(_parse_num(data.get('pdv_iznos')))}   "
                 f"Ukupno (EUR): {_fmt_num(_parse_num(data.get('ukupno_eur')))}")
    lines.append("")
    lines.append(f"• Vozač: {sess.get('vozac') or '⚠️'}")
    lines.append(f"• GB (vozilo): {sess.get('gb') or '⚠️'}")
    lines.append("")

    n = len(usable) if usable else 1
    lines.append(f"➡️ Upisat će se {n} redak(a) — jedan po stavci.")
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

def _build_rows(sess):
    """Sastavi N redaka (jedan po stavci) u redoslijedu COLUMNS.

    Ako racun nema citljivih stavki a ima ukupni iznos: jedan redak
    „(nespecificirano)”, Kolicina=1, JedinicnaCijena=UkupnoEUR,
    IznosStavke=UkupnoEUR. PDV i UkupnoEUR se ponavljaju u svakom retku."""
    data = sess["data"]

    def txt(k):
        v = data.get(k)
        return str(v).strip() if v not in (None, "") else ""

    def num(x):
        return x if x is not None else ""  # broj ili prazna celija

    ukupno = _parse_num(data.get("ukupno_eur"))
    pdv = _parse_num(data.get("pdv_iznos"))

    head = [txt("datum"), txt("vrijeme"), txt("izdavatelj"),
            txt("oib"), txt("broj_racuna")]                      # 5 kolona
    tail = [num(pdv), num(ukupno), txt("lokacija"),
            sess.get("vozac") or "", sess.get("gb") or "",
            _now().strftime("%Y-%m-%d %H:%M:%S"),
            int(sess["user_id"])]                                # 7 kolona

    usable = _usable_stavke(data)
    rows = []
    if usable:
        for s in usable:
            naziv, kol, cij, izn = _stavka_fields(s)
            rows.append(head + [naziv, num(kol), num(cij), num(izn)] + tail)
    else:
        # nema citljivih stavki -> jedan redak s ukupnim iznosom
        rows.append(head + ["(nespecificirano)", 1, num(ukupno), num(ukupno)]
                    + tail)
    return rows


def _create_workbook_bytes(initial_rows=None):
    """Kreiraj novi xlsx s Excel TABLICOM (ListObject) 'Racuni'.

    Ako su zadani initial_rows, upisemo ih odmah (tablica ima zaglavlje +
    N redaka). Tako prvi upis NE ovisi o workbook API-ju na tek nastalom
    fajlu (gdje Excel sesija zna kasniti/visjeti)."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = "Racuni"
    ws.append(COLUMNS)
    for r in (initial_rows or []):
        ws.append(r)

    last_col = _col_letter(len(COLUMNS))
    tab = Table(displayName=TABLE_NAME, ref=f"A1:{last_col}{ws.max_row}")
    tab.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tab)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _col_letter(n):
    """1 -> A, 16 -> P."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _fallback_append(rows):
    """Rezerva ako workbook API zapne: download -> append openpyxl -> upload.
    rows: lista redaka."""
    from openpyxl import load_workbook

    content = graph_client.download_file(EXCEL_FILE)
    wb = load_workbook(io.BytesIO(content))
    ws = wb["Racuni"] if "Racuni" in wb.sheetnames else wb.active
    for r in rows:
        ws.append(r)

    # Prosiri raspon tablice da ukljuci nove retke (ako tablica postoji)
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


def _append_via_workbook(rows):
    """Dodaj retke preko workbook API-ja s kratkim backoff retryjem.
    Dize GraphError ako ni nakon retryja ne uspije (pozivatelj ide na fallback)."""
    delays = [2, 4]  # nakon 1. i 2. neuspjeha; 3. pokusaj je zadnji
    for attempt in range(3):
        try:
            graph_client.append_table_rows(EXCEL_FILE, TABLE_NAME, rows)
            return
        except graph_client.GraphError as e:
            if e.status_code in _RETRYABLE and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise


# ---- Migracija starog fajla (stara struktura -> _STARO) ----

def _read_header():
    """Skini fajl i vrati listu vrijednosti zaglavlja (row 1), ili None."""
    from openpyxl import load_workbook

    content = graph_client.download_file(EXCEL_FILE)
    wb = load_workbook(io.BytesIO(content), read_only=True)
    try:
        ws = wb["Racuni"] if "Racuni" in wb.sheetnames else wb.active
        first = next(ws.iter_rows(min_row=1, max_row=1), None)
        return [c.value for c in first] if first else []
    finally:
        wb.close()


def _is_old_structure():
    """True ako postojeci fajl NEMA nove kolone (stara struktura).
    Jednostavna provjera zaglavlja. Kod greske vrati False (ne diramo fajl)."""
    try:
        header = _read_header()
    except Exception as e:
        _log(f"provjera strukture nije uspjela ({e}); pretpostavljam novu")
        return False
    if not header:
        return False
    return not all(marker in header for marker in _NEW_STRUCTURE_MARKERS)


def _rename_old_aside():
    """Preimenuj stari fajl u Racuni_terena_STARO.xlsx (uz sufiks ako je ime
    zauzeto). Vraca novo ime."""
    base, ext = "Racuni_terena_STARO", ".xlsx"
    candidates = [f"{base}{ext}"] + [f"{base}_{i}{ext}" for i in range(2, 21)]
    for name in candidates:
        try:
            graph_client.rename_file(EXCEL_FILE, name)
            return name
        except graph_client.GraphError as e:
            if e.status_code == 409:  # ime vec zauzeto -> probaj sljedece
                continue
            raise
    name = f"{base}_{_now().strftime('%Y%m%d_%H%M%S')}{ext}"
    graph_client.rename_file(EXCEL_FILE, name)
    return name


def _write_receipt(sess):
    """Upisi redak na SharePoint. UVIJEK vraca (bool ok, poruka) — nikad ne
    baca (pozivatelj se oslanja na to da poruka nikad ne ostane 'Upisujem...')."""
    if not graph_client.is_configured():
        _log("SharePoint nije konfiguriran (nedostaju Graph kredencijali).")
        return False, ("SharePoint nije konfiguriran (nedostaju Graph "
                       "kredencijali). Redak nije upisan.")

    step = "start"
    try:
        step = "1/6 auth"
        _log("1/6 auth (dohvacam Graph token)")
        graph_client.ensure_token()
        _log("1/6 auth OK")

        rows = _build_rows(sess)
        _log(f"pripremljeno redaka za upis: {len(rows)}")

        step = "2/6 provjera fajla"
        _log("2/6 provjera postoji li fajl")
        exists = graph_client.file_exists(EXCEL_FILE)
        _log(f"2/6 fajl postoji = {exists}")

        # Migracija: fajl postoji ali stara struktura -> preimenuj u STARO i
        # tretiraj kao novi fajl (kreiraj s novom strukturom).
        if exists:
            step = "2b/6 provjera strukture"
            _log("2b/6 provjera strukture zaglavlja")
            if _is_old_structure():
                old = _rename_old_aside()
                _log(f"2b/6 STARA struktura -> preimenovano u {old}; kreiram novi")
                monitoring.info(
                    f"Racuni: stari fajl preimenovan u {old} (migracija strukture).",
                    source="racuni")
                exists = False
            else:
                _log("2b/6 struktura OK (nova)")

        # PRVI upis / novi fajl: kreiraj xlsx s retcima vec unutra i uploadaj.
        # Bez workbook API-ja na svjezem fajlu (izbjegava vis/greske dok se
        # Excel sesija ne probudi).
        if not exists:
            step = "3/6 kreiranje xlsx"
            _log(f"3/6 kreiram xlsx s {len(rows)} redaka (openpyxl)")
            content = _create_workbook_bytes(initial_rows=rows)
            _log(f"3/6 xlsx kreiran ({len(content)} B)")
            step = "4/6 upload"
            _log("4/6 upload na SharePoint (PUT)")
            graph_client.upload_file(EXCEL_FILE, content)
            _log("4/6 upload OK")
            return True, (f"✅ Račun upisan — {len(rows)} stavka(i) "
                          "(kreiran novi Racuni_terena.xlsx).")

        # Fajl postoji (nova struktura): workbook API (retry), pa fallback.
        step = "5/6 workbook append"
        _log(f"5/6 workbook append {len(rows)} redaka (rows/add, s retryjem)")
        try:
            _append_via_workbook(rows)
            _log("5/6 workbook append OK")
            return True, (f"✅ Račun upisan — {len(rows)} stavka(i) u "
                          "Racuni_terena.xlsx.")
        except graph_client.GraphError as e:
            step = "5/6 fallback download/upload"
            _log(f"5/6 workbook append pao ({e}); fallback download->append->upload")
            monitoring.warning(
                f"Workbook API zapeo ({e}); prelazim na fallback download/upload.",
                source="racuni")
            _fallback_append(rows)
            _log("5/6 fallback OK")
            return True, (f"✅ Račun upisan — {len(rows)} stavka(i) "
                          "(rezervna metoda download→upload).")

    except graph_client.GraphError as e:
        _log(f"{step} GREŠKA: GraphError kod={e.status_code} {e}")
        if e.status_code == 403:
            monitoring.error("Graph 403 pri upisu racuna", source="racuni", exc=e)
            return False, ("❌ Nedostaje ovlast — provjeri admin consent za "
                           "Sites.ReadWrite.All.")
        monitoring.error("Graph greska pri upisu racuna", source="racuni", exc=e)
        return False, f"❌ Greška pri upisu na SharePoint (kod {e.status_code})."
    except Exception as e:
        _log(f"{step} GREŠKA: {type(e).__name__}: {e}")
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


def _do_write(sess, chat_id, msg_id):
    """Izvrsava upis u zasebnom threadu i UVIJEK uredi Telegram poruku u
    konacni status (uspjeh/greska). Izoliran od telebot worker poola."""
    try:
        ok, msg = _write_receipt(sess)
    except Exception as e:
        _log(f"_do_write neuhvacena greska: {type(e).__name__}: {e}")
        monitoring.error("Racun: neuhvacena greska pri upisu",
                         source="racuni", exc=e)
        ok, msg = False, "❌ Neočekivana greška pri upisu računa."

    _log("6/6 uredjujem Telegram poruku u konacni status")
    try:
        _bot.edit_message_text(msg, chat_id, msg_id)
    except Exception:
        try:
            _bot.send_message(chat_id, msg)
        except Exception:
            pass
    _log(f"KRAJ ({'uspjeh' if ok else 'greška'})")

    if ok and _log_note:
        try:
            _log_note(chat_id,
                      f"Račun upisan: {sess['data'].get('izdavatelj') or ''} "
                      f"{_fmt_num(_parse_num(sess['data'].get('ukupno_eur')))} EUR")
        except Exception:
            pass


def _on_callback(c):
    _log(f"callback ulaz: data={c.data} from={c.from_user.id}")
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
        _log(f"callback: ne mogu parsirati data={c.data}")
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
        polja = ", ".join(_EDIT_FIELD_NAMES)
        _bot.send_message(
            chat_id,
            "Koje polje želiš ispraviti? Napiši naziv, npr. 'oib'.\n"
            "(Pojedine stavke se ne uređuju — ako su krive, odbaci i pošalji "
            "jasniju fotku.)\n\n"
            f"Moguća polja: {polja}")
        return

    if action == "ok":
        msg_id = c.message.message_id
        _log(f"OK klik: token={token} chat={chat_id} -> upis u zasebnom threadu")
        try:
            _bot.edit_message_text("⏳ Upisujem račun...", chat_id, msg_id)
        except Exception:
            pass
        with _sessions_lock:
            _sessions.pop(chat_id, None)  # sprijeci dvostruki upis
        # Upis ide u ZASEBAN daemon thread: cak i ako neki poziv dugo traje,
        # ne blokira telebot worker pool (ostatak bota radi normalno).
        threading.Thread(
            target=_do_write, args=(sess, chat_id, msg_id), daemon=True
        ).start()
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
