# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## PowerShell Version
- David's machine runs **PowerShell 5.1** — does NOT support `&&`
- Always give commands as **separate lines**, never chained with `&&`
- Use `;` only if truly needed (doesn't stop on failure)

## OddsAPI
- **Key**: stored as env var `ODDS_API_KEY` (set 2026-03-30)
- **Tier**: Free (500 credits/month) — upgrade to 20K ($30/mo) when ready for historical data
- **NBA endpoint**: `https://api.the-odds-api.com/v4/sports/basketball_nba/odds`
- **MLB endpoint**: `https://api.the-odds-api.com/v4/sports/baseball_mlb/odds`
- **Use for**: Sports Vegas-Kalshi gap validation (polling script)

## TheNewsAPI.com
- **Key**: RGPtfv3i6ni4bucrlfpUrMuDUMmRuvi9fGubxwmt
- **Tier**: Free (100 req/day) — upgrade when needed
- **Endpoint**: https://api.thenewsapi.com/v1/news/all
- **Use for**: Geo module news volume signal (keyword search + `found` count)
- **Key param**: `found` field in response = article volume count for spike detection

## X / Twitter Access
- **Tool:** `bird` (npm, v0.8.0) — fast X CLI via GraphQL API
- **Capability:** Search tweets, post, reply, read timelines
- **Auth:** Chrome profile cookie extraction (auth_token + ct0)
- **Use for:** Sports injury signals, crypto sentiment, Fed/econ news monitoring
- **Status:** Active — installed, working
- **Note:** David set up a second account for this. Use `bird` not `xurl`.

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
