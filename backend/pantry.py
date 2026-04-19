from __future__ import annotations

import uuid

import aiosqlite

from backend.models import PantryItem


async def list_items(db: aiosqlite.Connection) -> list[PantryItem]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT id, name, quantity, unit FROM pantry ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    return [PantryItem(id=r["id"], name=r["name"], quantity=r["quantity"], unit=r["unit"]) for r in rows]


async def add_item(
    db: aiosqlite.Connection,
    name: str,
    quantity: float | None = None,
    unit: str | None = None,
) -> PantryItem:
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO pantry (id, name, quantity, unit) VALUES (?, ?, ?, ?)",
        (item_id, name, quantity, unit),
    )
    await db.commit()
    return PantryItem(id=item_id, name=name, quantity=quantity, unit=unit)


async def update_item(
    db: aiosqlite.Connection,
    item_id: str,
    name: str,
    quantity: float | None = None,
    unit: str | None = None,
) -> PantryItem | None:
    await db.execute(
        "UPDATE pantry SET name = ?, quantity = ?, unit = ? WHERE id = ?",
        (name, quantity, unit, item_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT id, name, quantity, unit FROM pantry WHERE id = ?", (item_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return PantryItem(id=row[0], name=row[1], quantity=row[2], unit=row[3])


async def delete_item(db: aiosqlite.Connection, item_id: str) -> bool:
    async with db.execute(
        "DELETE FROM pantry WHERE id = ?", (item_id,)
    ) as cur:
        await db.commit()
        return cur.rowcount > 0
