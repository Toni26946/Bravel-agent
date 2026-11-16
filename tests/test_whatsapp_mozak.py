# ============================================================
#  Testovi — WhatsApp → mozak (prijave kvarova aplikacija).
#
#    - bez MOZAK_WA_KLJUC je sve isključeno (bot radi kao prije)
#    - mozak preuzme → bot pošalje odgovor i zapamti broj (smije mu kasnije javiti)
#    - mozak ne preuzme / pukne → False (bot nastavlja svojim tokom)
#    - _dispecer_dozvoljen propušta samo brojeve koje je mozak preuzeo
#
#  Bez mreže: requests.post i whatsapp.send_text se mockiraju.
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================
import os
import tempfile
import unittest
from unittest import mock

import whatsapp
import whatsapp_mozak


class _Odg:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._d = data or {}

    def json(self):
        return self._d


MSG = {"type": "text", "id": "wamid.1", "text": {"body": "nalozi ne spremaju sliku"}}


class TestWhatsappMozak(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p_dat = mock.patch.object(whatsapp_mozak, "_DATOTEKA", os.path.join(self.tmp, "wa.json"))
        self.p_dat.start()
        os.environ["MOZAK_WA_KLJUC"] = "tajna-test"
        os.environ.pop("WHATSAPP_DISPECER_BROJEVI", None)
        self.poslano = []
        self.p_send = mock.patch.object(whatsapp, "send_text",
                                        side_effect=lambda to, t: self.poslano.append((to, t)) or {"ok": True})
        self.p_send.start()

    def tearDown(self):
        self.p_dat.stop()
        self.p_send.stop()
        os.environ.pop("MOZAK_WA_KLJUC", None)

    def test_bez_kljuca_iskljuceno(self):
        os.environ.pop("MOZAK_WA_KLJUC", None)
        with mock.patch("requests.post") as p:
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko", MSG))
            p.assert_not_called()
        self.assertFalse(whatsapp_mozak.dozvoljen("385911112222"))

    def test_preuzeto_salje_odgovor_i_pamti(self):
        with mock.patch("requests.post", return_value=_Odg(200, {"preuzeto": True, "odgovor": "Zaprimljeno"})) as p:
            self.assertTrue(whatsapp_mozak.ponudi("0911112222", "Marko", MSG))
            self.assertEqual(p.call_args.kwargs["headers"]["X-Mozak-WA"], "tajna-test")
        self.assertEqual(self.poslano, [("385911112222", "Zaprimljeno")])
        self.assertTrue(whatsapp_mozak.dozvoljen("+385 91 111 2222"))
        with mock.patch("imenik_flota.brojevi_mehanicara", return_value=set()):
            self.assertTrue(whatsapp._dispecer_dozvoljen("385911112222"))
            self.assertFalse(whatsapp._dispecer_dozvoljen("385999999999"))

    def test_nije_preuzeto_ili_greska(self):
        with mock.patch("requests.post", return_value=_Odg(200, {"preuzeto": False})):
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko", MSG))
        with mock.patch("requests.post", side_effect=OSError("mreža")):
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko", MSG))
        with mock.patch("requests.post", return_value=_Odg(401, {})):
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko", MSG))
        self.assertEqual(self.poslano, [])
        self.assertFalse(whatsapp_mozak.dozvoljen("385911112222"))

    def test_slika_bez_opisa_nepoznat_broj_nije_preuzeta(self):
        with mock.patch("requests.post", return_value=_Odg(200, {"preuzeto": False})) as p:
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko",
                                                   {"type": "image", "id": "x", "image": {"id": "m1"}}))
            self.assertEqual(p.call_args.kwargs["json"]["tekst"], "")
            self.assertTrue(p.call_args.kwargs["json"]["slika"])

    def test_glasovna_ne_ide_mozgu(self):
        with mock.patch("requests.post") as p:
            self.assertFalse(whatsapp_mozak.ponudi("385911112222", "Marko", {"type": "audio", "id": "x"}))
            p.assert_not_called()

    def test_slika_s_opisom_ide_mozgu_i_prilozi_se(self):
        msg = {"type": "image", "id": "w2", "image": {"id": "m1", "caption": "ovo mi izbaci u nalozima"}}
        pozivi = []

        def lazni_post(url, **kw):
            pozivi.append((url, kw))
            return _Odg(200, {"preuzeto": True, "odgovor": "Zaprimljeno", "zadatak": 77})
        with mock.patch("requests.post", side_effect=lazni_post), \
                mock.patch.object(whatsapp, "download_media", return_value=(b"JPG", "image/jpeg")):
            self.assertTrue(whatsapp_mozak.ponudi("385911112222", "Marko", msg))
        self.assertEqual(pozivi[0][1]["json"]["tekst"], "ovo mi izbaci u nalozima")
        self.assertTrue(pozivi[0][1]["json"]["slika"])
        self.assertTrue(pozivi[1][0].endswith("/slika/77"))
        self.assertEqual(pozivi[1][1]["data"], b"JPG")


if __name__ == "__main__":
    unittest.main()
