# WhatsApp Message Templates (Bravel)

Predlošci za **business-initiated** poruke (izvan 24 h prozora) — nužni za
podsjetnike vozačima. Poruke unutar 24 h prozora (tok računa/primki) NE trebaju
predložak i besplatne su.

## Kako dodati (Meta)
WhatsApp Manager → **Manage templates** → **Create template**:
1. **Category:** Utility (transakcijski; jeftiniji i lakše se odobrava od
   Marketinga; ne koristiti Marketing za ove poruke)
2. **Name:** točno kako je niže (mala slova, podvlake) — kod ih zove po nazivu
3. **Language:** Croatian (`hr`)
4. Zalijepi **Body**, dodaj **varijable** i **sample** vrijednosti
5. (Opcionalno) **Footer:** `Bravel d.o.o.`
6. **Submit** → odobrenje obično 1–24 h

⚠️ Varijable moraju biti `{{1}}`, `{{2}}` … redom. Meta traži sample vrijednosti
i odbija predloške koji su SAMO varijabla ili čisto promotivni tekst.

## Slanje iz koda
`whatsapp.send_template(to, name, lang_code="hr", components=[...])`, gdje su
`components` body parametri redom (v. Graph API "components"). VAŽNO: pozvati s
`lang_code="hr"` (default u modulu je `en_US`).

---

## 1) potvrda_racuna  (Utility, hr)
Potvrda vozaču da je dokument zaprimljen (fallback izvan prozora; unutar prozora
ide obična poruka).

**Body:**
```
Bok {{1}}, zaprimili smo tvoj dokument ({{2}}) broj {{3}} na iznos {{4}} €. Hvala!
```
**Varijable / sample:** {{1}}=`Ivan`, {{2}}=`račun`, {{3}}=`123/1/1`, {{4}}=`85,40`
**Footer:** `Bravel d.o.o.`

## 2) podsjetnik_racun  (Utility, hr)
Podsjetnik da vozač pošalje račune/primke.

**Body:**
```
Bok {{1}}, podsjetnik: još nismo primili račune/primke za {{2}}. Molimo te da ih fotografiraš i pošalješ na ovaj broj čim budeš u mogućnosti. Hvala!
```
**Varijable / sample:** {{1}}=`Ivan`, {{2}}=`ovaj tjedan`
**Footer:** `Bravel d.o.o.`

## 3) podsjetnik_voznje  (Utility, hr)
Podsjetnik za vožnju / relaciju.

**Body:**
```
Bok {{1}}, podsjetnik za vožnju: {{2}}, polazak {{3}}. Ako nešto ne odgovara, javi nam na ovaj broj.
```
**Varijable / sample:** {{1}}=`Ivan`, {{2}}=`Zagreb → Split`, {{3}}=`sutra u 06:00`
**Footer:** `Bravel d.o.o.`

## 4) poruka_dispecera  (Utility, hr)
Operativna poruka dispečera vozaču.

**Body:**
```
Bok {{1}}, nova poruka od dispečera:
{{2}}
Za pitanja odgovori na ovaj broj.
```
**Varijable / sample:** {{1}}=`Ivan`, {{2}}=`Molim te nazovi ured kad staneš.`
**Footer:** `Bravel d.o.o.`

⚠️ Ovaj je najrizičniji za odobrenje jer je {{2}} slobodan tekst. Fiksni okvir
("poruka od dispečera", "odgovori na ovaj broj") obično prođe kao Utility; ako
Meta odbije, suziti opis ili podijeliti u konkretnije predloške.

---

## Napomena o trošku
Utility, Hrvatska ≈ par euro-centi po poruci; naplaćuje se PO poslanoj poruci.
Ako je vozač u zadnja 24 h nešto poslao/odgovorio → prozor otvoren → besplatno.
