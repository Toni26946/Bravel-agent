"""AI obrada izgovorenog naloga (Claude) → strukturirani radni nalog."""
import base64
import json
import logging

from .config import settings
from .pojmovnik import pojmovnik_blok

log = logging.getLogger("ai")

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None


def ai_dostupan() -> bool:
    return bool(anthropic and settings.anthropic_api_key)


SUSTAV = (
    "Ti si asistent koji iz izgovorenog teksta (servis kamiona) izvlači "
    "strukturirani radni nalog. Ulazni tekst može biti na BILO KOJEM jeziku "
    "(hrvatski, engleski, hindski, pandžapski…) — razumij ga i svejedno vrati "
    "tražene vrijednosti (kategorije koristi iz danog popisa na hrvatskom). "
    "Vrati ISKLJUČIVO valjani JSON, bez teksta oko njega, točno ovog oblika:\n"
    '{"vozilo_gb": string|null, "voditelj": string|null, "vozac": string|null, '
    '"operacije": [{"kategorija": string, "zadaci": [{"opis": string, "radnik": string|null}]}]}\n'
    "Pravila:\n"
    "- vozilo_gb: garažni broj vozila kako je izgovoren (npr. \"21\"). Ako nije spomenut → null.\n"
    "- voditelj i vozac: odaberi TOČNO ime iz danih popisa koje najbolje odgovara "
    "izgovorenom; ako nije spomenuto ili nema poklapanja → null.\n"
    "- Svaku operaciju svrstaj u NAJBLIŽU kategoriju iz popisa DOZVOLJENE KATEGORIJE i "
    "koristi točan naziv iz tog popisa. Ako baš ništa ne odgovara, koristi izgovorenu riječ.\n"
    "- OSOVINE: mnoge se operacije dijele po osovini — npr. KOČNICE, BLATOBRANI, KOTAČI, "
    "GLAVČINE KOTAČA, DIJELOVI OVJESA/GIBNJEVI/ZRAČNI JASTUCI, DIFERENCIJAL, JASTUCI I ŠTICE. "
    "Ako se rad odnosi na određenu osovinu (npr. \"prva\"/\"1. osovina\", \"druga\", \"treća\", "
    "\"prednja/stražnja osovina\"), RAZDVOJI ga u ZASEBNU operaciju za SVAKU spomenutu osovinu i "
    "nazovi je DOSLJEDNO oblikom \"<OSNOVNA KATEGORIJA> N. OSOVINA\" "
    "(npr. \"KOČNICE 1. OSOVINA\", \"BLATOBRANI 2. OSOVINA\", \"KOTAČI 3. OSOVINA\"). "
    "Ako DOZVOLJENE KATEGORIJE sadrže baš tu varijantu, koristi točno nju; ako ne, svejedno složi "
    "isti oblik \"<kategorija> N. osovina\". Svaki zadatak stavi pod operaciju svoje osovine. "
    "Ako se kaže \"sve osovine\" ili \"sve tri osovine\", napravi zasebne operacije za 1., 2. i 3. osovinu. "
    "Ako osovina nije spomenuta, NE dodavaj oznaku osovine. "
    "VAŽNO: svaki zadatak opisuje posao BAŠ za svoju osovinu — NE kopiraj isti zadatak na više osovina, "
    "osim ako je izričito rečeno da se isti posao radi na svakoj. "
    "Primjer: \"kočnice, prva osovina zamjena pločica, druga osovina kontrola čeljusti\" → "
    "operacija \"KOČNICE 1. OSOVINA\" sa zadatkom \"zamjena pločica\" i operacija \"KOČNICE 2. OSOVINA\" "
    "sa zadatkom \"kontrola čeljusti\".\n"
    "- zadaci: kratki konkretni radovi unutar te operacije. Svaki zadatak je objekt "
    "{opis, radnik}. opis = konkretan rad (npr. \"zamjena ulja\").\n"
    "- radnik: ako je uz taj zadatak (ili operaciju) spomenut radnik/mehaničar koji ga "
    "obavlja, odaberi TOČNO ime iz popisa RADNICI koje najbolje odgovara izgovorenom; "
    "inače null. Ako je radnik spomenut za cijelu operaciju, primijeni ga na sve njezine zadatke.\n"
    "- Ako je spomenut posao bez jasne kategorije, stavi ga pod \"RAZNO\".\n"
    "- Ulaz može sadržavati žargon i germanizme automehaničara (npr. \"lajtung\", "
    "\"pakne\", \"dizna\"). Koristi priloženi RJEČNIK IZRAZA da ih protumačiš u ispravan "
    "naziv dijela/rada — nemoj ih doslovno prepisivati ako imaju poznato značenje.\n"
    "- Ne izmišljaj podatke koji nisu izgovoreni."
)


def _izvuci_json(tekst: str) -> dict:
    t = tekst.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if "\n" in t:
            t = t.split("\n", 1)[1]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j >= 0:
        t = t[i:j + 1]
    return json.loads(t)


def parsiraj(
    tekst: str, kategorije: list[str], voditelji: list[str],
    vozaci: list[str], radnici: list[str] | None = None,
) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    rjecnik = pojmovnik_blok()
    korisnicki = (
        f"IZGOVORENO:\n{tekst}\n\n"
        f"DOZVOLJENE KATEGORIJE:\n{', '.join(kategorije) or '(nema)'}\n\n"
        f"VODITELJI:\n{', '.join(voditelji) or '(nema)'}\n\n"
        f"VOZAČI:\n{', '.join(vozaci) or '(nema)'}\n\n"
        f"RADNICI:\n{', '.join(radnici or []) or '(nema)'}"
        + (f"\n\n{rjecnik}" if rjecnik else "")
    )
    poruka = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        temperature=0,
        system=SUSTAV,
        messages=[{"role": "user", "content": korisnicki}],
    )
    sirovo = "".join(getattr(b, "text", "") for b in poruka.content).strip()
    return _izvuci_json(sirovo)


# --- Procjena štete ----------------------------------------------------------
SUSTAV_STETA = (
    "Ti si iskusni procjenitelj troškova popravka teretnih vozila (kamiona i prikolica) "
    "u Hrvatskoj. Na temelju opisa oštećenja procijeni PRIBLIŽAN trošak popravka "
    "(dijelovi + rad) u eurima (EUR). Vrati ISKLJUČIVO valjani JSON, bez teksta okolo, "
    "točno ovog oblika:\n"
    '{"procjena": number, "stavke": [{"naziv": string, "cijena": number}], "obrazlozenje": string}\n'
    "Pravila:\n"
    "- procjena: ukupan procijenjeni trošak u EUR (približan zbroj svih stavki).\n"
    "- stavke: razloži trošak na pojedine dijelove i radove s približnom cijenom svakoga u EUR "
    "(npr. {\"naziv\": \"Prednji far\", \"cijena\": 180}). Uključi i stavku za rad/radne sate.\n"
    "- Koristi realne prosječne cijene za servis teretnih vozila u Hrvatskoj.\n"
    "- obrazlozenje: jedna kratka rečenica na hrvatskom kako si došao do procjene.\n"
    "- Ako je opis nejasan, procijeni najbolje što možeš i navedi pretpostavku u obrazloženju.\n"
    "- Ne izmišljaj oštećenja koja nisu spomenuta. Vrati samo JSON."
)


SUSTAV_STETA_GOVOR = (
    "Iz izgovorenog teksta (servis kamiona) izvuci prijavu štete koju je napravio vozač. "
    "Ulazni tekst može biti na BILO KOJEM jeziku (hrvatski, engleski, hindski, pandžapski…) "
    "— razumij ga; polje 'opis' napiši na hrvatskom. "
    "Vrati ISKLJUČIVO valjani JSON, bez teksta okolo, točno ovog oblika:\n"
    '{"vozilo_gb": string|null, "vozac": string|null, "opis": string}\n'
    "Pravila:\n"
    "- vozilo_gb: garažni broj kamiona kako je izgovoren (npr. \"122\"). Ako nije spomenut → null.\n"
    "- vozac: odaberi TOČNO ime iz danog popisa vozača koje najbolje odgovara izgovorenom; "
    "ako nije spomenuto ili nema poklapanja → null.\n"
    "- opis: jasan, sažet opis onoga što je oštećeno/potrgano (bez garažnog broja i imena vozača).\n"
    "- Ulaz može sadržavati žargon/germanizme (npr. \"lajtung\", \"pakne\"); koristi priloženi "
    "RJEČNIK IZRAZA da ih protumačiš u ispravan naziv u opisu.\n"
    "- Ne izmišljaj podatke koji nisu izgovoreni. Vrati samo JSON."
)


def parsiraj_stetu_govor(tekst: str, vozaci: list[str]) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    rjecnik = pojmovnik_blok()
    korisnicki = f"IZGOVORENO:\n{tekst}\n\nVOZAČI:\n{', '.join(vozaci) or '(nema)'}"
    if rjecnik:
        korisnicki += f"\n\n{rjecnik}"
    poruka = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=800,
        temperature=0,
        system=SUSTAV_STETA_GOVOR,
        messages=[{"role": "user", "content": korisnicki}],
    )
    sirovo = "".join(getattr(b, "text", "") for b in poruka.content).strip()
    return _izvuci_json(sirovo)


# --- Čitanje otpremnice (fotografija → stavke) -------------------------------
SUSTAV_OTPREMNICA = (
    "Ti si precizan asistent u skladištu servisa teretnih vozila. Na fotografijama je JEDNA "
    "otpremnica / dostavnica / račun dobavljača (hrvatski ili strani jezik). Ako je više slika, "
    "to su UZASTOPNE STRANICE ISTOG dokumenta (npr. 'Stranica 1/4') — obradi ih kao cjelinu. "
    "Vrati ISKLJUČIVO valjani JSON, bez teksta okolo, točno ovog oblika:\n"
    '{"dobavljac": string|null, "broj_otpremnice": string|null, "datum": string|null, '
    '"stavke": [{"artikl": string, "kolicina": number, "jedinica": string, "cijena": number|null}]}\n'
    "Pravila:\n"
    "- dobavljac: tvrtka koja ISPORUČUJE robu (pošiljatelj/dobavljač, obično uz logo na vrhu), NE primatelj/kupac. Ako ne piše → null.\n"
    "- broj_otpremnice: broj dokumenta (otpremnice/dostavnice/računa). Ako ga nema → null.\n"
    "- datum: datum dokumenta (datum izdavanja/otpreme) u formatu DD.MM.GGGG. Ako ga nema → null.\n"
    "- stavke: stavke robe iz tablice, SVE sa SVIH stranica, istim redoslijedom.\n"
    "  VAŽNO o formatu retka: jedan artikl često zauzima DVA reda — u gornjem redu su šifra/kod, "
    "barcode, količina i cijene, a naziv artikla je u DRUGOM redu (odmah ISPOD šifre istog rednog broja). "
    "Šifra i naziv tog istog rednog broja pripadaju ISTOM artiklu — NE pomiči naziv na susjedni red. "
    "Provjeri po rednom broju (Red.br/RB) i poravnaj točno.\n"
    "  artikl = naziv artikla + šifra u zagradi, npr. \"Disk pločice (13.0460-2796.2)\". Ako nema naziva, stavi samo šifru.\n"
    "  kolicina = iz stupca Količina (može biti >1). jedinica = iz stupca Mj/jedinica (kom, kg, l, m, pak, set…); zadano \"kom\".\n"
    "  cijena = JEDINIČNA cijena u EUR (po jednom komadu), iz stupca jedinične cijene (Cijena/JM, VPC ili Cijena), "
    "a NE ukupna vrijednost retka (Vrijednost). Ako su cijene u kunama (kn), preračunaj nije potrebno — uzmi stupac u EUR (€). Ako cijene nema → null.\n"
    "- Preskoči zaglavlje, podnožje, poreze, zbrojeve i dostavne napomene — samo artikle iz tablice.\n"
    "- Prepiši TOČNO ono što piše; NE izmišljaj artikle, šifre ni brojeve. Ako je redak nečitak, radije ga izostavi nego pogodi.\n"
    "- Ako na slikama nema prepoznatljive otpremnice, vrati prazne vrijednosti (stavke: [])."
)


def parsiraj_otpremnicu(slike: list[tuple[bytes, str]]) -> dict:
    """Pročitaj jednu ili više stranica otpremnice preko Claude vision.

    slike: lista (bajtovi, media_type). Više slika = uzastopne stranice istog dokumenta.
    Koristi jači vizualni model (ANTHROPIC_VISION_MODEL); ako padne, pokuša osnovnim modelom.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    sadrzaj: list[dict] = []
    vise = len(slike) > 1
    for i, (bajtovi, mt) in enumerate(slike, 1):
        if vise:
            sadrzaj.append({"type": "text", "text": f"Stranica {i} od {len(slike)}:"})
        sadrzaj.append({"type": "image", "source": {
            "type": "base64", "media_type": mt, "data": base64.standard_b64encode(bajtovi).decode()}})
    sadrzaj.append({"type": "text", "text": (
        "Pročitaj cijelu otpremnicu (sve stranice) i vrati tražene podatke kao JSON." if vise
        else "Pročitaj ovu otpremnicu i vrati tražene podatke kao JSON.")})

    modeli: list[str] = []
    if settings.anthropic_vision_model:
        modeli.append(settings.anthropic_vision_model)
    if settings.anthropic_model and settings.anthropic_model not in modeli:
        modeli.append(settings.anthropic_model)  # fallback ako vizualni model nije dostupan

    zadnja_greska: Exception | None = None
    for model in modeli:
        try:
            poruka = client.messages.create(
                model=model, max_tokens=4000, temperature=0,
                system=SUSTAV_OTPREMNICA,
                messages=[{"role": "user", "content": sadrzaj}],
            )
            sirovo = "".join(getattr(b, "text", "") for b in poruka.content).strip()
            return _izvuci_json(sirovo)
        except Exception as e:  # noqa: BLE001 — probaj sljedeći model
            log.warning("Čitanje otpremnice modelom %s nije uspjelo: %s", model, e)
            zadnja_greska = e
    raise zadnja_greska or RuntimeError("Nema dostupnog modela za čitanje otpremnice")


def procijeni_stetu(opis: str, vozilo_opis: str | None = None) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    korisnicki = f"OŠTEĆENJE:\n{opis}"
    if vozilo_opis:
        korisnicki += f"\n\nVOZILO:\n{vozilo_opis}"
    rjecnik = pojmovnik_blok()
    if rjecnik:
        korisnicki += f"\n\n{rjecnik}"
    poruka = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        temperature=0,
        system=SUSTAV_STETA,
        messages=[{"role": "user", "content": korisnicki}],
    )
    sirovo = "".join(getattr(b, "text", "") for b in poruka.content).strip()
    return _izvuci_json(sirovo)
