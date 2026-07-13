# ============================================================
#  BACKUP - dnevna kopija bot.db na SharePoint (preko graph_client)
#
#  - Jednom dnevno (03:00 Europe/Zagreb) u zasebnom daemon threadu s
#    dnevnom petljom (bez cron/novih ovisnosti).
#  - SQLite se NE kopira "sirovo" (moglo bi biti usred pisanja): koristimo
#    sqlite3 backup API (conn.backup) -> konzistentan snapshot u temp fajl,
#    pa uploadamo temp na SharePoint.
#  - Folder: BRAVEL/Backup/ (kreira se ako ne postoji).
#    Ime: bot_db_YYYY-MM-DD.db
#  - Retencija: nakon USPJEŠNOG uploada obrisi backupe starije od 30 dana.
#  - Sve je best-effort: neuspjeh backupa NE smije srusiti bota (sve iznimke
#    se hvataju; salje se event monitoru).
#
#  Integracija (main.py):  backup.setup(DB_FILE, TZ); backup.start()
#  Admin test:             /backup_sada  -> backup.run_backup()
# ============================================================

import os
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta

import graph_client
import monitoring

# ---- Postavke ----
BACKUP_FOLDER = f"{graph_client.FOLDER}/Backup"   # BRAVEL/Backup
RETENTION_DAYS = 30
_HOUR = 3        # 03:00 Europe/Zagreb
_MINUTE = 0

# Ime backupa: bot_db_YYYY-MM-DD.db  (datum je i kljuc za retenciju)
_NAME_RE = re.compile(r"^bot_db_(\d{4})-(\d{2})-(\d{2})\.db$")

# ---- Ovisnosti koje ubrizgava main.py ----
_db_file = None
_tz = None


def setup(db_file, tz):
    global _db_file, _tz
    _db_file = db_file
    _tz = tz


def _now():
    return datetime.now(_tz)


def _log(msg):
    print(f"[backup] {msg}", flush=True)


def _snapshot_bytes():
    """Konzistentan snapshot baze preko sqlite3 backup API-ja -> bytes.
    Radi ispravno i usred pisanja (WAL): backup API kopira atomarno."""
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="botdb_")
    os.close(fd)
    try:
        src = sqlite3.connect(_db_file, timeout=30)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)   # atomski snapshot, siguran usred pisanja
            finally:
                dst.close()
        finally:
            src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _date_from_name(name):
    """Iz 'bot_db_YYYY-MM-DD.db' izvuci date, ili None ako ime ne odgovara."""
    m = _NAME_RE.match(name or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def _cleanup_old(today):
    """Obrisi backupe starije od RETENTION_DAYS iz BACKUP_FOLDER. Brise SAMO
    fajlove koji odgovaraju obrascu imena (tude fajlove ne dira). Vraca broj
    obrisanih."""
    cutoff = today - timedelta(days=RETENTION_DAYS)
    removed = 0
    for it in graph_client.list_folder(BACKUP_FOLDER):
        name = it.get("name", "")
        d = _date_from_name(name)
        if d is not None and d < cutoff:
            try:
                graph_client.delete_item(f"{BACKUP_FOLDER}/{name}")
                removed += 1
                _log(f"retencija: obrisan {name}")
            except Exception as e:
                _log(f"retencija: brisanje {name} nije uspjelo: {e}")
    return removed


def run_backup():
    """Napravi JEDAN backup: snapshot -> upload -> (na uspjeh) retencija.
    Vraca (ok, ime). Nikad ne dize iznimku (best-effort)."""
    if not graph_client.is_configured():
        _log("GREŠKA: Graph nije konfiguriran — preskačem backup")
        monitoring.warning("Backup preskočen: Graph nije konfiguriran.",
                           source="backup")
        return False, None

    name = f"bot_db_{_now().strftime('%Y-%m-%d')}.db"
    try:
        graph_client.ensure_folder(BACKUP_FOLDER)
        data = _snapshot_bytes()
        graph_client.upload_bytes(f"{BACKUP_FOLDER}/{name}", data,
                                  "application/octet-stream")
        _log(f"OK {name} ({len(data)} B)")
        monitoring.info(f"Backup OK: {name} ({len(data)} B)", source="backup")
    except Exception as e:
        _log(f"GREŠKA: {type(e).__name__}: {e}")
        monitoring.error("Backup nije uspio", source="backup", exc=e)
        return False, name

    # Retencija je zasebna od uspjeha uploada — ako padne, backup je i dalje OK.
    try:
        n = _cleanup_old(_now().date())
        if n:
            _log(f"retencija: ukupno obrisano {n} starih backupa")
    except Exception as e:
        _log(f"GREŠKA (retencija, backup je OK): {type(e).__name__}: {e}")
        monitoring.warning(f"Backup retencija nije uspjela: {e}", source="backup")

    return True, name


def _loop():
    """Dnevna petlja: okine backup jednom kad je _HOUR:_MINUTE (Europe/Zagreb).
    Provjera svakih 30 s (kao check_reminders); guard po danu da okine 1x."""
    last_done_day = None
    while True:
        try:
            now = _now()
            if now.hour == _HOUR and now.minute == _MINUTE:
                day = now.strftime("%Y-%m-%d")
                if last_done_day != day:
                    last_done_day = day
                    run_backup()
        except Exception as e:
            # Petlja NE smije umrijeti — logiraj i nastavi.
            _log(f"petlja iznimka: {type(e).__name__}: {e}")
            monitoring.error("Backup petlja iznimka", source="backup", exc=e)
        time.sleep(30)


def start():
    """Pokreni dnevni backup scheduler u daemon threadu."""
    if _db_file is None or _tz is None:
        _log("GREŠKA: setup() nije pozvan — scheduler se ne pokreće")
        return
    threading.Thread(target=_loop, daemon=True, name="backup").start()
    _log(f"scheduler pokrenut (dnevno u {_HOUR:02d}:{_MINUTE:02d} "
         f"Europe/Zagreb, folder {BACKUP_FOLDER}, retencija {RETENTION_DAYS} dana)")
