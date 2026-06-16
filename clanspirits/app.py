import asyncio
import logging
import json
import os
import csv
from datetime import datetime
from pyplanet.apps.config import AppConfig
from pyplanet.contrib.command import Command
from pyplanet.contrib.setting import Setting
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from .models import Spirit, PlayerSpirit, PlayerSpiritMapScore, SpiritAggregateScore
from pyplanet.views.generics.list import ManualListView
from pyplanet.views.generics.widget import WidgetView
from peewee import fn
from types import SimpleNamespace

# Default scoring (position -> points)
# By default use a harmonic-style scoring for up to 300 positions (gentler falloff):
# rank 1 -> 300 pts, rank 2 -> 150 pts, rank 3 -> 100 pts, etc.
DEFAULT_SCORING = {i: int(300 / i) for i in range(1, 301)}


class ClanSpirits(AppConfig):
    name = 'ClanSpirits'
    game_dependencies = ['trackmania', 'trackmania_next']
    # Depends on the local_records app (label is 'local_records').
    app_dependencies = ['local_records']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)
        self.lock = asyncio.Lock()
        self.scoring = DEFAULT_SCORING.copy()
        # Default setting now contains the harmonic 300-place scoring so rank 1 -> 300 pts by default.
        self.setting_scoring = Setting(
            'clanspirits_scoring', 'ClanSpirits Scoring (JSON)', Setting.CAT_BEHAVIOUR,
            type=str, default=json.dumps(DEFAULT_SCORING)
        )
        self.setting_unique_spirit_per_map = Setting(
            'unique_spirit_map', 'Only best record per spirit per map counts', Setting.CAT_BEHAVIOUR,
            type=bool, default=False
        )
        # Announcer settings
        self.setting_announce_enabled = Setting(
            'clanspirits_announce_enabled', 'Enable periodic ClanSpirits announcements', Setting.CAT_BEHAVIOUR,
            type=bool, default=False
        )
        self.setting_announce_interval = Setting(
            'clanspirits_announce_interval_seconds', 'Announcement interval in seconds', Setting.CAT_BEHAVIOUR,
            type=int, default=300
        )
        self.setting_announce_target = Setting(
            'clanspirits_announce_target', 'Optional player login to send announcements to (empty = global chat)', Setting.CAT_BEHAVIOUR,
            type=str, default=''
        )
        # Background announcer task handle
        self._announce_task = None
        # Last announced signature to avoid duplicate announcements
        self._last_announced_signature = None

    async def on_start(self):
        # Register settings and load scoring config.
        await self.context.setting.register(
            self.setting_scoring,
            self.setting_unique_spirit_per_map,
            self.setting_announce_enabled,
            self.setting_announce_interval,
        )
        await self.load_scoring()

        # Register a permission for ClanSpirits administration.
        try:
            await self.instance.permission_manager.register('manage_clanspirits', 'Manage ClanSpirits', app=self, min_level=3)
        except Exception:
            # If permission manager isn't available or registration fails, continue but handlers will deny.
            self.logger.warning('ClanSpirits: permission manager not available or registration failed')

        # Register commands.
        await self.instance.command_manager.register(
            Command(command='joinspirit', target=self.cmd_joinspirit).add_param('name', help='Spirit name', required=True),
            Command(command='leavespirit', target=self.cmd_leavespirit, description='Leave your current spirit'),
            Command(command='spirits', target=self.cmd_spirits, description='Show spirit standings'),
            Command(command='myspirit', target=self.cmd_myspirit, description='Show your spirit and points'),
            Command(command='spiritswin', target=self.cmd_spirits_window, description='Open ClanSpirits standings window'),
            Command(command='spiritmembers', target=self.cmd_spirit_members, description='List members of your spirit or given spirit').add_param('name', required=False, help='Spirit name (optional)'),
            Command(command='spiritexport', target=self.cmd_spiritexport, description='Export spirit standings (csv/json)').add_param('format', required=False, help='csv or json'),
            Command(command='spirit_reset', target=self.cmd_spirit_reset, description='Reset spirit scoring data (confirm=yes to execute)').add_param('confirm', required=True, help='Set to yes to perform reset'),
            Command(command='spirit_recalc', target=self.cmd_spirit_recalc, description='Recalculate stored per-map points using current scoring'),
        )

        # Signals.
        self.context.signals.listen(tm_signals.finish, self.player_finish)
        self.context.signals.listen(mp_signals.map.map_begin, self.map_begin)

        self.logger.info('ClanSpirits started.')

        # Initialize widget.
        self.widget = ClanSpiritsWidget(self)
        await self.widget.display()

        # Start announcer task if enabled
        try:
            s_enabled = await self.context.setting.get_setting('clanspirits_announce_enabled')
            s_interval = await self.context.setting.get_setting('clanspirits_announce_interval_seconds')
            enabled = await s_enabled.get_value()
            interval = await s_interval.get_value()
            if enabled and interval and int(interval) > 0:
                self._announce_task = asyncio.create_task(self.announce_loop(int(interval)))
        except Exception:
            # If settings not available or task fails to start, log and continue.
            self.logger.exception('Failed to start ClanSpirits announcer task')

    async def on_stop(self):
        # PyPlanet signal manager provides 'remove' on app-scoped signals manager.
        for sig, cb in ((tm_signals.finish, self.player_finish), (mp_signals.map.map_begin, self.map_begin)):
            try:
                self.context.signals.remove(sig, cb)
            except Exception:
                continue
        self.logger.info('ClanSpirits stopped.')
        # Cancel announcer task if running
        if self._announce_task:
            try:
                self._announce_task.cancel()
                await asyncio.wait_for(self._announce_task, timeout=2)
            except Exception:
                pass

    async def announce_loop(self, interval_seconds: int):
        """Background task: every interval_seconds send brief standings to server chat."""
        try:
            while True:
                try:
                    # Build top 5 standings message
                    rows = await SpiritAggregateScore.execute(
                        SpiritAggregateScore.select(SpiritAggregateScore, Spirit).join(Spirit).order_by(SpiritAggregateScore.points.desc()).limit(5)
                    )
                    if not rows:
                        # nothing to announce
                        pass
                    else:
                        # compute signature to detect changes
                        sig = ','.join(f"{r.spirit.id}:{r.points}" for r in rows)
                        if sig != self._last_announced_signature:
                            self._last_announced_signature = sig
                            msg = self.format_standings_message(rows)
                            # Optional target: if configured, send only to that player login
                            try:
                                s_target = await self.context.setting.get_setting('clanspirits_announce_target')
                                target_login = await s_target.get_value()
                            except Exception:
                                target_login = ''
                            if target_login:
                                try:
                                    player = await self.instance.player_manager.get_player_by_login(target_login)
                                    if player:
                                        await self.instance.chat(msg, player)
                                        # continue to next iteration
                                        await asyncio.sleep(interval_seconds)
                                        continue
                                except Exception:
                                    # fallback to global chat
                                    pass
                            await self.instance.chat(msg)
                except Exception:
                    self.logger.exception('Error while announcing ClanSpirits standings')
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return

    def format_standings_message(self, rows):
        # Polish localized one-line message
        parts = ['ClanSpirits - aktualne miejsca:']
        rank = 1
        for r in rows:
            parts.append(f"{rank}. {r.spirit.name} ({r.points} pkt)")
            rank += 1
        return ' | '.join(parts)

    async def cmd_joinspirit(self, player, data, **kwargs):
        name = data.name.strip()[:32]
        async with self.lock:
            # Fetch or create spirit.
            spirit_rows = await Spirit.objects.execute(Spirit.select().where(Spirit.name == name).limit(1))
            if spirit_rows:
                spirit = spirit_rows[0]
            else:
                spirit = Spirit(name=name)
                await spirit.save()
            # Check existing membership.
            existing_rows = await PlayerSpirit.objects.execute(
                PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1)
            )
            existing = existing_rows[0] if existing_rows else None
            if existing:
                if existing.spirit_id == spirit.id:
                    return await self.instance.chat(f'Already in spirit {spirit.name}.', player)
                # Async delete using execute to avoid sync call.
                await PlayerSpirit.execute(PlayerSpirit.delete().where(PlayerSpirit.id == existing.id))
            rel = PlayerSpirit(player=player, spirit=spirit)
            await rel.save()
        await self.instance.chat(f'Joined spirit {spirit.name}.', player)
        await self.recalc_aggregate(spirit)

    async def cmd_leavespirit(self, player, data=None, **kwargs):
        rel_rows = await PlayerSpirit.objects.execute(
            PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1)
        )
        rel = rel_rows[0] if rel_rows else None
        if not rel:
            return await self.instance.chat('Not in a spirit.', player)
        spirit = await Spirit.get(id=rel.spirit_id)
        await PlayerSpirit.execute(
            PlayerSpirit.delete().where(PlayerSpirit.id == rel.id)
        )
        await self.instance.chat(f'Left spirit {spirit.name}.', player)
        await self.recalc_aggregate(spirit)

    async def cmd_myspirit(self, player, data=None, **kwargs):
        rel_rows = await PlayerSpirit.objects.execute(
            PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1)
        )
        rel = rel_rows[0] if rel_rows else None
        if not rel:
            return await self.instance.chat('Not in a spirit.', player)
        spirit = await Spirit.get(id=rel.spirit_id)
        agg_rows = await SpiritAggregateScore.objects.execute(
            SpiritAggregateScore.select().where(SpiritAggregateScore.spirit == spirit.id).limit(1)
        )
        agg = agg_rows[0] if agg_rows else None
        points = agg.points if agg else 0
        await self.instance.chat(f'Spirit: {spirit.name} ({points} pts)', player)

    async def cmd_spirits(self, player, data=None, **kwargs):
        rows = await SpiritAggregateScore.execute(
            SpiritAggregateScore.select(SpiritAggregateScore, Spirit).join(Spirit).order_by(SpiritAggregateScore.points.desc())
        )
        if not rows:
            return await self.instance.chat('No spirit scores yet.', player)
        msg = 'Spirit standings: ' + ' | '.join([
            f'{i + 1}. {r.spirit.name} {r.points}' for i, r in enumerate(rows)
        ])
        await self.instance.chat(msg, player)

    async def cmd_spirits_window(self, player, data=None, **kwargs):
        view = ClanSpiritsStandingsView(self)
        await view.display(player=player.login)

    async def cmd_spirit_members(self, player, data=None, **kwargs):
        """List members of a spirit (player's spirit if no name provided)."""
        target_spirit = None
        if data and getattr(data, 'name', None):
            name = data.name.strip()
            spirit_rows = await Spirit.objects.execute(Spirit.select().where(Spirit.name == name).limit(1))
            if spirit_rows:
                target_spirit = spirit_rows[0]
            else:
                return await self.instance.chat(f'Spirit {name} not found.', player)
        else:
            rel_rows = await PlayerSpirit.objects.execute(PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1))
            if rel_rows:
                target_spirit = rel_rows[0].spirit
            else:
                return await self.instance.chat('You are not in a spirit.', player)
        member_rows = await PlayerSpirit.objects.execute(PlayerSpirit.select().where(PlayerSpirit.spirit == target_spirit))
        if not member_rows:
            return await self.instance.chat(f'Spirit {target_spirit.name} has no members.', player)
        member_logins = [m.player.login for m in member_rows]
        await self.instance.chat(f'Members of {target_spirit.name} ({len(member_logins)}): ' + ', '.join(member_logins), player)

    async def cmd_spiritexport(self, player, data=None, **kwargs):
        fmt = 'csv'
        if data and getattr(data, 'format', None):
            fmt = data.format.lower()
        if fmt not in ('csv', 'json'):
            return await self.instance.chat('Format must be csv or json.', player)
        export = await self._gather_export_rows()
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        base_dir = os.path.join(os.getcwd(), 'tmp')
        os.makedirs(base_dir, exist_ok=True)
        path = os.path.join(base_dir, f'clanspirits_{ts}.{fmt}')
        try:
            if fmt == 'csv':
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['rank','spirit','members','maps','best_rank','points','avg_points'])
                    for row in export:
                        writer.writerow(row)
            else:
                payload = [
                    {
                        'rank': r[0], 'spirit': r[1], 'members': r[2], 'maps': r[3],
                        'best_rank': r[4], 'points': r[5], 'avg_points': r[6]
                    } for r in export
                ]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            await self.instance.chat(f'ClanSpirits exported to {path}', player)
        except Exception as e:
            self.logger.exception('ClanSpirits export failed')
            return await self.instance.chat(f'Export failed: {e}', player)
                                 
    async def _gather_export_rows(self):
        # Reuse logic from standings view (avoid duplicating ranking order logic).
        agg_rows = await SpiritAggregateScore.execute(
            SpiritAggregateScore.select(SpiritAggregateScore, Spirit).join(Spirit).order_by(SpiritAggregateScore.points.desc())
        )
        member_count_rows = await PlayerSpirit.execute(
            PlayerSpirit.select(PlayerSpirit.spirit, fn.COUNT(PlayerSpirit.player).alias('cnt')).group_by(PlayerSpirit.spirit)
        )
        counts = {}
        for r in member_count_rows:
            sid = getattr(r, 'spirit_id', None) or r.spirit
            counts[sid] = r.cnt
        spirit_ids = [ar.spirit.id for ar in agg_rows]
        pms_rows = await PlayerSpiritMapScore.execute(
            PlayerSpiritMapScore.select().where(PlayerSpiritMapScore.spirit << spirit_ids)
        )
        points_to_rank = {v: k for k, v in self.scoring.items() if isinstance(k, int) and isinstance(v, int)}
        map_counts = {}
        best_ranks = {}
        for row in pms_rows:
            sid = row.spirit_id if hasattr(row, 'spirit_id') else row.spirit.id
            if row.points and row.points > 0:
                mc = map_counts.setdefault(sid, set())
                mc.add(row.map_id if hasattr(row, 'map_id') else row.map.id)
                rank_guess = points_to_rank.get(row.points)
                if rank_guess:
                    current_best = best_ranks.get(sid)
                    if current_best is None or rank_guess < current_best:
                        best_ranks[sid] = rank_guess
        for sid, s in list(map_counts.items()):
            map_counts[sid] = len(s)
        rows = []
        rank_counter = 1
        for r in agg_rows:
            sid = getattr(r, 'spirit_id', None) or r.spirit.id
            members = counts.get(sid, 0)
            maps_played = map_counts.get(sid, 0)
            best_rank = best_ranks.get(sid, '-')
            avg_pts = round(r.points / maps_played, 2) if maps_played else 0
            rows.append([rank_counter, r.spirit.name, members, maps_played, best_rank, r.points, avg_pts])
            rank_counter += 1
        return rows

    async def cmd_spirit_reset(self, player, data=None, **kwargs):
        """Admin command: reset all stored per-map scores and spirit aggregates.
        Usage: /spirit_reset confirm=yes
        """
        if not data or getattr(data, 'confirm', '').lower() != 'yes':
            return await self.instance.chat('To prevent accidents, run: /spirit_reset confirm=yes', player)
        # Permission check (best-effort). If permission manager isn't available, deny by default.
        perm_ok = False
        pm = getattr(self.instance, 'permission_manager', None)
        if not pm:
            return await self.instance.chat('You do not have permission to reset ClanSpirits data.', player)

        # Prefer has_permission(app_label:perm_name) if available, fall back to check(permission_name).
        try:
            if hasattr(pm, 'has_permission'):
                perm_ok = await pm.has_permission(player, 'clanspirits:manage_clanspirits')
            elif hasattr(pm, 'check'):
                perm_ok = await pm.check(player, 'manage_clanspirits')
        except Exception:
            perm_ok = False

        if not perm_ok:
            try:
                if hasattr(pm, 'has_permission'):
                    perm_ok = await pm.has_permission(player, 'local_records:manage_records')
                elif hasattr(pm, 'check'):
                    perm_ok = await pm.check(player, 'manage_records')
            except Exception:
                perm_ok = False
        # Final fallback: allow server master admins by level (min_level used when registering was 3).
        try:
            if not perm_ok and hasattr(player, 'level') and getattr(player, 'level') is not None:
                # Treat level >= 3 as master/admin level allowed to run this command.
                if int(getattr(player, 'level')) >= 3:
                    perm_ok = True
        except Exception:
            pass

        if not perm_ok:
            return await self.instance.chat('You do not have permission to reset ClanSpirits data.', player)
        # Delete all per-map scores and zero aggregates.
        await PlayerSpiritMapScore.execute(PlayerSpiritMapScore.delete())
        agg_rows = await SpiritAggregateScore.objects.execute(SpiritAggregateScore.select())
        for agg in agg_rows:
            agg.points = 0
            await agg.save()
        self.logger.warning('ClanSpirits: scoring data reset by %s', getattr(player, 'login', None))
        await self.instance.chat('ClanSpirits scoring data has been reset.', player)

    async def cmd_spirit_recalc(self, player, data=None, **kwargs):
        """Admin command: recompute all stored per-map points using the currently loaded scoring.
        Usage: /spirit_recalc
        """
        # Reuse permission checks from reset.
        perm_ok = False
        pm = getattr(self.instance, 'permission_manager', None)
        if not pm:
            return await self.instance.chat('You do not have permission to recalc ClanSpirits data.', player)
        try:
            if hasattr(pm, 'has_permission'):
                perm_ok = await pm.has_permission(player, 'clanspirits:manage_clanspirits')
            elif hasattr(pm, 'check'):
                perm_ok = await pm.check(player, 'manage_clanspirits')
        except Exception:
            perm_ok = False
        if not perm_ok:
            try:
                if hasattr(pm, 'has_permission'):
                    perm_ok = await pm.has_permission(player, 'local_records:manage_records')
                elif hasattr(pm, 'check'):
                    perm_ok = await pm.check(player, 'manage_records')
            except Exception:
                perm_ok = False
        try:
            if not perm_ok and hasattr(player, 'level') and getattr(player, 'level') is not None:
                if int(getattr(player, 'level')) >= 3:
                    perm_ok = True
        except Exception:
            pass
        if not perm_ok:
            return await self.instance.chat('You do not have permission to recalc ClanSpirits data.', player)

        # Perform recalculation.
        local_records_app = self.instance.apps.apps.get('local_records')
        pms_rows = await PlayerSpiritMapScore.execute(PlayerSpiritMapScore.select())
        if not pms_rows:
            return await self.instance.chat('No stored per-map scores to recalc.', player)

        updated = 0
        for row in pms_rows:
            # Attempt to resolve player and map objects where possible.
            player_obj = None
            map_obj = None
            try:
                # Player by id if available
                if hasattr(self.instance, 'player_manager') and getattr(row, 'player_id', None):
                    try:
                        player_obj = await self.instance.player_manager.get_player_by_id(row.player_id)
                    except Exception:
                        player_obj = None
                # Map: try map_manager.get_map using stored map_id or uid
                if hasattr(self.instance, 'map_manager') and getattr(row, 'map_id', None):
                    try:
                        map_obj = await self.instance.map_manager.get_map(row.map_id)
                    except Exception:
                        map_obj = None
            except Exception:
                pass

            # If we can query local_records for rank, prefer that; else derive from stored points -> rank mapping.
            rank = None
            if local_records_app and player_obj and map_obj:
                try:
                    rank, _ = await local_records_app.get_player_record_and_rank_for_map(map_obj, player_obj)
                except Exception:
                    rank = None

            if rank:
                new_points = int(self.scoring.get(rank, 0))
            else:
                # Fallback: keep existing points or attempt to remap via points->rank mapping.
                new_points = int(row.points or 0)

            if new_points != (row.points or 0):
                row.points = new_points
                await row.save()
                updated += 1

        # Recalculate aggregates for all spirits
        spirit_rows = await Spirit.execute(Spirit.select())
        for c in spirit_rows:
            await self.recalc_aggregate(c)

        await self.instance.chat(f'ClanSpirits recalculation complete. Updated {updated} per-map scores.', player)

    async def map_begin(self, map):
        pass

    async def player_finish(self, player, race_time, lap_time, cps, flow, raw, **kwargs):
        rel_rows = await PlayerSpirit.objects.execute(
            PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1)
        )
        rel = rel_rows[0] if rel_rows else None
        if not rel:
            self.logger.debug('ClanSpirits: player_finish no PlayerSpirit rel for player %s', getattr(player, 'login', None))
            return
        spirit_id = rel.spirit_id
        # If spirit_id missing, attempt a fresh lookup (race between leave/join and finish signal possible).
        if not spirit_id:
            self.logger.warning('ClanSpirits: player_finish rel has no spirit_id for player %s, attempting re-query', getattr(player, 'login', None))
            re_rows = await PlayerSpirit.objects.execute(
                PlayerSpirit.select().where(PlayerSpirit.player == player).limit(1)
            )
            re_rel = re_rows[0] if re_rows else None
            if re_rel and re_rel.spirit_id:
                spirit_id = re_rel.spirit_id
                self.logger.info('ClanSpirits: re-fetched spirit_id=%s for player %s', spirit_id, getattr(player, 'login', None))
            else:
                self.logger.error('ClanSpirits: no spirit membership found for player %s after re-query; skipping score', getattr(player, 'login', None))
                return
        local_records_app = self.instance.apps.apps.get('local_records')
        if not local_records_app:
            return
        self.logger.debug('ClanSpirits: player_finish for %s on map=%s (map_id=%s)', getattr(player, 'login', None), getattr(self.instance.map_manager.current_map, 'name', None), getattr(self.instance.map_manager.current_map, 'id', None))
        # Retry several times in case local_records hasn't persisted yet (race condition on signal order).
        # Increase attempts/backoff to tolerate maps with many records (up to ~300) and slower persistence.
        rank = None
        record = None
        for attempt in range(8):
            rank, record = await local_records_app.get_player_record_and_rank_for_map(
                self.instance.map_manager.current_map, player
            )
            if rank:
                break
            await asyncio.sleep(0.20)
        if not rank:
            self.logger.debug('ClanSpirits: no rank for %s after finish (attempts=3), skipping.', getattr(player, 'login', None))
            return
        async with self.lock:
            raw_points = self.scoring.get(rank, 0)
            try:
                points_value = int(raw_points)
            except Exception:
                self.logger.warning(f'ClanSpirits: invalid points value {raw_points} for rank {rank}, using 0.')
                points_value = 0
            existing_rows = await PlayerSpiritMapScore.objects.execute(
                PlayerSpiritMapScore.select().where(
                    (PlayerSpiritMapScore.map == self.instance.map_manager.current_map) & (PlayerSpiritMapScore.player == player)
                ).limit(1)
            )
            existing = existing_rows[0] if existing_rows else None
            if existing:
                # Update only if improvement (more points) and always log.
                if points_value > existing.points:
                    existing.points = points_value
                    await existing.save()
                    self.logger.debug(f'ClanSpirits: improved points player={player.login} rank={rank} pts={points_value}')
                else:
                    self.logger.debug(f'ClanSpirits: no improvement player={player.login} rank={rank} pts={points_value} existing={existing.points}')
            else:
                pcm = PlayerSpiritMapScore(
                    map_id=getattr(self.instance.map_manager.current_map, 'id', None),
                    player_id=getattr(player, 'id', None),
                    spirit_id=spirit_id,
                    points=points_value
                )
                # Defensive checks: log types to catch coroutine assignment issues.
                self.logger.debug(
                    'ClanSpirits: creating PlayerSpiritMapScore map_id=%s player_id=%s spirit_id=%s points=%s types(map=%s,player=%s,spirit=%s,points=%s)',
                    getattr(self.instance.map_manager.current_map, 'id', None), getattr(player, 'id', None), spirit_id, points_value,
                    type(self.instance.map_manager.current_map), type(player), type(spirit_id), type(points_value)
                )
                try:
                    await pcm.save()
                except Exception as e:
                    self.logger.exception('ClanSpirits: failed saving PlayerSpiritMapScore for player=%s map=%s spirit=%s pts=%s',
                                          getattr(player, 'login', None), getattr(self.instance.map_manager.current_map, 'id', None), spirit_id, points_value)
                    raise
                self.logger.info('ClanSpirits: created PlayerSpiritMapScore player=%s spirit=%s map=%s pts=%s rank=%s',
                                 getattr(player, 'login', None), spirit_id, getattr(self.instance.map_manager.current_map, 'id', None), points_value, rank)
        # Fetch spirit model for aggregation and chat.
        spirit = await Spirit.get(id=spirit_id)
        await self.recalc_aggregate(spirit)
        # Refresh widget after score change
        if hasattr(self, 'widget') and self.widget:
            await self.widget.refresh()

    async def load_scoring(self):
        raw = await self.setting_scoring.get_value()
        try:
            data = json.loads(raw)
            parsed = {}
            for k, v in data.items():
                try:
                    parsed[int(k)] = int(v)
                except Exception:
                    continue
            if parsed:
                # Merge provided custom scoring into DEFAULT_SCORING so ranks not present in the
                # setting still fall back to the 300-place harmonic default.
                merged = DEFAULT_SCORING.copy()
                merged.update(parsed)
                self.scoring = merged
                self.logger.info(f'ClanSpirits scoring loaded (merged with default): top_defined={len(parsed)} total_positions={len(self.scoring)}')
        except Exception as e:
            self.logger.warning(f'Failed parsing clanspirits_scoring setting: {e}')

    async def recalc_aggregate(self, spirit):
        unique_only = await self.setting_unique_spirit_per_map.get_value()
        # Use spirit id for comparison to avoid peewee coercion on model instance in composite expressions.
        query = PlayerSpiritMapScore.select().where(PlayerSpiritMapScore.spirit == spirit.id)
        rows = await PlayerSpiritMapScore.execute(query)
        if unique_only:
            per_map = {}
            for r in rows:
                best = per_map.get(r.map_id)
                if not best or r.points > best:
                    per_map[r.map_id] = r.points
            total = sum(per_map.values())
        else:
            total = sum(r.points for r in rows)
        agg_rows = await SpiritAggregateScore.objects.execute(
            SpiritAggregateScore.select().where(SpiritAggregateScore.spirit == spirit.id).limit(1)
        )
        agg = agg_rows[0] if agg_rows else None
        if not agg:
            agg = SpiritAggregateScore(spirit=spirit, points=total)
            await agg.save()
        else:
            agg.points = total
            await agg.save()
        await self.instance.chat(f'Spirit {spirit.name} now at {agg.points} pts.')
        if hasattr(self, 'widget') and self.widget:
            await self.widget.refresh()


class ClanSpiritsStandingsView(ManualListView):
    title = 'ClanSpirits Standings'
    icon_style = 'Icons128x128_1'
    icon_substyle = 'Rankings'
    navbar_title = 'ClanSpirits'
    sorting_enabled = True
    searching_enabled = False
    default_sort = (0, True)  # sort by rank (index 0) asc

    def __init__(self, app):
        # Follow pattern from bundled apps (pass self first, then assign real manager)
        super().__init__(self)
        self.app = app
        self.manager = app.context.ui

    async def get_fields(self):
        return [
            {'name': '#', 'index': 'rank', 'width': 8},
            {'name': 'Spirit', 'index': 'spirit', 'width': 35, 'searching': True},
            {'name': 'Members', 'index': 'members', 'width': 15},
            {'name': 'Maps', 'index': 'maps', 'width': 15},
            {'name': 'Best Rank', 'index': 'best_rank', 'width': 20},
            {'name': 'Points', 'index': 'points', 'width': 20},
            {'name': 'AvgPts', 'index': 'avg_pts', 'width': 15},
        ]

    async def get_buttons(self):
        # Remove all default action buttons from the standings view to keep UI clean.
        return []

    async def get_data(self):
        agg_rows = await SpiritAggregateScore.execute(
            SpiritAggregateScore.select(SpiritAggregateScore, Spirit).join(Spirit).order_by(SpiritAggregateScore.points.desc())
        )
        # Get member counts in one grouped query.
        member_count_rows = await PlayerSpirit.execute(
            PlayerSpirit.select(PlayerSpirit.spirit, fn.COUNT(PlayerSpirit.player).alias('cnt')).group_by(PlayerSpirit.spirit)
        )
        counts = {}
        for r in member_count_rows:
            # r.spirit is FK value; use spirit_id attribute if present.
            sid = getattr(r, 'spirit_id', None) or r.spirit
            counts[sid] = r.cnt
        # Preload all player map scores for these spirits to compute map counts + best rank.
        spirit_ids = [ar.spirit.id for ar in agg_rows]
        pms_rows = await PlayerSpiritMapScore.execute(
            PlayerSpiritMapScore.select().where(PlayerSpiritMapScore.spirit << spirit_ids)
        )
        # Build map counts and best rank (by deriving from unique points mapping) per spirit.
        points_to_rank = {v: k for k, v in self.app.scoring.items() if isinstance(k, int) and isinstance(v, int)}
        map_counts = {}
        best_ranks = {}
        for row in pms_rows:
            sid = row.spirit_id if hasattr(row, 'spirit_id') else row.spirit.id
            if row.points and row.points > 0:
                # Map count distinct.
                mc = map_counts.setdefault(sid, set())
                mc.add(row.map_id if hasattr(row, 'map_id') else row.map.id)
                # Derive rank from points if possible.
                rank_guess = points_to_rank.get(row.points)
                if rank_guess:
                    current_best = best_ranks.get(sid)
                    if current_best is None or rank_guess < current_best:
                        best_ranks[sid] = rank_guess
        # Convert map sets to lengths.
        for sid, s in list(map_counts.items()):
            map_counts[sid] = len(s)
        data = []
        rank = 1
        for r in agg_rows:
            sid = getattr(r, 'spirit_id', None) or r.spirit.id
            members = counts.get(sid, 0)
            maps_played = map_counts.get(sid, 0)
            best_rank = best_ranks.get(sid, '-')
            avg_pts = round(r.points / maps_played, 2) if maps_played else 0
            # Color top 3 spirit names.
            name = r.spirit.name
            if rank == 1:
                name = f'$ff0{name}$z'
            elif rank == 2:
                name = f'$fa0{name}$z'
            elif rank == 3:
                name = f'$f80{name}$z'
            # Return object with named attributes so template getattr(row, field['index']) works.
            data.append(SimpleNamespace(rank=rank, spirit=name, members=members, maps=maps_played, best_rank=best_rank, points=r.points, avg_pts=avg_pts))
            rank += 1
        return data


class ClanSpiritsWidget(WidgetView):
    title = 'ClanSpirits'
    size_x = 60
    size_y = 30
    pos_x = -160
    pos_y = 80
    z_index = 5

    def __init__(self, app):
        super().__init__(self)
        self.app = app
        self.manager = app.context.ui
        # Expose a widget action receiver name for button clicks and subscribe to it.
        try:
            self.action = 'spirit_widget_action'
            # subscribe is provided by the WidgetView base; register widget action handler
            self.subscribe('spirit_widget_action', self.widget_action)
        except Exception:
            # If subscription isn't available at init time, ignore and rely on lazy registration.
            pass

    async def get_context_data(self):
        rows = await SpiritAggregateScore.execute(
            SpiritAggregateScore.select(SpiritAggregateScore, Spirit).join(Spirit).order_by(SpiritAggregateScore.points.desc()).limit(5)
        )
        lines = []
        rank = 1
        for r in rows:
            lines.append({'rank': rank, 'spirit': r.spirit.name, 'points': r.points})
            rank += 1
        # Add admin buttons (rendering depends on widget template supporting 'buttons').
        buttons = [
            {'id': 'export', 'label': 'Export', 'width': 40},
            {'id': 'recalc', 'label': 'Recalc', 'width': 40},
            {'id': 'reset', 'label': 'Reset', 'width': 40},
        ]
        return {'lines': lines, 'buttons': buttons}

    async def widget_action(self, player, action, values, **kwargs):
        # values expected to contain which button id was clicked.
        btn = None
        try:
            btn = values.get('button')
        except Exception:
            return
        # Permission check: admin only
        pm = getattr(self.app.instance, 'permission_manager', None)
        perm_ok = False
        try:
            if pm and hasattr(pm, 'has_permission'):
                perm_ok = await pm.has_permission(player, 'clanspirits:manage_clanspirits')
        except Exception:
            perm_ok = False
        if not perm_ok and hasattr(player, 'level') and getattr(player, 'level') is not None:
            try:
                if int(getattr(player, 'level')) >= 3:
                    perm_ok = True
            except Exception:
                pass
        if not perm_ok:
            return await self.app.instance.chat('You do not have permission to perform that action.', player)

        if btn == 'export':
            await self.app.cmd_spiritexport(player, data=SimpleNamespace(format='csv'))
        elif btn == 'recalc':
            await self.app.cmd_spirit_recalc(player)
        elif btn == 'reset':
            # ask for confirmation
            await self.app.instance.chat('To reset spirit data run: /spirit_reset confirm=yes', player)
        else:
            await self.app.instance.chat('Unknown widget action.', player)

    async def display(self, player=None):
        await super().display(player=player)

    async def refresh(self, player=None):
        await self.display(player=player)
