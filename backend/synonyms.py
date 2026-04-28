"""
synonyms.py — Multilingual ingredient synonym resolution.

Resolution order for a given ingredient name:
  1. In-memory dictionary (_DICT) — 103 canonical groups, 857 terms, 4 languages.
     Built once at module import from backend/data/ingredient_synonyms.json.
  2. SQLite ingredient_synonyms table — Claude API results cached permanently.
  3. Claude API (claude-haiku) — called once per unknown ingredient, result stored.
     Requires ANTHROPIC_API_KEY env var. If absent: passthrough (no crash).

Always returns a string. Never raises.

Entry point: resolve_ingredient(name, db)
Bulk pre-resolve: warm_cache(db, ingredient_names)  — call after cache refresh.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import aiosqlite

from backend.suggestions import normalise_ingredient_name

_LOGGER = logging.getLogger(__name__)

_DICT_PATH = Path(__file__).parent / "data" / "ingredient_synonyms.json"


# ---------------------------------------------------------------------------
# Dictionary — loaded once at import time
# ---------------------------------------------------------------------------

def _load_dictionary() -> dict[str, str]:
    """
    Build a flat lookup from the JSON synonym dictionary.

    For every term in every language group, store two keys:
      - The raw lowercased form (e.g. "tomatoes" → "tomato")
      - The normalised form via normalise_ingredient_name() (e.g. "tomatoe" → "tomato")

    Both are needed because normalise_ingredient_name strips trailing 's', turning
    "tomatoes" into "tomatoe" — which would miss a dict keyed on "tomatoes".
    """
    with open(_DICT_PATH, encoding="utf-8") as fh:
        data = json.load(fh)

    result: dict[str, str] = {}
    for group in data["ingredients"]:
        canonical: str = group["canonical"]
        for key, terms in group.items():
            if key in ("canonical",):
                continue
            for term in terms:
                raw = term.strip().lower()
                norm = normalise_ingredient_name(term)
                result[raw] = canonical
                result[norm] = canonical
    return result


_DICT: dict[str, str] = _load_dictionary()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def resolve_ingredient(
    name: str,
    db: Optional[aiosqlite.Connection] = None,
) -> str:
    """
    Resolve an ingredient name to its canonical English form.

    Steps:
      a. normalise_ingredient_name() — preposition strip + lowercase + plural 's' strip
      b. Check _DICT (raw lowercased form, then normalised form)
      c. Check SQLite ingredient_synonyms table  (skipped when db is None)
      d. Call Claude API; cache result in SQLite  (skipped when db is None)

    Returns the canonical name, or the normalised input if resolution fails.
    Never raises.
    """
    normalised = normalise_ingredient_name(name)
    lowered = name.strip().lower()

    # b. Dictionary lookup — try raw first (preserves "tomatoes"), then normalised
    if lowered in _DICT:
        return _DICT[lowered]
    if normalised in _DICT:
        return _DICT[normalised]

    if db is None:
        return normalised

    # c. SQLite cache
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT canonical_name FROM ingredient_synonyms WHERE normalised_name = ?",
        (normalised,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        return row["canonical_name"]

    # d. Claude API
    canonical = await _resolve_via_claude(normalised)
    await db.execute(
        """
        INSERT OR IGNORE INTO ingredient_synonyms (normalised_name, canonical_name, source)
        VALUES (?, ?, 'claude_api')
        """,
        (normalised, canonical),
    )
    await db.commit()
    return canonical


async def warm_cache(
    db: aiosqlite.Connection,
    ingredient_names: list[str],
) -> None:
    """
    Pre-resolve all ingredient names not already covered by the dictionary or SQLite cache.

    Called once after a full Cookidoo cache refresh so that daily use never hits the API.
    Rate-limited to 0.1 s between API calls.
    """
    unique = list(set(ingredient_names))

    # Find names that need API resolution
    to_resolve: list[str] = []
    for name in unique:
        normalised = normalise_ingredient_name(name)
        lowered = name.strip().lower()
        if lowered in _DICT or normalised in _DICT:
            continue
        async with db.execute(
            "SELECT 1 FROM ingredient_synonyms WHERE normalised_name = ?",
            (normalised,),
        ) as cur:
            if await cur.fetchone():
                continue
        to_resolve.append(name)

    _LOGGER.info(
        "Warming synonym cache for %d unique ingredient names (%d to resolve via API)",
        len(unique),
        len(to_resolve),
    )

    if not to_resolve or not os.getenv("ANTHROPIC_API_KEY"):
        _LOGGER.info("Synonym cache warm complete. 0 new API resolutions.")
        return

    resolved = 0
    for name in to_resolve:
        _LOGGER.info("Resolving unknown ingredient via Claude API: %s", name)
        normalised = normalise_ingredient_name(name)
        canonical = await _resolve_via_claude(normalised)
        await db.execute(
            "INSERT OR IGNORE INTO ingredient_synonyms (normalised_name, canonical_name, source) "
            "VALUES (?, ?, 'claude_api')",
            (normalised, canonical),
        )
        resolved += 1
        await asyncio.sleep(0.1)

    if resolved:
        await db.commit()

    _LOGGER.info("Synonym cache warm complete. %d new API resolutions.", resolved)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

async def _resolve_via_claude(name: str) -> str:
    """
    Call Claude Haiku to get the canonical English ingredient name.

    Returns the original name if the API key is absent, the call fails, or
    the response is empty. Never raises.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        _LOGGER.warning(
            "ANTHROPIC_API_KEY not set; skipping Claude API resolution for '%s'", name
        )
        return name

    try:
        import anthropic  # local import — optional dependency

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=32,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "What is the canonical English name for this cooking ingredient? "
                        "Reply with only the singular lowercase English ingredient name, "
                        "nothing else. If you are uncertain, reply with the original word.\n"
                        f"Ingredient: {name}"
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        first_line = raw.split("\n")[0].lower()
        canonical = re.sub(r"[^\w\s\-]", "", first_line).strip()
        _LOGGER.info("Claude resolved '%s' → '%s'", name, canonical or name)
        return canonical or name
    except Exception as exc:
        _LOGGER.warning("Claude API resolution failed for '%s': %s", name, exc)
        return name
