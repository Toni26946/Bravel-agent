"""AI obrada izgovorenog naloga (Claude) → strukturirani radni nalog."""
import json
import logging

from .config import settings

log = logging.getLogger("ai")

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None


def ai_dostupan() -> bool:
    return bool(anthropic and settings.anthropic_api_key)


SUSTAV = (
    "Ti si asistent koji iz izgovorenog teksta na hrvatskom (servis kamiona) izvlači "
    "strukturirani radni nalog. Vrati ISKLJUČIVO valjani JSON, bez teksta oko njega, "
    "točno ovog oblika:\n"
    '{"vozilo_gb": string|null, "voditelj": string|null, "vozac": string|null, '
    '"operacije": [{"kategorija": string, "zadaci": [string, ...]}]}\n'
    "Pravila:\n"
    "- vozilo_gb: garažni broj vozila kako je izgovoren (npr. \"21\"). Ako nije spomenut → null.\n"
    "- voditelj i vozac: odaberi TOČNO ime iz danih popisa koje najbolje odgovara "
    "izgovorenom; ako nije spomenuto ili nema poklapanja → null.\n"
    "- Svaku operaciju svrstaj u NAJBLIŽU kategoriju iz popisa DOZVOLJENE KATEGORIJE i "
    "koristi točan naziv iz tog popisa. Ako baš ništa ne odgovara, koristi izgovorenu riječ.\n"
    "- zadaci: kratki konkretni radovi unutar te operacije (npr. \"zamjena ulja\", "
    "\"provjera pločica\"). Grupiraj zadatke pod pravu operaciju.\n"
    "- Ako je spomenut posao bez jasne kategorije, stavi ga pod \"RAZNO\".\n"
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


def parsiraj(tekst: str, kategorije: list[str], voditelji: list[str], vozaci: list[str]) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    korisnicki = (
        f"IZGOVORENO:\n{tekst}\n\n"
        f"DOZVOLJENE KATEGORIJE:\n{', '.join(kategorije) or '(nema)'}\n\n"
        f"VODITELJI:\n{', '.join(voditelji) or '(nema)'}\n\n"
        f"VOZAČI:\n{', '.join(vozaci) or '(nema)'}"
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
