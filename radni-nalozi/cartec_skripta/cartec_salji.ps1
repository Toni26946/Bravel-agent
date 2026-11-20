# Bravel — Cartec valjci → Radni nalozi
# Radi na računalu s Cartec valjcima (Snap-on BR-Visualization). Ništa ne mijenja
# u Cartecu: samo ČITA njegove datoteke mjerenja i šalje rezultate u Radne naloge.
#
# Izvor: <Cartec>\Logs\AxleData_Service_NN.csv (radna kočnica, osovina NN) i
#        AxleData_Parking_NN.csv (parkirna). Cartec ih piše uživo (10x u sekundi):
#        TimeStamp;PedalForce;BrakeForceLeft;BrakeForceRight;Difference;WeightLeft;WeightRight;Weight;TestPhase;...
#        Ponovljeno mjerenje osovine prepiše datoteku → šaljemo svaku novu verziju.
# Vozilo: <Cartec>\Logs\<yyyyMMdd>_SaveVehicleData.log — „deleteAll = True" = novo vozilo.
#
# Pokretanje: instaliraj.bat (doda se u Startup, radi skriveno). Dnevnik: %LOCALAPPDATA%\BravelCartec\dnevnik.txt

$ErrorActionPreference = 'Continue'
# Verzija: portal poslužuje novu skriptu, pa se skripta sama ažurira kad je ovaj broj manji.
$Verzija   = '8'
$Baza      = 'https://bravel-radni-nalozi.fly.dev/api'
$CartecDir = 'C:\Program Files (x86)\BR-Visualization'
$Stanje    = Join-Path $env:LOCALAPPDATA 'BravelCartec'
# Za probu na drugom računalu (lokalni server / kopija Cartec mapa):
if ($env:BRAVEL_CARTEC_URL) { $Baza = $env:BRAVEL_CARTEC_URL }
if ($env:BRAVEL_CARTEC_DIR) { $CartecDir = $env:BRAVEL_CARTEC_DIR }
if ($env:BRAVEL_CARTEC_STANJE) { $Stanje = $env:BRAVEL_CARTEC_STANJE }
$TokenDat  = Join-Path $Stanje 'token.txt'
$PoslanoDat = Join-Path $Stanje 'poslano.txt'
# Red neposlanih mjerenja (v8): kad pukne veza, mjerenje se odmah spremi ovdje (jedan JSON po retku)
# i šalje se kasnije — i kad Cartec u međuvremenu prepiše datoteku osovine ili se računalo ponovno pokrene.
$RedDat    = Join-Path $Stanje 'red.txt'
$RedSek    = 20        # koliko često se pokušava poslati red
$Dnevnik   = Join-Path $Stanje 'dnevnik.txt'
$MirnoSek  = 30        # rezerva: sadržaj se ne mijenja ovoliko sekundi = mjerenje gotovo
                       # (redovno se osovina šalje čim Cartec pokaže rezultat — „SHOW BRAKE RESULT")
$KrajDat   = Join-Path $Stanje 'kraj.txt'
$KrajSek   = 45        # valjci prazni (Cartec „IDLE") ovoliko sekundi = vozilo sišlo, test gotov
                       # (između dviju osovina „IDLE" traje ~5–15 s dok vozilo pomakne iduću osovinu)
# Faze koje NISU kočenje (pokretanje valjaka, otpor kotrljanja) — ne ulaze u najveću silu.
$NeKocenje = @('BrakeStartUp', 'WaitingBeforeWheelDrag', 'WheelDrag')

New-Item -ItemType Directory -Force -Path $Stanje | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Samo jedna kopija skripte odjednom.
$mutex = New-Object System.Threading.Mutex($false, 'Global\BravelCartecSalji')
if (-not $mutex.WaitOne(0)) { exit }

function Zapisi($tekst) {
    $red = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $tekst
    try {
        Add-Content -Path $Dnevnik -Value $red -Encoding UTF8
        if ((Get-Item $Dnevnik).Length -gt 2MB) { Move-Item $Dnevnik "$Dnevnik.staro" -Force }
    } catch {}
}

function Dohvati($putanja, $token) {
    # PowerShell 5.1 bez „charset" u odgovoru čita tekst kao Latin-1 i pokvari č/ć/š/ž → dekodiramo sami (UTF-8).
    $odg = Invoke-WebRequest -Uri ($Baza + $putanja) -Method Get -Headers @{ 'X-Cartec-Token' = $token } -TimeoutSec 30 -UseBasicParsing
    $tekst = [Text.Encoding]::UTF8.GetString($odg.RawContentStream.ToArray())
    return $tekst | ConvertFrom-Json
}

function JaviStanje($token) {
    # Verzija + zadnji redovi dnevnika u portal (Šifrarnik → Cartec valjci) — kvar se vidi bez AnyDeska.
    if (-not $token) { return }
    try {
        $rep = ''
        if (Test-Path $Dnevnik) { $rep = (Get-Content $Dnevnik -Tail 60 -Encoding UTF8) -join "`n" }
        if ($rep.Length -gt 11000) { $rep = $rep.Substring($rep.Length - 11000) }
        $dij = ''
        try { $dij = Dijagnoza } catch { $dij = "dijagnoza: $($_.Exception.Message)" }
        if ($dij.Length -gt 8500) { $dij = $dij.Substring(0, 8500) }
        [void](Posalji '/cartec/stanje' @{ verzija = $Verzija; dnevnik = ($rep + "`n===== CARTEC =====`n" + $dij) } $token)
    } catch {}
}

function Dijagnoza {
    # Za dijagnozu bez AnyDeska: što je u datotekama osovina i tijek stanja valjaka (zadnjih ~40).
    $out = New-Object System.Collections.ArrayList
    foreach ($dat in @(Get-ChildItem -Path (Join-Path $CartecDir 'Logs') -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue)) {
        try {
            $t = ProcitajDijeljeno $dat.FullName
            $faze = @{}; $n = 0; $prvi = ''; $zadnji = ''; $maxL = 0; $maxD = 0
            foreach ($red in $t -split "`n") {
                $s = $red.Trim().Split(';')
                if ($s.Count -lt 9 -or $s[0] -eq 'TimeStamp') { continue }
                $n++; if (-not $prvi) { $prvi = $s[0] }; $zadnji = $s[0]
                $faze[$s[8]] = 1 + [int]$faze[$s[8]]
                $l = 0; $d = 0; [void][int]::TryParse($s[2], [ref]$l); [void][int]::TryParse($s[3], [ref]$d)
                if ($l -gt $maxL) { $maxL = $l }; if ($d -gt $maxD) { $maxD = $d }
            }
            $f = ($faze.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ','
            [void]$out.Add("$($dat.Name) $($t.Length)zn redova=$n $prvi..$zadnji maxL=$maxL maxD=$maxD [$f]")
        } catch { [void]$out.Add("$($dat.Name): $($_.Exception.Message)") }
    }
    $sad = Get-Date
    $tp = Join-Path $CartecDir ('Logs\' + $sad.ToString('yyyyMMdd') + '_TestProcedure.log')
    if (Test-Path $tp) {
        $faze = Faze (RepDatoteke $tp 2000000) $sad
        $tijek = New-Object System.Collections.ArrayList
        $bilo = ''
        for ($i = 0; $i -lt $faze.Count; $i++) {
            $fz = $faze[$i].Faza
            $do = if ($i + 1 -lt $faze.Count) { $faze[$i + 1].Kad } else { $sad }
            $traje = ($do - $faze[$i].Kad).TotalSeconds
            if ($fz -eq 'IDLE BRAKE' -and $traje -lt 3) { continue }        # titranje praznih valjaka
            if ($fz -eq 'IDLE' -and $bilo -eq 'IDLE') { continue }          # prazni valjci — samo prvi put
            $bilo = $fz
            [void]$tijek.Add($faze[$i].Kad.ToString('HH:mm:ss') + ' ' + $fz + ' ' + [int]$traje + 's')
        }
        $od = [Math]::Max(0, $tijek.Count - 70)
        for ($i = $od; $i -lt $tijek.Count; $i++) { [void]$out.Add($tijek[$i]) }
    }
    return ($out -join "`n")
}

function Azuriraj($token) {
    # Nova verzija s portala → prepiši ovu datoteku i izađi; pokretač (VBS) je pokrene ponovno.
    if (-not $token) { return }
    try {
        $r = Dohvati '/cartec/skripta' $token
        $nova = 0; $ova = 0
        [void][int]::TryParse([string]$r.verzija, [ref]$nova)
        [void][int]::TryParse($Verzija, [ref]$ova)
        if ($nova -gt $ova -and $r.sadrzaj) {
            $put = $PSCommandPath
            [IO.File]::WriteAllText($put, [string]$r.sadrzaj, (New-Object Text.UTF8Encoding($true)))
            Zapisi "Ažurirano s verzije $ova na $nova — ponovno pokretanje."
            try { $mutex.ReleaseMutex() } catch {}
            exit 0
        }
    } catch {}
}

function Posalji($putanja, $tijelo, $token) {
    $json = $tijelo | ConvertTo-Json -Compress
    $bajtovi = [Text.Encoding]::UTF8.GetBytes($json)
    $zaglavlja = @{}
    if ($token) { $zaglavlja['X-Cartec-Token'] = $token }
    return Invoke-RestMethod -Uri ($Baza + $putanja) -Method Post -Body $bajtovi `
        -ContentType 'application/json; charset=utf-8' -Headers $zaglavlja -TimeoutSec 20
}

function Token {
    if (Test-Path $TokenDat) {
        $t = (Get-Content $TokenDat -Raw).Trim()
        if ($t) { return $t }
    }
    try {
        $r = Posalji '/cartec/prijava' @{ naziv = "Cartec valjci ($env:COMPUTERNAME)" } $null
        Set-Content -Path $TokenDat -Value $r.token -Encoding ASCII
        Zapisi "Prijavljen kao uređaj $($r.id) — čeka odobrenje u Radnim nalozima (Šifrarnik → Cartec valjci)."
        return $r.token
    } catch {
        Zapisi "Prijava nije uspjela: $($_.Exception.Message)"
        return $null
    }
}

function ProcitajDijeljeno($put) {
    # Cartec drži datoteku otvorenom — čitamo uz dijeljenje.
    $fs = [IO.File]::Open($put, 'Open', 'Read', 'ReadWrite')
    try {
        $sr = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
        return $sr.ReadToEnd()
    } finally { $fs.Dispose() }
}

function RepDatoteke($put, $bajtova) {
    # Samo kraj (velike) datoteke, uz dijeljenje — Cartec je drži otvorenom.
    $fs = [IO.File]::Open($put, 'Open', 'Read', 'ReadWrite')
    try {
        [void]$fs.Seek([Math]::Max(0, $fs.Length - $bajtova), 'Begin')
        $sr = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
        return $sr.ReadToEnd()
    } finally { $fs.Dispose() }
}

function Faze($tekst, [datetime]$dan) {
    # Početci stanja iz Cartecovog TestProcedure.log: „HH:mm:ss,fff <X> ---- X START ----".
    $out = New-Object System.Collections.ArrayList
    foreach ($red in $tekst -split "`n") {
        if ($red -match '^(\d{2}:\d{2}:\d{2},\d{3}) <([A-Z ]+)> -+ ([A-Z ]+) START -+') {
            $kad = [datetime]::ParseExact($dan.ToString('yyyy-MM-dd') + ' ' + $Matches[1], 'yyyy-MM-dd HH:mm:ss,fff', $null)
            [void]$out.Add(@{ Kad = $kad; Faza = $Matches[3] })
        }
    }
    return ,$out
}

function NadjiKraj($faze, [datetime]$sad, [int]$sek) {
    # Vozilo sišlo s valjaka = prvi „IDLE" nakon zadnjeg „BRAKE TEST", i od tada $sek sekundi
    # nijedan „IDLE BRAKE" (kotač na valjcima) nije trajao 3 s ili više. Prazni valjci sami
    # titraju IDLE ↔ IDLE BRAKE (~0,1 s) — to se ne broji. Vrati @{ Kocenje; Odlazak } ili $null.
    $b = -1
    for ($i = $faze.Count - 1; $i -ge 0; $i--) { if ($faze[$i].Faza -eq 'BRAKE TEST') { $b = $i; break } }
    if ($b -lt 0) { return $null }
    $o = -1
    for ($i = $b + 1; $i -lt $faze.Count; $i++) { if ($faze[$i].Faza -eq 'IDLE') { $o = $i; break } }
    if ($o -lt 0) { return $null }
    for ($i = $o + 1; $i -lt $faze.Count; $i++) {
        if ($faze[$i].Faza -ne 'IDLE BRAKE') { continue }
        $do = if ($i + 1 -lt $faze.Count) { $faze[$i + 1].Kad } else { $sad }
        if (($do - $faze[$i].Kad).TotalSeconds -ge 3) { return $null }   # opet nešto na valjcima
    }
    if (($sad - $faze[$o].Kad).TotalSeconds -lt $sek) { return $null }
    return @{ Kocenje = $faze[$b].Kad; Odlazak = $faze[$o].Kad }
}

function FazeDanas {
    # Stanja valjaka iz današnjeg Cartec TestProcedure.log (zadnjih ~30 min); $null ako ga nema.
    $sad = Get-Date
    $dat = Join-Path $CartecDir ('Logs\' + $sad.ToString('yyyyMMdd') + '_TestProcedure.log')
    if (-not (Test-Path $dat)) { return $null }
    return ,(Faze (RepDatoteke $dat 150000) $sad)
}

function PosaljiUzivo($tekst, $token) {
    # Trenutna i najveća sila iz datoteke koja se upravo piše (Cartec 10x/s) → portal.
    if (-not $token) { return }
    $l = 0; $d = 0; $maxL = 0; $maxD = 0; $faza = ''
    foreach ($red in ($tekst -split "`n")) {
        $s = $red.Trim().Split(';')
        if ($s.Count -lt 9 -or $s[0] -eq 'TimeStamp') { continue }
        $a = 0; $b = 0
        [void][int]::TryParse($s[2], [ref]$a); [void][int]::TryParse($s[3], [ref]$b)
        $l = $a; $d = $b; $faza = $s[8]
        if ($NeKocenje -contains $s[8]) { continue }
        if ($a -gt $maxL) { $maxL = $a }
        if ($b -gt $maxD) { $maxD = $b }
    }
    try {
        $json = @{ l = $l; d = $d; max_l = $maxL; max_d = $maxD; faza = $faza } | ConvertTo-Json -Compress
        [void](Invoke-RestMethod -Uri ($Baza + '/cartec/uzivo') -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($json)) `
            -ContentType 'application/json; charset=utf-8' -Headers @{ 'X-Cartec-Token' = $token } -TimeoutSec 3)
    } catch {}   # uživo nije bitno — ne smije zakočiti petlju
}

function PrviRed($tekst) {
    # Vrijeme PRVOG retka mjerenja u datoteci = oznaka tog mjerenja (novo mjerenje prepiše datoteku).
    foreach ($red in ($tekst -split "`n")) {
        $s = $red.Trim().Split(';')
        if ($s.Count -lt 9 -or $s[0] -eq 'TimeStamp') { continue }
        if ($s[0] -notmatch '^(\d{2}:\d{2}:\d{2}),(\d{1,3})') { return $null }
        $sad = Get-Date
        $kad = [datetime]::ParseExact($sad.ToString('yyyy-MM-dd') + ' ' + $Matches[1], 'yyyy-MM-dd HH:mm:ss', $null).AddMilliseconds([int]$Matches[2])
        if ($kad -gt $sad.AddMinutes(10)) { $kad = $kad.AddDays(-1) }
        return $kad
    }
    return $null
}

function RezultatNakon($faze, [datetime]$pocetak) {
    # Je li Cartec pokazao rezultat („SHOW BRAKE RESULT") nakon početka ovog mjerenja → kočenje gotovo.
    # (Cartec u datoteku piše i nakon rezultata dok vozilo ne siđe, pa se „mirna datoteka" ne može čekati.)
    if (-not $faze) { return $false }
    foreach ($f in $faze) {
        if ($f.Faza -eq 'SHOW BRAKE RESULT' -and $f.Kad -ge $pocetak) { return $true }
    }
    return $false
}

function ProvjeriKraj($token, $faze) {
    # Kraj testa = vozilo sišlo s valjaka (Cartec <datum>_TestProcedure.log) → javi portalu,
    # a on pošalje poruku za upis GB-a. Jednom po testu (pamti se u kraj.txt).
    if (-not $token -or -not $faze) { return }
    $sad = Get-Date
    $k = NadjiKraj $faze $sad $KrajSek
    if (-not $k) { return }
    if (($sad - $k.Odlazak).TotalMinutes -gt 30) { return }   # staro (npr. nakon ponovnog pokretanja)
    $stanjeKad = $k.Odlazak
    $oznaka = $k.Kocenje.ToString('yyyy-MM-dd HH:mm:ss')
    if ($script:javljenKraj -eq $oznaka) { return }
    # Prvo neka odu sve osovine (datoteka koja se još mjeri ili čeka slanje, i red neposlanih).
    if ($script:redSlanja.Count -gt 0) { return }
    foreach ($v in $videno.Values) {
        if (-not $poslano.Contains($v.H) -and -not $prazno.Contains($v.H)) { return }
    }
    try {
        $r = Posalji '/cartec/kraj' @{ vrijeme = ([DateTimeOffset]$stanjeKad).ToString('yyyy-MM-ddTHH:mm:sszzz') } $token
        $script:javljenKraj = $oznaka
        Set-Content -Path $KrajDat -Value $oznaka -Encoding ASCII
        Zapisi "Vozilo sišlo s valjaka u $($stanjeKad.ToString('HH:mm:ss')) → kraj testa $($r.test_id), poruka poslana: $($r.poslano)."
    } catch {
        Zapisi "Javljanje kraja testa nije uspjelo: $($_.Exception.Message) — pokušat ću ponovno."
    }
}

function UcitajRed {
    # Red neposlanih mjerenja s diska (preživi ponovno pokretanje). Pokvareni redak se preskoči.
    $red = New-Object System.Collections.ArrayList
    if (-not (Test-Path $RedDat)) { return ,$red }
    foreach ($l in (Get-Content $RedDat -Encoding UTF8)) {
        if (-not $l.Trim()) { continue }
        try { [void]$red.Add(($l | ConvertFrom-Json)) } catch {}
    }
    return ,$red
}

function SpremiRed {
    $retci = @($script:redSlanja | ForEach-Object { $_ | ConvertTo-Json -Compress })
    if ($retci.Count -eq 0) { Remove-Item $RedDat -Force -ErrorAction SilentlyContinue; return }
    Set-Content -Path $RedDat -Encoding UTF8 -Value $retci
}

function URed($tijelo) {
    # Mjerenje koje nije otišlo → u red (isti otisak samo jednom).
    foreach ($m in $script:redSlanja) { if ($m.otisak -eq $tijelo.otisak) { return } }
    [void]$script:redSlanja.Add([pscustomobject]$tijelo)
    SpremiRed
}

function PosaljiRed($token) {
    # Najstarije prvo; stane na prvoj grešci veze (redoslijed osovina ostaje). Server po otisku
    # odbacuje duplikat, pa ponovno slanje istog mjerenja ne smeta.
    if (-not $token -or $script:redSlanja.Count -eq 0) { return }
    if (((Get-Date) - $script:zadnjiRed).TotalSeconds -lt $RedSek) { return }
    $script:zadnjiRed = Get-Date
    while ($script:redSlanja.Count -gt 0) {
        $m = $script:redSlanja[0]
        $tijelo = @{}
        foreach ($p in $m.PSObject.Properties) { $tijelo[$p.Name] = $p.Value }
        # (PowerShell 7 ISO tekst pretvori u datum — vrati ga u isti oblik kao pri prvom slanju.)
        if ($tijelo.vrijeme -is [datetime]) { $tijelo.vrijeme = ([DateTimeOffset]$tijelo.vrijeme).ToString('yyyy-MM-ddTHH:mm:sszzz') }
        try {
            $r = Posalji '/cartec/mjerenje' $tijelo $token
            $script:redSlanja.RemoveAt(0); SpremiRed
            Zapisi "Poslano iz reda: $($tijelo.vrsta) osovina $($tijelo.osovina) ($($tijelo.vrijeme)) → test $($r.test_id) ($($r.status), GB $($r.gb)); u redu još $($script:redSlanja.Count)."
        } catch {
            $kod = $null
            try { $kod = [int]$_.Exception.Response.StatusCode } catch {}
            if ($kod -eq 400 -or $kod -eq 422) {
                # Server ga trajno odbija (neispravni podaci) — inače bi zauvijek blokiralo red.
                $script:redSlanja.RemoveAt(0); SpremiRed
                Zapisi "Mjerenje iz reda odbijeno ($kod) i maknuto: osovina $($tijelo.osovina) ($($tijelo.vrijeme))."
                continue
            }
            if ($kod -eq 401) { Remove-Item $TokenDat -Force -ErrorAction SilentlyContinue; Zapisi 'Token odbijen — nova prijava (red čeka).' }
            elseif ($kod -eq 403) { Zapisi "Čeka odobrenje u Radnim nalozima — u redu $($script:redSlanja.Count) mjerenja." }
            else { Zapisi "Red: slanje nije uspjelo ($kod) — u redu $($script:redSlanja.Count) mjerenja, pokušat ću za $RedSek s." }
            return
        }
    }
}

function Otisak($tekst) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $h = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($tekst))
    return ([BitConverter]::ToString($h) -replace '-', '').ToLower()
}

function Sesija([datetime]$kad) {
    # Zadnji „novo vozilo" (deleteAll) prije mjerenja — iz dnevnika tog dana.
    $dat = Join-Path $CartecDir ('Logs\' + $kad.ToString('yyyyMMdd') + '_SaveVehicleData.log')
    if (-not (Test-Path $dat)) { return '' }
    $zadnje = ''
    try {
        foreach ($red in (ProcitajDijeljeno $dat) -split "`n") {
            if ($red -match '^(\d{2}:\d{2}:\d{2}),\d+.*deleteAll = True') {
                $t = [datetime]::ParseExact($kad.ToString('yyyy-MM-dd') + ' ' + $Matches[1], 'yyyy-MM-dd HH:mm:ss', $null)
                if ($t -le $kad) { $zadnje = $t.ToString('yyyy-MM-dd HH:mm:ss') }
            }
        }
    } catch {}
    return $zadnje
}

function Ocitaj($tekst, [datetime]$videno) {
    # Vrati najveću silu lijevo/desno u fazama kočenja i vrijeme zadnjeg retka.
    # $videno = kad smo prvi put vidjeli ovaj sadržaj (datum mjerenja; vrijeme datoteke nije pouzdano).
    $maxL = 0; $maxD = 0; $maxT = 0; $zadnjeVrijeme = $null; $ima = $false
    foreach ($red in ($tekst -split "`n")) {
        $s = $red.Trim().Split(';')
        if ($s.Count -lt 9 -or $s[0] -eq 'TimeStamp') { continue }
        $zadnjeVrijeme = $s[0]
        if ($NeKocenje -contains $s[8]) { continue }
        $l = 0; $d = 0; $w = 0
        [void][int]::TryParse($s[2], [ref]$l)
        [void][int]::TryParse($s[3], [ref]$d)
        [void][int]::TryParse($s[7], [ref]$w)
        $ima = $true
        if ($l -gt $maxL) { $maxL = $l }
        if ($d -gt $maxD) { $maxD = $d }
        if ($w -gt $maxT) { $maxT = $w }
    }
    if (-not $ima -or -not $zadnjeVrijeme) { return $null }
    # Vrijeme retka (HH:mm:ss,fff) + datum kad smo sadržaj vidjeli (oko ponoći: dan ranije).
    $hms = ($zadnjeVrijeme -split ',')[0]
    $kad = [datetime]::ParseExact($videno.ToString('yyyy-MM-dd') + ' ' + $hms, 'yyyy-MM-dd HH:mm:ss', $null)
    if ($kad -gt $videno.AddMinutes(10)) { $kad = $kad.AddDays(-1) }
    return @{ L = $maxL; D = $maxD; T = $maxT; Kad = $kad; Otisak = (Otisak $tekst) }
}

$poslano = New-Object 'System.Collections.Generic.HashSet[string]'
if (Test-Path $PoslanoDat) { Get-Content $PoslanoDat | ForEach-Object { [void]$poslano.Add($_.Trim()) } }
$prviPut = -not (Test-Path $PoslanoDat)
$zadnjiPokusaj = @{}
$videno = @{}                                   # datoteka → @{ H = otisak sadržaja; Kad = otkad je takav }
$prazno = New-Object 'System.Collections.Generic.HashSet[string]'   # sadržaji bez kočenja (već zapisano u dnevnik)
$logsStart = Join-Path $CartecDir 'Logs'
# Od v3 se pamti OTISAK SADRŽAJA, ne vrijeme/veličina datoteke: Cartec drži datoteke otvorene,
# pa Windows vrijeme i veličinu u mapi ne osvježava (osovina se znala pročitati prerano i preskočiti).
# Pri prvom pokretanju v3 sve što već leži u mapi smatra se starim i ne šalje se.
$Oznaka3 = Join-Path $Stanje 'v3.txt'
if (-not (Test-Path $Oznaka3)) {
    $n = 0
    foreach ($dat in @(Get-ChildItem -Path $logsStart -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue)) {
        try {
            $t = ProcitajDijeljeno $dat.FullName
            if ($t) { $h = Otisak $t; if ($poslano.Add($h)) { Add-Content $PoslanoDat $h; $n++ } }
        } catch {}
    }
    Set-Content -Path $Oznaka3 -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') -Encoding ASCII
    Zapisi "Prvo pokretanje v3: $n postojećih datoteka mjerenja označeno kao staro (ne šalju se)."
}
$javljenKraj = ''
if (Test-Path $KrajDat) { $javljenKraj = (Get-Content $KrajDat -Raw).Trim() }
# Datoteka → oznaka (prvi redak) mjerenja koje je već poslano: Cartec u datoteku dopisuje i
# nakon rezultata, pa isto mjerenje ne smije otići dvaput (ni nakon ponovnog pokretanja).
$GotovoDat = Join-Path $Stanje 'gotovo.txt'
$gotovaMjerenja = @{}
if (Test-Path $GotovoDat) {
    foreach ($red in (Get-Content $GotovoDat -Encoding UTF8)) {
        $dijelovi = $red.Split('|')
        if ($dijelovi.Count -eq 2) { $gotovaMjerenja[$dijelovi[0]] = $dijelovi[1] }
    }
}
# Prvo pokretanje v7: što već leži u datotekama je staro — samo zapamti oznake.
$Oznaka7 = Join-Path $Stanje 'v7.txt'
if (-not (Test-Path $Oznaka7)) {
    foreach ($dat in @(Get-ChildItem -Path $logsStart -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue)) {
        try {
            $t = ProcitajDijeljeno $dat.FullName
            $p = if ($t) { PrviRed $t } else { $null }
            if ($p) { $gotovaMjerenja[$dat.Name] = $p.ToString('HH:mm:ss.fff') }
        } catch {}
    }
    Set-Content -Path $GotovoDat -Encoding UTF8 -Value (@($gotovaMjerenja.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" }))
    Set-Content -Path $Oznaka7 -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') -Encoding ASCII
}
$redSlanja = UcitajRed
$zadnjiRed = [datetime]::MinValue
$zadnjeStanje = [datetime]::MinValue
$zadnjeAzuriranje = [datetime]::MinValue
$logsProvjera = Join-Path $CartecDir 'Logs'
$brAxle = @(Get-ChildItem -Path $logsProvjera -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue).Count
Zapisi "Pokrenuto v$Verzija ($env:COMPUTERNAME). Mapa Logs postoji: $(Test-Path $logsProvjera), AxleData datoteka: $brAxle, prvi put: $prviPut, u redu neposlanih: $($redSlanja.Count)."

while ($true) {
    try {
        $token = Token
        if (((Get-Date) - $zadnjeStanje).TotalSeconds -ge 120) { JaviStanje $token; $zadnjeStanje = Get-Date }
        if (((Get-Date) - $zadnjeAzuriranje).TotalMinutes -ge 10) { Azuriraj $token; $zadnjeAzuriranje = Get-Date }
        try { PosaljiRed $token } catch { Zapisi "Red: $($_.Exception.Message)" }
        $logs = Join-Path $CartecDir 'Logs'
        $datoteke = Get-ChildItem -Path $logs -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue
        $fazeSad = $null
        try { $fazeSad = FazeDanas } catch {}
        foreach ($dat in $datoteke) {
            if ($dat.Name -notmatch '^AxleData_(Service|Parking)_(\d+)\.csv$') { continue }
            $tip = $Matches[1]; $osovina = [int]$Matches[2]                # $Matches se kasnije prepiše
            # Čitamo SADRŽAJ (ne vrijeme/veličinu iz mape — dok Cartec drži datoteku otvorenom, nisu točni).
            try { $tekst = ProcitajDijeljeno $dat.FullName } catch { continue }
            if (-not $tekst) { $videno.Remove($dat.Name); continue }       # Cartec ju je ispraznio — novo mjerenje
            $kljuc = Otisak $tekst
            if ($poslano.Contains($kljuc)) { continue }
            $prvi = PrviRed $tekst
            $id = if ($prvi) { $prvi.ToString('HH:mm:ss.fff') } else { '' }
            if ($id -and $gotovaMjerenja[$dat.Name] -eq $id) { continue }   # već poslano — Cartec samo dopisuje
            $promijenjeno = (-not $videno.ContainsKey($dat.Name) -or $videno[$dat.Name].H -ne $kljuc)
            if ($promijenjeno) { $videno[$dat.Name] = @{ H = $kljuc; Kad = (Get-Date) } }
            # Gotovo: Cartec pokazao rezultat za ovo mjerenje (ODMAH) ili, rezervno, 30 s bez promjene.
            if (-not ($prvi -and (RezultatNakon $fazeSad $prvi))) {
                if ($promijenjeno) { PosaljiUzivo $tekst $token; continue }  # još se mjeri — sila uživo
                if (((Get-Date) - $videno[$dat.Name].Kad).TotalSeconds -lt $MirnoSek) { continue }
            }
            if ($prazno.Contains($kljuc)) { continue }
            if (-not $token) { continue }
            $pokusaj = if ($id) { "$($dat.Name)|$id" } else { $kljuc }
            if ($zadnjiPokusaj.ContainsKey($pokusaj) -and ((Get-Date) - $zadnjiPokusaj[$pokusaj]).TotalSeconds -lt 20) { continue }
            $zadnjiPokusaj[$pokusaj] = Get-Date

            $o = Ocitaj $tekst $videno[$dat.Name].Kad
            if (-not $o) {
                # Samo pokretanje valjaka, bez kočenja — NE označavamo kao poslano; čim stignu novi retci, čita se ponovno.
                [void]$prazno.Add($kljuc)
                Zapisi "$($dat.Name): još nema kočenja ($($tekst.Length) znakova) — čekam."
                continue
            }
            Zapisi "Šaljem $($dat.Name) (mjereno $($o.Kad.ToString('HH:mm:ss')))."
            $vrsta = if ($tip -eq 'Service') { 'radna' } else { 'parkirna' }
            $tijelo = @{
                sesija = (Sesija $o.Kad)
                osovina = $osovina
                vrsta = $vrsta
                vrijeme = ([DateTimeOffset]$o.Kad).ToString('yyyy-MM-ddTHH:mm:sszzz')
                sila_lijevo = $o.L
                sila_desno = $o.D
                tezina = $(if ($o.T -gt 0) { $o.T } else { $null })
                otisak = $o.Otisak
            }
            # Dok red nije prazan, novo mjerenje ide na KRAJ reda (redoslijed osovina ostaje).
            $poslanoSad = $false
            if ($redSlanja.Count -eq 0) {
                try {
                    $r = Posalji '/cartec/mjerenje' $tijelo $token
                    $poslanoSad = $true
                    Zapisi "Poslano: $vrsta osovina $($tijelo.osovina) L=$($o.L) D=$($o.D) → test $($r.test_id) ($($r.status), GB $($r.gb))"
                } catch {
                    $kod = $null
                    try { $kod = [int]$_.Exception.Response.StatusCode } catch {}
                    if ($kod -eq 401) { Remove-Item $TokenDat -Force -ErrorAction SilentlyContinue; Zapisi 'Token odbijen — nova prijava.' }
                    elseif ($kod -eq 403) { Zapisi 'Čeka odobrenje u Radnim nalozima — mjerenje ide u red.' }
                    else { Zapisi "Slanje nije uspjelo ($kod): $($_.Exception.Message) — mjerenje ide u red." }
                }
            }
            if (-not $poslanoSad) {
                URed $tijelo
                $zadnjiRed = Get-Date
                Zapisi "U redu: $vrsta osovina $($tijelo.osovina) (mjereno $($o.Kad.ToString('HH:mm:ss'))) — u redu $($redSlanja.Count)."
            }
            # Poslano ili sigurno spremljeno u red → ova datoteka je obrađena (ne čita se ponovno).
            [void]$poslano.Add($kljuc); Add-Content $PoslanoDat $kljuc
            if ($id) {
                $gotovaMjerenja[$dat.Name] = $id
                Set-Content -Path $GotovoDat -Encoding UTF8 -Value (@($gotovaMjerenja.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" }))
            }
        }
        try { ProvjeriKraj $token $fazeSad } catch { Zapisi "Provjera kraja testa: $($_.Exception.Message)" }
        if (-not (Test-Path $PoslanoDat)) { New-Item -ItemType File -Path $PoslanoDat | Out-Null }
        $prviPut = $false
    } catch {
        Zapisi "Greška u petlji: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 1          # svake sekunde — rezultat i sila uživo stižu odmah
}
