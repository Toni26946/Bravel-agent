import { createContext, useContext, useEffect, useState } from 'react'

// Podržani jezici (hrvatski je zadani i osnova za prijevode koji nedostaju).
export const JEZICI = [
  { code: 'hr', naziv: 'Hrvatski' },
  { code: 'en', naziv: 'English' },
  { code: 'hi', naziv: 'हिन्दी (Hindi)' },
  { code: 'pa', naziv: 'ਪੰਜਾਬੀ (Punjabi)' },
]

// Jezik za prepoznavanje govora (Web Speech API).
export const GOVOR_JEZIK = { hr: 'hr-HR', en: 'en-US', hi: 'hi-IN', pa: 'pa-IN' }

const HR = {
  'app.title': 'Bravel Radni Nalozi',
  'app.subtitle': 'Servis kamiona',
  'common.spremi': 'Spremi', 'common.odustani': 'Odustani', 'common.spremam': 'Spremam…',
  'common.obrisi': 'Obriši', 'common.ucitavam': 'Učitavam…',
  // login
  'login.username': 'Korisničko ime', 'login.password': 'Lozinka',
  'login.submit': 'Prijavi se', 'login.submitting': 'Prijava…',
  // tabovi / uloge
  'tab.prijave': 'Prijave', 'tab.nalozi': 'Nalozi', 'tab.sifrarnik': 'Šifrarnik',
  'tab.steta': 'Šteta', 'tab.profil': 'Profil',
  'uloga.vozac': 'Vozač', 'uloga.voditelj': 'Voditelj', 'uloga.radnik': 'Radnik',
  // statusi naloga
  'status.otvoren': 'Otvoren', 'status.u_radu': 'U radu', 'status.ceka_dijelove': 'Čeka dijelove',
  'status.gotov': 'Gotov', 'status.zatvoren': 'Zatvoren',
  // nalozi (popis)
  'nalozi.title.radnik': 'Moji nalozi', 'nalozi.title.ostalo': 'Radni nalozi',
  'filter.sve': 'Sve', 'filter.otvoreni': 'Otvoreni', 'filter.uradu': 'U radu', 'filter.gotovi': 'Gotovi',
  'nalozi.savjetBrisi': 'Savjet: dugim pritiskom na nalog možeš ga obrisati.',
  'nalozi.prazno': 'Nema naloga za prikaz.', 'nalozi.rok': 'rok',
  'nalozi.obrisatiNalog': 'Obrisati nalog?', 'nalozi.brisanjeTrajno': 'brisanje je trajno.',
  'nalozi.obrisiNalog': 'Obriši nalog',
  // nalog (detalj)
  'nalog.promijeniStatus': 'Promijeni status', 'nalog.operacijeIZadaci': 'Operacije i zadaci',
  'nalog.shemaKamiona': 'Shema kamiona', 'nalog.prikaziShemu': 'Prikaži shemu kamiona',
  'nalog.povijestDijelova': 'Povijest dijelova (kamion {gb})', 'nalog.povijestStatusa': 'Povijest statusa',
  'nalog.voditelj': 'Voditelj', 'nalog.vozac': 'Vozač', 'nalog.rok': 'Rok', 'nalog.kreirao': 'Kreirao',
  'nalog.spojeno': '🔗 Novi unos je spojen u ovaj postojeći nalog (kamion je već imao aktivan nalog).',
  // operacije/zadaci
  'op.operacija': 'Operacija', 'op.radnik': 'Radnik', 'op.nemaOperacija': 'Još nema operacija.',
  'op.dodajOperaciju': 'Dodaj operaciju', 'op.noviZadatak': 'Novi zadatak', 'op.zadatak': '+ Zadatak',
  'op.diktirajZadatak': 'Diktiraj zadatak',
  'kat.dodajte': 'Dodajte operaciju…', 'kat.izgovori': 'Izgovori kategoriju',
  'kat.dodaj': '＋ Dodaj „{q}”', 'kat.nema': 'Nema kategorija.',
  // shema
  'shema.nacrt': 'Nacrt', 'shema.3d': '3D',
  'shema.uputa2d': 'Dodirni dio nacrta za detalje',
  'shema.uputa3d': 'Vrti prstom · dva prsta za zoom · dodirni dio',
  'shema.dijeloviUNalogu': 'Dijelovi u ovom nalogu',
  'shema.ostaleOperacije': 'Ostale operacije (nisu vezane uz dio)',
  'shema.nemaOpZaDio': 'Nema operacija za ovaj dio u ovom nalogu.',
  'statusd.neutral': 'nema posla', 'statusd.treba': 'za napraviti',
  'statusd.djelomicno': 'djelomično', 'statusd.gotovo': 'gotovo',
  // zone
  'zona.kabina': 'Kabina', 'zona.motor': 'Motor i pogon', 'zona.osovine': 'Osovine i ovjes',
  'zona.kotaci': 'Kotači i gume', 'zona.kocnice': 'Kočnice', 'zona.sasija': 'Šasija i limarija',
  'zona.nadogradnja': 'Nadogradnja / sanduk', 'zona.spremnik': 'Spremnici (gorivo/AdBlue)',
  'zona.sedlo': 'Sedlo / vučni sklop', 'zona.hidraulika': 'Hidraulika', 'zona.elektrika': 'Elektrika i svjetla',
  // povijest dijelova
  'dio.zamjena': '+ Zamjena dijela', 'dio.nema': 'Još nema zabilježenih zamjena dijelova.',
  'dio.koji': 'Koji dio je zamijenjen', 'dio.zasto': 'Zašto / što se desilo',
  'dio.datum': 'Datum', 'dio.km': 'Kilometraža (opcionalno)',
  'dio.potvrdaBrisanja': 'Obrisati ovaj zapis iz povijesti?',
  'dio.diktirajNaziv': 'Diktiraj naziv dijela', 'dio.diktirajRazlog': 'Diktiraj razlog',
  'dio.phNaziv': 'npr. Prednje kočione pločice', 'dio.phRazlog': 'npr. istrošene, škripale su pri kočenju',
  'dio.phKm': 'npr. 250000',
  // profil
  'profil.title': 'Profil', 'profil.korime': 'Korisničko ime', 'profil.uloga': 'Uloga', 'profil.telefon': 'Telefon',
  'profil.jezik': 'Jezik aplikacije',
  'profil.push': '🔔 Uključi push obavijesti', 'profil.pushOn': 'Obavijesti su uključene ✅',
  'profil.pushNo': 'Obavijesti nisu dopuštene u pregledniku.',
  'profil.odjava': 'Odjava',
  'profil.savjetInstall': 'Savjet: dodaj aplikaciju na početni zaslon (izbornik preglednika → „Dodaj na početni zaslon”).',
  'profil.promijeniLozinku': '🔑 Promijeni lozinku', 'profil.promjenaLozinke': 'Promjena lozinke',
  'profil.trenutnaLoz': 'Trenutna lozinka', 'profil.novaLoz': 'Nova lozinka', 'profil.ponoviLoz': 'Ponovi novu lozinku',
  'profil.lozKratka': 'Nova lozinka mora imati barem 4 znaka.',
  'profil.lozNePodudara': 'Nova lozinka i potvrda se ne podudaraju.',
  'profil.lozPromijenjena': 'Lozinka je promijenjena ✅',
  'mik.diktiraj': 'Diktiraj',
}

const EN = {
  'app.title': 'Bravel Work Orders', 'app.subtitle': 'Truck service',
  'common.spremi': 'Save', 'common.odustani': 'Cancel', 'common.spremam': 'Saving…',
  'common.obrisi': 'Delete', 'common.ucitavam': 'Loading…',
  'login.username': 'Username', 'login.password': 'Password',
  'login.submit': 'Sign in', 'login.submitting': 'Signing in…',
  'tab.prijave': 'Reports', 'tab.nalozi': 'Orders', 'tab.sifrarnik': 'Settings',
  'tab.steta': 'Damage', 'tab.profil': 'Profile',
  'uloga.vozac': 'Driver', 'uloga.voditelj': 'Manager', 'uloga.radnik': 'Mechanic',
  'status.otvoren': 'Open', 'status.u_radu': 'In progress', 'status.ceka_dijelove': 'Waiting for parts',
  'status.gotov': 'Done', 'status.zatvoren': 'Closed',
  'nalozi.title.radnik': 'My orders', 'nalozi.title.ostalo': 'Work orders',
  'filter.sve': 'All', 'filter.otvoreni': 'Open', 'filter.uradu': 'In progress', 'filter.gotovi': 'Done',
  'nalozi.savjetBrisi': 'Tip: long-press an order to delete it.',
  'nalozi.prazno': 'No orders to show.', 'nalozi.rok': 'due',
  'nalozi.obrisatiNalog': 'Delete order?', 'nalozi.brisanjeTrajno': 'deletion is permanent.',
  'nalozi.obrisiNalog': 'Delete order',
  'nalog.promijeniStatus': 'Change status', 'nalog.operacijeIZadaci': 'Operations and tasks',
  'nalog.shemaKamiona': 'Truck scheme', 'nalog.prikaziShemu': 'Show truck scheme',
  'nalog.povijestDijelova': 'Parts history (truck {gb})', 'nalog.povijestStatusa': 'Status history',
  'nalog.voditelj': 'Manager', 'nalog.vozac': 'Driver', 'nalog.rok': 'Due', 'nalog.kreirao': 'Created by',
  'nalog.spojeno': '🔗 The new entry was merged into this existing order (the truck already had an active order).',
  'op.operacija': 'Operation', 'op.radnik': 'Mechanic', 'op.nemaOperacija': 'No operations yet.',
  'op.dodajOperaciju': 'Add operation', 'op.noviZadatak': 'New task', 'op.zadatak': '+ Task',
  'op.diktirajZadatak': 'Dictate task',
  'kat.dodajte': 'Add an operation…', 'kat.izgovori': 'Say the category',
  'kat.dodaj': '＋ Add “{q}”', 'kat.nema': 'No categories.',
  'shema.nacrt': 'Drawing', 'shema.3d': '3D',
  'shema.uputa2d': 'Tap a part of the drawing for details',
  'shema.uputa3d': 'Drag to rotate · pinch to zoom · tap a part',
  'shema.dijeloviUNalogu': 'Parts in this order',
  'shema.ostaleOperacije': 'Other operations (not tied to a part)',
  'shema.nemaOpZaDio': 'No operations for this part in this order.',
  'statusd.neutral': 'no work', 'statusd.treba': 'to do',
  'statusd.djelomicno': 'partial', 'statusd.gotovo': 'done',
  'zona.kabina': 'Cabin', 'zona.motor': 'Engine & drivetrain', 'zona.osovine': 'Axles & suspension',
  'zona.kotaci': 'Wheels & tyres', 'zona.kocnice': 'Brakes', 'zona.sasija': 'Chassis & bodywork',
  'zona.nadogradnja': 'Superstructure / box', 'zona.spremnik': 'Tanks (fuel/AdBlue)',
  'zona.sedlo': 'Fifth wheel / coupling', 'zona.hidraulika': 'Hydraulics', 'zona.elektrika': 'Electrics & lights',
  'dio.zamjena': '+ Part replacement', 'dio.nema': 'No part replacements recorded yet.',
  'dio.koji': 'Which part was replaced', 'dio.zasto': 'Why / what happened',
  'dio.datum': 'Date', 'dio.km': 'Mileage (optional)',
  'dio.potvrdaBrisanja': 'Delete this history entry?',
  'dio.diktirajNaziv': 'Dictate part name', 'dio.diktirajRazlog': 'Dictate reason',
  'dio.phNaziv': 'e.g. Front brake pads', 'dio.phRazlog': 'e.g. worn out, squealing when braking',
  'dio.phKm': 'e.g. 250000',
  'profil.title': 'Profile', 'profil.korime': 'Username', 'profil.uloga': 'Role', 'profil.telefon': 'Phone',
  'profil.jezik': 'App language',
  'profil.push': '🔔 Enable push notifications', 'profil.pushOn': 'Notifications enabled ✅',
  'profil.pushNo': 'Notifications are not allowed in the browser.',
  'profil.odjava': 'Sign out',
  'profil.savjetInstall': 'Tip: add the app to your home screen (browser menu → “Add to Home Screen”).',
  'profil.promijeniLozinku': '🔑 Change password', 'profil.promjenaLozinke': 'Change password',
  'profil.trenutnaLoz': 'Current password', 'profil.novaLoz': 'New password', 'profil.ponoviLoz': 'Repeat new password',
  'profil.lozKratka': 'New password must be at least 4 characters.',
  'profil.lozNePodudara': 'New password and confirmation do not match.',
  'profil.lozPromijenjena': 'Password changed ✅',
  'mik.diktiraj': 'Dictate',
}

const HI = {
  'app.title': 'Bravel वर्क ऑर्डर', 'app.subtitle': 'ट्रक सर्विस',
  'common.spremi': 'सेव करें', 'common.odustani': 'रद्द करें', 'common.spremam': 'सेव हो रहा है…',
  'common.obrisi': 'हटाएँ', 'common.ucitavam': 'लोड हो रहा है…',
  'login.username': 'यूज़रनेम', 'login.password': 'पासवर्ड',
  'login.submit': 'साइन इन करें', 'login.submitting': 'साइन इन हो रहा है…',
  'tab.prijave': 'रिपोर्ट', 'tab.nalozi': 'ऑर्डर', 'tab.sifrarnik': 'सेटिंग',
  'tab.steta': 'नुकसान', 'tab.profil': 'प्रोफ़ाइल',
  'uloga.vozac': 'ड्राइवर', 'uloga.voditelj': 'मैनेजर', 'uloga.radnik': 'मैकेनिक',
  'status.otvoren': 'खुला', 'status.u_radu': 'चल रहा है', 'status.ceka_dijelove': 'पार्ट्स का इंतज़ार',
  'status.gotov': 'पूरा', 'status.zatvoren': 'बंद',
  'nalozi.title.radnik': 'मेरे ऑर्डर', 'nalozi.title.ostalo': 'वर्क ऑर्डर',
  'filter.sve': 'सभी', 'filter.otvoreni': 'खुले', 'filter.uradu': 'चल रहे', 'filter.gotovi': 'पूरे',
  'nalozi.savjetBrisi': 'सुझाव: ऑर्डर हटाने के लिए उसे देर तक दबाएँ।',
  'nalozi.prazno': 'दिखाने के लिए कोई ऑर्डर नहीं।', 'nalozi.rok': 'नियत',
  'nalozi.obrisatiNalog': 'ऑर्डर हटाएँ?', 'nalozi.brisanjeTrajno': 'हटाना स्थायी है।',
  'nalozi.obrisiNalog': 'ऑर्डर हटाएँ',
  'nalog.promijeniStatus': 'स्थिति बदलें', 'nalog.operacijeIZadaci': 'ऑपरेशन और काम',
  'nalog.shemaKamiona': 'ट्रक का नक्शा', 'nalog.prikaziShemu': 'ट्रक का नक्शा दिखाएँ',
  'nalog.povijestDijelova': 'पार्ट्स इतिहास (ट्रक {gb})', 'nalog.povijestStatusa': 'स्थिति इतिहास',
  'nalog.voditelj': 'मैनेजर', 'nalog.vozac': 'ड्राइवर', 'nalog.rok': 'नियत तिथि', 'nalog.kreirao': 'बनाया',
  'nalog.spojeno': '🔗 नई प्रविष्टि इस मौजूदा ऑर्डर में जोड़ दी गई (ट्रक का पहले से सक्रिय ऑर्डर था)।',
  'op.operacija': 'ऑपरेशन', 'op.radnik': 'मैकेनिक', 'op.nemaOperacija': 'अभी कोई ऑपरेशन नहीं।',
  'op.dodajOperaciju': 'ऑपरेशन जोड़ें', 'op.noviZadatak': 'नया काम', 'op.zadatak': '+ काम',
  'op.diktirajZadatak': 'काम बोलकर लिखें',
  'kat.dodajte': 'ऑपरेशन जोड़ें…', 'kat.izgovori': 'श्रेणी बोलें',
  'kat.dodaj': '＋ जोड़ें “{q}”', 'kat.nema': 'कोई श्रेणी नहीं।',
  'shema.nacrt': 'नक्शा', 'shema.3d': '3D',
  'shema.uputa2d': 'विवरण के लिए नक्शे के हिस्से को छुएँ',
  'shema.uputa3d': 'घुमाने के लिए खींचें · ज़ूम के लिए दो उँगलियाँ · हिस्से को छुएँ',
  'shema.dijeloviUNalogu': 'इस ऑर्डर के हिस्से',
  'shema.ostaleOperacije': 'अन्य ऑपरेशन (किसी हिस्से से जुड़े नहीं)',
  'shema.nemaOpZaDio': 'इस ऑर्डर में इस हिस्से के लिए कोई ऑपरेशन नहीं।',
  'statusd.neutral': 'कोई काम नहीं', 'statusd.treba': 'करना है',
  'statusd.djelomicno': 'आंशिक', 'statusd.gotovo': 'हो गया',
  'zona.kabina': 'केबिन', 'zona.motor': 'इंजन और पावरट्रेन', 'zona.osovine': 'एक्सल और सस्पेंशन',
  'zona.kotaci': 'पहिए और टायर', 'zona.kocnice': 'ब्रेक', 'zona.sasija': 'चेसिस और बॉडी',
  'zona.nadogradnja': 'सुपरस्ट्रक्चर / बॉक्स', 'zona.spremnik': 'टैंक (ईंधन/AdBlue)',
  'zona.sedlo': 'फिफ्थ व्हील / कपलिंग', 'zona.hidraulika': 'हाइड्रोलिक्स', 'zona.elektrika': 'इलेक्ट्रिक और लाइट',
  'dio.zamjena': '+ पार्ट बदलना', 'dio.nema': 'अभी तक कोई पार्ट रिप्लेसमेंट दर्ज नहीं।',
  'dio.koji': 'कौन सा पार्ट बदला गया', 'dio.zasto': 'क्यों / क्या हुआ',
  'dio.datum': 'तारीख', 'dio.km': 'माइलेज (वैकल्पिक)',
  'dio.potvrdaBrisanja': 'यह इतिहास प्रविष्टि हटाएँ?',
  'dio.diktirajNaziv': 'पार्ट का नाम बोलें', 'dio.diktirajRazlog': 'कारण बोलें',
  'dio.phNaziv': 'जैसे फ्रंट ब्रेक पैड', 'dio.phRazlog': 'जैसे घिस गए, ब्रेक पर आवाज़ आती थी',
  'dio.phKm': 'जैसे 250000',
  'profil.title': 'प्रोफ़ाइल', 'profil.korime': 'यूज़रनेम', 'profil.uloga': 'भूमिका', 'profil.telefon': 'फ़ोन',
  'profil.jezik': 'ऐप की भाषा',
  'profil.push': '🔔 पुश सूचनाएँ चालू करें', 'profil.pushOn': 'सूचनाएँ चालू ✅',
  'profil.pushNo': 'ब्राउज़र में सूचनाओं की अनुमति नहीं है।',
  'profil.odjava': 'साइन आउट',
  'profil.savjetInstall': 'सुझाव: ऐप को होम स्क्रीन पर जोड़ें (ब्राउज़र मेन्यू → “Add to Home Screen”)।',
  'profil.promijeniLozinku': '🔑 पासवर्ड बदलें', 'profil.promjenaLozinke': 'पासवर्ड बदलें',
  'profil.trenutnaLoz': 'वर्तमान पासवर्ड', 'profil.novaLoz': 'नया पासवर्ड', 'profil.ponoviLoz': 'नया पासवर्ड दोहराएँ',
  'profil.lozKratka': 'नया पासवर्ड कम से कम 4 अक्षर का होना चाहिए।',
  'profil.lozNePodudara': 'नया पासवर्ड और पुष्टि मेल नहीं खाते।',
  'profil.lozPromijenjena': 'पासवर्ड बदल गया ✅',
  'mik.diktiraj': 'बोलकर लिखें',
}

const PA = {
  'app.title': 'Bravel ਵਰਕ ਆਰਡਰ', 'app.subtitle': 'ਟਰੱਕ ਸਰਵਿਸ',
  'common.spremi': 'ਸੇਵ ਕਰੋ', 'common.odustani': 'ਰੱਦ ਕਰੋ', 'common.spremam': 'ਸੇਵ ਹੋ ਰਿਹਾ…',
  'common.obrisi': 'ਹਟਾਓ', 'common.ucitavam': 'ਲੋਡ ਹੋ ਰਿਹਾ…',
  'login.username': 'ਯੂਜ਼ਰਨੇਮ', 'login.password': 'ਪਾਸਵਰਡ',
  'login.submit': 'ਸਾਈਨ ਇਨ ਕਰੋ', 'login.submitting': 'ਸਾਈਨ ਇਨ ਹੋ ਰਿਹਾ…',
  'tab.prijave': 'ਰਿਪੋਰਟਾਂ', 'tab.nalozi': 'ਆਰਡਰ', 'tab.sifrarnik': 'ਸੈਟਿੰਗ',
  'tab.steta': 'ਨੁਕਸਾਨ', 'tab.profil': 'ਪ੍ਰੋਫਾਈਲ',
  'uloga.vozac': 'ਡਰਾਈਵਰ', 'uloga.voditelj': 'ਮੈਨੇਜਰ', 'uloga.radnik': 'ਮਕੈਨਿਕ',
  'status.otvoren': 'ਖੁੱਲ੍ਹਾ', 'status.u_radu': 'ਚੱਲ ਰਿਹਾ', 'status.ceka_dijelove': 'ਪਾਰਟਸ ਦੀ ਉਡੀਕ',
  'status.gotov': 'ਪੂਰਾ', 'status.zatvoren': 'ਬੰਦ',
  'nalozi.title.radnik': 'ਮੇਰੇ ਆਰਡਰ', 'nalozi.title.ostalo': 'ਵਰਕ ਆਰਡਰ',
  'filter.sve': 'ਸਾਰੇ', 'filter.otvoreni': 'ਖੁੱਲ੍ਹੇ', 'filter.uradu': 'ਚੱਲ ਰਹੇ', 'filter.gotovi': 'ਪੂਰੇ',
  'nalozi.savjetBrisi': 'ਸੁਝਾਅ: ਆਰਡਰ ਹਟਾਉਣ ਲਈ ਉਸਨੂੰ ਦੇਰ ਤੱਕ ਦਬਾਓ।',
  'nalozi.prazno': 'ਦਿਖਾਉਣ ਲਈ ਕੋਈ ਆਰਡਰ ਨਹੀਂ।', 'nalozi.rok': 'ਨਿਯਤ',
  'nalozi.obrisatiNalog': 'ਆਰਡਰ ਹਟਾਉਣਾ?', 'nalozi.brisanjeTrajno': 'ਹਟਾਉਣਾ ਪੱਕਾ ਹੈ।',
  'nalozi.obrisiNalog': 'ਆਰਡਰ ਹਟਾਓ',
  'nalog.promijeniStatus': 'ਸਥਿਤੀ ਬਦਲੋ', 'nalog.operacijeIZadaci': 'ਓਪਰੇਸ਼ਨ ਅਤੇ ਕੰਮ',
  'nalog.shemaKamiona': 'ਟਰੱਕ ਦਾ ਨਕਸ਼ਾ', 'nalog.prikaziShemu': 'ਟਰੱਕ ਦਾ ਨਕਸ਼ਾ ਵਿਖਾਓ',
  'nalog.povijestDijelova': 'ਪਾਰਟਸ ਇਤਿਹਾਸ (ਟਰੱਕ {gb})', 'nalog.povijestStatusa': 'ਸਥਿਤੀ ਇਤਿਹਾਸ',
  'nalog.voditelj': 'ਮੈਨੇਜਰ', 'nalog.vozac': 'ਡਰਾਈਵਰ', 'nalog.rok': 'ਨਿਯਤ ਮਿਤੀ', 'nalog.kreirao': 'ਬਣਾਇਆ',
  'nalog.spojeno': '🔗 ਨਵੀਂ ਐਂਟਰੀ ਇਸ ਮੌਜੂਦਾ ਆਰਡਰ ਵਿੱਚ ਜੋੜ ਦਿੱਤੀ ਗਈ।',
  'op.operacija': 'ਓਪਰੇਸ਼ਨ', 'op.radnik': 'ਮਕੈਨਿਕ', 'op.nemaOperacija': 'ਹਾਲੇ ਕੋਈ ਓਪਰੇਸ਼ਨ ਨਹੀਂ।',
  'op.dodajOperaciju': 'ਓਪਰੇਸ਼ਨ ਜੋੜੋ', 'op.noviZadatak': 'ਨਵਾਂ ਕੰਮ', 'op.zadatak': '+ ਕੰਮ',
  'op.diktirajZadatak': 'ਕੰਮ ਬੋਲ ਕੇ ਲਿਖੋ',
  'kat.dodajte': 'ਓਪਰੇਸ਼ਨ ਜੋੜੋ…', 'kat.izgovori': 'ਸ਼੍ਰੇਣੀ ਬੋਲੋ',
  'kat.dodaj': '＋ ਜੋੜੋ “{q}”', 'kat.nema': 'ਕੋਈ ਸ਼੍ਰੇਣੀ ਨਹੀਂ।',
  'shema.nacrt': 'ਨਕਸ਼ਾ', 'shema.3d': '3D',
  'shema.uputa2d': 'ਵੇਰਵੇ ਲਈ ਨਕਸ਼ੇ ਦੇ ਹਿੱਸੇ ਨੂੰ ਛੂਹੋ',
  'shema.uputa3d': 'ਘੁਮਾਉਣ ਲਈ ਖਿੱਚੋ · ਜ਼ੂਮ ਲਈ ਦੋ ਉਂਗਲਾਂ · ਹਿੱਸੇ ਨੂੰ ਛੂਹੋ',
  'shema.dijeloviUNalogu': 'ਇਸ ਆਰਡਰ ਦੇ ਹਿੱਸੇ',
  'shema.ostaleOperacije': 'ਹੋਰ ਓਪਰੇਸ਼ਨ (ਕਿਸੇ ਹਿੱਸੇ ਨਾਲ ਨਹੀਂ ਜੁੜੇ)',
  'shema.nemaOpZaDio': 'ਇਸ ਆਰਡਰ ਵਿੱਚ ਇਸ ਹਿੱਸੇ ਲਈ ਕੋਈ ਓਪਰੇਸ਼ਨ ਨਹੀਂ।',
  'statusd.neutral': 'ਕੋਈ ਕੰਮ ਨਹੀਂ', 'statusd.treba': 'ਕਰਨਾ ਹੈ',
  'statusd.djelomicno': 'ਅੰਸ਼ਿਕ', 'statusd.gotovo': 'ਹੋ ਗਿਆ',
  'zona.kabina': 'ਕੈਬਿਨ', 'zona.motor': 'ਇੰਜਣ ਅਤੇ ਪਾਵਰਟ੍ਰੇਨ', 'zona.osovine': 'ਐਕਸਲ ਅਤੇ ਸਸਪੈਂਸ਼ਨ',
  'zona.kotaci': 'ਪਹੀਏ ਅਤੇ ਟਾਇਰ', 'zona.kocnice': 'ਬ੍ਰੇਕ', 'zona.sasija': 'ਚੈਸੀ ਅਤੇ ਬਾਡੀ',
  'zona.nadogradnja': 'ਸੁਪਰਸਟ੍ਰਕਚਰ / ਬਾਕਸ', 'zona.spremnik': 'ਟੈਂਕ (ਈਂਧਨ/AdBlue)',
  'zona.sedlo': 'ਫਿਫਥ ਵੀਲ / ਕਪਲਿੰਗ', 'zona.hidraulika': 'ਹਾਈਡ੍ਰੌਲਿਕਸ', 'zona.elektrika': 'ਇਲੈਕਟ੍ਰਿਕ ਅਤੇ ਲਾਈਟਾਂ',
  'dio.zamjena': '+ ਪਾਰਟ ਬਦਲਣਾ', 'dio.nema': 'ਹਾਲੇ ਕੋਈ ਪਾਰਟ ਰਿਪਲੇਸਮੈਂਟ ਦਰਜ ਨਹੀਂ।',
  'dio.koji': 'ਕਿਹੜਾ ਪਾਰਟ ਬਦਲਿਆ', 'dio.zasto': 'ਕਿਉਂ / ਕੀ ਹੋਇਆ',
  'dio.datum': 'ਮਿਤੀ', 'dio.km': 'ਮਾਈਲੇਜ (ਵਿਕਲਪਿਕ)',
  'dio.potvrdaBrisanja': 'ਇਹ ਇਤਿਹਾਸ ਐਂਟਰੀ ਹਟਾਉਣੀ?',
  'dio.diktirajNaziv': 'ਪਾਰਟ ਦਾ ਨਾਮ ਬੋਲੋ', 'dio.diktirajRazlog': 'ਕਾਰਨ ਬੋਲੋ',
  'dio.phNaziv': 'ਜਿਵੇਂ ਫਰੰਟ ਬ੍ਰੇਕ ਪੈਡ', 'dio.phRazlog': 'ਜਿਵੇਂ ਘਸ ਗਏ, ਬ੍ਰੇਕ ਤੇ ਆਵਾਜ਼',
  'dio.phKm': 'ਜਿਵੇਂ 250000',
  'profil.title': 'ਪ੍ਰੋਫਾਈਲ', 'profil.korime': 'ਯੂਜ਼ਰਨੇਮ', 'profil.uloga': 'ਭੂਮਿਕਾ', 'profil.telefon': 'ਫ਼ੋਨ',
  'profil.jezik': 'ਐਪ ਦੀ ਭਾਸ਼ਾ',
  'profil.push': '🔔 ਪੁਸ਼ ਸੂਚਨਾਵਾਂ ਚਾਲੂ ਕਰੋ', 'profil.pushOn': 'ਸੂਚਨਾਵਾਂ ਚਾਲੂ ✅',
  'profil.pushNo': 'ਬ੍ਰਾਊਜ਼ਰ ਵਿੱਚ ਸੂਚਨਾਵਾਂ ਦੀ ਇਜਾਜ਼ਤ ਨਹੀਂ।',
  'profil.odjava': 'ਸਾਈਨ ਆਊਟ',
  'profil.savjetInstall': 'ਸੁਝਾਅ: ਐਪ ਨੂੰ ਹੋਮ ਸਕ੍ਰੀਨ ਤੇ ਜੋੜੋ (ਬ੍ਰਾਊਜ਼ਰ ਮੇਨੂ → “Add to Home Screen”)।',
  'profil.promijeniLozinku': '🔑 ਪਾਸਵਰਡ ਬਦਲੋ', 'profil.promjenaLozinke': 'ਪਾਸਵਰਡ ਬਦਲੋ',
  'profil.trenutnaLoz': 'ਮੌਜੂਦਾ ਪਾਸਵਰਡ', 'profil.novaLoz': 'ਨਵਾਂ ਪਾਸਵਰਡ', 'profil.ponoviLoz': 'ਨਵਾਂ ਪਾਸਵਰਡ ਦੁਹਰਾਓ',
  'profil.lozKratka': 'ਨਵਾਂ ਪਾਸਵਰਡ ਘੱਟੋ-ਘੱਟ 4 ਅੱਖਰਾਂ ਦਾ ਹੋਵੇ।',
  'profil.lozNePodudara': 'ਨਵਾਂ ਪਾਸਵਰਡ ਅਤੇ ਪੁਸ਼ਟੀ ਮੇਲ ਨਹੀਂ ਖਾਂਦੇ।',
  'profil.lozPromijenjena': 'ਪਾਸਵਰਡ ਬਦਲ ਗਿਆ ✅',
  'mik.diktiraj': 'ਬੋਲ ਕੇ ਲਿਖੋ',
}

const PRIJEVODI = { hr: HR, en: EN, hi: HI, pa: PA }

function prevedi(jezik, kljuc, vars) {
  let s = (PRIJEVODI[jezik] && PRIJEVODI[jezik][kljuc])
    || PRIJEVODI.en[kljuc] || PRIJEVODI.hr[kljuc] || kljuc
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v)
  return s
}

const JezikContext = createContext({ jezik: 'hr', t: (k) => k, postaviJezik: () => {} })

export function JezikProvider({ children }) {
  const [jezik, setJezik] = useState(() => localStorage.getItem('jezik') || 'hr')
  useEffect(() => {
    localStorage.setItem('jezik', jezik)
    document.documentElement.lang = jezik
  }, [jezik])
  const t = (kljuc, vars) => prevedi(jezik, kljuc, vars)
  return (
    <JezikContext.Provider value={{ jezik, t, postaviJezik: setJezik }}>
      {children}
    </JezikContext.Provider>
  )
}

export function useT() {
  return useContext(JezikContext)
}
