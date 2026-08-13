"""AI obrada izgovorenog naloga (Claude) → strukturirani radni nalog."""
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
