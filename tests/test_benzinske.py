# ============================================================
#  Testovi za benzinske.py — cista logika (bez mreze/baze).
#
#  Cilj: zakljucati ponasanje koje je u proslosti VISE PUTA puklo:
#    - Tifon nestao (53 -> 21) jer je "ina" izbacivao INA-tagirane Tifon postaje.
#    - Crodux postaja (name=Adriaoil) pogresno pripisana Adri.
#    - Cijena dizela = 0,64 (goli broj iz <script> JSON blobova bez €).
#    - Cijena dizela = 1,86 (premium) umjesto obicnog eurodizela.
#    - Adria 44 -> duplikati/zaostaci (union vs. autoritativan sluzbeni popis).
#
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================

import unittest

import benzinske as b


class TestMatchBrand(unittest.TestCase):
    """_match_brand: OSM tagovi -> nas kljuc lanca (ili None)."""

    def test_tifon_tagiran_kao_ina_se_prepoznaje(self):
        # Tifon je INA-in brend; dio postaja u OSM-u ima brand=INA (name=Tifon…).
        # REGRESIJA: "ina" u iskljucenjima je gasio te postaje (53 -> 21).
        tags = {"brand": "INA", "name": "Tifon Sesvete", "operator": "INA d.d."}
        self.assertEqual(b._match_brand(tags), "tifon")

    def test_cista_ina_nije_nas_lanac(self):
        # Obicna INA postaja (bez Tifona u imenu) nije lanac koji pratimo.
        tags = {"brand": "INA", "name": "INA Zagreb Zapad", "operator": "INA d.d."}
        self.assertIsNone(b._match_brand(tags))

    def test_crodux_s_imenom_adriaoil_nije_adria(self):
        # REGRESIJA: Crodux postaja s name="Adriaoil" pripisana Adri po imenu.
        # Brand je autoritativan -> strani lanac se preskace bez obzira na name.
        tags = {"brand": "Crodux", "name": "Adriaoil", "operator": "Crodux derivati"}
        self.assertIsNone(b._match_brand(tags))

    def test_adria_varijante_imena(self):
        for naziv in ("Adria Oil", "adria-oil", "AdriaOil Rijeka"):
            with self.subTest(naziv=naziv):
                self.assertEqual(b._match_brand({"name": naziv}), "adria_oil")

    def test_shell_i_coral_su_isti_lanac(self):
        self.assertEqual(b._match_brand({"brand": "Shell"}), "shell")
        self.assertEqual(b._match_brand({"operator": "Coral Croatia d.o.o."}), "shell")

    def test_nepoznat_brend_je_none(self):
        self.assertIsNone(b._match_brand({"brand": "Lukoil", "name": "Lukoil 1"}))
        self.assertIsNone(b._match_brand({}))


class TestSpojiPopis(unittest.TestCase):
    """_spoji_popis: sluzbeni popis je AUTORITATIVAN; OSM samo obogacuje ime."""

    def test_osm_zaostatak_koji_popis_ne_potvrdi_se_izbacuje(self):
        # OSM "STARA" postaja koje nema u sluzbenom popisu -> mora nestati
        # (zatvorena/prebrendirana, zavarava vozaca).
        osm = [
            {"lat": 45.3300, "lon": 14.4400, "naziv": "Adria Rijeka", "grad": "Rijeka"},
            {"lat": 46.3000, "lon": 16.3300, "naziv": "Adria STARA", "grad": "Cakovec"},
        ]
        parovi = [(45.3305, 14.4402)]  # samo Rijeka je u sluzbenom popisu
        rez = b._spoji_popis(osm, parovi, "Adria Oil")
        self.assertEqual(len(rez), 1)
        self.assertFalse(any("STARA" in r["naziv"] for r in rez))

    def test_ime_i_grad_se_preuzmu_s_poklopljene_osm_postaje(self):
        osm = [{"lat": 45.3300, "lon": 14.4400, "naziv": "Adria Rijeka", "grad": "Rijeka"}]
        parovi = [(45.3305, 14.4402)]  # ~30 m od OSM postaje
        rez = b._spoji_popis(osm, parovi, "Adria Oil")
        self.assertEqual(rez[0]["naziv"], "Adria Rijeka")
        self.assertEqual(rez[0]["grad"], "Rijeka")

    def test_sluzbena_tocka_bez_osm_dobije_genericko_ime(self):
        parovi = [(45.8000, 15.9800)]  # Zagreb, nema OSM parnjaka
        rez = b._spoji_popis([], parovi, "Adria Oil")
        self.assertEqual(len(rez), 1)
        self.assertEqual(rez[0]["naziv"], "Adria Oil")

    def test_duplikat_unutar_popisa_se_spaja(self):
        parovi = [(45.3305, 14.4402), (45.3308, 14.4405)]  # ista postaja, ~30 m
        rez = b._spoji_popis([], parovi, "Adria Oil")
        self.assertEqual(len(rez), 1)

    def test_udaljene_tocke_ostaju_odvojene(self):
        parovi = [(45.3305, 14.4402), (45.8000, 15.9800)]  # Rijeka + Zagreb
        rez = b._spoji_popis([], parovi, "Adria Oil")
        self.assertEqual(len(rez), 2)


class TestIzvuciParove(unittest.TestCase):
    """_izvuci_parove: (lat,lon) u HR rasponu, oba redoslijeda, dedup ~100 m."""

    def test_oba_redoslijeda(self):
        self.assertIn((45.815, 15.982), b._izvuci_parove("lat 45.8150 lng 15.9820"))
        self.assertIn((45.815, 15.982), b._izvuci_parove("lng 15.9820, lat 45.8150"))

    def test_dedup_bliskih_tocaka(self):
        # Dvije skoro iste koordinate (3 decimale) -> jedan par.
        rez = b._izvuci_parove("45.8150,15.9820 i opet 45.81502,15.98201")
        self.assertEqual(len(rez), 1)

    def test_izvan_hr_raspona_se_ne_hvata(self):
        # 48.x (npr. Munchen) nije u HR latitude rasponu 42–46.
        self.assertEqual(b._izvuci_parove("48.1350, 11.5820"), [])


class TestParseCijena(unittest.TestCase):
    def test_normalan_raspon(self):
        self.assertEqual(b._parse_cijena("1", "452"), 1.452)

    def test_izvan_raspona_je_none(self):
        self.assertIsNone(b._parse_cijena("0", "10"))   # 0.10 < 0.3
        self.assertIsNone(b._parse_cijena("5", "00"))   # 5.0 > 3.0


class TestNormGorivo(unittest.TestCase):
    def test_specificnije_prije_opcenitog(self):
        self.assertEqual(b._norm_gorivo("Eurosuper 100"), "eurosuper100")
        self.assertEqual(b._norm_gorivo("Eurosuper 95"), "eurosuper95")
        self.assertEqual(b._norm_gorivo("Plavi dizel"), "plavi_dizel")
        self.assertEqual(b._norm_gorivo("Eurodizel"), "dizel")


class TestOcistiTekst(unittest.TestCase):
    def test_script_blokovi_se_izbacuju(self):
        html = '<script>var d={"dizel":0.64};</script><p>Eurodizel 1,45€</p>'
        plain = b._ocisti_tekst(html)
        self.assertNotIn("0.64", plain)
        self.assertIn("Eurodizel", plain)

    def test_euro_entitet_postaje_znak(self):
        self.assertIn("€", b._ocisti_tekst("1,45&euro; Eurodizel"))


class TestIzvuciCijene(unittest.TestCase):
    """Najkrhkiji dio — parser cijena s autoportal layoutom (cijena PRIJE naziva)."""

    def test_cijena_stoji_ispred_naziva(self):
        # Autoportal: '1,54€ - 1,64€ Eurosuper 95' -> uzmi donju granicu (1,54).
        html = "<p>1,54€ - 1,64€ Eurosuper 95 sa aditivima</p>"
        self.assertEqual(b._izvuci_cijene(html).get("eurosuper95"), 1.54)

    def test_dizel_uzima_najnizi_obicni_a_ne_plavi(self):
        # Plavi dizel (0,95 €, poljoprivredni) NE smije postati "dizel".
        # (Varijante su odvojene kao na autoportalu — svaka u svom bloku.)
        html = ("<p>1,45€ - 1,50€ Eurodizel bez aditiva</p>"
                "<p>2,10€ Eurosuper 95</p>"
                "<p>0,95€ Plavi dizel</p>")
        cij = b._izvuci_cijene(html)
        self.assertEqual(cij.get("dizel"), 1.45)
        self.assertEqual(cij.get("plavi_dizel"), 0.95)

    def test_premium_dizel_se_ne_uzima(self):
        # REGRESIJA: dizel = 1,86 (premium). Ako je JEDINO premium -> dizel = None.
        html = "<p>1,86€ Eurodizel Premium</p>"
        self.assertIsNone(b._izvuci_cijene(html).get("dizel"))

    def test_broj_bez_eura_se_ignorira(self):
        # REGRESIJA: goli broj iz <script> JSON-a (dizel=0.64). Bez € -> ne hvataj.
        bez = "<p>1,54 Eurosuper 95</p>"          # nema €
        sa = "<p>1,54€ Eurosuper 95</p>"          # ima €
        self.assertIsNone(b._izvuci_cijene(bez).get("eurosuper95"))
        self.assertEqual(b._izvuci_cijene(sa).get("eurosuper95"), 1.54)

    def test_script_json_ne_zavarava(self):
        html = ('<script>window.__DATA={"dizel":0.64,"cijena":0.99}</script>'
                '<p>1,45€ Eurodizel</p>')
        self.assertEqual(b._izvuci_cijene(html).get("dizel"), 1.45)


class TestHakCentar(unittest.TestCase):
    def test_centar_karte_prepoznat(self):
        # Ugradeni HAK iframe ?c=lat,lon je centar karte, NIJE postaja.
        m = b._HAK_CENTAR_RE.search("https://map.hak.hr/?c=45.100,15.200&z=8")
        self.assertIsNotNone(m)


if __name__ == "__main__":
    unittest.main()
