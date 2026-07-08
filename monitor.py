# ============================================================
#  BRAVEL MONITOR - zaseban Telegram bot za dijagnostiku
#  - Prima greske/logove glavnog bota preko HTTP ingest endpointa
#      POST /ingest  {level, source, message, traceback}
#    zasticen zaglavljem  X-Monitor-Secret: <MONITOR_SECRET>
#  - Sprema ih u vlastitu SQLite bazu (trajno na Fly volume /data)
#  - Kriticne greske (ERROR/CRITICAL) odmah salje adminu na Telegram
#  - Naredbe za admina: /greske /logovi /stats /clear /start
#
#  ENV varijable:
#    MONITOR_BOT_TOKEN  - token zasebnog Telegram bota (obavezno za alarme)
#    MONITOR_SECRET     - zajednicka tajna za ingest (obavezno u produkciji)
#    MONITOR_ADMIN_ID   - Telegram chat id admina (default 7599693099)
#    PORT               - port HTTP ingest servera (default 8080)
#    BIND_HOST          - adresa za bind (default '::' = dual-stack IPv6/IPv4)
# ============================================================

import os
import time
import json
import socket
import sqlite3
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import telebot

# ==================== KONFIGURACIJA ====================

MONITOR_BOT_TOKEN = os.getenv("MONITOR_BOT_TOKEN", "").strip()
MONITOR_SECRET = os.getenv("MONITOR_SECRET", "").strip()
ADMIN_ID = int(os.getenv("MONITOR_ADMIN_ID", "7599693099"))
PORT = int(os.getenv("PORT", "8080"))
BIND_HOST = os.getenv("BIND_HOST", "::")

DB_FILE = "/data/monitor.db" if os.path.isdir("/data") else "monitor.db"
TZ = ZoneInfo("Europe/Zagreb")

# Koliko dana cuvamo zapise prije automatskog brisanja.
RETENTION_DAYS = 30

# Heartbeat: ako od nekog izvora ne stigne 'puls' dulje od HEARTBEAT_TIMEOUT
# sekundi, smatramo ga mrtvim i alarmiramo. Watcher provjerava svakih
# HEARTBEAT_CHECK_INTERVAL sekundi. (Glavni bot salje puls svakih ~60 s.)
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "300"))       # 5 min
HEARTBEAT_CHECK_INTERVAL = int(os.getenv("HEARTBEAT_CHECK_INTERVAL", "30"))

# Razine koje odmah alarmiraju admina.
ALERT_LEVELS = {"ERROR", "CRITICAL"}
VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

LEVEL_EMOJI = {
    "DEBUG": "🔧", "INFO": "ℹ️", "WARNING": "⚠️",
    "ERROR": "❌", "CRITICAL": "🚨",
}

# Anti-spam za alarme: isti (source, message) se ne alarmira cesce od ovoga.
ALERT_DEDUP_SECONDS = 60
_last_alert = {}
_alert_lock = threading.Lock()

bot = telebot.TeleBot(MONITOR_BOT_TOKEN) if MONITOR_BOT_TOKEN else None


def get_now():
    return datetime.now(TZ)


# ==================== BAZA (SQLite) ====================

def db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL NOT NULL,     -- unix timestamp
                day       TEXT NOT NULL,     -- 'YYYY-MM-DD' (Europe/Zagreb)
                level     TEXT NOT NULL,     -- INFO/WARNING/ERROR/CRITICAL
                source    TEXT NOT NULL,     -- izvor (npr. 'bravel-agent')
                message   TEXT NOT NULL,
                traceback TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_level ON events (level, ts)"
        )
        # Zadnji 'puls' po izvoru + je li trenutno oznacen kao mrtav (down).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS heartbeats (
                source  TEXT PRIMARY KEY,
                last_ts REAL NOT NULL,
                down    INTEGER NOT NULL DEFAULT 0
            )
        """)
    print(f"Monitor baza spremna: {DB_FILE}")


def store_event(level, source, message, tb):
    now = get_now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO events (ts, day, level, source, message, traceback) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now.timestamp(), now.strftime("%Y-%m-%d"), level, source, message, tb)
        )
        return cur.lastrowid


def cleanup_old_events():
    cutoff = get_now().timestamp() - RETENTION_DAYS * 86400
    with db() as conn:
        conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))


# ==================== HEARTBEAT ====================

def record_heartbeat(source):
    """Zabiljezi puls izvora. Ako je izvor bio oznacen kao mrtav, javi
    oporavak adminu i skini oznaku."""
    now_ts = get_now().timestamp()
    with db() as conn:
        row = conn.execute(
            "SELECT down FROM heartbeats WHERE source = ?", (source,)
        ).fetchone()
        was_down = bool(row["down"]) if row else False
        conn.execute(
            "INSERT INTO heartbeats (source, last_ts, down) VALUES (?, ?, 0) "
            "ON CONFLICT(source) DO UPDATE SET last_ts = excluded.last_ts, down = 0",
            (source, now_ts)
        )
    if was_down:
        msg = f"Bot '{source}' se ponovno javio — opet radi. ✅"
        store_event("INFO", source, msg, None)
        threading.Thread(target=alert_admin, args=("INFO", source, msg, None),
                         daemon=True).start()


def check_heartbeats():
    """Pozadinska petlja: alarmira kad izvor prestane slati puls."""
    while True:
        try:
            now_ts = get_now().timestamp()
            with db() as conn:
                rows = conn.execute(
                    "SELECT source, last_ts, down FROM heartbeats"
                ).fetchall()
            for r in rows:
                silent = now_ts - r["last_ts"]
                if silent > HEARTBEAT_TIMEOUT and not r["down"]:
                    with db() as conn:
                        conn.execute(
                            "UPDATE heartbeats SET down = 1 WHERE source = ?",
                            (r["source"],)
                        )
                    mins = int(silent // 60)
                    last_seen = datetime.fromtimestamp(r["last_ts"], TZ).strftime(
                        "%d.%m. %H:%M:%S")
                    msg = (f"Bot '{r['source']}' se ne javlja {mins} min "
                           f"(zadnji signal {last_seen}). Moguć pad ili restart.")
                    store_event("CRITICAL", r["source"], msg, None)
                    alert_admin("CRITICAL", r["source"], msg, None)
        except Exception as e:
            print(f"Greska u check_heartbeats: {e}")
        time.sleep(HEARTBEAT_CHECK_INTERVAL)


# ==================== ALARMI ADMINU ====================

def _should_alert(source, message):
    """Deduplikacija: preskoci ako je identican alarm poslan nedavno."""
    key = (source, message)
    now_ts = get_now().timestamp()
    with _alert_lock:
        last = _last_alert.get(key, 0)
        if now_ts - last < ALERT_DEDUP_SECONDS:
            return False
        _last_alert[key] = now_ts
    return True


def alert_admin(level, source, message, tb):
    if bot is None:
        return
    if not _should_alert(source, message):
        return
    emoji = LEVEL_EMOJI.get(level, "•")
    when = get_now().strftime("%d.%m. %H:%M:%S")
    text = f"{emoji} {level} — {source}\n🕒 {when}\n\n{message}"
    if tb:
        # Zadnjih par redaka tracebacka su najkorisniji.
        tail = tb.strip().splitlines()[-12:]
        text += "\n\n📄 Traceback:\n" + "\n".join(tail)
    try:
        bot.send_message(ADMIN_ID, text[:4000])
    except Exception as e:
        print(f"Slanje alarma nije uspjelo: {e}")


# ==================== HTTP INGEST SERVER ====================

class IngestHandler(BaseHTTPRequestHandler):
    # Utisaj default logiranje svakog requesta na stderr.
    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/", "/healthz"):
            self._send(200, b"ok")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        path = self.path.rstrip("/") or "/"
        if path not in ("/ingest", "/heartbeat"):
            self._send(404, b"not found")
            return

        # Provjera zajednicke tajne (ako je postavljena).
        if MONITOR_SECRET:
            if self.headers.get("X-Monitor-Secret", "") != MONITOR_SECRET:
                self._send(401, b"unauthorized")
                return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send(400, b"bad json")
            return

        # --- Heartbeat: samo azuriraj puls, ne spremaj kao event ---
        if path == "/heartbeat":
            source = str(data.get("source", "unknown"))[:100]
            try:
                record_heartbeat(source)
                self._send(200, b"beat")
            except Exception as e:
                print(f"Greska pri heartbeatu: {e}")
                self._send(500, b"error")
            return

        # --- /ingest: obican dogadaj ---
        level = str(data.get("level", "INFO")).upper()
        if level not in VALID_LEVELS:
            level = "INFO"
        source = str(data.get("source", "unknown"))[:100]
        message = str(data.get("message", ""))[:4000]
        tb = data.get("traceback")
        if tb is not None:
            tb = str(tb)[:6000]

        try:
            store_event(level, source, message, tb)
            if level in ALERT_LEVELS:
                # Alarm u zasebnom threadu da HTTP odgovor bude brz.
                threading.Thread(
                    target=alert_admin, args=(level, source, message, tb),
                    daemon=True
                ).start()
            self._send(200, b"stored")
        except Exception as e:
            print(f"Greska pri spremanju eventa: {e}")
            self._send(500, b"error")


class DualStackServer(ThreadingHTTPServer):
    """IPv6 server koji prima i IPv4 (potrebno za Fly .internal mrezu)."""
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def run_http_server():
    server = DualStackServer((BIND_HOST, PORT), IngestHandler)
    print(f"HTTP ingest slusa na [{BIND_HOST}]:{PORT}  (POST /ingest)")
    server.serve_forever()


# ==================== TELEGRAM NAREDBE (admin) ====================

def _is_admin(message):
    return message.chat.id == ADMIN_ID


def _parse_limit(text, default=10, maximum=50):
    parts = text.split()
    if len(parts) > 1 and parts[1].isdigit():
        return max(1, min(int(parts[1]), maximum))
    return default


def _fmt_event(r, with_tb=False):
    when = datetime.fromtimestamp(r["ts"], TZ).strftime("%d.%m. %H:%M:%S")
    emoji = LEVEL_EMOJI.get(r["level"], "•")
    line = f"{emoji} {when}  [{r['source']}]\n{r['message']}"
    if with_tb and r["traceback"]:
        tail = r["traceback"].strip().splitlines()[-6:]
        line += "\n" + "\n".join(tail)
    return line


def _send_events(chat_id, rows, title, with_tb=False):
    if not rows:
        bot.send_message(chat_id, f"{title}\n\nNema zapisa. ✅")
        return
    blocks = [_fmt_event(r, with_tb) for r in rows]
    # Slaganje u poruke do ~3500 znakova (Telegram limit je 4096).
    chunk, size = [title, ""], len(title) + 2
    for b in blocks:
        if size + len(b) + 2 > 3500 and len(chunk) > 2:
            bot.send_message(chat_id, "\n\n".join(chunk))
            chunk, size = [], 0
        chunk.append(b)
        size += len(b) + 2
    if chunk:
        bot.send_message(chat_id, "\n\n".join(chunk))


if bot is not None:

    @bot.message_handler(commands=["start", "help"])
    def cmd_start(message):
        if not _is_admin(message):
            return
        bot.reply_to(
            message,
            "🩺 Bravel Monitor aktivan.\n\n"
            "Pratim greške i logove glavnog bota.\n\n"
            "Naredbe:\n"
            "/greske [N] — zadnjih N grešaka (ERROR/CRITICAL), default 10\n"
            "/logovi [N] — zadnjih N zapisa svih razina, default 15\n"
            "/stats — pregled brojeva + status botova (heartbeat)\n"
            "/clear — obriši sve spremljene zapise\n\n"
            "Kritične greške stižu automatski čim se dogode.\n"
            f"Ako bot zašuti dulje od {HEARTBEAT_TIMEOUT // 60} min, javljam ti pad "
            "(i oporavak kad se vrati)."
        )

    @bot.message_handler(commands=["greske", "greske@", "errors"])
    def cmd_errors(message):
        if not _is_admin(message):
            return
        n = _parse_limit(message.text, default=10)
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE level IN ('ERROR','CRITICAL') "
                "ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()
        _send_events(message.chat.id, rows,
                     f"❌ Zadnjih {len(rows)} grešaka:", with_tb=True)

    @bot.message_handler(commands=["logovi", "logs"])
    def cmd_logs(message):
        if not _is_admin(message):
            return
        n = _parse_limit(message.text, default=15)
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()
        _send_events(message.chat.id, rows,
                     f"📜 Zadnjih {len(rows)} zapisa:")

    @bot.message_handler(commands=["stats", "statistika"])
    def cmd_stats(message):
        if not _is_admin(message):
            return
        now_ts = get_now().timestamp()
        day_ago = now_ts - 86400
        week_ago = now_ts - 7 * 86400
        with db() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]

            def by_level(since):
                rows = conn.execute(
                    "SELECT level, COUNT(*) c FROM events WHERE ts >= ? "
                    "GROUP BY level", (since,)
                ).fetchall()
                return {r["level"]: r["c"] for r in rows}

            d24 = by_level(day_ago)
            d7 = by_level(week_ago)
            top = conn.execute(
                "SELECT source, COUNT(*) c FROM events "
                "WHERE level IN ('ERROR','CRITICAL') AND ts >= ? "
                "GROUP BY source ORDER BY c DESC LIMIT 5", (week_ago,)
            ).fetchall()
            last_err = conn.execute(
                "SELECT ts FROM events WHERE level IN ('ERROR','CRITICAL') "
                "ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            beats = conn.execute(
                "SELECT source, last_ts, down FROM heartbeats ORDER BY source"
            ).fetchall()

        def fmt(d):
            if not d:
                return "  nema zapisa"
            order = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
            return "\n".join(
                f"  {LEVEL_EMOJI.get(l, '•')} {l}: {d[l]}"
                for l in order if l in d
            )

        lines = [
            "📊 STATISTIKA MONITORINGA", "",
            f"Ukupno zapisa: {total}", "",
            "Zadnja 24 h:", fmt(d24), "",
            "Zadnjih 7 dana:", fmt(d7),
        ]
        if top:
            lines += ["", "Najčešći izvori grešaka (7 dana):"]
            lines += [f"  • {r['source']}: {r['c']}" for r in top]
        if last_err:
            when = datetime.fromtimestamp(last_err["ts"], TZ).strftime("%d.%m. %H:%M")
            lines += ["", f"Zadnja greška: {when}"]
        else:
            lines += ["", "Zadnja greška: nema ✅"]

        lines += ["", "❤️ Status (heartbeat):"]
        if not beats:
            lines.append("  (još nema pulsa ni od jednog bota)")
        else:
            now_ts = get_now().timestamp()
            for b in beats:
                silent = now_ts - b["last_ts"]
                seen = datetime.fromtimestamp(b["last_ts"], TZ).strftime("%d.%m. %H:%M:%S")
                if b["down"] or silent > HEARTBEAT_TIMEOUT:
                    lines.append(f"  🔴 {b['source']} — ne javlja se (zadnji {seen})")
                else:
                    lines.append(f"  🟢 {b['source']} — živ (prije {int(silent)} s)")
        bot.send_message(message.chat.id, "\n".join(lines))

    @bot.message_handler(commands=["clear", "ocisti"])
    def cmd_clear(message):
        if not _is_admin(message):
            return
        with db() as conn:
            conn.execute("DELETE FROM events")
        bot.reply_to(message, "🧹 Svi zapisi obrisani.")


def run_bot():
    print(f"Telegram monitor bot pokrenut (admin={ADMIN_ID})")
    bot.delete_webhook(drop_pending_updates=True)
    bot.infinity_polling(allowed_updates=["message"])


# ==================== START ====================

if __name__ == "__main__":
    print("🩺 Bravel Monitor se pokreće...")
    init_db()
    cleanup_old_events()

    # Watcher koji prati pulsove i alarmira ako izvor zasuti.
    threading.Thread(target=check_heartbeats, daemon=True).start()

    if bot is not None:
        # HTTP ingest u pozadinskom threadu, Telegram polling u glavnom.
        threading.Thread(target=run_http_server, daemon=True).start()
        run_bot()
    else:
        # Bez tokena: radi samo kao ingest/spremiste (bez alarma i naredbi).
        print("⚠️  MONITOR_BOT_TOKEN nije postavljen — radim samo kao ingest server "
              "(bez Telegram alarma i naredbi).")
        run_http_server()
