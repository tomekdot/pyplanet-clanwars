from peewee import *
from pyplanet.core.db import TimedModel
from pyplanet.apps.core.maniaplanet.models import Player, Map

class Spirit(TimedModel):
    name = CharField(unique=True, max_length=32)

class PlayerSpirit(TimedModel):
    player = ForeignKeyField(Player, index=True)
    spirit = ForeignKeyField(Spirit, index=True)

    class Meta:
        indexes = ((('player', 'spirit'), True),)

class PlayerSpiritMapScore(TimedModel):
    """Stores the points a player earned for a specific map (best attempt only)."""
    map = ForeignKeyField(Map, index=True)
    player = ForeignKeyField(Player, index=True)
    spirit = ForeignKeyField(Spirit, index=True)
    points = IntegerField(default=0)

    class Meta:
        indexes = ((('map', 'player'), True),)

class SpiritAggregateScore(TimedModel):
    spirit = ForeignKeyField(Spirit, unique=True)
    points = IntegerField(default=0)
