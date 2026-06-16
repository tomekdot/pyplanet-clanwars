---
name: pyplanet-clanwars
description: "Clan Wars plugin for PyPlanet — competitive clan scoring based on local records"
version: 1.0.0
author: tome
license: MIT-0
metadata:
  openclaw:
    name: pyplanet-clanwars
    description: "Clan Wars plugin for PyPlanet — competitive clan scoring based on local records"
    version: 1.0.0
    author: tome
    license: MIT-0
    tags: [pyplanet, maniaplanet, clan, scoring, competition]
  hermes:
    tags: [pyplanet, maniaplanet, clan, scoring, competition]
    homepage: https://github.com/tomekdot/pyplanet-clanwars
    related_skills: [pyplanet-github-installer]
---

# PyPlanet Clan Wars

Clan Wars plugin for PyPlanet — competitive clan/team scoring based on local record positions.

## When to Use

Use this skill when the user wants to:
- Install the Clan Wars plugin on their PyPlanet instance
- Understand how clan scoring works
- Configure clan scoring settings

## Quick Start

### Option 1: GitHub Installer (recommended)

```
/ghinstall tomekdot/pyplanet-clanwars
```

### Option 2: Manual Installation

1. Clone or download from https://github.com/tomekdot/pyplanet-clanwars
2. Place the `clanwars` folder inside your PyPlanet instance's `apps/` directory
3. Add `'apps.clanwars'` to `APPS['default']` in `settings/apps.py`
4. Start the instance

## Commands

| Command | Description |
|---------|-------------|
| `/joinclan <name>` | Join (or create) a clan |
| `/leaveclan` | Leave current clan |
| `/myclan` | Show your clan + total points |
| `/clans` | Show clan standings |
| `/clanswin` | Open standings window |
| `/clanmembers [name]` | List members of a clan |
| `/clanwexport [format]` | Export standings (csv/json) |
| `/clanw_reset confirm=yes` | Reset all scoring data (admin) |
| `/clanw_recalc` | Recalculate points (admin) |

## Data Model

```
Clan(id, name)
PlayerClan(player_id, clan_id)
PlayerClanMapScore(map_id, player_id, clan_id, points)
ClanAggregateScore(clan_id, points)
```

## Requirements

- PyPlanet >= 0.11
- `local_records` app (enabled by default)
- Trackmania or Trackmania Next game mode

## Source

- GitHub: https://github.com/tomekdot/pyplanet-clanwars
- ClawHub: `hermes skills install pyplanet-clanwars`

## License

MIT-0
