# ============================================================
#  GRAPH SMOKE TEST - brza provjera Azure kredencijala i dozvola
#  prije prvog pravog upisa racuna na SharePoint.
#
#  Sto radi:
#   1. provjeri jesu li Graph kredencijali postavljeni
#   2. dohvati app-only token (client credentials)
#   3. dohvati site ID (braveldoo.sharepoint.com/sites/tendenzanova)
#   4. dohvati drive ID (biblioteka "Zajednički dokumenti")
#   5. provjeri postoji li Racuni_terena.xlsx u folderu BRAVEL
#
#  Pokretanje (kredencijali moraju biti u okolini):
#     python graph_smoke.py
#  Na Fly-u:
#     fly ssh console -a <app> -C "python graph_smoke.py"
#
#  NE mijenja nista na SharePointu (samo cita).
# ============================================================

import sys

import graph_client as gc


def main():
    print("=== GRAPH SMOKE TEST ===\n")

    # 1. konfiguracija
    if not gc.is_configured():
        print("✗ Graph nije konfiguriran.")
        print("  Provjeri da su postavljeni: GRAPH_CLIENT_ID, GRAPH_TENANT_ID, "
              "GRAPH_CLIENT_SECRET")
        print("  te da je 'msal' instaliran (pip install msal).")
        return 1
    print("✓ Kredencijali postavljeni, msal dostupan.")

    # 2. token
    try:
        token = gc._get_token()
        print(f"✓ Token dohvaćen (duljina {len(token)}).")
    except gc.GraphError as e:
        print(f"✗ Autentikacija nije uspjela: {e}")
        return 1

    # 3. site
    try:
        site_id = gc.get_site_id()
        print(f"✓ Site ID: {site_id}")
    except gc.GraphError as e:
        print(f"✗ Dohvat sajta nije uspio: {e}")
        return 1

    # 4. drive (biblioteka)
    try:
        drive_id = gc.get_drive_id()
        print(f"✓ Drive ID (biblioteka): {drive_id}")
    except gc.GraphError as e:
        print(f"✗ Dohvat biblioteke nije uspio: {e}")
        if e.status_code == 403:
            print("  → 403: provjeri Application permission Sites.ReadWrite.All "
                  "+ admin consent.")
        return 1

    # 5. postoji li Excel fajl u BRAVEL folderu
    try:
        postoji = gc.file_exists("Racuni_terena.xlsx")
        if postoji:
            print(f"✓ '{gc.FOLDER}/Racuni_terena.xlsx' postoji.")
        else:
            print(f"• '{gc.FOLDER}/Racuni_terena.xlsx' još ne postoji "
                  "(kreirat će se pri prvom upisu).")
    except gc.GraphError as e:
        print(f"✗ Provjera fajla nije uspjela: {e}")
        if e.status_code == 403:
            print("  → 403: nedostaje ovlast za čitanje/pisanje datoteka.")
        return 1

    print("\n=== SVE OK — kredencijali i dozvole rade. ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
