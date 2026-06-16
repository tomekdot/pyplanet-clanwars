from peewee import *
from pyplanet.core.db import TimedModel
from pyplanet.apps.core.maniaplanet.models import Player, Map

class Clan(TimedModel):
    name = CharField(unique=True, max_length=32)

class PlayerClan(TimedModel):
    player = ForeignKeyField(Player, index=True)
    clan = ForeignKeyField(Clan, index=True)

    class Meta:
        indexes = ((('player', 'clan'), True),)

class PlayerClanMapScore(TimedModel):
    """Stores the points a player earned for a specific map (best attempt only)."""
    map = ForeignKeyField(Map, index=True)
    player = ForeignKeyField(Player, index=True)
    clan = ForeignKeyField(Clan, index=True)
    points = IntegerField(default=0)

    class Meta:
        indexes = ((('map', 'player'), True),)

class ClanAggregateScore(TimedModel):
    clan = ForeignKeyField(Clan, unique=True)
    points = IntegerField(default=0)
