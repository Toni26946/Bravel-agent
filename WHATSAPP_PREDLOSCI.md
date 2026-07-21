# WhatsApp Message Templates (Bravel) — priprema za Meta odobrenje

Predlošci za **business-initiated** poruke (izvan 24 h prozora) — nužni za
proaktivne podsjetnike i poruke vozačima. Poruke UNUTAR 24 h prozora (npr. tok
računa/primki, odgovori vozaču koji je zadnji pisao) NE trebaju predložak i
besplatne su.

Definicije u kodu: `main.py` → `_WA_PREDLOSCI_DEF` (5 predložaka). Kreiraju se
komandom `/wa_kreiraj_predloske`, a status se prati s `/wa_predlosci`.

> ⚠️ Naziv + jezik su ključ predloška na Meti. Ako je predložak već PENDING/APPROVED,
> ponovno kreiranje istog naziva vraća „već postoji" i NE mijenja tekst. Za izmjenu
> teksta: obriši postojeći u WhatsApp Manageru pa ponovno kreiraj (`/wa_kreiraj_predloske`).

---

## Submitanje i praćenje

**Preko bota (preporučeno):**
1. `/wa_kreiraj_predloske` — kreira svih 5 na ispravnoj WABA-i (Bravel doo, 1482…).
2. `/wa_predlosci` — status: `PENDING` → `APPROVED`/`REJECTED` (obično 1–24 h).

**Ručno (WhatsApp Manager → Manage templates → Create template):**
Category **Utility**, Language **Croatian (hr)**, Name točno kao niže, zalijepi
Body + Footer, dodaj sample vrijednosti za svaku varijablu, Submit.

---

## Meta compliance — checklist (da prođe iz prve)

- **Category = UTILITY** (transakcijski). NE Marketing. Meta zna sam prekategorizirati
  u Marketing ako tekst zvuči promotivno — naši su operativni pa bi trebali ostati Utility.
- **Varijable `{{1}}`, `{{2}}`… redom**, bez preskoka. Nikad dvije varijable zaredom.
- **Ne smije biti SAMO varijabla** ni počinjati/završavati golom varijablom bez okvira.
- **Sample vrijednosti obavezne** za svaku varijablu (dane su niže; realne, ne „test").
- **Bez URL-skraćivača, bez promotivnih fraza** („akcija", „popust", „najbolje cijene").
- Emoji i višeredni tekst su dopušteni (koristimo umjereno).

---

## Predlošci (točno kako su u kodu)

### 1) `potvrda_racuna` · UTILITY · hr — RIZIK: nizak
Potvrda vozaču da je dokument zaprimljen (fallback izvan prozora).

**Body:**
```
Bok {{1}}, zaprimili smo tvoj dokument ({{2}}) broj {{3}} na iznos {{4}} €. Hvala!
```
**Footer:** `Bravel d.o.o.`
**Varijable:** {{1}} ime · {{2}} vrsta (račun/primka) · {{3}} broj dokumenta · {{4}} iznos
**Sample:** `Ivan` · `račun` · `123/1/1` · `85,40`

### 2) `podsjetnik_racun` · UTILITY · hr — RIZIK: nizak–srednji
Tjedni podsjetnik da vozač pošalje račune/primke (šalje `whatsapp_podsjetnici.py`).

**Body:**
```
Bok {{1}}, podsjetnik: još nismo primili račune/primke za {{2}}. Molimo te da ih fotografiraš i pošalješ na ovaj broj čim budeš u mogućnosti. Hvala!
```
**Footer:** `Bravel d.o.o.`
**Varijable:** {{1}} ime · {{2}} razdoblje
**Sample:** `Ivan` · `ovaj tjedan`
**Sender:** `send_template(broj, "podsjetnik_racun", "hr", components=body(ime, razdoblje))`

### 3) `podsjetnik_voznje` · UTILITY · hr — RIZIK: srednji
Podsjetnik za vožnju/relaciju.

**Body:**
```
Bok {{1}}, podsjetnik za vožnju: {{2}}, polazak {{3}}. Ako nešto ne odgovara, javi nam na ovaj broj.
```
**Footer:** `Bravel d.o.o.`
**Varijable:** {{1}} ime · {{2}} relacija · {{3}} polazak
**Sample:** `Ivan` · `Zagreb - Split` · `sutra u 06:00`

### 4) `poruka_dispecera` · UTILITY · hr — RIZIK: VISOK (slobodan tekst {{2}})
Operativna poruka dispečera vozaču.

**Body:**
```
Bok {{1}}, nova poruka od dispečera:
{{2}}
Za pitanja odgovori na ovaj broj.
```
**Footer:** `Bravel d.o.o.`
**Varijable:** {{1}} ime · {{2}} poruka (slobodan tekst)
**Sample:** `Ivan` · `Molim te nazovi ured kad staneš.`
**Napomena:** slobodan tekst u {{2}} je najrizičniji za odobrenje (Meta ga zna
odbiti kao „generički container"). Fiksni okvir („poruka od dispečera",
„odgovori na ovaj broj") obično prođe kao Utility. **Praktično:** dispečerske
poruke vozaču koji je nedavno pisao idu UNUTAR 24 h prozora → `/wa_send` (bez
predloška, besplatno); predložak treba samo za hladan kontakt izvan prozora.

### 5) `podsjetnik_opci` · UTILITY · hr — RIZIK: srednji (echo korisnikovog teksta)
Podsjetnik koji si zaposlenik sam postavi preko WhatsApp izbornika; šalje se izvan
prozora (`whatsapp_meni.py`).

**Body:**
```
🔔 Podsjetnik koji si postavio:
{{1}}
Hvala i ugodan dan!
```
**Footer:** `Bravel d.o.o.`
**Varijable:** {{1}} tekst podsjetnika
**Sample:** `natoči gorivo prije polaska`
**Napomena:** „koji si postavio" jasno označava da je korisnik sam tražio poruku
(smanjuje spam-rizik). Ako Meta odbije zbog slobodnog {{1}}, suzi okvir.

---

## Ako Meta ODBIJE predložak (playbook)

1. Pročitaj razlog u WhatsApp Manageru (najčešće: kriva kategorija ili „generički"
   slobodan tekst).
2. **Kriva kategorija** → ostavi tekst, promijeni na Utility (ili obrnuto ako je
   sadržaj zaista promotivan — nije naš slučaj).
3. **Slobodan tekst (poruka_dispecera / podsjetnik_opci)** → dodaj konkretniji
   fiksni okvir oko varijable ili razdvoji u više namjenskih predložaka; obriši
   odbijeni pa ponovno kreiraj.
4. Nakon izmjene teksta u `main.py` (`_WA_PREDLOSCI_DEF`): **obriši** stari predložak
   u Manageru (isti naziv se ne može ažurirati) pa `/wa_kreiraj_predloske`.

---

## Trošak
Utility, Hrvatska ≈ par euro-centi po poruci; naplaćuje se PO poslanoj poruci.
Ako je vozač u zadnja 24 h pisao/odgovorio → prozor otvoren → besplatno (bez predloška).
