# Cartec valjci → Radni nalozi

Skripta za računalo s Cartec valjcima (Snap-on „BR-Visualization”) u radioni.
Svaki test kočnica sama šalje u Radne naloge. Cartec se ne mijenja, skripta samo čita njegove datoteke.

## Instalacija (jednom, preko AnyDeska)
1. Kopiraj mapu `cartec_skripta` na računalo s valjcima.
2. Dvoklik na `instaliraj.bat` (ne treba administrator).
3. U Radnim nalozima: **Šifrarnik → 🛞 Cartec valjci → Odobri** novo računalo.

## Kako radi
- Cartec za svaku osovinu piše `Logs\AxleData_Service_NN.csv` (radna) i `AxleData_Parking_NN.csv` (parkirna), 10× u sekundi.
- Kad se datoteka 30 s ne mijenja, skripta uzme najveću silu lijevo/desno (bez faza pokretanja valjaka i otpora kotrljanja) i pošalje je.
- Ponovljeno mjerenje osovine prepiše datoteku → šalje se ponovno; u portalu vrijedi zadnje, ranije je „ponovljeno”.
- Novo vozilo = `Logs\<datum>_SaveVehicleData.log` „deleteAll = True” → novi test.
- Test se sam veže uz nalog na kojem se tog trena radi. Ako nije jasno, u **Pregled radova → Testovi kočnica** stoji pitanje „Test kočnica u HH:MM — koje vozilo?” s gumbima.
- Nema interneta / čeka odobrenje → mjerenje se odmah spremi u red (`%LOCALAPPDATA%\BravelCartec\red.txt`) i šalje se
  samo svakih 20 s, najstarije prvo — i kad Cartec u međuvremenu prepiše datoteku osovine ili se računalo ponovno pokrene (od v8).
  Kraj testa se javlja tek kad je red prazan. Server duplikate (isti otisak) odbacuje.

Dnevnik: `%LOCALAPPDATA%\BravelCartec\dnevnik.txt`
