# asyncpg pool + migration runner for the user-system Postgres.
# init() is called from the FastAPI lifespan hook; everything in ptd_users
# assumes the pool exists and crashes if it does not.

from pathlib import Path

import asyncpg

from config import DATABASE_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

pool: asyncpg.Pool = None


async def init():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await _migrate()


async def close():
    await pool.close()


async def _migrate():
    async with pool.acquire() as conn:
        await conn.execute("""
            create table if not exists schema_migrations (
                filename   text primary key,
                applied_at timestamptz not null default now()
            )
        """)
        applied = {r["filename"] for r in await conn.fetch("select filename from schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            # One transaction per file: either the whole migration lands and is
            # recorded, or the app refuses to start.
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute(
                    "insert into schema_migrations (filename) values ($1)", path.name
                )
            print(f"Applied migration {path.name}", flush=True)
