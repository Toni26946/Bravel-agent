# ============================================================
#  MONITORING KLIJENT (za glavni bot)
#  - report(...) salje greske/logove monitoring botu preko HTTP-a
#  - Sve je best-effort u daemon threadu: monitoring NIKAD ne smije
#    srusiti ni usporiti glavni bot (sve iznimke se gutaju).
#  - Ako MONITOR_INGEST_URL nije postavljen, sve funkcije su no-op,
#    pa se glavni bot ponasa potpuno isto kao prije.
# ============================================================

import os
import sys
import json
import time
import threading
import traceback as _tb
import urllib.request

_URL = os.getenv("MONITOR_INGEST_URL", "").strip()
_SECRET = os.getenv("MONITOR_SECRET", "").strip()
_TIMEOUT = 5  # sekundi za HTTP POST

_SOURCE = "bravel-agent"  # zadani naziv izvora (moze se promijeniti u install())


def _derive(url, endpoint):
    """Iz ingest URL-a izvedi susjedni endpoint (npr. .../ingest -> .../heartbeat)."""
    if not url:
        return ""
    if url.endswith("/ingest"):
        return url[:-len("/ingest")] + "/" + endpoint
    return url.rstrip("/") + "/" + endpoint


_HEARTBEAT_URL = _derive(_URL, "heartbeat")


def enabled():
    """True ako je monitoring konfiguriran (postoji ingest URL)."""
    return bool(_URL)


def _post(payload, url=None):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url or _URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if _SECRET:
            req.add_header("X-Monitor-Secret", _SECRET)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            resp.read()
    except Exception:
        # Namjerno tiho: greska monitoringa ne smije utjecati na glavni bot.
        pass


def report(level, message, source=None, tb=None):
    """Posalji dogadaj monitoring botu (asinkrono, best-effort)."""
    if not _URL:
        return
    payload = {
        "level": str(level).upper(),
        "message": str(message)[:4000],
        "source": source or _SOURCE,
        "traceback": (tb[:6000] if tb else None),
    }
    threading.Thread(target=_post, args=(payload,), daemon=True).start()


def _format_exc(exc):
    if exc is None:
        return None
    return "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))


def info(message, source=None):
    report("INFO", message, source)


def warning(message, source=None):
    report("WARNING", message, source)


def error(message, source=None, exc=None):
    report("ERROR", message, source, _format_exc(exc))


def critical(message, source=None, exc=None):
    report("CRITICAL", message, source, _format_exc(exc))


def start_heartbeat(interval=60, source=None):
    """Pokrece daemon thread koji svakih `interval` sekundi salje 'puls'
    monitoringu. Ako monitor ne primi puls dulje od svog praga, alarmira
    admina da je glavni bot zasutio. No-op ako monitoring nije konfiguriran."""
    if not _HEARTBEAT_URL:
        return
    src = source or _SOURCE

    def _loop():
        while True:
            _post({"source": src}, url=_HEARTBEAT_URL)
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="heartbeat").start()
    print(f"[monitoring] heartbeat svakih {interval}s -> {_HEARTBEAT_URL}")


def install(source="bravel-agent"):
    """Registrira globalne excepthook-ove da uhvati NEuhvacene iznimke
    (u glavnoj niti i u pozadinskim threadovima) i posalje ih monitoringu."""
    global _SOURCE
    _SOURCE = source

    _prev = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            text = "".join(_tb.format_exception(exc_type, exc, tb))
            report("CRITICAL", f"Neuhvacena iznimka: {exc_type.__name__}: {exc}",
                   source, text)
        except Exception:
            pass
        _prev(exc_type, exc, tb)

    sys.excepthook = _hook

    # threading.excepthook postoji od Pythona 3.8
    if hasattr(threading, "excepthook"):
        def _thook(args):
            try:
                text = "".join(_tb.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback))
                tname = getattr(args.thread, "name", "?")
                report("CRITICAL",
                       f"Neuhvacena iznimka u threadu '{tname}': "
                       f"{args.exc_type.__name__}: {args.exc_value}",
                       source, text)
            except Exception:
                pass

        threading.excepthook = _thook

    if enabled():
        print(f"[monitoring] aktivno -> {_URL}")
    else:
        print("[monitoring] neaktivno (MONITOR_INGEST_URL nije postavljen)")
