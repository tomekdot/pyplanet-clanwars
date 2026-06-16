# pyplanet-clanspirits

Clan Spirits plugin for PyPlanet — competitive spirit/team scoring based on local record positions.

## Features

* Join / leave spirits with chat commands
* Points awarded when a player sets/improves a local record
* Configurable scoring (harmonic by default: rank 1 → 300 pts, rank 2 → 150 pts, etc.)
* Aggregate spirit standings with per-player per-map best tracking
* Optional unique-per-spirit-per-map rule
* CSV/JSON export
* Periodic standings announcements
* Admin commands: reset, recalculate, export

## Installation

### Option 1: GitHub Installer (recommended)

```
/ghinstall tomekdot/pyplanet-clanspirits
```

### Option 2: Manual

1. Clone or download from https://github.com/tomekdot/pyplanet-clanspirits
2. Place the `clanspirits` folder inside your PyPlanet instance's `apps/` directory
3. Add `'apps.clanspirits'` to `APPS['default']` in `settings/apps.py`
4. Restart PyPlanet

## Commands

| Command | Description |
|---------|-------------|
| `/joinspirit <name>` | Join (or create) a spirit |
| `/leavespirit` | Leave current spirit |
| `/spirits` | Show spirit standings |
| `/myspirit` | Show your spirit and points |
| `/spiritswin` | Open ClanSpirits standings window |
| `/spiritmembers [name]` | List members of a spirit |
| `/spiritexport [format]` | Export standings (csv/json) |
| `/spirit_reset confirm=yes` | Reset all scoring data (admin) |
| `/spirit_recalc` | Recalculate points (admin) |

## Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `clanspirits_scoring` | string (JSON) | `{"1":300,"2":150,...}` | JSON map of rank → points |
| `unique_spirit_map` | bool | `false` | Only best record per spirit per map counts |
| `clanspirits_announce_enabled` | bool | `false` | Enable periodic announcements |
| `clanspirits_announce_interval_seconds` | int | `300` | Announcement interval |
| `clanspirits_announce_target` | string | `""` | Target player login (empty = global) |

## Data Model

```
Spirit(id, name)
PlayerSpirit(player_id, spirit_id)
PlayerSpiritMapScore(map_id, player_id, spirit_id, points)
SpiritAggregateScore(spirit_id, points)
```

## Requirements

* PyPlanet ≥ 0.11
* `local_records` app (enabled by default in PyPlanet)
* Trackmania or Trackmania Next game mode

## License

MIT-0
