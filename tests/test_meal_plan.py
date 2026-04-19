"""
Tests for backend/meal_plan.py.

Uses an in-memory aiosqlite database initialised with the real schema so we
exercise the actual SQL without touching the filesystem.
"""
from __future__ import annotations

from datetime import date, timedelta

import aiosqlite
import pytest

from backend.db import init_schema
from backend.meal_plan import (
    clear_slot,
    get_recent_ids,
    get_week,
    set_slot,
    _iso_week_str,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_week() -> str:
    return _iso_week_str(date.today())


def next_week() -> str:
    return _iso_week_str(date.today() + timedelta(weeks=1))


def past_week() -> str:
    return _iso_week_str(date.today() - timedelta(weeks=2))


def far_future_week() -> str:
    return _iso_week_str(date.today() + timedelta(weeks=3))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def db():
    """In-memory aiosqlite connection with schema applied."""
    async with aiosqlite.connect(":memory:") as conn:
        await init_schema(conn)
        yield conn


# ---------------------------------------------------------------------------
# Write-enforcement tests
# ---------------------------------------------------------------------------

async def test_set_slot_current_week_accepted(db):
    slot = await set_slot(db, current_week(), day=0, meal=0, recipe_id="r001")
    assert slot.iso_week == current_week()
    assert slot.recipe_id == "r001"


async def test_set_slot_next_week_accepted(db):
    slot = await set_slot(db, next_week(), day=3, meal=1, recipe_id="r002")
    assert slot.iso_week == next_week()
    assert slot.recipe_id == "r002"


async def test_set_slot_past_week_rejected(db):
    with pytest.raises(ValueError, match="current"):
        await set_slot(db, past_week(), day=0, meal=0, recipe_id="r001")


async def test_set_slot_far_future_week_rejected(db):
    with pytest.raises(ValueError, match="next"):
        await set_slot(db, far_future_week(), day=0, meal=0, recipe_id="r001")


# ---------------------------------------------------------------------------
# get_week tests
# ---------------------------------------------------------------------------

async def test_get_week_returns_assigned_slots(db):
    week = current_week()
    await set_slot(db, week, day=0, meal=0, recipe_id="r001")
    await set_slot(db, week, day=1, meal=1, recipe_id="r002")

    slots = await get_week(db, week)
    assert len(slots) == 2
    ids = {s.recipe_id for s in slots}
    assert ids == {"r001", "r002"}


async def test_get_week_empty_returns_empty_list(db):
    slots = await get_week(db, current_week())
    assert slots == []


async def test_get_week_isolates_by_week(db):
    cw = current_week()
    nw = next_week()
    await set_slot(db, cw, day=0, meal=0, recipe_id="r001")
    await set_slot(db, nw, day=0, meal=0, recipe_id="r002")

    current_slots = await get_week(db, cw)
    assert len(current_slots) == 1
    assert current_slots[0].recipe_id == "r001"


async def test_set_slot_upsert_replaces_existing(db):
    week = current_week()
    await set_slot(db, week, day=2, meal=0, recipe_id="r001")
    await set_slot(db, week, day=2, meal=0, recipe_id="r999")

    slots = await get_week(db, week)
    assert len(slots) == 1
    assert slots[0].recipe_id == "r999"


# ---------------------------------------------------------------------------
# clear_slot tests
# ---------------------------------------------------------------------------

async def test_clear_slot_removes_row(db):
    week = current_week()
    await set_slot(db, week, day=0, meal=0, recipe_id="r001")
    removed = await clear_slot(db, week, day=0, meal=0)

    assert removed is True
    assert await get_week(db, week) == []


async def test_clear_slot_returns_false_when_not_found(db):
    removed = await clear_slot(db, current_week(), day=5, meal=1)
    assert removed is False


async def test_clear_slot_only_removes_targeted_slot(db):
    week = current_week()
    await set_slot(db, week, day=0, meal=0, recipe_id="r001")
    await set_slot(db, week, day=0, meal=1, recipe_id="r002")

    await clear_slot(db, week, day=0, meal=0)
    slots = await get_week(db, week)
    assert len(slots) == 1
    assert slots[0].recipe_id == "r002"


# ---------------------------------------------------------------------------
# get_recent_ids tests
# ---------------------------------------------------------------------------

async def test_get_recent_ids_empty_when_no_history(db):
    ids = await get_recent_ids(db)
    assert ids == set()


async def test_get_recent_ids_excludes_current_week(db):
    """Recipes assigned this week must NOT appear in recent ids."""
    # Directly insert into the DB so we bypass write enforcement.
    week = current_week()
    await db.execute(
        "INSERT INTO meal_plan (iso_week, day, meal, recipe_id, recipe_type) VALUES (?,?,?,?,?)",
        (week, 0, 0, "r_current", "cookidoo"),
    )
    await db.commit()

    ids = await get_recent_ids(db)
    assert "r_current" not in ids


async def test_get_recent_ids_returns_ids_from_w_minus_1_and_w_minus_2(db):
    """
    Manually insert rows with the exact ISO weeks that SQLite's
    strftime('%G-W%V', 'now', '-7 days') and '-14 days' produce,
    so the test is always correct regardless of when it runs.
    """
    from datetime import timezone
    import aiosqlite as _aiosqlite

    d_minus7 = date.today() - timedelta(days=7)
    d_minus14 = date.today() - timedelta(days=14)
    w_minus1 = _iso_week_str(d_minus7)
    w_minus2 = _iso_week_str(d_minus14)

    for week, rid in [(w_minus1, "r_w1"), (w_minus2, "r_w2")]:
        await db.execute(
            "INSERT INTO meal_plan (iso_week, day, meal, recipe_id, recipe_type) VALUES (?,?,?,?,?)",
            (week, 0, 0, rid, "cookidoo"),
        )
    await db.commit()

    ids = await get_recent_ids(db)
    assert "r_w1" in ids
    assert "r_w2" in ids


async def test_get_recent_ids_ignores_older_weeks(db):
    old_week = _iso_week_str(date.today() - timedelta(weeks=5))
    await db.execute(
        "INSERT INTO meal_plan (iso_week, day, meal, recipe_id, recipe_type) VALUES (?,?,?,?,?)",
        (old_week, 0, 0, "r_old", "cookidoo"),
    )
    await db.commit()

    ids = await get_recent_ids(db)
    assert "r_old" not in ids
