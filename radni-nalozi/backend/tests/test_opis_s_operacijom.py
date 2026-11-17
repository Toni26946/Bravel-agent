"""Mehaničar uz opis zadatka dobiva i naziv operacije (WhatsApp prijava #298):
„lijevi kotač blokira" sam ne govori na kojoj je osovini."""
from app.routers.dispecer import opis_s_operacijom


def test_naziv_operacije_ide_ispred_opisa():
    assert opis_s_operacijom("Kočnice 3. osovina", "lijevi kotač blokira") == \
        "Kočnice 3. osovina – lijevi kotač blokira"


def test_razno_i_prazno_se_ne_dodaju():
    assert opis_s_operacijom("RAZNO", "zamijeni žarulju") == "zamijeni žarulju"
    assert opis_s_operacijom(None, "zamijeni žarulju") == "zamijeni žarulju"
    assert opis_s_operacijom("", None) == ""


def test_ne_ponavlja_ako_je_vec_u_opisu():
    assert opis_s_operacijom("Kočnice", "kočnice 3. osovina lijevo") == "kočnice 3. osovina lijevo"


def test_samo_operacija_bez_opisa():
    assert opis_s_operacijom("Kočnice 3. osovina", "") == "Kočnice 3. osovina"
