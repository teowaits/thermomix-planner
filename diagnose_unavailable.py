"""One-shot diagnostic: fetch details for 10 unavailable recipes and print the error."""
import asyncio
import sqlite3

import ssl
import aiohttp
import certifi
from dotenv import load_dotenv
import os

load_dotenv()

from cookidoo_api import Cookidoo
from cookidoo_api.types import CookidooConfig, CookidooLocalizationConfig

async def main():
    # Get 10 unavailable recipe IDs from DB
    con = sqlite3.connect("db/planner.db")
    cur = con.cursor()
    cur.execute("SELECT id, name FROM recipes WHERE status = 'unavailable' LIMIT 10")
    recipes = cur.fetchall()
    con.close()

    country = os.getenv("COOKIDOO_COUNTRY", "it")
    language = os.getenv("COOKIDOO_LANGUAGE", "it-IT")
    cfg = CookidooConfig(
        email=os.environ["COOKIDOO_EMAIL"],
        password=os.environ["COOKIDOO_PASSWORD"],
        localization=CookidooLocalizationConfig(
            country_code=country,
            language=language,
            url=f"https://cookidoo.{country}/foundation/{language}",
        ),
    )

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = Cookidoo(session, cfg)
        await client.login()
        print(f"Logged in. Testing {len(recipes)} unavailable recipes...\n")

        for recipe_id, recipe_name in recipes:
            try:
                details = await client.get_recipe_details(recipe_id)
                print(f"  OK     {recipe_id}  {recipe_name[:50]}")
            except Exception as exc:
                print(f"  ERROR  {recipe_id}  {recipe_name[:50]}")
                print(f"         {type(exc).__name__}: {exc}")

asyncio.run(main())
