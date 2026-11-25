# CLAUDE.md — Bravel-agent

<!-- oblak-blok -->
## Radiš u oblaku? (claude.ai/code s mobitela — Tonijevo računalo je možda ugašeno)
1. **Prvo** pozovi Moj_mozak MCP alat `pravila_rada` — Tonijeva globalna pravila i zajedničko znanje
   (lokalni `~/.claude/CLAUDE.md` ovdje ne postoji) — i drži ih se (hrvatski, kratki odgovori, radi sve sam).
2. Zatim `gdje_smo_stali` za projekt „bravel-agent (Telegram bot)” ili „Radni nalozi” (mapa radni-nalozi/).
3. Na kraju stvarnog posla `zapisi_projekt` (umjesto lokalne skripte zapisi_projekt.py).
Lokalne putanje (`C:\…`, OneDrive/SharePoint mapa, Excel COM, Chrome) u oblaku ne postoje — SharePoint preko
konektora Microsoft 365; što traži računalo zapiši kao sljedeći korak.
<!-- oblak-blok -->

## Radni nalozi — Plan radione: automatika samo PREDLAŽE (Toni 25.11.2026.)
Raspored u Plan → Radnici, kakav slože poslovođe, automatika NE smije mijenjati. To vrijedi za
`auto_popuni`, `auto_slanje`, nove pozadinske petlje i jednokratne migracije: ne dodjeljuju, ne miču i ne
preslaguju dodijeljene zadatke (`zadaci.radnici`, `red_ruc`). Smiju samo postaviti 💡 prijedlog
(`zadaci.prijedlog_radnik_id`). Poslovođa ga prihvaća ✓, odbija ✕ ili povlači drugom (`/api/plan/prijedlog/…`).
Promjena dodjela izvan toga je dopuštena samo na Tonijevu izričitu naredbu.

