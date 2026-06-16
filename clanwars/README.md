Clan Wars App for PyPlanet
==========================

Competitive clan/team scoring based on local record positions (anti-grind: only best record per player per map counts). Optional rule: only best record of a clan per map counts.

Features
--------
* Join / leave clans with chat commands.
* Points awarded when a player sets/improves a local record; points depend on record rank (configurable).
* Aggregate clan standings.
* Per-player per-map best stored; improvements update scores.
* Optional unique-per-clan-per-map rule.

Installation
------------
1. Place this folder as `apps/clanwars` inside your instance.
2. Add `apps.clanwars` to `APPS['default']` in `settings/apps.py`.
3. Start the instance (peewee models will auto-migrate if using PyPlanet migration helpers; otherwise integrate into migration flow).

Commands
--------
//joinclan <name>  Join (or create) a clan.
//leaveclan        Leave current clan.
//myclan           Show your clan + total points.
//clans            Show clan standings.

Configuration
-------------
Settings (via admin/settings GUI or settings system):
* clanwars_scoring (JSON string) default {"1":10,"2":7,"3":5,"4":3,"5":1}
* unique_clan_map (bool) only best player result per map counts per clan.

Data Model
----------
Clan(id, name)
PlayerClan(player_id, clan_id)
PlayerClanMapScore(map_id, player_id, clan_id, points)  (best points a player contributed on a map)
ClanAggregateScore(clan_id, points)  (cached sum; recomputed on changes)

How Scoring Works
-----------------
On finish, after local_records updates, we determine the player's record rank. If rank has configured points and beats prior best, we store/update PlayerClanMapScore and recompute ClanAggregateScore.

Roadmap
-------
* GUI widgets (standings, recent gains)
* Season reset & history export
* JSON/CSV export
* Admin commands to rename/remove clans
* Per-map score weight modifiers

License
-------
Same license as the parent project (inherit instance terms) unless specified otherwise.
