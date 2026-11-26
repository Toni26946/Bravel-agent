"""📺 Upute iz videa — YouTube video popravka → kratke upute za mehaničara.

Tok (Toni 26.11.2026.): poslovođa/Toni uz zadatak zalijepi YouTube link →
1. yt-dlp izvuče titlove (ručne ili automatske; prednost EN/DE/HR, inače izvorni jezik),
   skida se SAMO JEDAN zapis titlova (više jezika odjednom → YouTube vrati 429),
2. Claude iz titlova složi strukturirani JSON (koraci s vremenom u videu, dijelovi s OE
   brojem, alat, momenti pritezanja, upozorenja) — sve na hrvatskom,
3. sličice ključnih koraka iz YouTube „storyboard" mozaika (bez skidanja videa i ffmpeg-a),
4. sve se sprema uz zadatak (tablica video_upute) i prikazuje mehaničaru na /z/<token>.
"""
import io
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger("video_upute")

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/|/v/)([A-Za-z0-9_-]{11})")
# Redoslijed prednosti jezika titlova
_JEZICI = ("hr", "en", "de")


def video_id(url: str) -> str | None:
    """YouTube ID (11 znakova) iz bilo kojeg uobičajenog oblika poveznice."""
    s = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    if not re.search(r"(youtube\.com|youtu\.be)", s, re.I):
        return None
    m = _ID_RE.search(s)
    return m.group(1) if m else None


def vrijeme(sek) -> str:
    try:
        s = max(0, int(sek))
    except (TypeError, ValueError):
        return ""
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --- 1. titlovi --------------------------------------------------------------
def _osnovni(kod: str) -> str:
    return (kod or "").split("-")[0].lower()


def odaberi_titlove(subs: dict, auto: dict, izvorni: str | None = None) -> tuple[str, str, bool] | None:
    """Odaberi JEDAN zapis titlova → (jezik, url, automatski).

    Prednost: ručni titlovi HR/EN/DE → ručni bilo koji → automatski u IZVORNOM jeziku
    videa („-orig" ili jezik videa) ako je HR/EN/DE → automatski EN (YouTube prijevod) →
    automatski izvorni (bilo koji). Uzima se format json3 (ima vremena po riječima),
    inače vtt."""
    def url_za(popis):
        if not popis:
            return None
        for ext in ("json3", "vtt", "srv3"):
            for f in popis:
                if f.get("ext") == ext and f.get("url"):
                    return f["url"], ext
        return None

    subs = {k: v for k, v in (subs or {}).items() if k != "live_chat"}
    auto = auto or {}
    for jez in _JEZICI:
        for k, v in subs.items():
            if _osnovni(k) == jez and url_za(v):
                return k, url_za(v)[0], False
    for k, v in subs.items():
        if url_za(v):
            return k, url_za(v)[0], False
    # Automatski: UVIJEK izvorni jezik videa (bilo koji — Claude ga razumije). YouTubeov
    # strojni prijevod (npr. ru → en, &tlang=) vraća 429 vrlo brzo, pa je tek zadnja opcija.
    izv = _osnovni(izvorni or "")
    orig = [k for k in auto if k.endswith("-orig")]
    kandidati = orig + ([izv] if izv and izv in auto else [])
    for k in kandidati:
        if url_za(auto[k]):
            return k, url_za(auto[k])[0], True
    if "en" in auto and url_za(auto["en"]):
        return "en", url_za(auto["en"])[0], True
    return None


def parsiraj_json3(tekst: str) -> list[tuple[float, str]]:
    """YouTube json3 → [(sekunda, tekst)]."""
    d = json.loads(tekst)
    out = []
    for ev in d.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if t:
            out.append(((ev.get("tStartMs") or 0) / 1000.0, t))
    return out


_VTT_T = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->")


def parsiraj_vtt(tekst: str) -> list[tuple[float, str]]:
    out, t = [], None
    for red in tekst.splitlines():
        m = _VTT_T.search(red)
        if m:
            h, mi, s, ms = m.groups()
            t = int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000
            continue
        red = re.sub(r"<[^>]+>", "", red).strip()
        if t is not None and red and not red.startswith(("WEBVTT", "Kind:", "Language:")):
            if not out or out[-1][1] != red:
                out.append((t, red))
    return out


def sazmi_transkript(linije: list[tuple[float, str]], razmak: float = 8.0) -> str:
    """Spoji retke u odlomke od ~8 s s oznakom vremena [m:ss] — kraći ulaz za Claude.
    Automatski titlovi ponavljaju riječi između događaja, pa se uzastopni duplikati preskaču."""
    blokovi: list[list] = []
    zadnje = ""
    for t, tx in linije:
        if tx == zadnje:
            continue
        zadnje = tx
        if not blokovi or t - blokovi[-1][0] >= razmak:
            blokovi.append([t, tx])
        else:
            blokovi[-1][1] += " " + tx
    return "\n".join(f"[{vrijeme(t)}] {' '.join(tx.split())}" for t, tx in blokovi)


def _ydl():
    import yt_dlp  # noqa: PLC0415 — teški uvoz samo kad treba
    return yt_dlp.YoutubeDL({
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "socket_timeout": 20,
    })


def dohvati_video(vid: str) -> dict:
    """Podaci o videu + titlovi (jedan zapis) + storyboard. Diže RuntimeError s
    razumljivom porukom (spremi se uz zadatak) kad nešto ne ide."""
    with _ydl() as ydl:
        try:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        except Exception as e:  # noqa: BLE001
            poruka = str(e)
            if "Sign in to confirm" in poruka or "bot" in poruka.lower():
                raise RuntimeError("YouTube blokira server (traži prijavu) — video treba obraditi lokalno") from e
            raise RuntimeError(f"Video se ne može otvoriti: {poruka[:200]}") from e
        izbor = odaberi_titlove(info.get("subtitles"), info.get("automatic_captions"), info.get("language"))
        if not izbor:
            raise RuntimeError("Video nema titlova (ni automatskih) — iz njega se ne mogu složiti upute")
        jezik, url, automatski = izbor
        sirovo = None
        for pokusaj in range(3):   # YouTube zna vratiti 429 — kratka pauza pa ponovno
            try:
                sirovo = ydl.urlopen(url).read().decode("utf-8", "replace")
                break
            except Exception as e:  # noqa: BLE001
                if "429" not in str(e) or pokusaj == 2:
                    raise RuntimeError(f"Titlovi se ne mogu skinuti: {str(e)[:200]}") from e
                import time  # noqa: PLC0415
                time.sleep(5 * (pokusaj + 1))
    linije = parsiraj_json3(sirovo) if sirovo.lstrip().startswith("{") else parsiraj_vtt(sirovo)
    if not linije:
        raise RuntimeError("Titlovi su prazni")
    return {
        "naslov": info.get("title") or "",
        "kanal": info.get("channel") or info.get("uploader") or "",
        "trajanje": info.get("duration"),
        "jezik": jezik, "automatski": automatski,
        "transkript": sazmi_transkript(linije),
        "storyboard": _storyboard(info.get("formats") or []),
        "slika": info.get("thumbnail"),
    }


# --- 2. Claude → strukturirane upute -----------------------------------------
SUSTAV = (
    "Ti si iskusni majstor za teretna vozila (kamioni, tegljači, prikolice) u radioni u Hrvatskoj. "
    "Dobit ćeš transkript (titlove) YouTube videa popravka ili dijagnostike, s oznakama vremena [m:ss]. "
    "Titlovi mogu biti na bilo kojem jeziku i automatski (s greškama u riječima) — razumij smisao. "
    "Dobit ćeš i podatke VOZILA IZ NALOGA (kamion na kojem se radi). "
    "Od toga složi KRATKE, PRAKTIČNE upute za mehaničara na HRVATSKOM. "
    "Vrati ISKLJUČIVO valjani JSON, bez teksta okolo, točno ovog oblika:\n"
    '{"odgovara": boolean, "video_vozilo": string, "razlog": string, '
    '"naslov": string, "sazetak": string, '
    '"koraci": [{"t": number, "opis": string}], '
    '"dijelovi": [{"naziv": string, "oe": string|null, "kolicina": string|null}], '
    '"alat": [string], '
    '"momenti": [{"sto": string, "vrijednost": string}], '
    '"upozorenja": [string], '
    '"kljucni": [number]}\n'
    "Pravila:\n"
    "- PRVO provjeri je li video za BAŠ OVAJ KAMION iz naloga (Toni: video mora biti za kamion iz "
    "naloga, nikoji drugi). odgovara = true SAMO ako se iz naslova ili transkripta JASNO vidi da je u "
    "videu ISTA MARKA i ISTI MODEL/SERIJA (npr. vozilo SCANIA R450 → video za Scania R-seriju, R450/R500; "
    "vozilo MAN TGX → video za MAN TGX) i generacija nije očito drugačija od godine vozila. "
    "Ako je video za drugu marku, drugi model/seriju, drugu generaciju, za prikolicu umjesto kamiona "
    "(ili obrnuto), ili se iz videa NE MOŽE utvrditi za koji je model — odgovara = false. Kad nisi siguran → false. "
    "Nadogradnja (dizalica, kiper, tegljač, šumarska oprema) NE mijenja model: npr. VOLVO FH 460 dizalica i "
    "video za kočnice/motor/ovjes Volvo FH kamiona → odgovara (posao je na istoj šasiji). Nadogradnja je "
    "bitna samo kad se posao radi baš na njoj (npr. popravak dizalice).\n"
    "- video_vozilo: za koje je vozilo video (marka, model/serija, godište ako se zna), kratko.\n"
    "- razlog: jedna kratka rečenica zašto odgovara / ne odgovara.\n"
    "- Ako odgovara = false, ostala polja vrati prazna (\"\" / []).\n"
    "- naslov: kratki naziv posla na hrvatskom (npr. \"Zamjena kočionih pločica – prednja osovina\").\n"
    "- sazetak: jedna rečenica što se radi i na kojem vozilu/sustavu (ako se zna).\n"
    "- koraci: redom kako se radi, 5–15 koraka, svaki kratak (do ~15 riječi), u obliku naredbe "
    "(npr. \"Olabavi vijke kotača pa podigni osovinu dizalicom\"). t = sekunda u videu kad korak počinje "
    "(iz oznake [m:ss] najbližeg odlomka; 1:05 = 65). Preskoči uvod, reklame, pozdrave i priču koja nije rad.\n"
    "- dijelovi: samo dijelovi koji se mijenjaju/ugrađuju. oe = OE/kataloški broj SAMO ako je izgovoren "
    "ili jasno naveden, inače null. kolicina ako se spominje (npr. \"1 komplet\"), inače null.\n"
    "- alat: alati i oprema koji se koriste (npr. \"nasadni ključ 22 mm\", \"moment ključ\", \"potiskivač klipa\").\n"
    "- momenti: momenti pritezanja i ostale bitne vrijednosti (zračnost, tlak) SAMO ako su izgovoreni "
    "(npr. {\"sto\": \"vijci kotača\", \"vrijednost\": \"600 Nm\"}). NE izmišljaj vrijednosti.\n"
    "- upozorenja: sigurnost i česte greške (podupiranje vozila, ispuštanje zraka iz sustava, "
    "opruge kočionog cilindra, zaštitne naočale…). Ako ih video ne spominje, dodaj samo 1–3 OSNOVNA "
    "sigurnosna upozorenja koja za taj posao uvijek vrijede.\n"
    "- kljucni: indeksi (od 0) 2–4 najvažnija koraka u polju koraci za koje vrijedi pokazati sličicu.\n"
    "- Ne izmišljaj dijelove, brojeve ni momente kojih nema u videu. Vrati samo JSON."
)


def _izvuci_json(tekst: str) -> dict:
    t = (tekst or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("Odgovor nema JSON")
    return json.loads(t[i:j + 1])


def podaci_vozila(db, zadatak) -> dict:
    """Vozilo iz naloga (po GB-u): marka/model iz naloga + matični podaci iz registra
    (vozilo, tip, vrsta, prva registracija, broj šasije, norma)."""
    from .models import RegistarVozila  # noqa: PLC0415
    nalog = zadatak.operacija.nalog if zadatak.operacija else None
    voz = nalog.vozilo if nalog else None
    gb = (voz.gb if voz else "") or ""
    reg = None
    if gb:
        reg = db.query(RegistarVozila).filter(RegistarVozila.gb == gb).first()
        if reg is None and gb.lstrip("0") != gb:
            reg = db.query(RegistarVozila).filter(RegistarVozila.gb == gb.lstrip("0")).first()
    d = {
        "gb": gb,
        "marka_model": " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x),
        "vozilo": reg.vozilo if reg else None,
        "tip": reg.tip if reg else None,
        "vrsta": reg.vrsta if reg else None,
        "prva_registracija": reg.prva_registracija if reg else None,
        "broj_sasije": reg.broj_sasije if reg else None,
        "norma": reg.norma if reg else None,
    }
    return {k: v for k, v in d.items() if v}


def vozilo_poznato(v: dict) -> bool:
    """Znamo li marku/model vozila (inače se ne može provjeriti je li video za njega)."""
    tekst = f"{v.get('marka_model') or ''} {v.get('vozilo') or ''}".strip()
    return bool(tekst) and tekst.upper() not in ("TEST", "TEST TEST")


def vozilo_kratko(v: dict) -> str:
    return f"GB {v.get('gb') or '?'} · {v.get('vozilo') or v.get('marka_model') or 'nepoznato'}"


def ai_upute(video: dict, vozilo: dict) -> dict:
    import anthropic  # noqa: PLC0415
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    transkript = video["transkript"]
    if len(transkript) > 60000:   # vrlo dugi videi — dovoljan je početak
        transkript = transkript[:60000]
    voz = "\n".join(f"  {k}: {v}" for k, v in vozilo.items())
    korisnicki = (
        f"VOZILO IZ NALOGA:\n{voz}\n\n"
        f"NASLOV VIDEA: {video.get('naslov') or '-'}\n"
        f"KANAL: {video.get('kanal') or '-'}\n"
        f"JEZIK TITLOVA: {video.get('jezik')}{' (automatski)' if video.get('automatski') else ''}\n"
        f"TRAJANJE: {vrijeme(video.get('trajanje') or 0)}\n\n"
        f"TRANSKRIPT:\n{transkript}"
    )
    poruka = client.messages.create(
        model=settings.anthropic_video_model or settings.anthropic_model,
        max_tokens=4000,
        system=SUSTAV,
        messages=[{"role": "user", "content": korisnicki}],
    )
    sirovo = "".join(getattr(b, "text", "") for b in poruka.content).strip()
    return ocisti_upute(_izvuci_json(sirovo), video.get("trajanje"))


def ocisti_upute(d: dict, trajanje=None) -> dict:
    """Normaliziraj AI odgovor (tipovi, granice) da prikaz nikad ne pukne."""
    def s(x, n=300):
        return " ".join(str(x).split())[:n] if x not in (None, "") else None

    koraci = []
    for k in d.get("koraci") or []:
        if not isinstance(k, dict) or not s(k.get("opis")):
            continue
        try:
            t = max(0, int(float(k.get("t") or 0)))
        except (TypeError, ValueError):
            t = 0
        if trajanje and t > int(trajanje):
            t = int(trajanje)
        koraci.append({"t": t, "opis": s(k.get("opis"))})
    dijelovi = []
    for x in d.get("dijelovi") or []:
        if isinstance(x, str):
            x = {"naziv": x}
        if isinstance(x, dict) and s(x.get("naziv")):
            dijelovi.append({"naziv": s(x.get("naziv")), "oe": s(x.get("oe"), 60), "kolicina": s(x.get("kolicina"), 40)})
    momenti = []
    for x in d.get("momenti") or []:
        if isinstance(x, dict) and s(x.get("vrijednost")):
            momenti.append({"sto": s(x.get("sto")) or "", "vrijednost": s(x.get("vrijednost"), 60)})
    kljucni = []
    for i in d.get("kljucni") or []:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(koraci) and i not in kljucni:
            kljucni.append(i)
    return {
        "odgovara": d.get("odgovara") is True,
        "video_vozilo": s(d.get("video_vozilo"), 120) or "",
        "razlog": s(d.get("razlog"), 300) or "",
        "naslov": s(d.get("naslov"), 200) or "",
        "sazetak": s(d.get("sazetak"), 400) or "",
        "koraci": koraci,
        "dijelovi": dijelovi,
        "alat": [s(x, 120) for x in (d.get("alat") or []) if s(x)],
        "momenti": momenti,
        "upozorenja": [s(x) for x in (d.get("upozorenja") or []) if s(x)],
        "kljucni": kljucni[:4],
    }


# --- 3. sličice iz storyboarda -----------------------------------------------
def _storyboard(formats: list[dict]) -> dict | None:
    """Najveći storyboard (mozaik sličica) koji YouTube nudi — bez skidanja videa."""
    sb = [f for f in formats if (f.get("format_note") == "storyboard" or str(f.get("format_id", "")).startswith("sb"))
          and f.get("fragments") and f.get("rows") and f.get("columns")]
    if not sb:
        return None
    f = max(sb, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
    return {
        "rows": int(f["rows"]), "columns": int(f["columns"]),
        "width": int(f.get("width") or 0), "height": int(f.get("height") or 0),
        "fragments": [{"url": x.get("url"), "duration": float(x.get("duration") or 0)} for x in f["fragments"]],
    }


def tocka_storyboarda(sb: dict, t: float) -> tuple[int, int] | None:
    """(indeks fragmenta, indeks sličice u mozaiku) za sekundu t."""
    po_fragmentu = sb["rows"] * sb["columns"]
    pocetak = 0.0
    for i, fr in enumerate(sb["fragments"]):
        d = fr["duration"] or 0
        if t < pocetak + d or i == len(sb["fragments"]) - 1:
            if d <= 0:
                return i, 0
            korak = d / po_fragmentu
            return i, min(po_fragmentu - 1, max(0, int((t - pocetak) / korak)))
        pocetak += d
    return None


def slicice(sb: dict | None, vremena: list[int]) -> dict[int, str]:
    """Izreži sličice za zadana vremena → {t: web putanja}. Greške se tiho preskaču
    (sličice su „po želji")."""
    out: dict[int, str] = {}
    if not sb or not vremena:
        return out
    try:
        import httpx  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return out
    mape: dict[int, Image.Image] = {}
    up = Path(settings.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    for t in vremena:
        try:
            poz = tocka_storyboarda(sb, t)
            if poz is None:
                continue
            fi, ti = poz
            if fi not in mape:
                r = httpx.get(sb["fragments"][fi]["url"], timeout=20, follow_redirects=True)
                r.raise_for_status()
                mape[fi] = Image.open(io.BytesIO(r.content)).convert("RGB")
            img = mape[fi]
            w = sb["width"] or img.width // sb["columns"]
            h = sb["height"] or img.height // sb["rows"]
            red, stup = divmod(ti, sb["columns"])
            isjecak = img.crop((stup * w, red * h, stup * w + w, red * h + h))
            if isjecak.width < 320:   # malene sličice malo povećaj da se vidi na mobitelu
                f = 320 / isjecak.width
                isjecak = isjecak.resize((320, int(isjecak.height * f)), Image.LANCZOS)
            naziv = "yt_" + secrets.token_hex(10) + ".jpg"
            isjecak.save(up / naziv, format="JPEG", quality=85)
            out[t] = f"/uploads/{naziv}"
        except Exception as e:  # noqa: BLE001
            log.warning("Sličica za %ss nije uspjela: %s", t, e)
    return out


# --- 4. cijela obrada (pozadina) ---------------------------------------------
def obradi(uputa_id: int) -> None:
    """Pozadinska obrada jedne upute: titlovi → Claude → sličice → spremi. Vlastita sesija."""
    from .database import SessionLocal  # noqa: PLC0415
    from .models import VideoUputa  # noqa: PLC0415
    db = SessionLocal()
    try:
        u = db.get(VideoUputa, uputa_id)
        if u is None:
            return
        try:
            if not settings.anthropic_api_key:
                raise RuntimeError("Nije postavljen ANTHROPIC_API_KEY")
            # Video mora biti za BAŠ OVAJ kamion iz naloga (Toni 26.11.2026.) — bez poznate
            # marke/modela ne može se provjeriti, pa se upute ne slažu.
            vozilo = podaci_vozila(db, u.zadatak)
            if not vozilo_poznato(vozilo):
                raise RuntimeError(f"Za GB {vozilo.get('gb') or '?'} nisu upisani marka i model — "
                                   "ne može se provjeriti je li video za ovaj kamion")
            video = dohvati_video(u.video_id)
            u.naslov = (video["naslov"] or "")[:300]
            u.jezik = (video["jezik"] or "")[:20]
            db.commit()
            upute = ai_upute(video, vozilo)
            if not upute["odgovara"]:
                raise RuntimeError(
                    f"Video nije za ovaj kamion ({vozilo_kratko(vozilo)}). "
                    f"Video je za: {upute['video_vozilo'] or 'nepoznato vozilo'}. {upute['razlog']}".strip())
            if not upute["koraci"]:
                raise RuntimeError("Iz videa se nisu mogli izvući koraci (možda nije video popravka)")
            kljucni = upute["kljucni"] or list(range(min(3, len(upute["koraci"]))))
            sl = slicice(video.get("storyboard"), [upute["koraci"][i]["t"] for i in kljucni])
            for i in kljucni:
                k = upute["koraci"][i]
                if k["t"] in sl:
                    k["slika"] = sl[k["t"]]
            upute["video"] = {"naslov": video["naslov"], "kanal": video["kanal"],
                              "trajanje": video["trajanje"], "jezik": video["jezik"],
                              "automatski": video["automatski"]}
            upute["vozilo"] = vozilo_kratko(vozilo)
            u.podaci = json.dumps(upute, ensure_ascii=False)
            u.status = "gotovo"
            u.greska = None
        except Exception as e:  # noqa: BLE001 — greška se sprema uz zadatak (vidi je poslovođa)
            log.warning("Video upute %s (%s) nisu uspjele: %s", uputa_id, u.video_id, e)
            u.status = "greska"
            u.greska = str(e)[:500]
        u.azurirano = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def za_prikaz(u) -> dict | None:
    """Uputa za frontend / stranicu mehaničara (s poveznicom na video)."""
    if u is None:
        return None
    d = {"id": u.id, "zadatak_id": u.zadatak_id, "url": u.url, "video_id": u.video_id,
         "status": u.status, "greska": u.greska, "naslov": u.naslov}
    if u.podaci:
        try:
            d["upute"] = json.loads(u.podaci)
        except ValueError:
            d["upute"] = None
    return d
