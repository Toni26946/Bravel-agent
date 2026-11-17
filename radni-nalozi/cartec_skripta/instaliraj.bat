@echo off
rem Bravel — instalacija slanja testova kočnica (Cartec valjci → Radni nalozi).
rem Dvoklik. Ne treba administrator. Ništa ne dira u Cartecu, samo čita njegove datoteke.
set CILJ=%LOCALAPPDATA%\BravelCartec
if not exist "%CILJ%" mkdir "%CILJ%"
copy /Y "%~dp0cartec_salji.ps1" "%CILJ%\cartec_salji.ps1" >nul
copy /Y "%~dp0pokreni_skriveno.vbs" "%CILJ%\pokreni_skriveno.vbs" >nul
rem Automatski start pri prijavi u Windows (mapa Startup trenutnog korisnika).
copy /Y "%~dp0pokreni_skriveno.vbs" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\BravelCartec.vbs" >nul
rem Pokreni odmah.
wscript "%CILJ%\pokreni_skriveno.vbs"
echo.
echo Instalirano. Skripta radi u pozadini i pali se sama s Windowsima.
echo Dnevnik: %CILJ%\dnevnik.txt
echo.
pause
