"""Replicate retry_unavailable() logic for 5 recipes and show exact errors."""
import asyncio
import dataclasses
import json
import re
import sqlite3
import ssl

import aiohttp
import certifi
from dotenv import load_dotenv
import os

load_dotenv()

from cookidoo_api import Cookidoo
from cookidoo_api.types import CookidooConfig, CookidooLocalizationConfig

_QTY_RE = re.compile(r'^(\d+/\d+|\d+(?:[.,]\d+)?)\s*(.*)?$')

def _parse_description(desc):
    if not desc:
        return None, None
    desc = desc.strip()
    m = _QTY_RE.match(desc)
    if not m:
        return None, None
    qty_str = m.group(1)
    unit = (m.group(2) or "").strip() or None
    if "/" in qty_str:
        try:
            num, den = qty_str.split("/", 1)
            qty = float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None, None
    else:
        try:
            qty = float(qty_str.replace(",", "."))
        except ValueError:
            return None, None
    return qty, unit


async def main():
    con = sqlite3.connect("db/planner.db")
    cur = con.cursor()
    cur.execute("SELECT id, name, recipe_type, collection_id FROM recipes WHERE status = 'unavailable' LIMIT 5")
    rows = cur.fetchall()
    con.close()

    country = os.getenv("COOKIDOO_COUNTRY", "it")
    language = os.getenv("COOKIDOO_LANGUAGE", "it-IT")
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=connector) as session:
        cfg = CookidooConfig(
            email=os.environ["COOKIDOO_EMAIL"],
            password=os.environ["COOKIDOO_PASSWORD"],
            localization=CookidooLocalizationConfig(
                country_code=country,
                language=language,
                url=f"https://cookidoo.{country}/foundation/{language}",
            ),
        )
        client = Cookidoo(session, cfg)
        await client.login()
        print("Logged in.\n")

        for recipe_id, recipe_name, recipe_type, collection_id in rows:
            print(f"--- {recipe_id} | {recipe_name} | type={recipe_type} ---")
            try:
                # Step 1: fetch
                details = await client.get_recipe_details(recipe_id)
                print(f"  fetch OK: type={type(details).__name__}")
                print(f"  is_dataclass={dataclasses.is_dataclass(details)}")

                # Step 2: ingredients
                ingredients = [
                    {
                        "name": ing.name,
                        "quantity": _parse_description(ing.description)[0],
                        "unit": _parse_description(ing.description)[1],
                    }
                    for ing in details.ingredients
                ]
                print(f"  ingredients parsed: {len(ingredients)}")

                # Step 3: raw_json
                raw = json.dumps(dataclasses.asdict(details))
                print(f"  dataclasses.asdict OK, json len={len(raw)}")

                # Step 4: cooking_time
                ct = details.total_time // 60 if details.total_time else None
                sv = details.serving_size or None
                print(f"  cooking_time={ct}, servings={sv}")
                print(f"  -> WOULD UPSERT as status=ok")

            except Exception as exc:
                print(f"  ERROR {type(exc).__name__}: {exc}")
            print()

asyncio.run(main())
