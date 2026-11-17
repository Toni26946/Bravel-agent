@echo off
rem Bravel — instalacija slanja testova kočnica (Cartec valjci → Radni nalozi).
rem Dvoklik. Ne treba administrator. Ništa ne dira u Cartecu, samo čita njegove datoteke.
rem Ponovni dvoklik = ponovna instalacija (ugasi staru kopiju i pokrene novu).
set CILJ=%LOCALAPPDATA%\BravelCartec
if not exist "%CILJ%" mkdir "%CILJ%"
rem Ugasi stari pokretač i staru skriptu (ako rade).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID } | Where-Object { $_.CommandLine -like '*cartec_salji*' -or $_.CommandLine -like '*BravelCartec.vbs*' -or $_.CommandLine -like '*pokreni_skriveno.vbs*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
copy /Y "%~dp0cartec_salji.ps1" "%CILJ%\cartec_salji.ps1" >nul
copy /Y "%~dp0pokreni_skriveno.vbs" "%CILJ%\pokreni_skriveno.vbs" >nul
rem Automatski start pri prijavi u Windows (mapa Startup trenutnog korisnika).
copy /Y "%~dp0pokreni_skriveno.vbs" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\BravelCartec.vbs" >nul
rem Pokreni odmah (pokretač ostaje raditi u pozadini).
start "" wscript "%CILJ%\pokreni_skriveno.vbs"
echo.
echo Instalirano. Skripta radi u pozadini i pali se sama s Windowsima.
echo Dnevnik: %CILJ%\dnevnik.txt
echo.
pause
