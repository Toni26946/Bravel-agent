"""Pojmovnik (rječnik) žargona automehaničara.

Pomaže AI-u da ispravno protumači izgovorene izraze — germanizme i sleng koji se
koriste u radioni — i mapira ih na standardne nazive dijelova i radova, kako se ne
bi upisivale krive operacije i zadaci.

Popis je namjerno na jednom mjestu i lako proširiv: dodaj par "izraz": "značenje"
i to se automatski uključuje u AI upute. Ključ neka bude malim slovima.
"""

# izraz (kako se izgovara/piše u radioni) -> standardno značenje
POJMOVNIK: dict[str, str] = {
    # --- vodovi, crijeva, brtve, spojnice ---
    "lajtung": "vod ili crijevo (npr. kočiono, zračno ili crijevo goriva)",
    "lajtunga": "vod ili crijevo",
    "šlauf": "crijevo",
    "slauf": "crijevo",
    "dihtung": "brtva",
    "dihtunga": "brtva",
    "semering": "uljna brtva (semering)",
    "simering": "uljna brtva (semering)",
    "oring": "O-brtveni prsten",
    "šelna": "obujmica (šelna)",
    "šelne": "obujmice",
    "selna": "obujmica",
    # --- vijci i alat ---
    "šraf": "vijak",
    "sraf": "vijak",
    "šarafa": "vijak",
    "šrafciger": "odvijač",
    "srafciger": "odvijač",
    "muta": "matica",
    # --- kočnice ---
    "bremza": "kočnica",
    "bremze": "kočnice",
    "pakne": "kočione obloge (čeljusti)",
    "ferod": "kočione obloge",
    "ferodo": "kočione obloge",
    "ferodi": "kočione obloge",
    # --- pogon, motor ---
    "kuplung": "spojka (kvačilo)",
    "kuplunga": "spojka (kvačilo)",
    "getriba": "mjenjač",
    "getriga": "mjenjač",
    "anlaser": "elektropokretač (starter)",
    "anlasser": "elektropokretač (starter)",
    "dizna": "sapnica / injektor",
    "brizgaljka": "injektor",
    "radilica": "koljenasto vratilo",
    "bregasta": "bregasta osovina",
    "karter": "uljno korito",
    "turbina": "turbopunjač",
    "kardan": "kardansko vratilo",
    "difer": "diferencijal",
    "karike": "klipni prstenovi",
    # --- hlađenje, remenje ---
    "hladnjak": "hladnjak",
    "interkuler": "hladnjak zraka (intercooler)",
    "termostat": "termostat",
    "rolna": "napinjač / valjak remena",
    "remen": "remen",
    # --- elektrika ---
    "aku": "akumulator",
    "akU": "akumulator",
    "birner": "žarulja",
    "birna": "žarulja",
    "relej": "relej",
    "osigurač": "osigurač",
    "sonda": "lambda / NOx sonda",
    "masa": "uzemljenje (masa)",
    "šalter": "prekidač",
    "salter": "prekidač",
    "far": "prednji far / svjetlo",
    "migavac": "pokazivač smjera (žmigavac)",
    # --- ispuh, obrada ispušnih plinova ---
    "auspuh": "ispušni sustav",
    "egr": "EGR ventil",
    "adblue": "AdBlue sustav",
    "adblu": "AdBlue sustav",
    "dpf": "DPF filtar (filtar čestica)",
    "katalizator": "katalizator / DPF",
    # --- zrak, ovjes ---
    "kompresor": "kompresor zraka",
    "sušač": "sušač zraka",
    "mijeh": "zračni mijeh (ovjes)",
    "mjeh": "zračni mijeh (ovjes)",
    "gibanj": "lisnata opruga (gibanj)",
    "pero": "lisnata opruga",
    "amortizer": "amortizer",
    # --- upravljanje, kotači ---
    "spona": "spona upravljača",
    "špurštangla": "spona upravljača",
    "kugla": "kuglični zglob",
    "silentblok": "silentblok",
    "glavčina": "glavčina kotača",
    "felga": "naplatak (felga)",
    "felna": "naplatak (felga)",
    "lager": "ležaj",
    # --- karoserija, staklo ---
    "hauba": "poklopac motora",
    "blatobran": "blatobran",
    "šoferšajba": "vjetrobransko staklo",
    "sofersajba": "vjetrobransko staklo",
    "retrovizor": "vanjsko ogledalo",
    "brisač": "brisač stakla",
}


def pojmovnik_blok() -> str:
    """Vrati formatirani blok rječnika za umetanje u AI upute (ili prazno)."""
    if not POJMOVNIK:
        return ""
    redovi = "\n".join(f"- {izraz} = {znacenje}" for izraz, znacenje in POJMOVNIK.items())
    return (
        "RJEČNIK IZRAZA (žargon/germanizmi automehaničara → značenje) — protumači "
        "ove i slične izgovorene izraze u ispravan standardni naziv:\n" + redovi
    )
