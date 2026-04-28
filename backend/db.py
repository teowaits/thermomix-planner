from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

DB_DIR = Path(__file__).parent.parent / "db"
DB_PATH = DB_DIR / "planner.db"


async def init_schema(db: aiosqlite.Connection) -> None:
    DB_DIR.mkdir(exist_ok=True)

    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'ok',
            recipe_type      TEXT NOT NULL DEFAULT 'cookidoo',
            collection_id    TEXT,
            cooking_time     INTEGER,
            servings         INTEGER,
            ingredients_json TEXT,
            raw_json         TEXT
        )
    """)
    # Idempotent migration for DBs created before recipe_type was added
    try:
        await db.execute(
            "ALTER TABLE recipes ADD COLUMN recipe_type TEXT NOT NULL DEFAULT 'cookidoo'"
        )
    except Exception:
        pass  # column already exists

    # Idempotent migration for source_url (Phase 2 — custom recipes)
    try:
        await db.execute("ALTER TABLE recipes ADD COLUMN source_url TEXT")
    except Exception:
        pass  # column already exists

    await db.execute("""
        CREATE TABLE IF NOT EXISTS meal_plan (
            iso_week     TEXT    NOT NULL,
            day          INTEGER NOT NULL,
            meal         INTEGER NOT NULL,
            recipe_id    TEXT,
            recipe_type  TEXT    NOT NULL DEFAULT 'cookidoo',
            assigned_at  TEXT,
            PRIMARY KEY (iso_week, day, meal)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS pantry (
            id       TEXT PRIMARY KEY,
            name     TEXT NOT NULL,
            quantity REAL,
            unit     TEXT
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS ingredient_synonyms (
            normalised_name TEXT PRIMARY KEY,
            canonical_name  TEXT NOT NULL,
            source          TEXT NOT NULL,
            resolved_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.commit()
