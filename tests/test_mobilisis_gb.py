# ============================================================
#  Testovi: GB se uzima iz NAZIVA vozila u Mobilisisu, ne iz registracije
#  (Toni 17.11.2026.: „fiksno gledaj samo gb").
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================

import unittest

import mobilisis as m


class TestGbIzNaziva(unittest.TestCase):
    def test_naziv_s_gb(self):
        self.assertEqual(m.gb_iz_teksta("DAF 406 Vinothkannan"), "406")
        self.assertEqual(m.gb_iz_teksta("MAN 42 Najam Agroburza"), "42")
        self.assertEqual(m.gb_iz_teksta("ACTROS 446 H Tharu"), "446")

    def test_registracija_nije_gb(self):
        for t in ("ZG1257HU", "ZG-5267-KM", "Š 303040", "MAN TGX 18.520", ""):
            self.assertIsNone(m.gb_iz_teksta(t), t)

    def test_naziv_prednost_pred_registracijom(self):
        uredaj = {"Id": 77, "Name": "ZG9464KR", "Description": "MAN 37 Novi vozač"}
        self.assertEqual(m.gb_iz_naziva(uredaj, {}), "37")

    def test_bez_gb_u_nazivu(self):
        self.assertIsNone(m.gb_iz_naziva({"Id": 5, "Name": "ZG1257HU"}, {"deviceId": 5}))


if __name__ == "__main__":
    unittest.main()
