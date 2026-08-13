"""Pojmovnik (rječnik) žargona radione Bravel.

Pomaže AI-u da ispravno protumači izgovoreni/izdiktirani tekst — kratice,
germanizme i sleng koji mehaničari stvarno koriste u opisima radova — i mapira
ih na standardne nazive dijelova i radova, kako se ne bi upisivale krive
operacije i zadaci.

Izvor: stvarni opisi radova iz evidencije radione. Popis je namjerno na jednom
mjestu i lako proširiv: dodaj par "izraz": "značenje" i to se automatski uključi
u AI upute. Ključ neka bude malim slovima (bez kvačica je isto ok).
"""

# izraz (kako se piše/izgovara u radioni) -> standardno značenje
POJMOVNIK: dict[str, str] = {
    # --- KRATICE RADOVA (važno: mijenjaju smisao operacije!) ---
    "dem": "demontaža (skidanje/rastavljanje)",
    "mon": "montaža (ugradnja)",
    "kon": "kontrola",
    "kontr": "kontrola",
    "rep": "reparacija (popravak/obnova)",
    "reparatura": "reparacija (popravak/obnova)",
    "defektaza": "defektaža (rastavljanje radi utvrđivanja kvara)",
    "defektaža": "defektaža (rastavljanje radi utvrđivanja kvara)",
    "pp": "poluprikolica",
    "l i d": "lijeva i desna strana",
    "zad": "stražnji (zadnji)",

    # --- KOČNICE ---
    "bremza": "kočnica",
    "bremze": "kočnice",
    "pakne": "kočione papuče (obloge)",
    "pakni": "kočione papuče (obloge)",
    "dobos": "kočioni bubanj",
    "dobosa": "kočioni bubanj",
    "ferod": "kočione obloge",
    "ferodo": "kočione obloge",
    "čeljust": "kočiona čeljust",
    "čeljusti": "kočione čeljusti",
    "celjusti": "kočione čeljusti",
    "disk": "kočioni disk",
    "diskovi": "kočioni diskovi",
    "pločice": "kočione pločice",
    "plocice": "kočione pločice",
    "plocica": "kočione pločice",
    "modulator": "ABS/EBS modulator (kočnice)",
    "četverokružni ventil": "četverokružni zaštitni ventil (kočnice)",
    "cetverokruzni ventil": "četverokružni zaštitni ventil (kočnice)",
    "retarder": "retarder (usporivač)",
    "ebs": "elektronički kočni sustav (EBS)",
    "abs": "protublokirajući kočni sustav (ABS)",

    # --- OVJES / OSOVINE ---
    "selen": "silentblok (gumena čahura ovjesa)",
    "selena": "silentblok (gumena čahura ovjesa)",
    "seleni": "silentblok (gumena čahura ovjesa)",
    "selane": "silentblok (gumena čahura ovjesa)",
    "selna": "silentblok (gumena čahura ovjesa)",
    "silentblok": "silentblok (gumena čahura ovjesa)",
    "gibanj": "lisnata opruga (gibanj)",
    "gibnja": "lisnata opruga (gibanj)",
    "gibnjeva": "lisnate opruge (gibnjevi)",
    "torzionka": "torzijska šipka",
    "torzione": "torzijska šipka",
    "w spona": "W-poluga ovjesa (W-spona)",
    "v-spona": "V-poluga ovjesa (V-spona)",
    "v spona": "V-poluga ovjesa (V-spona)",
    "spona": "spona/poluga ovjesa ili upravljača",
    "amortizer": "amortizer",
    "jastuk": "zračni mijeh (zračni jastuk ovjesa)",
    "zračni jastuk": "zračni mijeh (zračni jastuk ovjesa)",
    "zracni jastuk": "zračni mijeh (zračni jastuk ovjesa)",
    "mijeh": "zračni mijeh (ovjes)",
    "mjeh": "zračni mijeh (ovjes)",
    "klobna": "dio zračnog ovjesa (klizač/vodilica – 'klobna')",
    "klobne": "dio zračnog ovjesa (klizač/vodilica – 'klobna')",
    "klobni": "dio zračnog ovjesa (klizač/vodilica – 'klobna')",
    "štica": "nosač/čašica zračnog jastuka (limeni nosač – 'štica')",
    "štice": "nosači/čašice zračnih jastuka ('štice')",
    "stica": "nosač/čašica zračnog jastuka ('štica')",
    "nivelacija": "regulacija razine ovjesa (nivelacija)",
    "glavčina": "glavčina kotača",
    "felga": "naplatak (felga)",
    "felna": "naplatak (felga)",
    "lager": "ležaj",

    # --- MOTOR / POGON ---
    "getriba": "mjenjač",
    "getribe": "mjenjač",
    "getribu": "mjenjač",
    "kuplung": "spojka (kvačilo)",
    "kvačilo": "spojka",
    "kvacilo": "spojka",
    "set kvačila": "komplet spojke",
    "dizna": "sapnica / injektor",
    "inektor": "injektor",
    "injektor": "injektor",
    "brizgaljka": "injektor",
    "radilica": "koljenasto vratilo",
    "bregasta": "bregasta osovina",
    "karter": "uljno korito (karter)",
    "turbina": "turbopunjač",
    "kardan": "kardansko vratilo",
    "anlaser": "elektropokretač (starter)",
    "webasto": "nezavisni grijač kabine (Webasto)",
    "webasta": "nezavisni grijač kabine (Webasto)",

    # --- ISPUH / OBRADA PLINOVA ---
    "auspuh": "ispušni sustav",
    "egr": "EGR ventil",
    "eger ventil": "EGR ventil",
    "dpf": "DPF filtar (filtar krutih čestica)",
    "adblue": "AdBlue sustav",
    "ad blu": "AdBlue sustav",
    "adblu": "AdBlue sustav",
    "plovak": "plovak (senzor razine, npr. AdBlue)",

    # --- ZRAK / PNEUMATIKA ---
    "kompresor": "kompresor zraka",
    "sušač": "sušač zraka",
    "isušivač": "sušač zraka (ventil isušivača)",
    "isusivac": "sušač zraka (ventil isušivača)",
    "boca zraka": "spremnik (boca) zraka",
    "spremnik zraka": "spremnik zraka",
    "španer": "zatezač/napinjač remena (španer)",
    "spaner": "zatezač/napinjač remena (španer)",
    "rolice": "napinjači/valjci remena (rolice)",
    "rolica": "napinjač/valjak remena (rolica)",
    "remenica": "remenica",
    "remen": "remen",

    # --- HLAĐENJE ---
    "hladnjak": "hladnjak",
    "interkuler": "hladnjak zraka (intercooler)",
    "termostat": "termostat",
    "antifriz": "antifriz (rashladna tekućina)",

    # --- ELEKTRIKA ---
    "aku": "akumulator",
    "akU": "akumulator",
    "birner": "žarulja",
    "birna": "žarulja",
    "relej": "relej",
    "osigurač": "osigurač",
    "sonda": "lambda / NOx sonda",
    "masa": "uzemljenje (masa)",
    "šalter": "prekidač",
    "far": "prednji far / svjetlo",
    "lampa": "svjetlo (lampa)",
    "gabarit": "gabaritno svjetlo",
    "gabariti": "gabaritna svjetla",
    "migavac": "pokazivač smjera (žmigavac)",

    # --- HIDRAULIKA / DIZALICA (kran) ---
    "lajtung": "hidraulični vod / crijevo",
    "lajtunga": "hidraulični vod / crijevo",
    "hidrol": "hidrauličko ulje / hidraulika",
    "razvodnik": "hidraulički razvodnik",
    "kran": "dizalica (na vozilu)",
    "kranu": "dizalica (na vozilu)",
    "dizalica": "dizalica (kran)",
    "teleskop": "teleskopski cilindar dizalice",
    "ruka": "krak/segment dizalice (ruka)",
    "stabilizator": "stabilizator (potpora dizalice)",

    # --- KAROSERIJA / KABINA / PRIKOLICA ---
    "sedlo": "sedlo tegljača (peta/spojni tanjur)",
    "rud": "ruda prikolice (rudo)",
    "ruda": "ruda prikolice (rudo)",
    "šlepa": "prikolica / poluprikolica",
    "šlepe": "prikolica / poluprikolica",
    "slepa": "prikolica / poluprikolica",
    "poluprikolica": "poluprikolica",
    "stranica": "prednja stranica (čelo kabine/šasije)",
    "branik": "branik",
    "blatobran": "blatobran",
    "spojler": "spojler",
    "sic": "sjedalo (vozačevo)",
    "hauba": "poklopac motora (hauba)",
    "vijenac": "senzorski vijenac (npr. EBS/ABS prsten)",
    "gurtne": "vezice/trake za pričvršćenje tereta (gurtne)",
    "gurtni": "vezice/trake za pričvršćenje tereta (gurtne)",
    "boks": "bočni sanduk/pretinac (boks)",
    "feder plate": "opružna ploča (feder ploča)",

    # --- UPRAVLJANJE / OSTALO ---
    "servo": "servo upravljač",
    "kugla": "kuglični zglob",
    "sajla": "sajla (uže)",
    "sajle": "sajle (užad)",

    # --- BRTVLJENJE / SPOJEVI / ALAT ---
    "šlauf": "crijevo",
    "dihtung": "brtva",
    "dihtunga": "brtva",
    "semering": "uljna brtva (semering)",
    "simering": "uljna brtva (semering)",
    "oring": "O-brtveni prsten",
    "šelna": "obujmica (Schelle – šelna)",
    "šelne": "obujmice (Schelle – šelne)",
    "šelnama": "obujmice (Schelle)",
    "šraf": "vijak",
    "sraf": "vijak",
    "šarafa": "vijak",
    "šrafciger": "odvijač",
    "muta": "matica",

    # --- ŽARGONSKI GLAGOLI / STANJA ---
    "zaštekao": "zaglavio / blokirao",
    "zastekao": "zaglavio / blokirao",
    "piksirati": "fiksirati / učvrstiti",
    "piksiranje": "fiksiranje / učvršćivanje",
    "luta": "ima zazor / klima se",
    "haba se": "troši se / tare se",
    "slini": "curi / propušta (malo)",
    "cvili": "škripi / zavija (zvuk)",
}


def pojmovnik_blok() -> str:
    """Vrati formatirani blok rječnika za umetanje u AI upute (ili prazno)."""
    if not POJMOVNIK:
        return ""
    redovi = "\n".join(f"- {izraz} = {znacenje}" for izraz, znacenje in POJMOVNIK.items())
    return (
        "RJEČNIK IZRAZA RADIONE (kratice, žargon i germanizmi → značenje) — "
        "izdiktirani tekst često sadrži ove izraze i tipfelere; protumači ih u "
        "ispravan standardni naziv dijela/rada, a ne doslovno. Posebno pazi na "
        "kratice DEM (demontaža/skidanje) i MON (montaža/ugradnja) jer određuju "
        "je li dio skinut ili ugrađen:\n" + redovi
    )
