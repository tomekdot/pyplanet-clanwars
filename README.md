# pyplanet-clanwars

Clan Wars plugin for PyPlanet — competitive clan/team scoring based on local record positions.

## Features

* Join / leave clans with chat commands
* Points awarded when a player sets/improves a local record
* Configurable scoring (harmonic by default: rank 1 → 300 pts, rank 2 → 150 pts, etc.)
* Aggregate clan standings with per-player per-map best tracking
* Optional unique-per-clan-per-map rule
* CSV/JSON export
* Periodic standings announcements
* Admin commands: reset, recalculate, export

## Installation

### Option 1: GitHub Installer (recommended)

```
/ghinstall tomekdot/pyplanet-clanwars
```

### Option 2: Manual

1. Clone or download this repository
2. Place the `clanwars` folder inside your PyPlanet instance's `apps/` directory
3. Add `'apps.clanwars'` to `APPS['default']` in `settings/apps.py`
4. Restart PyPlanet

## Commands

| Command | Description |
|---------|-------------|
| `/joinclan <name>` | Join (or create) a clan |
| `/leaveclan` | Leave current clan |
| `/myclan` | Show your clan + total points |
| `/clans` | Show clan standings |
| `/clanswin` | Open Clan Wars standings window |
| `/clanmembers [name]` | List members of a clan |
| `/clanwexport [format]` | Export standings (csv/json) |
| `/clanw_reset confirm=yes` | Reset all scoring data (admin) |
| `/clanw_recalc` | Recalculate points using current scoring (admin) |

## Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `clanwars_scoring` | string (JSON) | `{"1":300,"2":150,...}` | JSON map of rank → points |
| `unique_clan_map` | bool | `false` | Only best record per clan per map counts |
| `clanwars_announce_enabled` | bool | `false` | Enable periodic announcements |
| `clanwars_announce_interval_seconds` | int | `300` | Announcement interval |
| `clanwars_announce_target` | string | `""` | Target player login (empty = global) |

## Data Model

```
Clan(id, name)
PlayerClan(player_id, clan_id)
PlayerClanMapScore(map_id, player_id, clan_id, points)
ClanAggregateScore(clan_id, points)
```

## Requirements

* PyPlanet ≥ 0.11
* `local_records` app (enabled by default in PyPlanet)
* Trackmania or Trackmania Next game mode

## License

MIT-0
