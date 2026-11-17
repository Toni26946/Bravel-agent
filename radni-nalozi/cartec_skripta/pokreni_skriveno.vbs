' Pokreće cartec_salji.ps1 bez prozora i pazi da radi (Bravel — testovi kočnica).
' Ako skripta stane (greška, samoažuriranje), pokrene je ponovno nakon 30 s.
' Druga kopija skripte sama izađe (mutex), pa višestruko pokretanje ne smeta.
Set sh = CreateObject("WScript.Shell")
skripta = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\BravelCartec\cartec_salji.ps1"
Do
    sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & skripta & """", 0, True
    WScript.Sleep 30000
Loop
