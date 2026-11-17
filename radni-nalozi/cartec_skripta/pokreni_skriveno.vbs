' Pokreće cartec_salji.ps1 bez prozora (Bravel — testovi kočnica).
Set sh = CreateObject("WScript.Shell")
skripta = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\BravelCartec\cartec_salji.ps1"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & skripta & """", 0, False
