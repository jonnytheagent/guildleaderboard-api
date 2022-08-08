from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, List

import asyncpg
from dotenv import load_dotenv

if TYPE_CHECKING:
    pass

load_dotenv()
DB_IP = os.getenv("DB_IP")
DB_USER = os.getenv("DB_USER")
DB_PWD = os.getenv("DB_PWD")


class Database:
    """
CREATE TABLE guilds (
    guild_id TEXT,
    guild_name TEXT,
    capture_date TIMESTAMP,
    players TEXT[],
    average_weight REAL,
    average_skills REAL,
    average_catacombs REAL,
    average_slayer REAL,
    scammers SMALLINT,
    position_change SMALLINT

)
guilds.players is an aray of uuids

CREATE TABLE players (
    uuid TEXT UNIQUE,
    name TEXT,
    weight REAL,
    skill_weight REAL,
    slayer_weight REAL,
    dungeon_weight REAL,
    average_skill REAL,
    catacomb REAL,
    catacomb_xp REAL,
    total_slayer REAL,
    capture_date TIMESTAMP,
    scam_reason TEXT
)

CREATE TABLE guild_information (
    guild_id TEXT,
    discord TEXT
)
"""

    pool: asyncpg.pool.Pool = None

    def __init__(self, app):
        self.app = app
        self.json_keys = []
        self.cached_guilds = {}

    @staticmethod
    async def get_pool():
        kwargs = {
            "host": DB_IP,
            "port": 5432,
            "user": DB_USER,
            "password": DB_PWD,
            "min_size": 3,
            "max_size": 10,
            "command_timeout": 60,
            "loop": asyncio.get_event_loop()
        }
        return await asyncpg.create_pool(**kwargs)

    async def open(self):
        self.app.logger.info('Initializing database connection...')
        Database.pool = await self.get_pool()
        self.app.logger.info('Database connection initialized.')
        return self

    async def close(self):
        await Database.pool.close()
        self.app.logger.info('Database connection closed.')
        return self

    def format_json(self, record: asyncpg.Record) -> dict:
        if record is None:
            return None
        return {key: (json.loads(value) if key in self.json_keys else value) for (key, value) in dict(record).items()}

    async def get_guilds(self):
        r = await self.pool.fetch("""
SELECT DISTINCT ON (guild_id) ROUND(average_catacombs::numeric, 2)::float AS average_catacombs, ROUND(average_skills::numeric, 2)::float AS average_skills, ROUND(average_slayer::numeric, 2)::float AS average_slayer, ROUND(average_weight::numeric, 2)::float AS average_weight, guild_id, guild_name, array_length(players, 1) AS players, NOW() - capture_date::timestamptz at time zone 'UTC' AS time_difference, scammers, position_change FROM guilds ORDER BY guild_id, capture_date DESC;
        """)
        return [self.format_json(row) for row in r]

    async def get_guild(self, guild_id, conn=None):
        query_str = """
SELECT DISTINCT ON (guild_id) ROUND(average_catacombs::numeric, 2)::float AS average_catacombs, ROUND(average_skills::numeric, 2)::float AS average_skills, ROUND(average_slayer::numeric, 2)::float AS average_slayer, ROUND(average_weight::numeric, 2)::float AS average_weight, guild_id, guild_name, players, NOW() - capture_date::timestamptz at time zone 'UTC' AS time_difference, scammers FROM guilds WHERE guild_id = $1 ORDER BY guild_id, capture_date DESC;
        """
        if conn:
            r = await conn.fetchrow(query_str, guild_id)
        else:
            r = await self.pool.fetchrow(query_str, guild_id)
        return self.format_json(r)

    async def get_guild_metrics(self, guild_id):
        r = await self.pool.fetch("""
SELECT
    ROUND(average_weight::numeric, 2)::float AS average_weight,
    ROUND(average_skills::numeric, 2)::float AS average_skills,
    ROUND(average_catacombs::numeric, 2)::float AS average_catacombs,
    ROUND(average_slayer::numeric, 2)::float AS average_slayer,
    cardinality(players) AS member_count,
    NOW() - capture_date::timestamptz at time zone 'UTC' AS time_difference
FROM guilds
    WHERE guild_id = $1
    ORDER BY capture_date
        """, str(guild_id))
        return [self.format_json(row) for row in r] if r else []

    async def get_guild_history(self, guild_id):
        r = await self.pool.fetch("""
SELECT
    players,
    NOW() - capture_date::timestamptz at time zone 'UTC' AS time_difference
FROM guilds
    WHERE guild_id = $1
ORDER BY capture_date
    """, str(guild_id))
        return [self.format_json(row) for row in r] if r else []

    async def get_id_name_autocomplete(self):
        r = await self.pool.fetch("""
SELECT DISTINCT ON (guild_id) guild_id, guild_name FROM guilds ORDER BY guild_id, capture_date DESC;""")
        return [{"id": row['guild_id'], "name": row['guild_name']} for row in r]

    async def get_names(self, uuids):
        r = await self.pool.fetch("""
SELECT uuid, name FROM players WHERE uuid = ANY($1)""", uuids)
        return {row['uuid']: row['name'] for row in r}

    async def get_players(self, uuids: List[str], conn=None):
        query_str = """
SELECT uuid, name, ROUND(weight::numeric, 2)::float AS weight, ROUND(average_skill::numeric, 2)::float AS average_skill, ROUND(catacomb::numeric, 2)::float AS catacomb, ROUND(total_slayer::numeric, 2)::float AS total_slayer, NOW() - capture_date::timestamptz at time zone 'UTC' AS time_difference, scam_reason FROM players WHERE uuid = ANY($1);
        """
        if conn:
            r = await conn.fetch(query_str, uuids)
        else:
            r = await self.pool.fetch(query_str, uuids)
        return [self.format_json(row) for row in r]

    async def upsert_guild_info(self, guild_id: str, discordid: str):
        query_str = """
INSERT INTO guild_information (guild_id, discord)
VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET discord = $2;
        """
        await self.pool.execute(query_str, guild_id, discordid)

    async def get_guild_discord(self, guild_id: str, conn=None):
        query_str = """
SELECT discord FROM guild_information WHERE guild_id = $1;
        """
        if conn:
            r = await conn.fetchrow(query_str, guild_id)
        else:
            r = await self.pool.fetchrow(query_str, guild_id)
        return r["discord"] if r else None
