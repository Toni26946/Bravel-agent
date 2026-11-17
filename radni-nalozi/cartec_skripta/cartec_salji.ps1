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
$Verzija   = '2'
$Baza      = 'https://bravel-radni-nalozi.fly.dev/api'
$CartecDir = 'C:\Program Files (x86)\BR-Visualization'
$Stanje    = Join-Path $env:LOCALAPPDATA 'BravelCartec'
# Za probu na drugom računalu (lokalni server / kopija Cartec mapa):
if ($env:BRAVEL_CARTEC_URL) { $Baza = $env:BRAVEL_CARTEC_URL }
if ($env:BRAVEL_CARTEC_DIR) { $CartecDir = $env:BRAVEL_CARTEC_DIR }
if ($env:BRAVEL_CARTEC_STANJE) { $Stanje = $env:BRAVEL_CARTEC_STANJE }
$TokenDat  = Join-Path $Stanje 'token.txt'
$PoslanoDat = Join-Path $Stanje 'poslano.txt'
$Dnevnik   = Join-Path $Stanje 'dnevnik.txt'
$MirnoSek  = 30        # datoteka se ne smije mijenjati ovoliko sekundi = mjerenje gotovo
$StaroSati = 12        # pri prvom pokretanju ne šalji stara mjerenja
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
        [void](Posalji '/cartec/stanje' @{ verzija = $Verzija; dnevnik = $rep } $token)
    } catch {}
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

function Ocitaj($dat) {
    # Vrati najveću silu lijevo/desno u fazama kočenja i vrijeme zadnjeg retka.
    $tekst = ProcitajDijeljeno $dat.FullName
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
    # Vrijeme retka (HH:mm:ss,fff) + datum datoteke.
    $hms = ($zadnjeVrijeme -split ',')[0]
    $kad = [datetime]::ParseExact($dat.LastWriteTime.ToString('yyyy-MM-dd') + ' ' + $hms, 'yyyy-MM-dd HH:mm:ss', $null)
    return @{ L = $maxL; D = $maxD; T = $maxT; Kad = $kad; Otisak = (Otisak $tekst) }
}

$poslano = New-Object 'System.Collections.Generic.HashSet[string]'
if (Test-Path $PoslanoDat) { Get-Content $PoslanoDat | ForEach-Object { [void]$poslano.Add($_.Trim()) } }
$prviPut = -not (Test-Path $PoslanoDat)
$pocetak = Get-Date
$zadnjiPokusaj = @{}
$zadnjeStanje = [datetime]::MinValue
$zadnjeAzuriranje = [datetime]::MinValue
$logsProvjera = Join-Path $CartecDir 'Logs'
$brAxle = @(Get-ChildItem -Path $logsProvjera -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue).Count
Zapisi "Pokrenuto v$Verzija ($env:COMPUTERNAME). Mapa Logs postoji: $(Test-Path $logsProvjera), AxleData datoteka: $brAxle, prvi put: $prviPut."

while ($true) {
    try {
        $token = Token
        if (((Get-Date) - $zadnjeStanje).TotalSeconds -ge 120) { JaviStanje $token; $zadnjeStanje = Get-Date }
        if (((Get-Date) - $zadnjeAzuriranje).TotalMinutes -ge 10) { Azuriraj $token; $zadnjeAzuriranje = Get-Date }
        $logs = Join-Path $CartecDir 'Logs'
        $datoteke = Get-ChildItem -Path $logs -Filter 'AxleData_*.csv' -ErrorAction SilentlyContinue
        foreach ($dat in $datoteke) {
            if ($dat.Name -notmatch '^AxleData_(Service|Parking)_(\d+)\.csv$') { continue }
            $tip = $Matches[1]; $osovina = [int]$Matches[2]                # $Matches se kasnije prepiše
            if ($dat.Length -le 0) { continue }
            $starost = ((Get-Date) - $dat.LastWriteTime).TotalSeconds
            if ($starost -lt $MirnoSek) { continue }                       # još se mjeri
            $kljuc = $dat.FullName + '|' + $dat.LastWriteTime.Ticks + '|' + $dat.Length
            if ($poslano.Contains($kljuc)) { continue }
            if ($prviPut -and $dat.LastWriteTime -lt $pocetak.AddHours(-$StaroSati)) {
                # Stara mjerenja od prije instalacije — samo zapamti da ih ne šaljemo.
                [void]$poslano.Add($kljuc); Add-Content $PoslanoDat $kljuc; continue
            }
            if (-not $token) { continue }
            if ($zadnjiPokusaj.ContainsKey($kljuc) -and ((Get-Date) - $zadnjiPokusaj[$kljuc]).TotalSeconds -lt 60) { continue }
            $zadnjiPokusaj[$kljuc] = Get-Date
            Zapisi "Šaljem $($dat.Name) ($($dat.LastWriteTime.ToString('HH:mm:ss')))."

            $o = Ocitaj $dat
            if (-not $o) {                                                  # samo pokretanje valjaka, bez kočenja
                [void]$poslano.Add($kljuc); Add-Content $PoslanoDat $kljuc; continue
            }
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
            try {
                $r = Posalji '/cartec/mjerenje' $tijelo $token
                [void]$poslano.Add($kljuc); Add-Content $PoslanoDat $kljuc
                Zapisi "Poslano: $vrsta osovina $($tijelo.osovina) L=$($o.L) D=$($o.D) → test $($r.test_id) ($($r.status), GB $($r.gb))"
            } catch {
                $kod = $null
                try { $kod = [int]$_.Exception.Response.StatusCode } catch {}
                if ($kod -eq 401) { Remove-Item $TokenDat -Force -ErrorAction SilentlyContinue; Zapisi 'Token odbijen — nova prijava.' }
                elseif ($kod -eq 403) { Zapisi 'Čeka odobrenje u Radnim nalozima — mjerenje ostaje za kasnije.' }
                else { Zapisi "Slanje nije uspjelo ($kod): $($_.Exception.Message) — pokušat ću ponovno." }
            }
        }
        if (-not (Test-Path $PoslanoDat)) { New-Item -ItemType File -Path $PoslanoDat | Out-Null }
        $prviPut = $false
    } catch {
        Zapisi "Greška u petlji: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 5
}
