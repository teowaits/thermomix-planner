from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import aiosqlite

from backend.models import WeekSlot


def _iso_week_str(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _allowed_weeks() -> tuple[str, str]:
    today = date.today()
    current = _iso_week_str(today)
    next_week = _iso_week_str(today + timedelta(weeks=1))
    return current, next_week


async def get_week(db: aiosqlite.Connection, iso_week: str) -> list[WeekSlot]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT iso_week, day, meal, recipe_id, recipe_type, assigned_at"
        " FROM meal_plan WHERE iso_week = ?",
        (iso_week,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        WeekSlot(
            iso_week=r["iso_week"],
            day=r["day"],
            meal=r["meal"],
            recipe_id=r["recipe_id"],
            recipe_type=r["recipe_type"],
            assigned_at=r["assigned_at"],
        )
        for r in rows
    ]


async def set_slot(
    db: aiosqlite.Connection,
    iso_week: str,
    day: int,
    meal: int,
    recipe_id: str,
    recipe_type: str = "cookidoo",
) -> WeekSlot:
    current, next_week = _allowed_weeks()
    if iso_week not in (current, next_week):
        raise ValueError(
            f"Writes only allowed for current ({current}) or next ({next_week}) "
            f"ISO week; got {iso_week!r}"
        )

    assigned_at = datetime.now(timezone.utc).isoformat()

    await db.execute(
        """
        INSERT INTO meal_plan (iso_week, day, meal, recipe_id, recipe_type, assigned_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(iso_week, day, meal) DO UPDATE SET
            recipe_id   = excluded.recipe_id,
            recipe_type = excluded.recipe_type,
            assigned_at = excluded.assigned_at
        """,
        (iso_week, day, meal, recipe_id, recipe_type, assigned_at),
    )
    await db.commit()

    return WeekSlot(
        iso_week=iso_week,
        day=day,
        meal=meal,
        recipe_id=recipe_id,
        recipe_type=recipe_type,
        assigned_at=assigned_at,
    )


async def clear_slot(
    db: aiosqlite.Connection,
    iso_week: str,
    day: int,
    meal: int,
) -> bool:
    async with db.execute(
        "DELETE FROM meal_plan WHERE iso_week = ? AND day = ? AND meal = ?",
        (iso_week, day, meal),
    ) as cur:
        await db.commit()
        return cur.rowcount > 0


async def get_recent_ids(db: aiosqlite.Connection) -> set[str]:
    """
    Return recipe_ids used in the 2 completed ISO weeks immediately before
    the current week (W-1 and W-2).  Current week is excluded so that
    recipes assigned this week are still eligible for suggestions.
    """
    async with db.execute(
        """
        SELECT DISTINCT recipe_id FROM meal_plan
        WHERE recipe_id IS NOT NULL
          AND iso_week IN (
              strftime('%G-W%V', 'now', '-7 days'),
              strftime('%G-W%V', 'now', '-14 days')
          )
        """
    ) as cur:
        rows = await cur.fetchall()
    return {row[0] for row in rows}
